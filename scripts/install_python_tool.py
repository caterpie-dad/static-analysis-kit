#!/usr/bin/env python3
"""Install one chosen, pinned Python analysis tool into an isolated local venv.

Downloads wheels from PyPI, records their hashes, then installs offline. No
target repository is imported, built, modified, or executed. --plan is offline
and creates nothing. Native/source-only distributions need another installer.
"""

import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys


KIT_ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def commands(destination, package, version):
    executable = destination / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    prefix = [str(executable), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check"]
    wheels = destination / "wheels"
    spec = f"{package}=={version}"
    return executable, {
        "venv": [sys.executable, "-I", "-m", "venv", str(destination / "venv")],
        "download": prefix + ["download", "--no-input", "--no-cache-dir", "--only-binary=:all:",
                               "--index-url", "https://pypi.org/simple", "--dest", str(wheels), spec],
        "install": prefix + ["install", "--no-input", "--no-cache-dir", "--no-index",
                              "--find-links", str(wheels), "--only-binary=:all:", spec],
        "packages": prefix + ["list", "--format=json"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, help="Plain PyPI package name; no URL/extras/options")
    parser.add_argument("--version", required=True, help="Exact version selected from official distribution metadata")
    parser.add_argument("--base", type=Path, default=KIT_ROOT / ".tools" / "python")
    parser.add_argument("--timeout", type=int, default=600, help="Maximum seconds per preparation stage")
    parser.add_argument("--plan", action="store_true", help="Print commands only; no network or writes")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", args.package):
        parser.error("--package must be a plain package name")
    if not re.fullmatch(r"[0-9][A-Za-z0-9.!+_-]*", args.version):
        parser.error("--version must be an exact numeric-leading version without paths or options")
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    normalized = re.sub(r"[-_.]+", "-", args.package).lower()
    destination = args.base.expanduser().resolve() / normalized / args.version
    executable, stages = commands(destination, args.package, args.version)
    plan = {"package": args.package, "version": args.version,
            "destination": str(destination), "index": "https://pypi.org/simple",
            "commands": stages}
    if args.plan:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if destination.exists():
        parser.error(f"destination already exists; inspect/reuse its manifest or choose another base: {destination}")
    destination.mkdir(parents=True)
    (destination / "wheels").mkdir()
    log_path = destination / "install.log"
    stage = "venv"
    try:
        with log_path.open("wb") as log:
            bootstrap_artifacts = []
            try:
                subprocess.run(stages["venv"], cwd=destination, stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=args.timeout)
            except subprocess.CalledProcessError:
                # Some distributions ship venv without ensurepip. Bootstrap a
                # pinned pip wheel into this venv only, using the trusted host
                # pip; never install into the host's site-packages.
                stage = "venv-without-pip"
                stages[stage] = [sys.executable, "-I", "-m", "venv", "--without-pip", str(destination / "venv")]
                subprocess.run(stages[stage], cwd=destination, stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=args.timeout)
                pip_version = importlib.metadata.version("pip")
                bootstrap = destination / "bootstrap-wheels"
                bootstrap.mkdir()
                host_pip = [sys.executable, "-I", "-m", "pip", "--isolated", "--disable-pip-version-check"]
                stage = "bootstrap-download"
                stages[stage] = host_pip + ["download", "--no-input", "--no-cache-dir", "--no-deps",
                                            "--only-binary=:all:", "--index-url", "https://pypi.org/simple",
                                            "--dest", str(bootstrap), f"pip=={pip_version}"]
                subprocess.run(stages[stage], cwd=destination, stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=args.timeout)
                bootstrap_artifacts = [{"filename": p.name, "sha256": digest(p), "bytes": p.stat().st_size}
                                       for p in sorted(bootstrap.glob("*.whl"))]
                if not bootstrap_artifacts:
                    raise ValueError("bootstrap produced no pip wheel")
                stage = "venv-site-path"
                stages[stage] = [str(executable), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"]
                site_result = subprocess.run(stages[stage], cwd=destination, stdin=subprocess.DEVNULL,
                                             stdout=subprocess.PIPE, stderr=log, text=True,
                                             check=True, timeout=args.timeout)
                site_path = Path(site_result.stdout.strip()).resolve()
                if not site_path.is_relative_to((destination / "venv").resolve()):
                    raise ValueError("venv site-packages is outside the isolated environment")
                stage = "bootstrap-install"
                stages[stage] = host_pip + ["install", "--no-input", "--no-cache-dir", "--no-index",
                                            "--no-deps", "--ignore-installed", "--find-links", str(bootstrap),
                                            "--target", str(site_path), f"pip=={pip_version}"]
                subprocess.run(stages[stage], cwd=destination, stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=args.timeout)
            stage = "download"
            subprocess.run(stages[stage], cwd=destination, stdin=subprocess.DEVNULL,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=args.timeout)
            wheels = sorted((destination / "wheels").glob("*.whl"))
            if not wheels:
                raise ValueError("download produced no wheels")
            artifacts = [{"filename": p.name, "sha256": digest(p), "bytes": p.stat().st_size} for p in wheels]
            stage = "install"
            subprocess.run(stages[stage], cwd=destination, stdin=subprocess.DEVNULL,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=args.timeout)
            stage = "packages"
            packages = subprocess.run(stages[stage], cwd=destination, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=log, check=True,
                                      timeout=args.timeout, text=True)
        manifest = {"schema_version": 1, "status": "installed",
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    **plan, "artifacts": artifacts, "bootstrap_artifacts": bootstrap_artifacts,
                    "packages": json.loads(packages.stdout),
                    "python": str(executable), "executables": str(executable.parent),
                    "log": str(log_path),
                    "provenance_note": "PyPI over TLS; recorded local wheel hashes, not an independent publisher signature."}
        manifest_path = destination / "install-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "installed", "manifest": str(manifest_path),
                          "executables": str(executable.parent)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError) as error:
        failure = {"schema_version": 1, "status": "failed", "stage": stage,
                   "error_type": type(error).__name__, "log": str(log_path), **plan}
        (destination / "install-failure.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "failed", "stage": stage, "error_type": type(error).__name__,
                          "log": str(log_path)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
