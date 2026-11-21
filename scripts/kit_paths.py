"""Writable locations for a checkout or an installed, immutable kit package."""

import json
from pathlib import Path


def runtime_paths(root):
    root = Path(root).resolve()
    marker = root / ".installation.json"
    if not marker.exists():
        return root / "runs", root / ".tools"
    metadata = json.loads(marker.read_text(encoding="utf-8"))
    base = Path(metadata["data_root"])
    if not base.is_absolute() or metadata.get("schema_version") != 1:
        raise ValueError("invalid installed kit runtime location")
    return base / "runs", base / "tools"
