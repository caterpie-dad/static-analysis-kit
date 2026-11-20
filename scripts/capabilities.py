#!/usr/bin/env python3
"""Inventory local static-analysis capabilities without installing or running targets.

This reports whether representative host tools are available and reads only
public model catalog metadata from a Codex model cache. It never accesses
credentials, contacts a network, or executes project or target code.
"""

import argparse
import datetime
import json
import platform
import shutil
import subprocess
import sys
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
)
MAX_VERSION_CHARS = 240
MAX_VERSION_OUTPUT = 4096


def _version(path, args):
    """Run only a fixed version query, with a strict time limit."""
    try:
        process = subprocess.Popen(
            [path, *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
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
    for name, args in TOOL_PROBES:
        path = shutil.which(name)
        entry = {"name": name, "path": path, "present": path is not None,
                 "version": None, "version_error": None}
        if path is not None:
            entry["version"], entry["version_error"] = _version(path, args)
        tools.append(entry)
    return tools


def _model_records(value):
    """Extract only recognized catalog identifiers and reasoning levels."""
    records = []
    seen = set()

    def add_record(item, key_hint=None):
        if not isinstance(item, dict):
            return
        identifiers = []
        for key in ("slug", "id", "model_id", "modelId"):
            candidate = item.get(key)
            if isinstance(candidate, str) and candidate.strip():
                value = candidate.strip()
                if value not in identifiers:
                    identifiers.append(value)
        if (not identifiers and isinstance(key_hint, str)
                and key_hint.startswith(("gpt-", "o1", "o3", "o4", "codex-"))):
            identifiers.append(key_hint.strip())
        if not identifiers:
            return
        levels = item.get("supported_reasoning_levels")
        if levels is None:
            levels = item.get("supportedReasoningLevels")
        if isinstance(levels, list):
            parsed_levels = []
            for level in levels:
                if isinstance(level, dict):
                    level = level.get("effort", level.get("level"))
                if isinstance(level, str) and level.strip() and level.strip() not in parsed_levels:
                    parsed_levels.append(level.strip())
            levels = parsed_levels
        else:
            levels = None
        signature = (tuple(identifiers), tuple(levels) if levels is not None else None)
        if signature in seen:
            return
        seen.add(signature)
        record = {"identifiers": identifiers}
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
        for key, item in value.items():
            if isinstance(item, dict):
                add_record(item, key)
    records.sort(key=lambda item: item["identifiers"])
    return records


def _model_cache(chosen_path):
    source = "provided" if chosen_path else "default"
    path = Path(chosen_path).expanduser() if chosen_path else Path.home() / ".codex" / "models_cache.json"
    result = {
        "source": source,
        "available": path.is_file(),
        "models": [],
        "cached_catalog_only": True,
        "access_confirmed": False,
    }
    if not result["available"]:
        return result
    try:
        # A cache is metadata, but cap its size to keep the inventory bounded.
        if path.stat().st_size > 2 * 1024 * 1024:
            result["cache_error"] = "too_large"
            return result
        with path.open("r", encoding="utf-8") as cache_file:
            cache_data = json.load(cache_file)
    except json.JSONDecodeError:
        result["cache_error"] = "malformed_json"
    except (OSError, UnicodeError):
        result["cache_error"] = "unreadable"
    else:
        result["models"] = _model_records(cache_data)[:500]
    return result


def _report(model_cache_path):
    return {
        "schema_version": 1,
        "collected_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        # These are suggestions for the host environment, not prerequisites or
        # evidence that any particular analysis can be performed.
        "tools": _probe_tools(),
        "model_cache": _model_cache(model_cache_path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="write JSON to this path (default: stdout)")
    parser.add_argument("--model-cache", help="read model catalog metadata from this cache path")
    parser.add_argument("--force", action="store_true", help="allow replacing an existing output file")
    args = parser.parse_args(argv)

    report = _report(args.model_cache)
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
