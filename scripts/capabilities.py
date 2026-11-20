#!/usr/bin/env python3
"""Inventory local static-analysis capabilities without installing or running targets.

This reports representative host commands and optional public model metadata.
No client cache is read unless a client or catalog is explicitly selected.
Provider settings and credential stores are not searched. Version queries run
in an empty temporary directory; no project or target code is executed.
"""

import argparse
import datetime
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


TOOL_PROBES = (
    ("rg", ("--version",)),
    ("git", ("--version",)),
    ("python3", ("--version",)),
    ("node", ("--version",)),
    ("npm", ("--version",)),
    ("uv", ("--version",)),
    ("pipx", ("--version",)),
    ("semgrep", ("--version",)),
    ("codeql", ("version", "--format=json")),
    ("syft", ("version",)),
    ("trivy", ("--version",)),
    ("checkov", ("--version",)),
    ("go", ("version",)),
    ("java", ("-version",)),
    ("codex", ("--version",)),
    ("claude", ("--version",)),
    ("vibe", ("--version",)),
    ("opencode", ("--version",)),
)
CLIENT_COMMANDS = {"codex": "codex", "claude-code": "claude",
                   "mistral-vibe": "vibe", "opencode": "opencode"}
MAX_VERSION_CHARS = 240
MAX_VERSION_OUTPUT = 4096
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_MODELS = 500


def _version(path, args, cwd=None):
    """Run only a fixed version query, with a strict time limit."""
    try:
        process = subprocess.Popen(
            [path, *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            cwd=cwd,
        )
    except OSError:
        return None, "execution_failed"

    captured = bytearray()
    too_large = threading.Event()

    def read_bounded_output():
        while True:
            chunk = process.stdout.read(512)
            if not chunk:
                return
            room = MAX_VERSION_OUTPUT - len(captured)
            captured.extend(chunk[:room])
            if len(chunk) > room:
                too_large.set()
                try:
                    process.kill()
                except OSError:
                    pass
                return

    reader = threading.Thread(target=read_bounded_output, daemon=True)
    reader.start()
    try:
        returncode = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        reader.join(timeout=0.5)
        return None, "timeout"
    reader.join(timeout=0.5)
    if too_large.is_set():
        return None, "output_too_large"

    # Never return diagnostic text as an error, since tools may include
    # unrelated local details in their output.
    raw = bytes(captured).decode("utf-8", errors="replace")
    if returncode != 0:
        return None, "exit_{}".format(returncode)
    if not raw.strip():
        return None, "empty_output"

    if args == ("version", "--format=json"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for key in ("version", "versionInfo", "release"):
                    candidate = data.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate.strip()[:MAX_VERSION_CHARS], None
                    if isinstance(candidate, dict):
                        nested = candidate.get("version")
                        if isinstance(nested, str) and nested.strip():
                            return nested.strip()[:MAX_VERSION_CHARS], None
        except (ValueError, TypeError):
            pass

    version = next((line.strip() for line in raw.splitlines() if line.strip()), "")
    if not version:
        return None, "empty_output"
    return version[:MAX_VERSION_CHARS], None


def _probe_tools():
    tools = []
    with tempfile.TemporaryDirectory(prefix="static-kit-version-") as temporary:
        for name, args in TOOL_PROBES:
            path = shutil.which(name)
            if path is not None:
                path = str(Path(path).resolve())
            entry = {"name": name, "path": path, "present": path is not None,
                     "version": None, "version_error": None}
            if path is not None:
                entry["version"], entry["version_error"] = _version(path, args, cwd=temporary)
            tools.append(entry)
    return tools


def _public_text(value, maximum=1024):
    if isinstance(value, str):
        value = value.strip()
        if value and len(value) <= maximum and not any(ord(char) < 32 for char in value):
            return value
    return None


def _model_records(value):
    """Extract an allow-list of metadata fields without restricting model names.

    A model list, a single record, and ``models``/``data`` containers are
    recognized. Mapping keys are IDs only inside these catalog containers or
    when a top-level value has recognizable public model metadata. Arbitrary
    nested configuration keys are not interpreted as model identifiers.
    """
    records = []
    seen = set()

    def add_record(item, key_hint=None):
        if not isinstance(item, dict) or len(records) >= MAX_MODELS:
            return
        identifiers = []
        for key in ("slug", "id", "model_id", "modelId"):
            candidate = _public_text(item.get(key))
            if candidate and candidate not in identifiers:
                identifiers.append(candidate)
        if not identifiers and _public_text(key_hint):
            identifiers.append(key_hint.strip())
        if not identifiers:
            return
        levels = item.get("supported_reasoning_levels")
        if levels is None:
            levels = item.get("supportedReasoningLevels")
        if levels is None:
            levels = item.get("reasoning_efforts")
        if isinstance(levels, list):
            parsed_levels = []
            for level in levels:
                if isinstance(level, dict):
                    level = level.get("effort", level.get("level"))
                level = _public_text(level, maximum=64)
                if level and level not in parsed_levels:
                    parsed_levels.append(level)
                if len(parsed_levels) >= 32:
                    break
            levels = parsed_levels
        else:
            levels = None
        provider = _public_text(item.get("provider"), maximum=128)
        signature = (provider, tuple(identifiers), tuple(levels) if levels is not None else None)
        if signature in seen:
            return
        seen.add(signature)
        record = {"identifiers": identifiers}
        if provider:
            record["provider"] = provider
        if levels is not None:
            record["supported_reasoning_levels"] = levels
        records.append(record)

    if isinstance(value, list):
        for item in value:
            add_record(item)
    elif isinstance(value, dict):
        add_record(value)
        for key in ("models", "data"):
            entries = value.get(key)
            if isinstance(entries, list):
                for item in entries:
                    add_record(item)
            elif isinstance(entries, dict):
                for identifier, item in entries.items():
                    add_record(item, identifier)
        public_metadata_keys = {"supported_reasoning_levels", "supportedReasoningLevels",
                                "reasoning_efforts", "context_window", "contextWindow",
                                "display_name", "capabilities"}
        for key, item in value.items():
            if isinstance(item, dict) and public_metadata_keys.intersection(item):
                add_record(item, key)
    records.sort(key=lambda item: (item.get("provider", ""), item["identifiers"]))
    return records


def _empty_catalog(client=None, source="none", catalog_format=None):
    return {
        "client": client,
        "source": source,
        "catalog_format": catalog_format,
        "catalog_file_present": False,
        "catalog_parsed": False,
        "catalog_format_supported": False,
        "models": [],
        "metadata_only": True,
        "cached_catalog_only": catalog_format == "codex-cache",
        "current_session_model": None,
        "access_tested": False,
        "access_confirmed": False,
    }


def _read_catalog(path, client, source, catalog_format):
    result = _empty_catalog(client, source, catalog_format)
    try:
        result["catalog_file_present"] = path.is_file()
        if not result["catalog_file_present"]:
            result["catalog_error"] = "missing"
            return result
        # Bounded reads also cover a file that grows after stat().
        if path.stat().st_size > MAX_CATALOG_BYTES:
            result["catalog_error"] = "too_large"
            return result
        with path.open("rb") as catalog_file:
            raw = catalog_file.read(MAX_CATALOG_BYTES + 1)
        if len(raw) > MAX_CATALOG_BYTES:
            result["catalog_error"] = "too_large"
            return result
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        result["catalog_error"] = "malformed_json"
    except (OSError, UnicodeError, ValueError):
        result["catalog_error"] = "unreadable"
    else:
        result["catalog_parsed"] = True
        if catalog_format == "public-catalog-v1":
            supported = (isinstance(data, dict) and data.get("schema_version") == 1
                         and not isinstance(data.get("schema_version"), bool)
                         and isinstance(data.get("models"), (list, dict)))
        else:
            supported = (isinstance(data, list) or (isinstance(data, dict) and (
                any(isinstance(data.get(key), (list, dict)) for key in ("models", "data"))
                or bool(_model_records(data)))))
        result["catalog_format_supported"] = supported
        if supported:
            records = {"models": data["models"]} if catalog_format == "public-catalog-v1" else data
            result["models"] = _model_records(records)
            result["entries_may_be_truncated"] = len(result["models"]) >= MAX_MODELS
        else:
            result["catalog_error"] = "unsupported_format"
    return result


def _model_cache(chosen_path):
    """Compatibility wrapper for explicitly selected Codex catalog metadata.

    ``available`` retains its historical meaning: the cache file exists. It is
    not model access. New callers should use the explicit catalog flags.
    """
    path = Path(chosen_path).expanduser() if chosen_path else Path.home() / ".codex" / "models_cache.json"
    result = _read_catalog(path, "codex", "provided" if chosen_path else "default", "codex-cache")
    result["available"] = result["catalog_file_present"]
    if "catalog_error" in result:
        result["cache_error"] = result["catalog_error"]
    return result


def _model_catalog(client=None, model_cache_path=None, model_catalog_path=None):
    if model_catalog_path:
        return _read_catalog(Path(model_catalog_path).expanduser(), client,
                             "provided", "public-catalog-v1")
    if client == "codex" or model_cache_path:
        return _model_cache(model_cache_path)
    return _empty_catalog(client)


def _report(model_cache_path=None, client=None, model_catalog_path=None):
    if model_cache_path and client is None:
        client = "codex"
    tools = _probe_tools()
    by_name = {entry["name"]: entry for entry in tools}
    clients = {}
    for name, command in CLIENT_COMMANDS.items():
        tool = by_name.get(command, {})
        clients[name] = {"command": command, "present": tool.get("present", False),
                         "version": tool.get("version"), "access_confirmed": False,
                         "current_session_model": None}
    return {
        "schema_version": 2,
        "collected_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "selected_client": client,
        # Presence/version metadata are not evidence of login, model access,
        # delegation support, or the settings of the active agent session.
        "tools": tools,
        "clients": clients,
        "model_catalog": _model_catalog(client, model_cache_path, model_catalog_path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="write JSON to this path (default: stdout)")
    parser.add_argument("--client", choices=sorted(CLIENT_COMMANDS), help="select a client's public catalog adapter")
    catalogs = parser.add_mutually_exclusive_group()
    catalogs.add_argument("--model-cache", help="read an explicitly provided Codex model cache (legacy option)")
    catalogs.add_argument("--model-catalog", help="read public model metadata JSON with schema_version=1 and models")
    parser.add_argument("--force", action="store_true", help="allow replacing an existing output file")
    args = parser.parse_args(argv)
    if args.model_cache and args.client not in (None, "codex"):
        parser.error("--model-cache contains Codex metadata; use --model-catalog for another client")

    report = _report(args.model_cache, args.client, args.model_catalog)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if not args.output:
        sys.stdout.write(rendered)
        return 0

    output_path = Path(args.output).expanduser()
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if args.force else "x"
        with output_path.open(mode, encoding="utf-8") as output_file:
            output_file.write(rendered)
    except FileExistsError:
        parser.error("output exists; pass --force to replace it")
    except OSError as error:
        parser.error("cannot write output ({}): {}".format(type(error).__name__, output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
