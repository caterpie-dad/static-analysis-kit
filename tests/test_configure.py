"""Offline behavioral tests for model binding and generated-file ownership."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "scripts"))
try:
    import configure
    import runtime_config as runtime
finally:
    sys.path.pop(0)


class ProfileChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="static-kit-profile-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def profile(self, name, content):
        path = self.base / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_default_inheritance_has_no_provider_specific_model_requirement(self):
        for client in runtime.RENDERERS:
            with self.subTest(client=client):
                resolved = runtime.resolve_configuration(KIT, client)
                self.assertTrue(all(spec["model"] is None and not spec["options"]
                                    for spec in resolved["roles"].values()))
                self.assertFalse(resolved["access_confirmed"])
                self.assertIsNone(resolved["current_session_model"])
                self.assertEqual(len(resolved["source_hashes"]), 6)
                files = runtime.render_files(KIT, resolved)
                for path, content in files.items():
                    if path.endswith(".toml"):
                        runtime.tomllib.loads(content)
                    if path.endswith(".md") and path != "CLAUDE.md":
                        front = content.split("---\n", 2)[1]
                        for line in front.splitlines():
                            key, value = line.split(": ", 1)
                            self.assertTrue(key)
                            json.loads(value)

    def test_examples_resolve_all_clients_with_exact_native_options(self):
        for client in runtime.RENDERERS:
            with self.subTest(client=client):
                result = runtime.resolve_configuration(KIT, client, KIT / "profiles/models.example.toml")
                self.assertTrue(all(spec["model"] for spec in result["roles"].values()))
                for relative, content in runtime.render_files(KIT, result).items():
                    if relative.endswith(".toml"):
                        runtime.tomllib.loads(content)
                self.assertFalse(result["runtime_compatibility_verified"])

    def test_local_override_changes_one_role_without_changing_shared_profile(self):
        profile = self.profile("profile.toml", '''schema_version = 1
[roles]
inventory = "worker"
analyst = "worker"
reviewer = "worker"
[clients.opencode.models]
worker = "company/provider:model-a"
''')
        override = self.profile("models.local.toml", '''schema_version = 1
[roles]
reviewer = "independent"
[clients.opencode.models]
independent = "custom-provider/새로운-model-v9"
[clients.opencode.options.independent]
reasoningEffort = "provider-specific-level"
''')
        original = profile.read_bytes()
        result = runtime.resolve_configuration(KIT, "opencode", profile, override)
        self.assertEqual(result["roles"]["inventory"]["model"], "company/provider:model-a")
        self.assertEqual(result["roles"]["reviewer"]["model"], "custom-provider/새로운-model-v9")
        self.assertEqual(result["roles"]["reviewer"]["options"], {"reasoningEffort": "provider-specific-level"})
        self.assertEqual(profile.read_bytes(), original)

    def test_local_empty_options_clear_old_settings_when_a_model_is_replaced(self):
        override = self.profile("models.local.toml", '''schema_version = 1
[clients.codex.models]
deep = "replacement-without-reasoning-option"
[clients.codex.options.deep]
''')
        result = runtime.resolve_configuration(KIT, "codex", KIT / "profiles/models.example.toml", override)
        self.assertEqual(result["roles"]["analyst"]["model"], "replacement-without-reasoning-option")
        self.assertEqual(result["roles"]["analyst"]["options"], {})
        parsed = runtime.tomllib.loads(runtime.render_files(KIT, result)[".codex/agents/static_analyst.toml"])
        self.assertNotIn("model_reasoning_effort", parsed)

    def test_unbound_alias_and_unknown_keys_fail_instead_of_silent_fallback(self):
        cases = (
            '[roles]\nreviewer = "unregistered"',
            '[roles]\nanalayst = "inherit"',
            '[clients.codxe.models]\nworker = "new-model"',
            '[clients.codex.models]\ninherit = "replacement"',
            '[clients.codex.options.inherit]\npermissionMode = "bypass"',
            '[delegation]\nmax_concurrent = true',
        )
        for index, tail in enumerate(cases):
            with self.subTest(tail=tail):
                path = self.profile("invalid-{}.toml".format(index), "schema_version = 1\n" + tail + "\n")
                with self.assertRaises(runtime.ConfigurationError):
                    runtime.resolve_configuration(KIT, "codex", path)

    def test_native_scalar_escaping_does_not_inject_configuration(self):
        model = 'custom/quoted"model\\branch'
        profile = self.profile("quoted.toml", 'schema_version = 1\n[roles]\ninventory = "custom"\n'
                               '[clients.codex.models]\ncustom = ' + json.dumps(model) + '\n')
        resolved = runtime.resolve_configuration(KIT, "codex", profile)
        files = runtime.render_files(KIT, resolved)
        parsed = runtime.tomllib.loads(files[".codex/agents/static_inventory.toml"])
        self.assertEqual(parsed["model"], model)
        self.assertEqual(parsed["name"], "static_inventory")

    def test_claude_instruction_import_handles_a_checkout_path_with_spaces(self):
        checkout = self.base / "kit checkout"
        shutil.copytree(KIT, checkout, ignore=shutil.ignore_patterns(
            ".git", ".tools", "runs", "__pycache__", "*.pyc"))
        resolved = runtime.resolve_configuration(checkout, "claude-code")
        first_line = runtime.render_files(checkout, resolved)["CLAUDE.md"].splitlines()[0]
        self.assertFalse(first_line.startswith('@"'))
        self.assertIn("\\ ", first_line)
        imported = Path(first_line[1:].replace("\\ ", " "))
        self.assertEqual(imported, checkout / "AGENTS.md")
        self.assertTrue(imported.is_file())


class GeneratedOwnershipChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="static-kit-render-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.output = self.base / "output with spaces"

    def plan(self, client="codex", **kwargs):
        return configure.prepare_plan(KIT, client, output=self.output, **kwargs)

    def test_default_cli_plan_creates_no_files(self):
        result = subprocess.run([sys.executable, str(KIT / "scripts/configure.py"),
                                 "--client", "claude-code", "--output", str(self.output)],
                                cwd=self.base, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertFalse(plan["written"])
        self.assertFalse(plan["access_confirmed"])
        self.assertFalse(self.output.exists())

    def test_each_client_writes_only_its_planned_files_and_manifest(self):
        for client in runtime.RENDERERS:
            with self.subTest(client=client):
                self.output = self.base / client
                plan = self.plan(client)
                configure.write_plan(plan)
                files = {str(path.relative_to(self.output)) for path in self.output.rglob("*") if path.is_file()}
                self.assertEqual(files, {entry["path"] for entry in plan["files"]} | {plan["ownership_manifest"]})
                record = json.loads((self.output / plan["ownership_manifest"]).read_text())
                self.assertFalse(record["runtime_compatibility_verified"])
                self.assertEqual(record["source_hashes"], plan["source_hashes"])
                self.assertTrue(all(entry["action"] == "unchanged" for entry in self.plan(client)["files"]))

    def test_unmanaged_config_is_preserved_even_with_force_without_partial_writes(self):
        existing = self.output / ".codex/config.toml"
        existing.parent.mkdir(parents=True)
        existing.write_text('[agents]\nenabled = false\n')
        plan = self.plan(force=True)
        self.assertIn(".codex/config.toml", plan["conflicts"])
        with self.assertRaises(configure.ConfigurationError):
            configure.write_plan(plan)
        self.assertEqual(existing.read_text(), '[agents]\nenabled = false\n')
        self.assertFalse((self.output / ".codex/agents").exists())
        self.assertFalse((self.output / ".tools").exists())

    def test_force_updates_owned_files_but_rejects_manual_changes(self):
        configure.write_plan(self.plan())
        changed = self.plan(profile_path=KIT / "profiles/models.example.toml")
        self.assertTrue(changed["conflicts"])
        configure.write_plan(self.plan(profile_path=KIT / "profiles/models.example.toml", force=True))
        agent = self.output / ".codex/agents/static_analyst.toml"
        agent.write_text(agent.read_text() + "# manual edit\n")
        before = agent.read_bytes()
        plan = self.plan(force=True)
        self.assertIn(".codex/agents/static_analyst.toml", plan["conflicts"])
        with self.assertRaises(configure.ConfigurationError):
            configure.write_plan(plan)
        self.assertEqual(agent.read_bytes(), before)

    def test_identical_user_files_are_not_adopted_as_generated_ownership(self):
        initial = self.plan()
        entry = next(item for item in initial["files"] if item["path"].endswith("static_analyst.toml"))
        existing = self.output / entry["path"]
        existing.parent.mkdir(parents=True)
        existing.write_text(entry["content"], encoding="utf-8")
        plan = self.plan()
        action = next(item["action"] for item in plan["files"] if item["path"] == entry["path"])
        self.assertEqual(action, "unchanged-unmanaged")
        configure.write_plan(plan)
        manifest = json.loads((self.output / plan["ownership_manifest"]).read_text())
        self.assertNotIn(entry["path"], manifest["files"])
        changed = self.plan(profile_path=KIT / "profiles/models.example.toml", force=True)
        self.assertIn(entry["path"], changed["conflicts"])

    def test_symlinked_parent_or_destination_cannot_escape_output(self):
        outside = self.base / "outside"
        outside.mkdir()
        self.output.mkdir()
        try:
            (self.output / ".codex").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(configure.ConfigurationError):
            self.plan()
        self.assertEqual(list(outside.iterdir()), [])

    def test_destination_changed_after_planning_is_not_overwritten(self):
        plan = self.plan()
        existing = self.output / ".codex/config.toml"
        existing.parent.mkdir(parents=True)
        existing.write_text("# another writer\n")
        with self.assertRaises(configure.ConfigurationError):
            configure.write_plan(plan)
        self.assertEqual(existing.read_text(), "# another writer\n")
        self.assertFalse((self.output / ".tools").exists())

    def test_write_failure_rolls_back_previously_updated_generated_files(self):
        plan = self.plan()
        real_write = configure._atomic_write
        calls = 0

        def fail_second(path, content):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated write failure")
            return real_write(path, content)

        with mock.patch.object(configure, "_atomic_write", side_effect=fail_second):
            with self.assertRaises(OSError):
                configure.write_plan(plan)
        self.assertFalse(any(path.is_file() for path in self.output.rglob("*")))


if __name__ == "__main__":
    unittest.main()
