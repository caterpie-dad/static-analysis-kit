"""Offline checks for common-kit and optional client configuration validation."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


KIT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("kit_configuration_checker", KIT / "scripts/check_kit.py")
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class ConfigurationValidationChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="static-kit-config-check-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "kit"
        shutil.copytree(KIT, self.root, ignore=shutil.ignore_patterns(
            ".git", ".tools", "runs", "__pycache__", "*.pyc", ".pytest_cache"))

    def check(self, **kwargs):
        return CHECKER.Checker(self.root).run(**kwargs)

    def cli(self, *arguments):
        return subprocess.run([sys.executable, str(self.root / "scripts/check_kit.py"), *arguments],
                              cwd=self.temporary.name, text=True, capture_output=True, timeout=30)

    def test_core_does_not_require_native_client_configuration(self):
        for name in (".codex", ".claude", ".vibe", ".opencode"):
            shutil.rmtree(self.root / name, ignore_errors=True)
        result = self.check()
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["summary"]["adapters_checked"], 0)

    def test_selected_clients_validate_without_writing_native_files(self):
        for client in ("codex", "claude-code", "mistral-vibe", "opencode"):
            with self.subTest(client=client):
                before = set(self.root.rglob("*"))
                result = self.check(client=client)
                self.assertTrue(result["ok"], result["errors"])
                self.assertEqual(result["summary"]["adapters_checked"], 1)
                self.assertGreater(result["summary"]["generated_files_checked"], 0)
                self.assertFalse(result["configuration"]["account_access_confirmed"])
                self.assertFalse(result["configuration"]["native_execution_verified"])
                self.assertEqual(set(self.root.rglob("*")), before)

    def test_arbitrary_registered_model_ids_are_not_restricted_by_prefix(self):
        profile = self.root / "profiles/custom-test.toml"
        profile.write_text('''schema_version = 1
[roles]
inventory = "custom"
analyst = "custom"
reviewer = "custom"
[clients.opencode.models]
custom = "company-provider/internal-code-v7"
''', encoding="utf-8")
        result = self.check(client="opencode", profile_path=profile)
        self.assertTrue(result["ok"], result["errors"])

    def test_unknown_client_and_invalid_profile_fail_as_json(self):
        malformed = self.root / "profiles/broken-test.toml"
        malformed.write_text("[roles\n", encoding="utf-8")
        for arguments in (("--client", "unknown-client"),
                          ("--client", "codex", "--profile", str(malformed)),
                          ("--profile", str(malformed))):
            with self.subTest(arguments=arguments):
                result = self.cli(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(json.loads(result.stdout)["ok"])

    def test_unsupported_native_options_fail_validation(self):
        profile = self.root / "profiles/unsupported-test.toml"
        profile.write_text('''schema_version = 1
[roles]
inventory = "custom"
analyst = "custom"
reviewer = "custom"
[clients.codex.models]
custom = "custom-model-v7"
[clients.codex.options.custom]
unsupported_native_option = "enabled"
''', encoding="utf-8")
        result = self.check(client="codex", profile_path=profile)
        self.assertFalse(result["ok"])
        self.assertTrue(any("configuration" in message for message in result["errors"]))

    def test_local_override_is_checked_in_the_selected_client_context(self):
        override = self.root / "profiles/invalid-override-test.toml"
        override.write_text('schema_version = 1\n[roles]\nreviewer = "unbound-local-model"\n',
                            encoding="utf-8")
        result = self.check(client="claude-code", override_path=override)
        self.assertFalse(result["ok"])
        self.assertTrue(any("configuration" in message for message in result["errors"]))

    def test_malformed_default_profile_is_reported_without_selecting_a_client(self):
        (self.root / "profiles/default.toml").write_text("schema_version = 1\nroles = []\n",
                                                        encoding="utf-8")
        result = self.check()
        self.assertFalse(result["ok"])
        self.assertTrue(any("roles must be a table" in message for message in result["errors"]))

    def test_unselected_native_files_do_not_affect_common_kit_validation(self):
        agents = self.root / ".codex/agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "local-test.toml").write_text("[malformed native config\n", encoding="utf-8")
        (self.root / "CLAUDE.md").write_text("[local guidance](local-only.md)\n", encoding="utf-8")
        result = self.check()
        self.assertTrue(result["ok"], result["errors"])


class GeneratedBundleChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="static-kit-bundle-check-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checker = CHECKER.Checker(self.root)

    def test_links_may_resolve_to_another_generated_file(self):
        self.checker.check_generated_files({
            "generated/entry.md": "Read [shared guidance](common.md).\n",
            "generated/common.md": "Shared guidance.\n",
        })
        self.assertEqual(self.checker.errors, [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unsafe_paths_broken_links_and_malformed_native_files_are_rejected(self):
        self.checker.check_generated_files({
            "../outside.md": "Escape.\n",
            "generated/entry.md": "Read [missing guidance](missing.md).\n",
            ".codex/config.toml": "[agents\n",
            "opencode.json": "[]\n",
            ".claude/agents/empty.md": "No frontmatter.\n",
        })
        errors = "\n".join(self.checker.errors)
        for fragment in ("unsafe output path", "broken generated local link",
                         "invalid generated configuration", "must be an object", "frontmatter"):
            self.assertIn(fragment, errors)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
