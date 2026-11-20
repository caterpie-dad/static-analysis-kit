"""Offline behavioral checks for workspace isolation and evidence integrity."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


KIT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, KIT / "scripts" / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def command(script, *arguments, success=True):
    result = subprocess.run([sys.executable, str(KIT / "scripts" / script), *map(str, arguments)],
                            cwd=KIT, capture_output=True, text=True, timeout=30)
    if success and result.returncode:
        raise AssertionError(result.stderr + result.stdout)
    return result


class WorkspaceChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="static-kit-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.file = self.source / "service.py"
        self.file.write_text("def resolve(key):\n    return key\n", encoding="utf-8")
        self.run = self.base / "review"
        command("workspace.py", "init", "--target", self.source, "--output", self.run)

    def test_initialization_isolated_and_no_overwrite(self):
        self.assertEqual(self.file.read_text(), "def resolve(key):\n    return key\n")
        self.assertEqual([p.name for p in self.source.iterdir()], ["service.py"])
        self.assertNotEqual(command("workspace.py", "init", "--target", self.source,
                                    "--output", self.run, success=False).returncode, 0)
        self.assertNotEqual(command("workspace.py", "init", "--target", self.source,
                                    "--output", self.source / "output", success=False).returncode, 0)

    def test_inventory_limit_does_not_imply_review(self):
        (self.source / "second.py").write_text("value = 1\n")
        command("workspace.py", "inventory", "--run", self.run, "--max-files", "1")
        result = json.loads((self.run / "evidence/inventory-primary.json").read_text())
        self.assertFalse(result["complete_enumeration"])
        self.assertEqual(result["review_status"], "unreviewed")
        self.assertEqual(len(result["entries"]), 1)
        self.assertEqual(json.loads((self.run / "coverage.json").read_text())["units"], [])

    def test_reference_integrity_and_escape(self):
        result = command("workspace.py", "ref", "--run", self.run, "--root", "primary",
                         "--path", "service.py", "--start", "1", "--end", "2",
                         "--symbol", "resolve", "--claim", "returns the supplied key")
        ref = json.loads(result.stdout)
        self.assertEqual(ref["sha256"], hashlib.sha256(self.file.read_bytes()).hexdigest())
        coverage = {"schema_version": 1, "units": [{
            "id": "U-1", "kind": "function", "locator": "primary:service.py:resolve",
            "status": "reviewed", "questions": ["What value is returned?"],
            "source_refs": [ref], "rationale": "Inspected the function body",
            "next_action": "Resolve callers in the wider application"}]}
        (self.run / "coverage.json").write_text(json.dumps(coverage))
        self.assertEqual(command("check_kit.py", "--run", self.run).returncode, 0)
        self.file.write_text("def resolve(key):\n    return None\n")
        stale = command("check_kit.py", "--run", self.run, success=False)
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("SHA-256", stale.stdout)
        escaped = command("workspace.py", "ref", "--run", self.run, "--root", "primary",
                          "--path", "../outside.py", "--start", "1", "--end", "1",
                          "--symbol", "outside", "--claim", "outside", success=False)
        self.assertNotEqual(escaped.returncode, 0)
        outside = self.base / "outside.py"
        outside.write_text("outside = True\n")
        try:
            (self.source / "link.py").symlink_to(outside)
        except (OSError, NotImplementedError):
            return
        escaped = command("workspace.py", "ref", "--run", self.run, "--root", "primary",
                          "--path", "link.py", "--start", "1", "--end", "1",
                          "--symbol", "outside", "--claim", "outside", success=False)
        self.assertNotEqual(escaped.returncode, 0)

    def test_malformed_record_fails_without_traceback(self):
        (self.run / "state.json").write_text(json.dumps({"schema_version": 1, "status": []}))
        result = command("check_kit.py", "--run", self.run, success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(json.loads(result.stdout)["ok"])


class CapabilityChecks(unittest.TestCase):
    def test_catalog_metadata_not_account_access(self):
        probe = module("capabilities")
        data = {"models": [{"slug": "vendor/model-next", "supported_reasoning_levels": [
            {"effort": "high", "description": "description is not an ID"}, "medium"]}]}
        self.assertEqual(probe._model_records(data), [{
            "identifiers": ["vendor/model-next"], "supported_reasoning_levels": ["high", "medium"]}])
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "cache.json"
            cache.write_text("not JSON")
            result = probe._model_cache(str(cache))
            self.assertEqual(result["cache_error"], "malformed_json")
            self.assertFalse(result["access_confirmed"])


class InstallerChecks(unittest.TestCase):
    def test_plan_creates_nothing_and_rejects_package_options(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "tools"
            result = command("install_python_tool.py", "--package", "example-tool", "--version", "1.0",
                             "--base", base, "--plan")
            plan = json.loads(result.stdout)
            self.assertIn("--no-index", plan["commands"]["install"])
            self.assertIn("--only-binary=:all:", plan["commands"]["download"])
            self.assertFalse(base.exists())
            bad = command("install_python_tool.py", "--package", "pkg; touch marker", "--version", "1.0",
                          "--base", base, success=False)
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse(base.exists())

    def test_offline_wheel_install_and_artifact_manifest(self):
        if importlib.util.find_spec("ensurepip") is None and os.environ.get("STATIC_KIT_ALLOW_NETWORK_TESTS") != "1":
            self.skipTest("host lacks ensurepip; set STATIC_KIT_ALLOW_NETWORK_TESTS=1 to check PyPI pip-bootstrap fallback")
        installer = module("install_python_tool")
        real_run = subprocess.run
        with tempfile.TemporaryDirectory(prefix="static-kit-wheel-") as temp:
            base = Path(temp) / "tools"

            def prepare_download(argv, *args, **kwargs):
                if "download" not in argv or any(value.startswith("pip==") for value in argv):
                    return real_run(argv, *args, **kwargs)
                wheels = Path(argv[argv.index("--dest") + 1])
                wheel = wheels / "analysis_kit_probe-1.0-py3-none-any.whl"
                dist = "analysis_kit_probe-1.0.dist-info"
                files = {
                    "analysis_kit_probe/__init__.py": "__version__ = '1.0'\n",
                    f"{dist}/METADATA": "Metadata-Version: 2.1\nName: analysis-kit-probe\nVersion: 1.0\n",
                    f"{dist}/WHEEL": "Wheel-Version: 1.0\nGenerator: static-kit-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
                }
                files[f"{dist}/RECORD"] = "".join(f"{name},,\n" for name in [*files, f"{dist}/RECORD"])
                with zipfile.ZipFile(wheel, "w") as archive:
                    for name, content in files.items():
                        archive.writestr(name, content)
                return subprocess.CompletedProcess(argv, 0)

            argv = ["install_python_tool.py", "--package", "analysis-kit-probe", "--version", "1.0", "--base", str(base)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(installer.subprocess, "run", side_effect=prepare_download):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(installer.main(), 0)
            directory = base / "analysis-kit-probe" / "1.0"
            manifest = json.loads((directory / "install-manifest.json").read_text())
            self.assertEqual(manifest["status"], "installed")
            self.assertIn({"name": "analysis-kit-probe", "version": "1.0"}, manifest["packages"])
            artifact = manifest["artifacts"][0]
            self.assertEqual(artifact["sha256"], hashlib.sha256((directory / "wheels" / artifact["filename"]).read_bytes()).hexdigest())
            self.assertFalse((base.parent / "source").exists())


if __name__ == "__main__":
    unittest.main()
