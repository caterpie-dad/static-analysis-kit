#!/usr/bin/env python3
"""Check kit structure and evidence references without claiming semantic validation."""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

try:
    import tomllib
    TOML_PARSER_NAME = "tomllib"
except ImportError:
    try:
        import tomli as tomllib
        TOML_PARSER_NAME = "tomli"
    except ImportError:
        try:
            import pip._vendor.tomli as tomllib
            TOML_PARSER_NAME = "pip._vendor.tomli"
        except ImportError:
            tomllib = None
            TOML_PARSER_NAME = "unavailable"


REQUIRED_FILES = (
    "README.md",
    "START_HERE.md",
    "AGENTS.md",
    "SECURITY.md",
    ".agents/skills/system-static-analysis/SKILL.md",
    ".codex/config.toml",
    ".codex/agents/static-analyst.toml",
    ".codex/agents/static-inventory.toml",
    ".codex/agents/static-reviewer.toml",
    "references/investigation.md",
    "references/evidence.md",
    "references/tooling.md",
    "references/model-routing.md",
    "references/sources.md",
    "templates/REPORT.md",
    "scripts/capabilities.py",
    "scripts/workspace.py",
    "scripts/install_python_tool.py",
    "scripts/check_kit.py",
    "schemas/run.schema.json",
    "schemas/state.schema.json",
    "schemas/source-ref.schema.json",
    "schemas/coverage.schema.json",
    "schemas/finding.schema.json",
)
AGENT_KEYS = ("name", "description", "developer_instructions", "model", "model_reasoning_effort")
FINDING_STATUSES = {"hypothesis", "source-supported", "conditional", "rejected", "merged", "needs-evidence"}
COVERAGE_STATUSES = {"reviewed", "partial", "unreviewed", "blocked", "excluded"}
EDGE_STATUSES = {"observed", "conditional", "unknown"}
PLACEHOLDER_PATTERNS = (
    re.compile(r"\bTODO\b", re.IGNORECASE),
    re.compile(r"\bFIXME\b", re.IGNORECASE),
    re.compile(r"\bREPLACE_ME\b", re.IGNORECASE),
    re.compile(r"\bINSERT[_ -](?:HERE|VALUE|TEXT)\b", re.IGNORECASE),
)
LINK_RE = re.compile(r"!?\[[^\]]*\]\((.*?)\)")
ESCAPED_MARKDOWN_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!<>|])")


class Checker:
    def __init__(self, root):
        self.root = root.resolve()
        self.errors = []
        self.stats = {"files_checked": 0, "schemas_checked": 0, "source_refs_checked": 0}

    def error(self, path, message):
        try:
            label = str(Path(path).resolve().relative_to(self.root))
        except (ValueError, OSError):
            label = str(path)
        self.errors.append(f"{label}: {message}")

    def _walk_files(self):
        skipped = {".git", "__pycache__", ".tools", "runs"}
        for directory, subdirs, filenames in os.walk(self.root):
            subdirs[:] = sorted(name for name in subdirs if name not in skipped)
            for filename in filenames:
                yield Path(directory) / filename

    def read_json(self, path):
        try:
            with path.open("r", encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            self.error(path, f"invalid or unreadable JSON ({type(exc).__name__})")
            return None

    @staticmethod
    def _read_toml(path):
        return tomllib.loads(path.read_text(encoding="utf-8"))

    def check_required_files(self):
        for relative in REQUIRED_FILES:
            path = self.root / relative
            if not path.is_file():
                self.error(relative, "required file is missing")

    def check_markdown_links(self):
        for path in self._walk_files():
            if path.suffix.lower() != ".md":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                self.error(path, f"cannot read Markdown ({type(exc).__name__})")
                continue
            self.stats["files_checked"] += 1
            text = re.sub(r"(?ms)^\s*(```|~~~).*?^\s*\1\s*$", "", text)
            for match in LINK_RE.finditer(text):
                destination = match.group(1).strip()
                if not destination:
                    continue
                if destination.startswith("<") and ">" in destination:
                    destination = destination[1:destination.index(">")]
                else:
                    destination = re.split(r"\s+['\"]", destination, maxsplit=1)[0]
                destination = ESCAPED_MARKDOWN_RE.sub(r"\1", destination)
                if not destination or destination.startswith("#"):
                    continue
                parsed = urlsplit(destination)
                if parsed.scheme or parsed.netloc or destination.startswith("/"):
                    continue
                local_path = unquote(parsed.path)
                if not local_path:
                    continue
                target = (path.parent / local_path).resolve()
                if not target.exists():
                    self.error(path, f"broken local link: {destination}")

    def check_toml_and_skill(self):
        config = self.root / ".codex/config.toml"
        if tomllib is None:
            self.error(config, "no TOML parser available; use Python 3.11 or install tomli")
            return
        if config.is_file():
            try:
                self._read_toml(config)
            except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
                self.error(config, f"invalid TOML ({type(exc).__name__})")
        for path in sorted((self.root / ".codex/agents").glob("*.toml")):
            try:
                data = self._read_toml(path)
            except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
                self.error(path, f"invalid TOML ({type(exc).__name__})")
                continue
            for key in AGENT_KEYS:
                if not isinstance(data.get(key), str) or not data[key].strip():
                    self.error(path, f"agent field {key!r} must be a nonempty string")

        skill = self.root / ".agents/skills/system-static-analysis/SKILL.md"
        if skill.is_file():
            try:
                text = skill.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                self.error(skill, f"cannot read skill ({type(exc).__name__})")
                return
            frontmatter = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|\Z)", text, re.DOTALL)
            if not frontmatter:
                self.error(skill, "missing YAML frontmatter")
                return
            values = {}
            for line in frontmatter.group(1).splitlines():
                found = re.match(r"^(name|description):\s*(.*?)\s*$", line)
                if found:
                    values[found.group(1)] = found.group(2).strip().strip("\"'")
            if not values.get("name"):
                self.error(skill, "frontmatter name is required")
            elif not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", values["name"]):
                self.error(skill, "frontmatter name must be lowercase kebab-case")
            if not values.get("description"):
                self.error(skill, "frontmatter description is required")

    def check_placeholders(self):
        for path in self._walk_files():
            if path.name == "check_kit.py":
                continue
            if path.suffix.lower() not in {".md", ".py", ".toml", ".json", ".yaml", ".yml", ".txt"}:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for pattern in PLACEHOLDER_PATTERNS:
                if pattern.search(content):
                    self.error(path, f"scaffold placeholder matched {pattern.pattern!r}")
                    break

    def check_schemas(self):
        schema_dir = self.root / "schemas"
        schema_paths = sorted(schema_dir.glob("*.json")) if schema_dir.is_dir() else []
        if not schema_paths:
            self.error("schemas", "no JSON schemas found")
            return
        for path in schema_paths:
            self.stats["schemas_checked"] += 1
            self.read_json(path)

    @staticmethod
    def _required_object(value, required, label, path, checker):
        if not isinstance(value, dict):
            checker.error(path, f"{label} must be an object")
            return False
        for key in required:
            if key not in value:
                checker.error(path, f"{label}.{key} is required")
        return True

    def _source_ref(self, ref, roots, label):
        required = ("root_id", "path", "start_line", "end_line", "sha256", "symbol", "claim")
        if not self._required_object(ref, required, label, label, self):
            return
        root_id, relative = ref.get("root_id"), ref.get("path")
        if not isinstance(root_id, str) or root_id not in roots:
            self.error(label, "root_id does not identify a declared source root")
            return
        if not isinstance(relative, str) or not relative:
            self.error(label, "path must be a nonempty relative path")
            return
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            self.error(label, "source path must be relative and cannot contain parent traversal")
            return
        root = roots[root_id]
        candidate = (root / relative_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            self.error(label, "source path escapes its declared root")
            return
        if not candidate.is_file():
            self.error(label, "source path is not a regular file")
            return
        try:
            data = candidate.read_bytes()
            data.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            self.error(label, f"source is unreadable or not UTF-8 ({type(exc).__name__})")
            return
        digest = hashlib.sha256(data).hexdigest()
        if not isinstance(ref.get("sha256"), str) or ref["sha256"].lower() != digest:
            self.error(label, "source SHA-256 is stale or invalid")
        try:
            lines = data.decode("utf-8").splitlines()
        except UnicodeError:
            return
        start, end = ref.get("start_line"), ref.get("end_line")
        if (not isinstance(start, int) or isinstance(start, bool) or
                not isinstance(end, int) or isinstance(end, bool) or
                start < 1 or end < start or end > len(lines)):
            self.error(label, "line range must be valid and 1-based")
        if not isinstance(ref.get("symbol"), str):
            self.error(label, "symbol must be a string")
        if not isinstance(ref.get("claim"), str) or not ref["claim"].strip():
            self.error(label, "claim must be a nonempty string")
        self.stats["source_refs_checked"] += 1

    def check_run(self, run_path):
        run_path = run_path.resolve()
        run_dir = run_path.parent
        run = self.read_json(run_path)
        if run is None:
            return
        if not isinstance(run, dict):
            self.error(run_path, "run.json must contain an object")
            return
        if run.get("schema_version") != 1:
            self.error(run_path, "schema_version must be 1")
        if run.get("mode") != "static-only":
            self.error(run_path, "mode must be static-only")
        source_roots = run.get("source_roots")
        roots = {}
        root_ids = set()
        if not isinstance(source_roots, list) or not source_roots:
            self.error(run_path, "source_roots must be a nonempty array")
        else:
            for index, root_item in enumerate(source_roots):
                label = f"{run_path}:source_roots[{index}]"
                if not self._required_object(root_item, ("id", "path"), "source root", label, self):
                    continue
                root_id, root_path = root_item.get("id"), root_item.get("path")
                if not isinstance(root_id, str) or not root_id:
                    self.error(label, "id must be a nonempty string")
                    continue
                if root_id in root_ids:
                    self.error(label, f"duplicate source root id {root_id!r}")
                    continue
                root_ids.add(root_id)
                if not isinstance(root_path, str) or not Path(root_path).is_absolute():
                    self.error(label, "path must be absolute")
                    continue
                resolved = Path(root_path).resolve()
                if not resolved.is_dir():
                    self.error(label, "source root must be an existing directory")
                    continue
                roots[root_id] = resolved

        state_path = run_dir / "state.json"
        state = self.read_json(state_path)
        if isinstance(state, dict):
            if state.get("schema_version") != 1:
                self.error(state_path, "schema_version must be 1")
            state_status = state.get("status")
            if not isinstance(state_status, str) or state_status not in {"active", "complete", "partial", "blocked"}:
                self.error(state_path, "status must be active, complete, partial, or blocked")
            for key in ("next_actions", "blockers"):
                values = state.get(key)
                if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                    self.error(state_path, f"{key} must be an array of strings")
            if not isinstance(state.get("updated_at"), str) or not state["updated_at"].strip():
                self.error(state_path, "updated_at must be a nonempty string")
        elif state is not None:
            self.error(state_path, "state.json must contain an object")

        coverage_path = run_dir / "coverage.json"
        coverage = self.read_json(coverage_path)
        if isinstance(coverage, dict):
            if coverage.get("schema_version") != 1:
                self.error(coverage_path, "schema_version must be 1")
            units = coverage.get("units")
            if not isinstance(units, list):
                self.error(coverage_path, "units must be an array")
            else:
                unit_ids = set()
                for index, unit in enumerate(units):
                    label = f"{coverage_path}:units[{index}]"
                    fields = ("id", "kind", "locator", "status", "questions", "source_refs", "rationale", "next_action")
                    if not self._required_object(unit, fields, "coverage unit", label, self):
                        continue
                    unit_status = unit.get("status")
                    if not isinstance(unit_status, str) or unit_status not in COVERAGE_STATUSES:
                        self.error(label, "status is not a recognized coverage status")
                    for key in ("id", "kind", "locator"):
                        if not isinstance(unit.get(key), str) or not unit[key].strip():
                            self.error(label, f"{key} must be a nonempty string")
                    unit_id = unit.get("id")
                    if isinstance(unit_id, str) and unit_id:
                        if unit_id in unit_ids:
                            self.error(label, f"duplicate coverage unit id {unit_id!r}")
                        unit_ids.add(unit_id)
                    for key in ("questions", "source_refs"):
                        if not isinstance(unit.get(key), list):
                            self.error(label, f"{key} must be an array")
                    for key in ("rationale", "next_action"):
                        if not isinstance(unit.get(key), str):
                            self.error(label, f"{key} must be a string")
                    refs = unit.get("source_refs")
                    if isinstance(refs, list):
                        for ref_index, ref in enumerate(refs):
                            self._source_ref(ref, roots, f"{label}.source_refs[{ref_index}]")
                    questions = unit.get("questions")
                    if isinstance(questions, list) and any(not isinstance(question, str) for question in questions):
                        self.error(label, "questions items must be strings")
                    if unit_status == "reviewed":
                        if not isinstance(questions, list) or not questions:
                            self.error(label, "reviewed units require nonempty questions")
                        if not isinstance(refs, list) or not refs:
                            self.error(label, "reviewed units require nonempty source_refs")
                    if unit_status in {"blocked", "excluded"} and not (isinstance(unit.get("rationale"), str) and unit["rationale"].strip()):
                        self.error(label, "blocked/excluded units require rationale")
                    if unit_status in {"partial", "unreviewed"} and not (isinstance(unit.get("next_action"), str) and unit["next_action"].strip()):
                        self.error(label, "partial/unreviewed units require next_action")
        elif coverage is not None:
            self.error(coverage_path, "coverage.json must contain an object")

        findings_dir = run_dir / "findings"
        if findings_dir.is_dir():
            finding_records = []
            finding_ids = set()
            for finding_path in sorted(findings_dir.glob("*.json")):
                finding = self.read_json(finding_path)
                if not isinstance(finding, dict):
                    continue
                finding_records.append((finding_path, finding))
                finding_id = finding.get("id")
                if isinstance(finding_id, str) and finding_id:
                    if finding_id in finding_ids:
                        self.error(finding_path, f"duplicate finding id {finding_id!r}")
                    finding_ids.add(finding_id)

            for finding_path, finding in finding_records:
                label = finding_path
                fields = ("id", "title", "status", "hypothesis", "attacker", "preconditions", "invariant", "chain", "source_refs", "counterevidence", "impact", "uncertainties", "review", "next_action")
                if not self._required_object(finding, fields, "finding", label, self):
                    continue
                finding_status = finding.get("status")
                if not isinstance(finding_status, str) or finding_status not in FINDING_STATUSES:
                    self.error(label, "status is not a recognized finding status")
                for key in ("id", "title", "hypothesis", "attacker", "invariant", "next_action"):
                    if not isinstance(finding.get(key), str) or not finding[key].strip():
                        self.error(label, f"{key} must be a nonempty string")
                for key in ("preconditions", "chain", "source_refs", "counterevidence", "uncertainties"):
                    if not isinstance(finding.get(key), list):
                        self.error(label, f"{key} must be an array")
                refs = finding.get("source_refs")
                if isinstance(refs, list):
                    for ref_index, ref in enumerate(refs):
                        self._source_ref(ref, roots, f"{label}.source_refs[{ref_index}]")
                chain = finding.get("chain")
                if isinstance(chain, list):
                    for edge_index, edge in enumerate(chain):
                        edge_label = f"{label}.chain[{edge_index}]"
                        required_edge = ("from", "to", "transition", "requires", "controls", "evidence_indices", "status")
                        if not self._required_object(edge, required_edge, "chain edge", edge_label, self):
                            continue
                        for key in ("from", "to", "transition"):
                            if not isinstance(edge.get(key), str) or not edge[key].strip():
                                self.error(edge_label, f"{key} must be a nonempty string")
                        for key in ("requires", "controls", "evidence_indices"):
                            if not isinstance(edge.get(key), list):
                                self.error(edge_label, f"{key} must be an array")
                        edge_status = edge.get("status")
                        if not isinstance(edge_status, str) or edge_status not in EDGE_STATUSES:
                            self.error(edge_label, "status is not observed, conditional, or unknown")
                        for key in ("requires", "controls"):
                            values = edge.get(key)
                            if isinstance(values, list) and any(not isinstance(value, str) for value in values):
                                self.error(edge_label, f"{key} items must be strings")
                        indices = edge.get("evidence_indices")
                        if isinstance(indices, list):
                            for evidence_index in indices:
                                if (not isinstance(evidence_index, int) or isinstance(evidence_index, bool)
                                        or not isinstance(refs, list) or evidence_index < 0 or evidence_index >= len(refs)):
                                    self.error(edge_label, "evidence_indices must index finding.source_refs")
                impact = finding.get("impact")
                if self._required_object(impact, ("scope", "statement", "runtime_verified", "conditions"), "impact", label, self):
                    for key in ("scope", "statement"):
                        if not isinstance(impact.get(key), str) or not impact[key].strip():
                            self.error(label, f"impact.{key} must be a nonempty string")
                    if impact.get("runtime_verified") is not False:
                        self.error(label, "static runs require impact.runtime_verified=false")
                    if not isinstance(impact.get("conditions"), list):
                        self.error(label, "impact.conditions must be an array")
                review = finding.get("review")
                if self._required_object(review, ("status", "reviewer", "model", "conclusion"), "review", label, self):
                    review_status = review.get("status")
                    if not isinstance(review_status, str) or review_status not in {"pending", "reviewed"}:
                        self.error(label, "review.status must be pending or reviewed")
                    for key in ("reviewer", "model"):
                        if review.get(key) is not None and not isinstance(review.get(key), str):
                            self.error(label, f"review.{key} must be a string or null")
                    if not isinstance(review.get("conclusion"), str):
                        self.error(label, "review.conclusion must be a string")
                status = finding_status if isinstance(finding_status, str) else ""
                if status == "source-supported":
                    if not isinstance(refs, list) or not refs:
                        self.error(label, "source-supported findings require source_refs")
                    if not isinstance(chain, list) or not chain:
                        self.error(label, "source-supported findings require chain")
                    if not isinstance(review, dict) or review.get("status") != "reviewed":
                        self.error(label, "source-supported findings require review.status=reviewed")
                if status == "conditional":
                    uncertainties = finding.get("uncertainties")
                    preconditions = finding.get("preconditions")
                    if not ((isinstance(uncertainties, list) and uncertainties) or
                            (isinstance(preconditions, list) and preconditions)):
                        self.error(label, "conditional findings require uncertainties or preconditions")
                if status in {"rejected", "merged"} and not (isinstance(finding.get("next_action"), str) and finding["next_action"].strip()):
                    self.error(label, "rejected/merged findings require next_action")
                if status == "merged":
                    merged_into = finding.get("merged_into")
                    if not isinstance(merged_into, str) or not merged_into:
                        self.error(label, "merged findings require merged_into")
                    elif merged_into == finding.get("id") or merged_into not in finding_ids:
                        self.error(label, "merged_into must identify another finding in this run")

    def run(self, run_path=None):
        self.check_required_files()
        self.check_markdown_links()
        self.check_toml_and_skill()
        self.check_placeholders()
        self.check_schemas()
        if run_path is not None:
            self.check_run(run_path)
        return {
            "ok": not self.errors,
            "structural_checks_only": True,
            "toml_parser": TOML_PARSER_NAME,
            "summary": self.stats,
            "errors": self.errors,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", help="validate a run directory or its run.json")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    run_path = None
    if args.run:
        selected = Path(args.run).expanduser()
        run_path = (selected / "run.json") if selected.is_dir() else selected
    result = Checker(root).run(run_path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
