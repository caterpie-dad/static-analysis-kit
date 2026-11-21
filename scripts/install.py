#!/usr/bin/env python3
"""Install the complete core and client-native user skills without config edits."""

import argparse
import hashlib
import json
import os
import shlex
from pathlib import Path
import shutil
import sys
import tempfile

from runtime_config import RENDERERS, render_files, resolve_configuration


SOURCE = Path(__file__).resolve().parents[1]
SKILL = "static-analysis-kit"
LEGACY_SKILL = "system-static-analysis"
CLIENT_DIRS = {"codex": ("CODEX_HOME", ".codex"),
               "claude-code": ("CLAUDE_CONFIG_DIR", ".claude"),
               "mistral-vibe": ("VIBE_HOME", ".vibe")}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def safe_path(value):
    path = Path(value).expanduser().absolute()
    if any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        raise ValueError("installation paths must be single-line strings")
    # Do not follow links when registering/unregistering user configuration.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("symlink installation path: {}".format(part))
    return path


def client_home(client):
    if client == "opencode":
        default = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "opencode"
        return safe_path(os.environ.get("OPENCODE_CONFIG_DIR", str(default)))
    variable, default = CLIENT_DIRS[client]
    return safe_path(os.environ.get(variable, str(Path.home() / default)))


def package_files(source):
    """Only distribute kit resources, never runs, downloads, or local profiles."""
    files = {}
    for directory in (".agents/skills", "adapters", "profiles", "references", "roles",
                      "schemas", "scripts", "templates", "tests"):
        for path in sorted((source / directory).rglob("*")):
            relative = path.relative_to(source)
            if "__pycache__" in relative.parts or ".local." in path.name:
                continue
            if path.is_symlink():
                raise ValueError("kit resources cannot be symlinks: {}".format(relative))
            if path.is_file() and path.suffix in {".md", ".py", ".toml", ".json", ".yaml", ".yml"}:
                files[relative.as_posix()] = path.read_bytes()
    for path in sorted(source.glob("*.md")) + [source / "kit.toml", source / "install.sh"]:
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing/linked kit resource: {}".format(path))
        files[path.name] = path.read_bytes()
    for required in ("START_HERE.md", "AGENTS.md", "SECURITY.md", "scripts/kit_paths.py",
                     ".agents/skills/system-static-analysis/SKILL.md"):
        if required not in files:
            raise ValueError("incomplete kit distribution: {}".format(required))
    return files


def package_plan(source, base):
    files = package_files(source)
    metadata = {"schema_version": 1, "data_root": str(base), "python": sys.executable,
                "python_version": sys.version, "python_sha256": sha(Path(sys.executable).read_bytes()),
                "files": {name: sha(content) for name, content in sorted(files.items())}}
    version = sha(encoded(metadata))[:24]
    metadata["version"] = version
    files[".installation.json"] = encoded(metadata)
    return base / "packages" / version, files


def model_profile(resolved):
    """Persist role choices, without credentials or references to temporary files."""
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    lines = ["schema_version = 1", "[roles]"]
    aliases = {}
    for role, spec in resolved["roles"].items():
        lines.append("{} = {}".format(role, quote(spec["alias"])))
        aliases[spec["alias"]] = spec
    lines.extend(["[delegation]", "max_concurrent = {}".format(resolved["max_concurrent"])])
    client = quote(resolved["client"])
    lines.append("[clients.{}.models]".format(client))
    for alias, spec in aliases.items():
        if spec["model"] is not None:
            lines.append("{} = {}".format(quote(alias), quote(spec["model"])))
    for alias, spec in aliases.items():
        lines.append("[clients.{}.options.{}]".format(client, quote(alias)))
        for name, value in spec["options"].items():
            lines.append("{} = {}".format(quote(name), json.dumps(value, ensure_ascii=False)))
    return "\n".join(lines) + "\n"


def resolve_install_profile(source, client, args, old):
    if args.profile is not None or args.override is not None or not old or not old.get("model_profile"):
        return resolve_configuration(source, client, args.profile, args.override)
    with tempfile.TemporaryDirectory(prefix="static-kit-profile-") as directory:
        saved = Path(directory) / "saved-profile.toml"
        saved.write_text(old["model_profile"], encoding="utf-8")
        return resolve_configuration(source, client, saved)


def registration_files(client, package, base, native):
    home = client_home(client)
    files = {}
    for name, content in native.items():
        relative = Path(name)
        if len(relative.parts) == 3 and relative.parts[1] == "agents":
            files[home / "agents" / relative.name] = content.encode()
    start = package / "START_HERE.md"
    # The tiny wrapper is discoverable; all shared policy stays in the core.
    body = (
        "[에이전트 안에서 사용하기](<{}>)를 먼저 읽는다. "
        "단독 호출·도움말·모델 설정 요청이면 그 안내에 따라 설정을 조회·변경한다. "
        "설정을 위해 대상 소스 경로나 사용자 TOML 파일을 요구하지 않는다. "
        "분석 요청이면 저장된 모델 의도를 확인한 뒤 [START_HERE.md](<{}>)를 적용한다. "
        "KIT_ROOT는 `{}`이다. 전체 키트는 이 경로에 설치되어 있다.\n\n"
        "이 설치의 헬퍼 실행기는 `{}`이다. 지침의 `python3` 대신 이 실행기를 사용한다. "
        "조사 기록은 `{}`, 도구 캐시는 `{}`에 둔다. "
        "설치 패키지는 수정하지 않는다. 현재 클라이언트는 `{}`이며 등록 역할은 "
        "`static_inventory`, `static_analyst`, `static_reviewer`이다. "
        "실제 위임·모델·파일 접근·네트워크 권한을 확인하며 호스트 정책을 따른다.\n"
        "\n현재 설치 설정 조회 명령(에이전트가 실행):\n\n```sh\n{}\n```\n"
    ).format(package / "references/agent-interface.md", start, package, sys.executable,
             base / "runs", base / "tools", client,
             shlex.join([sys.executable, str(package / "scripts/manage.py"),
                         "models", "show", "--client", client]))
    for name in (SKILL, LEGACY_SKILL):
        description = ("정적 보안 분석 키트의 시작·재개와 역할별 모델 설정을 대화로 처리한다."
                       if name == SKILL else
                       "기존 system-static-analysis 호출을 위한 호환 진입점. 정적 분석과 키트 모델 설정을 연결한다.")
        front = "---\nname: {}\ndescription: {}\n---\n\n".format(name, description)
        files[home / "skills" / name / "SKILL.md"] = (front + body).encode()
    return files


def current(path):
    safe_path(path)
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("expected a regular file: {}".format(path))
    return path.read_bytes()


def atomic_write(path, content, create_only=False):
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".static-kit-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        if create_only:
            os.link(temporary, path)  # Atomically refuse a concurrently created user file.
        else:
            temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_transaction(changes, originals=None):
    if originals is None:
        originals = {path: current(path) for path in changes}
    written = []
    try:
        for path, content in changes.items():
            if current(path) != originals[path]:
                raise ValueError("file changed during installation: {}".format(path))
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, content, create_only=originals[path] is None)
            written.append(path)
    except BaseException:
        for path in reversed(written):
            if current(path) != changes[path]:
                continue  # Preserve an external edit made during rollback, too.
            if originals[path] is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, originals[path])
        raise


def install(args, source=SOURCE):
    base = safe_path(os.environ.get("STATIC_ANALYSIS_KIT_HOME", str(
        Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "static-analysis-kit")))
    base.mkdir(parents=True, exist_ok=True)
    lock = base / ".install.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("another installation is running (or inspect stale lock): {}".format(lock)) from exc
    os.close(descriptor)
    try:
        clients = list(RENDERERS) if args.client == "all" else [args.client]
        changes = {}
        originals = {}
        package = None
        if not args.uninstall:
            package, resources = package_plan(source, base)
        for client in clients:
            manifest_path = base / "registrations" / (client + ".json")
            old_bytes = current(manifest_path)
            expected_manifest = getattr(args, "expected_manifest", None)
            if expected_manifest is not None and old_bytes != expected_manifest:
                raise ValueError("model settings changed during preparation; read settings again")
            originals[manifest_path] = old_bytes
            old = json.loads(old_bytes) if old_bytes is not None else None
            if old is not None and (not isinstance(old, dict) or old.get("schema_version") != 1 or old.get("client") != client):
                raise ValueError("invalid installation manifest: {}".format(manifest_path))
            owned = old["files"] if old else {}
            for name, expected in owned.items():
                content = current(Path(name))
                originals[Path(name)] = content
                if content is not None and sha(content) != expected:
                    raise ValueError("modified kit registration; preserve or move it first: {}".format(name))
            if args.uninstall:
                for name in owned:
                    changes[Path(name)] = None
                if old:
                    changes[manifest_path] = None
                continue
            # Render from original shared policies with absolute installed paths.
            resolved = resolve_install_profile(source, client, args, old)
            preferences = getattr(args, "model_preferences", None)
            if preferences is None:
                preferences = ((old or {}).get("model_preferences", {})
                               if args.profile is None and args.override is None else {})
            if not preferences:
                preferences = {"mode": "roles" if any(spec["model"] is not None for spec in resolved["roles"].values())
                               else "client-default", "main_model": None}
            native = render_files(package, resolved)
            files = registration_files(client, package, base, native)
            for path in files:
                content = current(path)
                if str(path) in owned and content != originals[path]:
                    raise ValueError("file changed during installation: {}".format(path))
                if content is not None and str(path) not in owned:
                    raise ValueError("existing user file; refusing overwrite: {}".format(path))
                originals[path] = content
                if path in changes:
                    raise ValueError("client directories overlap: {}".format(path))
            for name in owned:
                if Path(name) not in files:
                    changes[Path(name)] = None
            changes.update(files)
            changes[manifest_path] = encoded({"schema_version": 1, "client": client,
                "package": str(package), "files": {str(p): sha(c) for p, c in files.items()},
                "model_profile": model_profile(resolved),
                "model_preferences": preferences,
                "max_concurrent": resolved["max_concurrent"],
                "role_models": {role: {key: spec[key] for key in ("alias", "model", "options")}
                                for role, spec in resolved["roles"].items()},
                "model_access_verified": False})
        if package is not None:
            safe_path(package)
            if package.exists():
                actual = {p.relative_to(package).as_posix(): p.read_bytes()
                          for p in package.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
                if actual != resources or any(p.is_symlink() for p in package.rglob("*")):
                    raise ValueError("installed package was modified: {}".format(package))
            else:
                package.parent.mkdir(parents=True, exist_ok=True)
                stage = Path(tempfile.mkdtemp(dir=package.parent, prefix=".staging-"))
                try:
                    for name, content in resources.items():
                        path = stage / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(content)
                    stage.rename(package)
                finally:
                    if stage.exists():
                        shutil.rmtree(stage)
        write_transaction(changes, {path: originals[path] for path in changes})
        for client in clients:
            print("{}: {}".format(client, "uninstalled" if args.uninstall else "installed"))
        if args.uninstall:
            print("Investigation records, packages and downloaded tools were preserved: {}".format(base))
        else:
            print("Start a new client session. Codex: $static-analysis-kit 설정")
            print("Investigation records: {}".format(base / "runs"))
            print("Client configuration/authentication unchanged; actual skill/agent loading is not verified.")
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client", choices=[*RENDERERS, "all"])
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--override", type=Path)
    args = parser.parse_args()
    try:
        install(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("Installation failed: {}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
