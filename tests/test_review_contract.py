"""Offline checks for full-source coverage and preparation/completion boundaries."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_helpers import KIT, module


CATALOG_FIXTURE = ('<Weakness_Catalog Name="CWE" Version="fixture"><Weaknesses>'
                   '<Weakness ID="20" Name="Input validation"/>'
                   '<Weakness ID="862" Name="Authorization"/>'
                   '</Weaknesses></Weakness_Catalog>')


class FullReviewChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="full-source-review-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.kit = self.base / "kit"
        shutil.copytree(KIT, self.kit, ignore=shutil.ignore_patterns(
            ".git", ".tools", "runs", "__pycache__", "*.pyc", ".pytest_cache",
            ".codex", ".claude", ".vibe", ".opencode", "CLAUDE.md"))
        # A test-only pin in the isolated kit admits the synthetic two-entry catalog.
        lock = {"schema_version": 1, "releases": {"fixture": {
            "xml_sha256": hashlib.sha256(CATALOG_FIXTURE.encode()).hexdigest(), "weaknesses": 2}}}
        (self.kit / "references/cwe-catalogs.json").write_text(json.dumps(lock))
        self.source = self.base / "source"
        self.source.mkdir()
        self.code = self.source / "main.py"
        self.code.write_text("def lookup(value):\n    return value\n")
        self.run = self.base / "run"
        self.command("workspace.py", "init", "--target", self.source, "--output", self.run)

    def command(self, script, *args, success=True):
        result = subprocess.run([sys.executable, str(self.kit / "scripts" / script), *map(str, args)],
                                cwd=self.base, capture_output=True, text=True, timeout=30)
        if success and result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result

    def read(self, name):
        return json.loads((self.run / name).read_text())

    def write(self, name, value):
        (self.run / name).write_text(json.dumps(value))

    def check(self, *flags, success=True):
        result = self.command("check_kit.py", "--run", self.run, *flags, success=success)
        self.assertNotIn("Traceback", result.stderr)
        return json.loads(result.stdout)

    def reference(self, start=1, end=2):
        return json.loads(self.command("workspace.py", "ref", "--run", self.run,
                                  "--root", "primary", "--path", "main.py",
                                  "--start", start, "--end", end, "--symbol", "lookup",
                                  "--claim", "returns the supplied value").stdout)

    def ready(self):
        # A tiny, explicitly synthetic catalog tests the mechanics offline.
        xml = self.base / "catalog.xml"
        xml.write_text(CATALOG_FIXTURE)
        self.command("workspace.py", "cwe", "--run", self.run, "--xml", xml)
        plan = self.read("review-plan.json")
        plan["phase"] = "ready"
        plan["stack"] = [{"id": "python", "name": "Python", "version": None, "security_resources": ["fixture-doc"],
                          "source_refs": [self.reference()]}]
        doc = self.run / "tools/security-doc.txt"
        doc.write_text("Synthetic offline fixture: inspect argument trust and caller authorization.")
        plan["resources"] = [{"id": "fixture-doc", "purpose": "Fixture stack security requirements",
                              "status": "available", "url": "provided:synthetic-test-document",
                              "path": "tools/security-doc.txt", "sha256": hashlib.sha256(doc.read_bytes()).hexdigest()}]
        for row in plan["weaknesses"]:
            row.update(applicability="applicable", rationale="Inspect all inputs and caller controls",
                       stack_ids=["python"], status="reviewed", coverage_unit_ids=["whole-file"])
        for task in plan["tasks"]:
            task.update(status="done", result_paths=["notes/review.md"])
        (self.run / "notes/review.md").write_text("Reviewed the function and absence of other entrypoints.")
        self.write("coverage.json", {"schema_version": 1, "units": [{
            "id": "whole-file", "kind": "file-and-callers", "locator": "primary:main.py",
            "status": "unreviewed", "questions": ["Inspect input and caller authorization"],
            "source_refs": [], "rationale": "", "next_action": "Read source and trace callers"}]})
        self.write("review-plan.json", plan)
        return plan

    def complete(self):
        self.ready()
        self.write("coverage.json", {"schema_version": 1, "units": [{
            "id": "whole-file", "kind": "file-and-callers", "locator": "primary:main.py",
            "status": "reviewed", "questions": ["Can callers bypass validation or authorization?"],
            "source_refs": [self.reference()], "rationale": "Inspected both lines and the source tree",
            "next_action": "No remaining code review in this fixture"}]})
        state = self.read("state.json")
        state.update(status="complete", next_actions=[], blockers=[])
        self.write("state.json", state)
        (self.run / "REPORT.md").write_text("# Fixture review\nAll source reviewed; no source-supported finding.\n")

    def candidate(self):
        finding = {"id": "F-1", "title": "Caller-controlled value", "status": "conditional",
                   "hypothesis": "An untrusted caller may reach a sensitive downstream operation",
                   "attacker": "caller", "preconditions": ["sensitive downstream use exists"],
                   "invariant": "untrusted input must be validated before sensitive use",
                   "chain": [{"from": "argument", "to": "return", "transition": "identity",
                              "requires": [], "controls": [], "evidence_indices": [0], "status": "observed"}],
                   "source_refs": [self.reference()], "counterevidence": ["No downstream operation is supplied"],
                   "impact": {"scope": "returned value", "statement": "conditional on downstream use",
                              "runtime_verified": False, "conditions": ["downstream sensitive use"]},
                   "uncertainties": ["downstream consumer"],
                   "review": {"status": "reviewed", "reviewer": "fixture-reviewer", "model": None,
                              "conclusion": "Only identity propagation is shown"},
                   "next_action": "Request downstream implementation if scope expands"}
        self.write("findings/F-1.json", finding)
        return finding

    def test_initial_snapshot_does_not_execute_code_and_includes_ignored_hidden_files(self):
        (self.source / ".hidden.py").write_text("raise RuntimeError('must not execute')\n")
        (self.source / ".gitignore").write_text("vendor/\n")
        (self.source / "vendor").mkdir()
        (self.source / "vendor/lib.js").write_text("throw new Error('must not execute');\n")
        self.command("workspace.py", "snapshot", "--run", self.run)
        entries = self.read("evidence/source-inventory.json")["entries"]
        self.assertEqual({e["path"] for e in entries}, {"main.py", ".hidden.py", ".gitignore", "vendor/lib.js"})
        self.assertTrue(all(len(e["sha256"]) == 64 for e in entries))
        self.assertEqual(self.read("review-plan.json")["phase"], "preparing")
        self.assertFalse(self.check("--require-ready", success=False)["ok"])

    def test_complete_rejects_empty_coverage_and_unprepared_plan(self):
        state = self.read("state.json")
        state["status"] = "complete"
        self.write("state.json", state)
        result = self.check(success=False)
        self.assertFalse(result["ok"])
        self.assertTrue(any("100%" in e for e in result["errors"]))

    def test_ready_requires_every_catalog_and_stack_pair(self):
        plan = self.ready()
        self.assertTrue(self.check("--require-ready")["ok"])
        plan["stack"].append(dict(plan["stack"][0], id="worker"))
        self.write("review-plan.json", plan)
        errors = self.check("--require-ready", success=False)["errors"]
        self.assertTrue(any("every CWE/stack pair" in e for e in errors))
        plan["stack"].pop()
        plan["weaknesses"].pop()
        self.write("review-plan.json", plan)
        self.assertTrue(any("omits" in e for e in self.check(success=False)["errors"]))

    def test_complete_requires_full_intervals_and_does_not_double_count_overlap(self):
        self.complete()
        result = self.check()
        self.assertEqual(result["summary"]["source_lines"], 2)
        self.assertEqual(result["summary"]["reviewed_source_lines"], 2)
        coverage = self.read("coverage.json")
        coverage["units"][0]["source_refs"] = [self.reference(1, 1), self.reference(1, 1)]
        self.write("coverage.json", coverage)
        result = self.check(success=False)
        self.assertEqual(result["summary"]["reviewed_source_lines"], 1)
        self.assertTrue(any("100%" in e for e in result["errors"]))
        coverage["units"][0]["status"] = "excluded"
        self.write("coverage.json", coverage)
        self.assertFalse(self.check(success=False)["ok"])

    def test_new_file_and_source_changes_invalidate_completion(self):
        self.complete()
        (self.source / "extra.py").write_text("new_entry = True\n")
        result = self.check(success=False)
        self.assertTrue(any("inventory/SHA-256 changed" in e for e in result["errors"]))
        self.command("workspace.py", "snapshot", "--run", self.run)
        self.assertEqual(self.read("state.json")["status"], "active")
        self.assertEqual(self.read("review-plan.json")["phase"], "preparing")
        self.assertTrue(list((self.run / "evidence/inventory-history").glob("*.json")))
        self.code.write_text("def lookup(value):\n    return None\n")
        self.assertTrue(any("SHA-256" in e for e in self.check(success=False)["errors"]))

    def test_unfinished_work_weaknesses_and_resources_block_complete(self):
        self.complete()
        plan = self.read("review-plan.json")
        plan["weaknesses"][0]["coverage_unit_ids"] = []
        plan["tasks"][0]["status"] = "blocked"
        plan["resources"] = [{"id": "missing-parser", "status": "unavailable"}]
        self.write("review-plan.json", plan)
        errors = self.check(success=False)["errors"]
        self.assertTrue(any("applicable weakness" in e for e in errors))
        self.assertTrue(any("completed results" in e for e in errors))
        self.assertTrue(any("required resource" in e for e in errors))

    def test_candidates_require_code_refs_and_evidence_on_observed_edges(self):
        finding = self.candidate()
        finding["source_refs"] = []
        finding["chain"] = []
        self.write("findings/F-1.json", finding)
        self.assertTrue(any("every finding/candidate" in e for e in self.check(success=False)["errors"]))
        finding["source_refs"] = [self.reference()]
        finding["chain"] = self.candidate()["chain"]
        finding["chain"][0]["evidence_indices"] = []
        self.write("findings/F-1.json", finding)
        self.assertTrue(any("observed chain" in e for e in self.check(success=False)["errors"]))

    def test_completion_requires_resolved_candidates_and_report_evidence(self):
        self.complete()
        finding = self.candidate()
        self.assertTrue(any("REPORT.md must" in e for e in self.check(success=False)["errors"]))
        (self.run / "REPORT.md").write_text("F-1 main.py lines 1–2 lookup " + self.reference()["sha256"])
        self.assertTrue(self.check()["ok"])
        finding["status"] = "needs-evidence"
        self.write("findings/F-1.json", finding)
        self.assertTrue(any("unresolved/unreviewed" in e for e in self.check(success=False)["errors"]))

    def test_non_utf8_source_cannot_be_classified_out_of_coverage(self):
        (self.source / "legacy.py").write_bytes(b"name = '\xff'\n")
        self.complete()
        self.command("workspace.py", "snapshot", "--run", self.run)
        self.complete()
        entry = next(e for e in self.read("evidence/source-inventory.json")["entries"] if e["path"] == "legacy.py")
        coverage = self.read("coverage.json")
        coverage["non_source_files"] = [dict(entry, rationale="Pretend this is an image", reviewer="test")]
        self.write("coverage.json", coverage)
        self.assertTrue(any("artifact needs source" in e for e in self.check(success=False)["errors"]))

    def test_external_symlink_must_be_in_declared_roots(self):
        external = self.base / "external.py"
        external.write_text("outside = True\n")
        (self.source / "alias.py").symlink_to(external)
        self.command("workspace.py", "snapshot", "--run", self.run)
        self.complete()
        self.assertTrue(any("unregistered symlink" in e for e in self.check(success=False)["errors"]))

    def test_malformed_plan_reports_errors_without_traceback(self):
        plan = self.ready()
        plan["weaknesses"][0]["applicability"] = []
        plan["tasks"][0]["executor"] = []
        plan["resources"] = [[]]
        self.write("review-plan.json", plan)
        self.assertFalse(self.check(success=False)["ok"])

    def test_view_urls_and_xml_entities_are_rejected(self):
        result = self.command("workspace.py", "cwe", "--run", self.run,
                         "--url", "https://cwe.mitre.org/data/definitions/20.xml.zip", success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        contract = module("review_contract")
        with self.assertRaises(ValueError):
            contract.cwe_catalog(b'<!DOCTYPE x [<!ENTITY a "bad">]><Weakness_Catalog/>')

    def test_streamed_hash_and_lines_match_source_reference_semantics(self):
        contract = module("review_contract")
        for data in (b"", b"x\r\ny\n", b"x" * (1024 * 1024 - 1) + b"\r\nx",
                     "x\u2028y\x85z\v".encode(), b"broken\xff", b"binary\0"):
            sha, size, lines = contract.file_facts(io.BytesIO(data))
            self.assertEqual(sha, hashlib.sha256(data).hexdigest())
            self.assertEqual(size, len(data))
            try:
                expected = None if b"\0" in data else len(data.decode().splitlines())
            except UnicodeError:
                expected = None
            self.assertEqual(lines, expected)

    def test_truncated_catalog_cannot_be_imported_or_substituted(self):
        plan = self.ready()
        truncated = CATALOG_FIXTURE.replace('<Weakness ID="862" Name="Authorization"/>', '')
        xml = self.base / "truncated.xml"
        xml.write_text(truncated)
        result = self.command("workspace.py", "cwe", "--run", self.run, "--xml", xml, success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("do not match the kit pin", result.stderr)
        catalog = self.run / plan["catalogs"][0]["path"]
        catalog.write_text(truncated)
        plan["catalogs"][0]["sha256"] = hashlib.sha256(catalog.read_bytes()).hexdigest()
        self.write("review-plan.json", plan)
        self.assertTrue(any("invalid full CWE catalog" in e for e in self.check("--require-ready", success=False)["errors"]))

    def test_ready_requires_planned_review_and_stack_security_material(self):
        plan = self.ready()
        plan["resources"] = []
        self.write("review-plan.json", plan)
        self.write("coverage.json", {"schema_version": 1, "units": []})
        errors = self.check("--require-ready", success=False)["errors"]
        self.assertTrue(any("planned review units" in e for e in errors))
        self.assertTrue(any("security_resources" in e for e in errors))

    def test_nonapplicable_rows_still_require_explicit_completed_decision(self):
        self.complete()
        plan = self.read("review-plan.json")
        plan["weaknesses"][1].update(applicability="not-applicable", status="reviewed", coverage_unit_ids=[])
        self.write("review-plan.json", plan)
        self.assertTrue(self.check()["ok"])
        del plan["weaknesses"][1]["status"]
        del plan["weaknesses"][1]["coverage_unit_ids"]
        self.write("review-plan.json", plan)
        self.assertTrue(any("needs status" in e for e in self.check(success=False)["errors"]))

    def test_empty_files_need_explicit_file_review(self):
        (self.source / "empty.txt").write_bytes(b"")
        self.command("workspace.py", "snapshot", "--run", self.run)
        self.complete()
        errors = self.check(success=False)["errors"]
        self.assertTrue(any("empty source file" in e for e in errors))
        entry = next(e for e in self.read("evidence/source-inventory.json")["entries"] if e["path"] == "empty.txt")
        coverage = self.read("coverage.json")
        coverage["empty_files"] = [dict(entry, rationale="Confirmed zero-byte ancillary file", reviewer="fixture-reviewer")]
        self.write("coverage.json", coverage)
        self.assertTrue(self.check()["ok"])

    def test_malformed_resource_metadata_does_not_count_as_available(self):
        plan = self.ready()
        del plan["resources"][0]["purpose"]
        plan["resources"][0]["url"] = {"not": "an origin string"}
        self.write("review-plan.json", plan)
        self.assertTrue(any("required resource" in e for e in self.check(success=False)["errors"]))

    def test_ready_requires_concrete_review_questions(self):
        self.ready()
        coverage = self.read("coverage.json")
        coverage["units"][0]["questions"] = []
        self.write("coverage.json", coverage)
        self.assertTrue(any("nonempty questions" in e for e in self.check("--require-ready", success=False)["errors"]))

    def test_candidate_analysis_cannot_precede_preparation(self):
        self.candidate()
        self.assertTrue(any("requires ready preparation" in e for e in self.check(success=False)["errors"]))

    def test_legacy_snapshot_migration_does_not_invent_completed_work(self):
        (self.run / "review-plan.json").unlink()
        self.command("workspace.py", "snapshot", "--run", self.run)
        plan = self.read("review-plan.json")
        self.assertEqual(plan["phase"], "preparing")
        self.assertEqual(plan["stack"], [])
        self.assertFalse(self.check("--require-ready", success=False)["ok"])


if __name__ == "__main__":
    unittest.main()
