"""CPU-only source accounting and review-record checks; never import target code."""

import hashlib
import codecs
import json
import os
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path


BREAKS = re.compile(r"\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]")
FULL_CWE_URL = re.compile(r"https://cwe[.]mitre[.]org/data/xml/cwec_(?:latest|v[0-9]+(?:[.][0-9]+)+)[.]xml(?:[.]zip)?\Z")
CODE_SUFFIXES = {".so", ".dll", ".exe", ".class", ".jar", ".wasm", ".pyc", ".o", ".a",
                 ".py", ".c", ".h", ".cc", ".cpp", ".hpp", ".java", ".kt", ".go", ".rs",
                 ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cs", ".php", ".rb", ".swift",
                 ".sh", ".ps1", ".pl", ".sql", ".json", ".xml", ".yaml", ".yml", ".toml",
                 ".html", ".vue", ".svelte", ".tf", ".gradle", ".scala", ".r", ".lua"}


def file_facts(handle):
    """Hash large files without buffering them; count the same lines as str.splitlines."""
    hasher, size, count, last, text_ok = hashlib.sha256(), 0, 0, "", True
    decoder = codecs.getincrementaldecoder("utf-8")()
    while True:
        chunk = handle.read(1024 * 1024)
        if chunk:
            hasher.update(chunk)
            size += len(chunk)
        if text_ok:
            try:
                text = decoder.decode(chunk, final=not chunk)
                if "\0" in text:
                    text_ok = False
                else:
                    count += len(BREAKS.findall(text)) - int(last == "\r" and text.startswith("\n"))
                    if text:
                        last = text[-1]
            except UnicodeError:
                text_ok = False
        if not chunk:
            break
    lines = (count + int(bool(last) and BREAKS.fullmatch(last) is None)) if text_ok else None
    return hasher.hexdigest(), size, lines


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(roots, skip_paths=()):
    """Include ignored/hidden/vendor files. Only Git internals and our output are omitted."""
    entries, omitted, errors = [], [], []
    skip = {Path(p).resolve() for p in skip_paths}
    for root_id, root in sorted(roots.items()):
        root = Path(root).resolve()

        def fail(error):
            errors.append({"root_id": root_id, "path": str(Path(error.filename).relative_to(root))
                           if error.filename else ".", "error": type(error).__name__})

        for current, directories, files in os.walk(root, topdown=True, followlinks=False, onerror=fail):
            base = Path(current)
            names = list(files)
            retained = []
            for name in sorted(directories):
                path = base / name
                if path.is_symlink():
                    names.append(name)
                elif name == ".git" or path in skip:
                    omitted.append({"root_id": root_id, "path": path.relative_to(root).as_posix(),
                                    "reason": "git internals" if name == ".git" else "kit output/cache"})
                else:
                    retained.append(name)
            directories[:] = retained
            for name in sorted(names):
                path = base / name
                relative = path.relative_to(root).as_posix()
                if name == ".git":
                    omitted.append({"root_id": root_id, "path": relative, "reason": "git internals"})
                    continue
                record = {"root_id": root_id, "path": relative}
                try:
                    before = path.lstat()
                    if stat.S_ISLNK(before.st_mode):
                        target = os.readlink(path)
                        record.update(kind="symlink", target=target,
                                      sha256=digest(os.fsencode(target)), lines=None)
                    elif stat.S_ISREG(before.st_mode):
                        # O_NOFOLLOW refuses a symlink substituted after lstat.
                        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                                     | getattr(os, "O_NONBLOCK", 0))
                        with os.fdopen(fd, "rb") as handle:
                            opened = os.fstat(handle.fileno())
                            if not stat.S_ISREG(opened.st_mode):
                                raise ValueError("file kind changed during snapshot")
                            sha, size, lines = file_facts(handle)
                            after = os.fstat(handle.fileno())
                        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                            raise ValueError("file changed during snapshot")
                        record.update(kind="file", sha256=sha, size=size, lines=lines)
                    else:
                        raise ValueError("unsupported file kind")
                    entries.append(record)
                except (OSError, ValueError) as error:
                    errors.append({"root_id": root_id, "path": relative,
                                   "error": type(error).__name__})
    return {"schema_version": 1, "roots": {k: str(Path(v).resolve()) for k, v in roots.items()},
            "complete_enumeration": not errors, "entries": entries,
            "excluded": omitted, "errors": errors}


def cwe_catalog(data):
    """Read the full CWE XML, including entries outside a small Top-N view."""
    # Catalogs are downloaded data, never plugins; disallow entity declarations.
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("CWE XML must not contain DTD/entity declarations")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("malformed CWE XML") from error
    if (root.tag.rsplit("}", 1)[-1] != "Weakness_Catalog" or root.get("Name") != "CWE"
            or not root.get("Version")):
        raise ValueError("expected a versioned full CWE Weakness_Catalog, not a view")
    rows = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "Weakness":
            number = node.get("ID", "")
            if not number.isdigit() or not node.get("Name"):
                raise ValueError("invalid CWE weakness ID/name")
            rows.append({"id": "CWE-" + number, "name": node.get("Name"),
                         "catalog_status": node.get("Status", "unknown")})
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("CWE catalog must contain unique weaknesses")
    return root.get("Version"), rows


def artifact(run, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("artifact path must be run-relative")
    path = (run / relative).resolve(strict=True)
    if run.resolve() not in path.parents or not path.is_file():
        raise ValueError("artifact escapes run or is not a file")
    return path


def read_object(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def verified_cwe_catalog(data, kit):
    version, rows = cwe_catalog(data)
    locks = read_object(kit / "references/cwe-catalogs.json").get("releases", {})
    release = locks.get(version) if isinstance(locks, dict) else None
    if (not isinstance(release, dict) or release.get("xml_sha256") != digest(data)
            or release.get("weaknesses") != len(rows)):
        raise ValueError("full CWE release bytes/count do not match the kit pin; independently verify the official full release before updating references/cwe-catalogs.json")
    return version, rows


def check_contract(checker, run, roots, coverage, state, require_ready=False):
    """Reject incomplete records, without claiming their semantic judgments are true."""
    complete = state.get("status") == "complete"
    label = run / "evidence/source-inventory.json"
    try:
        saved = read_object(artifact(run, "evidence/source-inventory.json"))
        from kit_paths import runtime_paths
        current = snapshot(roots, (run, *runtime_paths(checker.root)))
        if not saved.get("complete_enumeration") or current["errors"]:
            checker.error(label, "source enumeration is incomplete; 100% coverage is unavailable")
        if (saved.get("roots") != current["roots"] or saved.get("entries") != current["entries"]
                or saved.get("excluded") != current["excluded"]):
            checker.error(label, "source inventory/SHA-256 changed; refresh snapshot and re-review changed sources")
        entries = current["entries"]
    except (OSError, ValueError, TypeError) as error:
        checker.error(label, f"missing/invalid source inventory ({type(error).__name__})")
        entries = []

    units = coverage.get("units", []) if isinstance(coverage, dict) else []
    units = [u for u in units if isinstance(u, dict)] if isinstance(units, list) else []
    reviewed = {u.get("id") for u in units if u.get("status") == "reviewed"
                and isinstance(u.get("id"), str)}
    spans = {}
    for unit in units:
        if unit.get("status") != "reviewed" or not isinstance(unit.get("source_refs"), list):
            continue
        for ref in unit["source_refs"]:
            if not isinstance(ref, dict):
                continue
            a, b = ref.get("start_line"), ref.get("end_line")
            if type(a) is int and type(b) is int and 1 <= a <= b:
                key = (ref.get("root_id"), ref.get("path"), ref.get("sha256"))
                if all(isinstance(part, str) for part in key):
                    spans.setdefault(key, []).append((a, b))
    files, covered_files, total_lines, covered_lines = 0, 0, 0, 0
    opaque = coverage.get("non_source_files", []) if isinstance(coverage, dict) else []
    opaque = opaque if isinstance(opaque, list) else []
    for entry in entries:
        if entry["kind"] == "symlink":
            if complete or require_ready:
                try:
                    dest = (roots[entry["root_id"]] / entry["path"]).resolve(strict=True)
                    if not any(dest == r or r in dest.parents for r in roots.values()):
                        raise ValueError("unregistered symlink target")
                except (OSError, RuntimeError, ValueError):
                    checker.error(label, f"unresolved/unregistered symlink: {entry['root_id']}:{entry['path']}")
            continue
        if entry["lines"] is None:
            # Binary/non-UTF-8 input is never silently counted as reviewed source.
            disposition = [d for d in opaque if isinstance(d, dict) and all(
                d.get(k) == entry[k] for k in ("root_id", "path", "sha256"))]
            executable = Path(entry["path"]).suffix.lower() in CODE_SUFFIXES
            if (complete or require_ready) and (executable or len(disposition) != 1 or not all(
                    isinstance(disposition[0].get(k), str) and disposition[0][k].strip()
                    for k in ("rationale", "reviewer"))):
                checker.error(label, f"opaque/code artifact needs source or justified non-source classification: {entry['path']}")
            continue
        files += 1
        count = entry["lines"]
        total_lines += count
        cursor, covered = 1, 0
        for start, end in sorted(spans.get((entry["root_id"], entry["path"], entry["sha256"]), [])):
            if start > cursor:
                # Keep gaps in the denominator; later intervals still count.
                cursor = start
            end = min(end, count)
            if end >= cursor:
                covered += end - cursor + 1
                cursor = end + 1
        covered_lines += covered
        if count == 0:
            empty_records = coverage.get("empty_files", []) if isinstance(coverage, dict) else []
            empty_records = empty_records if isinstance(empty_records, list) else []
            confirmed = [d for d in empty_records if isinstance(d, dict) and all(
                d.get(k) == entry[k] for k in ("root_id", "path", "sha256")) and all(
                isinstance(d.get(k), str) and d[k].strip() for k in ("rationale", "reviewer"))]
            if len(confirmed) == 1:
                covered_files += 1
            elif complete:
                checker.error(label, f"empty source file needs an explicit review record: {entry['path']}")
        elif covered == count:
            covered_files += 1
        elif complete:
            checker.error(label, f"source review below 100%: {entry['root_id']}:{entry['path']} ({covered}/{count} lines)")
    checker.stats.update(source_files=files, reviewed_source_files=covered_files,
                         source_lines=total_lines, reviewed_source_lines=covered_lines)
    if complete:
        if not files:
            checker.error(label, "complete requires a nonempty source inventory")
        if any(u.get("status") != "reviewed" for u in units):
            checker.error(run / "coverage.json", "complete requires every review unit to be reviewed")
        if state.get("blockers") or state.get("next_actions"):
            checker.error(run / "state.json", "complete cannot retain required next_actions/blockers")

    plan_path = run / "review-plan.json"
    try:
        plan = read_object(artifact(run, "review-plan.json"))
    except (OSError, ValueError, TypeError) as error:
        checker.error(plan_path, f"missing/invalid review plan ({type(error).__name__})")
        return
    ready = plan.get("phase") == "ready"
    if plan.get("schema_version") != 1 or plan.get("phase") not in ("preparing", "ready"):
        checker.error(plan_path, "review plan needs schema_version=1 and phase preparing/ready")
    for key in ("stack", "catalogs", "weaknesses", "tasks", "resources"):
        if not isinstance(plan.get(key), list):
            checker.error(plan_path, f"review-plan.{key} must be an array")
    checker.stats["preparation_ready"] = ready
    if not ready and any((run / "findings").glob("*.json")):
        checker.error(plan_path, "finding analysis requires ready preparation; keep preliminary leads in notes")
    if not (complete or require_ready or ready):
        return
    if not ready:
        checker.error(plan_path, "review-plan.phase must be ready before analysis/completion")
    stacks = plan.get("stack")
    if not isinstance(stacks, list) or not stacks:
        checker.error(plan_path, "technology stack with source evidence is required")
        stacks = []
    stack_ids, security_links = set(), []
    for stack in stacks:
        if not isinstance(stack, dict) or not isinstance(stack.get("id"), str):
            checker.error(plan_path, "invalid technology stack entry")
            continue
        if (stack["id"] in stack_ids or not stack["id"].strip()
                or not isinstance(stack.get("name"), str) or not stack["name"].strip()
                or "version" not in stack or not (stack["version"] is None or isinstance(stack["version"], str))):
            checker.error(plan_path, "technology stack IDs/names must be unique/nonempty")
        stack_ids.add(stack["id"])
        security_refs = stack.get("security_resources")
        if not isinstance(security_refs, list) or not security_refs or any(
                not isinstance(key, str) or not key.strip() for key in security_refs):
            checker.error(plan_path, "every stack needs linked official security_resources")
        else:
            security_links.extend(security_refs)
        refs = stack.get("source_refs")
        if not isinstance(refs, list) or not refs:
            checker.error(plan_path, "stack entries require source_refs")
        else:
            for ref in refs:
                checker._source_ref(ref, roots, plan_path)
    expected = set()
    catalogs = plan.get("catalogs", [])
    for catalog in catalogs if isinstance(catalogs, list) else []:
        try:
            if not isinstance(catalog, dict) or catalog.get("id") != "cwe":
                raise ValueError("expected full CWE catalog")
            data = artifact(run, catalog.get("path")).read_bytes()
            version, rows = verified_cwe_catalog(data, checker.root)
            if (catalog.get("sha256") != digest(data) or catalog.get("version") != version
                    or not isinstance(catalog.get("url"), str)
                    or FULL_CWE_URL.fullmatch(catalog["url"]) is None):
                raise ValueError("catalog provenance/hash/version mismatch")
            expected.update(row["id"] for row in rows)
        except (OSError, ValueError, TypeError) as error:
            checker.error(plan_path, f"invalid full CWE catalog ({type(error).__name__})")
    if not expected:
        checker.error(plan_path, "a pinned full CWE XML catalog is required; Top-N lists are insufficient")
    weaknesses = plan.get("weaknesses", [])
    weaknesses = weaknesses if isinstance(weaknesses, list) else []
    seen, pairs, applicable_stacks = set(), set(), set()
    planned = {u.get("id") for u in units if isinstance(u.get("id"), str)}
    for row in weaknesses:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            checker.error(plan_path, "invalid weakness mapping")
            continue
        key = row["id"]
        seen.add(key)
        links = row.get("coverage_unit_ids")
        if (row.get("status") not in ("pending", "reviewed", "blocked") or not isinstance(links, list)
                or any(not isinstance(link, str) or not link.strip() for link in links)):
            checker.error(plan_path, f"weakness needs status and coverage_unit_ids: {key}")
            links = []
        ids = row.get("stack_ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(s, str) or s not in stack_ids for s in ids):
            checker.error(plan_path, f"weakness needs valid stack_ids: {key}")
            ids = []
        for stack_id in ids:
            pair = (key, stack_id)
            if pair in pairs:
                checker.error(plan_path, "duplicate weakness/stack mapping")
            pairs.add(pair)
        if (row.get("applicability") not in ("applicable", "not-applicable")
                or not isinstance(row.get("rationale"), str) or not row["rationale"].strip()):
            checker.error(plan_path, f"weakness applicability/rationale pending: {key}")
        if row.get("applicability") == "applicable":
            applicable_stacks.update(ids)
            if not links or any(link not in planned for link in links):
                checker.error(plan_path, f"applicable weakness needs planned review units before analysis: {key}")
            if complete and (row.get("status") != "reviewed" or not isinstance(links, list)
                             or not links or any(not isinstance(k, str) or k not in reviewed for k in links)):
                checker.error(plan_path, f"applicable weakness is not linked to completed review: {key}")
        elif row.get("applicability") == "not-applicable" and row.get("status") != "reviewed":
            checker.error(plan_path, f"non-applicability requires a completed decision: {key}")
    if not expected.issubset(seen):
        checker.error(plan_path, "weakness matrix omits entries from the full CWE catalog")
    if any((key, stack_id) not in pairs for key in expected for stack_id in stack_ids):
        checker.error(plan_path, "every CWE/stack pair needs an explicit applicability decision")
    if stack_ids - applicable_stacks:
        checker.error(plan_path, "every stack component needs applicable weakness analysis")
    tasks = plan.get("tasks", [])
    tasks = tasks if isinstance(tasks, list) else []
    if not {"ai", "cpu"}.issubset({t.get("executor") for t in tasks
                                   if isinstance(t, dict) and isinstance(t.get("executor"), str)}):
        checker.error(plan_path, "explicit AI and CPU work assignments are required")
    for task in tasks:
        if not isinstance(task, dict) or task.get("executor") not in ("ai", "cpu") or not all(
                isinstance(task.get(k), str) and task[k].strip() for k in ("id", "purpose", "method")):
            checker.error(plan_path, "invalid AI/CPU task assignment")
            continue
        if complete:
            paths = task.get("result_paths")
            if task.get("status") != "done" or not isinstance(paths, list) or not paths:
                checker.error(plan_path, "all assigned tasks need completed results")
            else:
                for path in paths:
                    try:
                        artifact(run, path)
                    except (OSError, ValueError, TypeError):
                        checker.error(plan_path, "task result is missing or outside the run")
    resources = plan.get("resources", [])
    if not isinstance(resources, list):
        checker.error(plan_path, "resources must be an array")
        resources = []
    available_resources = set()
    for resource in resources:
        try:
            if not isinstance(resource, dict) or resource.get("status") not in ("available", "downloaded"):
                raise ValueError("required resource remains unavailable")
            if not all(isinstance(resource.get(k), str) and resource[k].strip()
                       for k in ("id", "purpose", "url")):
                raise ValueError("resource needs id, purpose and origin")
            if resource["id"] in available_resources:
                raise ValueError("duplicate resource ID")
            data = artifact(run, resource.get("path")).read_bytes()
            if resource.get("sha256") != digest(data):
                raise ValueError("resource origin/hash is missing")
            available_resources.add(resource["id"])
        except (OSError, ValueError, TypeError):
            checker.error(plan_path, "required resource needs downloaded/available artifact, origin and SHA-256")
    if any(key not in available_resources for key in security_links):
        checker.error(plan_path, "stack security_resources must reference available pinned resources")
