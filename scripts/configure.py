#!/usr/bin/env python3
"""Plan or write optional client configuration from shared roles and profiles."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile

from runtime_config import ConfigurationError, RENDERERS, render_files, resolve_configuration


KIT_ROOT = Path(__file__).resolve().parent.parent


def digest(content):
    return hashlib.sha256(content).hexdigest()


def _destination(output, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts) or "\\" in relative:
        raise ConfigurationError("generated path must remain in the output directory")
    selected = output.joinpath(*path.parts)
    for parent in [output, *selected.relative_to(output).parents]:
        current = parent if parent == output else output / parent
        if current.is_symlink():
            raise ConfigurationError("refusing a symlink in generated output: {}".format(current))
        if current.exists() and not current.is_dir():
            raise ConfigurationError("generated parent is not a directory: {}".format(current))
    if selected.is_symlink():
        raise ConfigurationError("refusing a generated-file symlink: {}".format(selected))
    if selected.exists() and not selected.is_file():
        raise ConfigurationError("generated destination is not a file: {}".format(selected))
    return selected


def _read_manifest(path, client):
    if not path.exists():
        return {"files": {}}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ConfigurationError("cannot read generated-file ownership manifest") from exc
    if (not isinstance(record, dict) or record.get("schema_version") != 1
            or record.get("client") != client or not isinstance(record.get("files"), dict)):
        raise ConfigurationError("invalid generated-file ownership manifest")
    for name, sha in record["files"].items():
        if not isinstance(name, str) or not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ConfigurationError("invalid generated-file ownership hash")
    return record


def _atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".static-kit-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def prepare_plan(root, client, profile_path=None, override_path=None, output=None, force=False):
    root = Path(root).resolve()
    output = Path(output).expanduser().absolute() if output is not None else root
    if output.is_symlink():
        raise ConfigurationError("output directory cannot be a symlink")
    resolved = resolve_configuration(root, client, profile_path, override_path)
    rendered = render_files(root, resolved)
    relative_manifest = ".tools/adapter-state/{}.json".format(client)
    manifest_path = _destination(output, relative_manifest)
    previous = _read_manifest(manifest_path, client)
    entries = []
    conflicts = []
    for relative, content in rendered.items():
        destination = _destination(output, relative)
        content_bytes = content.encode("utf-8")
        wanted_hash = digest(content_bytes)
        exists = destination.exists()
        current_hash = digest(destination.read_bytes()) if exists else None
        action = "create"
        if current_hash == wanted_hash:
            action = "unchanged" if previous["files"].get(relative) == current_hash else "unchanged-unmanaged"
        elif exists:
            owned_hash = previous["files"].get(relative)
            if owned_hash is None:
                action = "conflict-unmanaged"
            elif current_hash != owned_hash:
                action = "conflict-modified"
            elif force:
                action = "replace-generated"
            else:
                action = "requires-force"
            if action != "replace-generated":
                conflicts.append(relative)
        entries.append({"path": relative, "sha256": wanted_hash, "action": action, "content": content})
    plan = {
        "schema_version": 1, "client": client, "output": str(output), "kit_root": str(root),
        "profile_sources": resolved["profile_sources"], "adapter": resolved["adapter"],
        "source_hashes": resolved["source_hashes"],
        "requested_roles": {role: {key: spec[key] for key in ("name", "alias", "model", "options")}
                            for role, spec in resolved["roles"].items()},
        "requested_max_concurrent": resolved["max_concurrent"],
        "current_session_model": None, "access_confirmed": False,
        "runtime_compatibility_verified": False,
        "files": entries, "conflicts": conflicts, "ownership_manifest": relative_manifest,
        "notes": ["Plan only unless --write is supplied.",
                  "Generated references require this checkout; regenerate after moving it.",
                  "No client, provider, model, plugin, or MCP connection is started.",
                  "Only Codex receives a native concurrency setting; other clients retain their own limits.",
                  "Client reload, model access, supported model options, and host policies need session confirmation."],
    }
    return plan


def write_plan(plan):
    if plan["conflicts"]:
        raise ConfigurationError("configuration conflicts; existing user or modified generated files are preserved")
    output = Path(plan["output"])
    # Preflight every destination before creating even the first directory.
    destinations = [(entry, _destination(output, entry["path"])) for entry in plan["files"]]
    manifest = _destination(output, plan["ownership_manifest"])
    previous = _read_manifest(manifest, plan["client"])
    originals = {}
    written = []
    try:
        for entry, destination in destinations:
            existing = destination.read_bytes() if destination.exists() else None
            wanted = entry["content"].encode("utf-8")
            if existing == wanted:
                continue
            # Recheck ownership after planning, before replacing a file.
            if entry["action"] == "create" and existing is not None:
                raise ConfigurationError("destination appeared after planning")
            if entry["action"] == "replace-generated" and (existing is None or digest(existing) != previous["files"].get(entry["path"])):
                raise ConfigurationError("generated destination changed after planning")
            if entry["action"].startswith("unchanged"):
                raise ConfigurationError("unchanged destination changed after planning")
            originals[destination] = existing
            _atomic_write(destination, wanted)
            written.append(destination)
        record = {
            "schema_version": 1, "client": plan["client"], "kit_root": plan["kit_root"],
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "profile_sources": plan["profile_sources"], "requested_roles": plan["requested_roles"],
            "source_hashes": plan["source_hashes"],
            "adapter": {key: plan["adapter"][key] for key in ("native_schema", "reference_version", "checked_at", "validation")},
            "files": {entry["path"]: entry["sha256"] for entry in plan["files"]
                      if entry["action"] != "unchanged-unmanaged"},
            "current_session_model": None, "access_confirmed": False,
            "runtime_compatibility_verified": False,
        }
        _atomic_write(manifest, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except (OSError, ConfigurationError):
        for destination in reversed(written):
            original = originals[destination]
            if original is None:
                destination.unlink(missing_ok=True)
            else:
                _atomic_write(destination, original)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True, choices=tuple(RENDERERS))
    parser.add_argument("--profile", help="profile layered over the default profile")
    parser.add_argument("--override", help="explicit local override; no implicit home-file discovery")
    parser.add_argument("--output", help="native config destination (default: kit checkout)")
    parser.add_argument("--write", action="store_true", help="write planned native files and an ownership manifest")
    parser.add_argument("--force", action="store_true", help="replace only unchanged, previously generated files")
    args = parser.parse_args(argv)
    try:
        plan = prepare_plan(KIT_ROOT, args.client, args.profile, args.override, args.output, args.force)
        if args.write:
            write_plan(plan)
        plan["written"] = bool(args.write)
        plan["ok"] = not plan["conflicts"]
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0 if plan["ok"] else 1
    except (OSError, ConfigurationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "written": False}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
