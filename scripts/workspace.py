#!/usr/bin/env python3
"""Create static-only investigation workspaces and source references.

No target code is run. Inventory uses directory metadata only; ref reads only
the requested source file and emits its location and hash, never its contents.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


KIT_ROOT = Path(__file__).resolve().parent.parent
ROOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def within(path, parent):
    return path == parent or parent in path.parents


def directory(value):
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("expected a directory: {}".format(path))
    return path


def source_directory(value):
    path = directory(value)
    if within(path, KIT_ROOT):
        raise ValueError("the toolkit and its descendants cannot be source targets")
    return path


def validate_root_id(value):
    if not isinstance(value, str) or not ROOT_ID.fullmatch(value):
        raise ValueError("root ID must contain 1-64 letters, digits, '.', '_' or '-', starting with a letter or digit")
    return value


def check_output_location(output, source):
    if within(output, source) and not within(output, KIT_ROOT / "runs"):
        raise ValueError("output cannot be inside a source root except under the toolkit's runs directory")


def write_json(path, value):
    """Replace only a workspace artifact, using an atomic sibling file."""
    if path.is_symlink():
        raise ValueError("refusing to replace a symlink artifact: {}".format(path))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".workspace-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def git_metadata(path):
    """Read only HEAD; worktree status can invoke target-configured filters."""
    if shutil.which("git") is None:
        return None, None
    # Ignore inherited Git overrides and disable optional writes. No environment
    # or Git configuration is reported, and worktree status is never invoked.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"})

    def query(arguments):
        try:
            result = subprocess.run(["git", "-C", str(path), *arguments],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, env=env, timeout=5,
                                    check=False, shell=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout if result.returncode == 0 else None

    raw_commit = query(["rev-parse", "HEAD"])
    commit = None
    if raw_commit is not None:
        candidate = raw_commit.decode("ascii", errors="replace").strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", candidate):
            commit = candidate
    return commit, None


def root_record(root_id, path):
    commit, dirty = git_metadata(path)
    return {"id": root_id, "path": str(path), "git_commit": commit, "git_dirty": dirty,
            "git_dirty_reason": "not evaluated; source hashes identify reviewed bytes"}


def load_run(value):
    run = directory(value)
    metadata_path = run / "run.json"
    if metadata_path.is_symlink():
        raise ValueError("run.json cannot be a symlink")
    with metadata_path.open(encoding="utf-8") as handle:
        metadata = json.load(handle)
    if not isinstance(metadata, dict) or metadata.get("schema_version") != 1:
        raise ValueError("unsupported or malformed run.json")
    if metadata.get("mode") != "static-only":
        raise ValueError("run must use static-only mode")
    roots = metadata.get("source_roots")
    if not isinstance(roots, list) or not roots:
        raise ValueError("run.json must declare source roots")
    seen_ids, seen_paths = set(), []
    for root in roots:
        if not isinstance(root, dict):
            raise ValueError("malformed source root")
        root_id = validate_root_id(root.get("id"))
        raw_path = root.get("path")
        if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
            raise ValueError("source root paths must be absolute")
        source = source_directory(raw_path)
        if root_id in seen_ids or any(within(source, other) or within(other, source)
                                      for other in seen_paths):
            raise ValueError("duplicate or overlapping source roots")
        check_output_location(run, source)
        seen_ids.add(root_id)
        seen_paths.append(source)
    return run, metadata


def select_root(metadata, root_id):
    validate_root_id(root_id)
    for root in metadata["source_roots"]:
        if root["id"] == root_id:
            return directory(root["path"])
    raise ValueError("unknown source root ID: {}".format(root_id))


def initialize(args):
    target = source_directory(args.target)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", target.name).strip("-.")[:60] or "target"
    run_id = "{}-{}-{}".format(slug, stamp, uuid.uuid4().hex[:8])
    requested_output = Path(args.output).expanduser() if args.output else KIT_ROOT / "runs" / run_id
    if requested_output.exists() or requested_output.is_symlink():
        raise ValueError("output already exists; choose a new investigation directory")
    output = requested_output.resolve()
    check_output_location(output, target)
    root = root_record("primary", target)
    created = utc_now()
    # mkdir's exclusive final component also refuses a concurrent re-init.
    output.mkdir(parents=True, exist_ok=False)
    for name in ("findings", "evidence", "tools", "notes"):
        (output / name).mkdir()
    write_json(output / "run.json", {"schema_version": 1, "run_id": run_id,
               "created_at": created, "mode": "static-only", "source_roots": [root],
               "kit_root": str(KIT_ROOT)})
    write_json(output / "state.json", {"schema_version": 1, "status": "active",
               "next_actions": [], "blockers": [], "updated_at": created})
    write_json(output / "coverage.json", {"schema_version": 1, "units": []})
    documents = {
        "RUN.md": "# 정적 보안 조사\n\n- 조사 ID: {}\n- 생성 시점: {}\n- 모드: static-only\n- 소스 루트 primary: {}\n\n조사 범위와 배포 조건은 검토 대기 상태다. 초기화는 소스 검토가 아니다.\n".format(run_id, created, target),
        "CHECKPOINT.md": "# 조사 체크포인트\n\n상태: active. 초기 작업 공간만 생성했다.\n\n## 다음 작업\n\n- 소스 목록과 범위를 확인한다.\n- 아키텍처와 보안 불변조건을 근거로 모델링한다.\n- 검토 단위를 coverage.json에 명시한다.\n\n## 차단·미확인\n\n아직 조사하지 않았으므로 배포 조건·권한 경계·결함 여부는 미확인이다.\n",
        "architecture.md": "# 아키텍처 모델\n\n상태: pending. 구성 요소·흐름·실행 문맥·신뢰 경계는 아직 검토하지 않았다.\n\n사실, 가정, 추론과 소스 참조를 구분해 갱신한다.\n",
        "threat-model.md": "# 위협 모델\n\n상태: pending. 행위자·초기 능력·자산·보안 불변조건·권한 전환은 아직 검토하지 않았다.\n\n배포 상태를 추측하거나 검토 공백을 안전으로 처리하지 않는다.\n",
    }
    for name, content in documents.items():
        (output / name).write_text(content, encoding="utf-8")
    template = KIT_ROOT / "templates" / "REPORT.md"
    if template.is_file():
        shutil.copyfile(template, output / "REPORT.md")
    print(output)


def add_root(args):
    run, metadata = load_run(args.run)
    root_id = validate_root_id(args.id)
    source = source_directory(args.path)
    check_output_location(run, source)
    for root in metadata["source_roots"]:
        other = Path(root["path"]).resolve()
        if root["id"] == root_id:
            raise ValueError("source root ID already exists")
        if within(source, other) or within(other, source):
            raise ValueError("source root overlaps an existing root; attribution would be ambiguous")
    record = root_record(root_id, source)
    metadata["source_roots"].append(record)
    write_json(run / "run.json", metadata)
    print(json.dumps(record, ensure_ascii=False))


def inventory(args):
    run, metadata = load_run(args.run)
    source = select_root(metadata, args.root)
    evidence = run / "evidence"
    if evidence.is_symlink() or not evidence.is_dir():
        raise ValueError("run evidence must be an existing directory, not a symlink")
    entries, excluded, errors = [], [], []
    truncated = False
    skip_paths = {run, KIT_ROOT / "runs", KIT_ROOT / ".tools"}

    def relative(path):
        return Path(path).relative_to(source).as_posix()

    def on_error(error):
        name = error.filename
        try:
            label = relative(name) if name else "."
        except ValueError:
            label = "."
        errors.append({"path": label, "error": type(error).__name__})

    for current, directories, files in os.walk(source, topdown=True, onerror=on_error,
                                                followlinks=False):
        base = Path(current)
        directories.sort()
        files.sort()
        retained = []
        candidates = list(files)
        for name in directories:
            path = base / name
            if path.is_symlink():
                candidates.append(name)
            elif name == ".git":
                excluded.append({"path": relative(path), "reason": "git internals"})
            elif path in skip_paths:
                excluded.append({"path": relative(path), "reason": "investigation output or toolkit tool cache"})
            else:
                retained.append(name)
        directories[:] = retained
        for name in sorted(candidates):
            if len(entries) >= args.max_files:
                truncated = True
                break
            path = base / name
            try:
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    kind = "symlink"
                elif stat.S_ISREG(info.st_mode):
                    kind = "file"
                else:
                    errors.append({"path": relative(path), "error": "unsupported_file_kind"})
                    continue
                entries.append({"path": relative(path), "kind": kind, "size": info.st_size})
            except OSError as error:
                on_error(error)
        if truncated:
            break
    complete = not truncated and not errors
    result = {"source_root_id": args.root, "complete_enumeration": complete,
              "status": "enumerated" if complete else "pending", "truncated": truncated,
              "max_files": args.max_files, "collected_at": utc_now(),
              "entries": entries, "excluded": excluded, "errors": errors,
              "review_status": "unreviewed"}
    destination = evidence / "inventory-{}.json".format(args.root)
    write_json(destination, result)
    print(json.dumps({"path": str(destination), "entries": len(entries),
                      "complete_enumeration": complete, "status": result["status"],
                      "truncated": truncated, "errors": len(errors)}, ensure_ascii=False))


def reference(args):
    _, metadata = load_run(args.run)
    source = select_root(metadata, args.root)
    relative = Path(args.path)
    if relative.is_absolute() or not args.path or ".." in relative.parts:
        raise ValueError("reference path must be relative and cannot contain '..'")
    path = (source / relative).resolve(strict=True)
    if not within(path, source):
        raise ValueError("reference path escapes its declared source root")
    if not path.is_file():
        raise ValueError("reference must be a regular file")
    with path.open("rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("reference must be a regular file")
        content = handle.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("reference file must be valid UTF-8") from None
    line_count = len(text.splitlines())
    if args.start < 1 or args.end < args.start or args.end > line_count:
        raise ValueError("line range must be positive, ordered and within the file ({} lines)".format(line_count))
    result = {"root_id": args.root, "path": relative.as_posix(),
              "start_line": args.start, "end_line": args.end,
              "sha256": hashlib.sha256(content).hexdigest(),
              "symbol": args.symbol, "claim": args.claim}
    print(json.dumps(result, ensure_ascii=False))


def positive_integer(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("init", help="create a fresh static-only investigation")
    command.add_argument("--target", required=True)
    command.add_argument("--output")
    command.set_defaults(action=initialize)
    command = commands.add_parser("add-root", help="register another non-overlapping source root")
    command.add_argument("--run", required=True)
    command.add_argument("--id", required=True)
    command.add_argument("--path", required=True)
    command.set_defaults(action=add_root)
    command = commands.add_parser("inventory", help="enumerate metadata without reading source contents")
    command.add_argument("--run", required=True)
    command.add_argument("--root", default="primary")
    command.add_argument("--max-files", type=positive_integer, default=100000)
    command.set_defaults(action=inventory)
    command = commands.add_parser("ref", help="emit a source reference without snippets or writes")
    command.add_argument("--run", required=True)
    command.add_argument("--root", required=True)
    command.add_argument("--path", required=True)
    command.add_argument("--start", required=True, type=positive_integer)
    command.add_argument("--end", required=True, type=positive_integer)
    command.add_argument("--symbol", required=True)
    command.add_argument("--claim", required=True)
    command.set_defaults(action=reference)
    args = parser.parse_args(argv)
    try:
        args.action(args)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        if isinstance(error, json.JSONDecodeError):
            message = "malformed JSON workspace metadata"
        elif isinstance(error, UnicodeError):
            message = "workspace metadata must be valid UTF-8"
        elif isinstance(error, OSError):
            message = "filesystem operation failed ({}): {}".format(type(error).__name__, error.filename or "workspace")
        else:
            message = str(error)
        parser.error(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
