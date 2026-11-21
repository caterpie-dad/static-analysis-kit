"""Installed in-agent model settings, without real models or user-auth changes."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


KIT = Path(__file__).resolve().parents[1]


class ModelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="static-kit-model-settings-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "kit"
        shutil.copytree(KIT, self.source, ignore=shutil.ignore_patterns(
            ".git", ".tools", "runs", "__pycache__", "*.pyc"))
        self.home = self.base / "user home"
        self.home.mkdir()
        self.data = self.home / ".local/share/static-analysis-kit"
        self.env = {key: value for key, value in os.environ.items() if key not in {
            "CODEX_HOME", "CLAUDE_CONFIG_DIR", "VIBE_HOME", "OPENCODE_CONFIG_DIR",
            "XDG_CONFIG_HOME", "XDG_DATA_HOME", "STATIC_ANALYSIS_KIT_HOME",
            "STATIC_ANALYSIS_KIT_SOURCE", "STATIC_ANALYSIS_KIT_REF"}}
        self.env.update(HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1")
        self.command("sh", self.source / "install.sh", "all")

    def command(self, *args, input=None, success=True):
        result = subprocess.run(list(map(str, args)), env=self.env, cwd=self.base,
                                input=input, capture_output=True, text=True, timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def manifest(self, client="codex"):
        return json.loads((self.data / "registrations" / (client + ".json")).read_text())

    def manage(self, action, *args, client="codex", request=None, success=True):
        package = Path(self.manifest(client)["package"])
        result = self.command(sys.executable, package / "scripts/manage.py", "models", action,
                              "--client", client, *args,
                              input=json.dumps(request) if request is not None else None,
                              success=success)
        return json.loads(result.stdout)

    def test_public_entrypoint_and_legacy_alias_are_both_installed(self):
        manifest = self.manifest()
        for name in ("static-analysis-kit", "system-static-analysis"):
            path = self.home / ".codex/skills" / name / "SKILL.md"
            self.assertTrue(path.is_file())
            self.assertIn(str(path), manifest["files"])
            self.assertIn("references/agent-interface.md", path.read_text())

    def test_previous_installation_with_only_legacy_skill_upgrades_to_public_entrypoint(self):
        path = self.data / "registrations/codex.json"
        previous = self.manifest()
        public = self.home / ".codex/skills/static-analysis-kit/SKILL.md"
        public.unlink()
        del previous["files"][str(public)]
        previous.pop("model_preferences")
        previous.pop("max_concurrent")
        path.write_text(json.dumps(previous))
        self.command("sh", self.source / "install.sh", "codex")
        self.assertTrue(public.exists())
        self.assertTrue((self.home / ".codex/skills/system-static-analysis/SKILL.md").exists())
        self.manage("set", request={"roles": {"reviewer": "chosen-model"}})
        self.assertEqual(self.manage("show")["roles"]["reviewer"]["model"], "chosen-model")

    def test_show_needs_no_target_or_user_profile(self):
        for client in ("codex", "claude-code", "mistral-vibe", "opencode"):
            with self.subTest(client=client):
                value = self.manage("show", client=client)
                self.assertEqual(value["mode"], "client-default")
                self.assertTrue(all(spec["model"] is None for spec in value["roles"].values()))
                self.assertIsNone(value["actual_main_model"])
        self.assertFalse((self.data / "runs").exists())

    def test_role_change_is_persisted_for_each_client_and_other_roles_are_unchanged(self):
        for client in ("codex", "claude-code", "mistral-vibe", "opencode"):
            with self.subTest(client=client):
                value = self.manage("set", client=client, request={"roles": {"reviewer": "registered-reviewer"}})
                self.assertTrue(value["saved"])
                self.assertFalse(value["settings"]["current_session_changed"])
                self.assertFalse(value["settings"]["model_access_verified"])
                self.assertIsNone(value["settings"]["roles"]["inventory"]["model"])
                self.assertEqual(value["settings"]["roles"]["reviewer"]["model"], "registered-reviewer")
                paths = self.manifest(client)["files"]
                role = next(Path(p) for p in paths if Path(p).stem == "static_reviewer")
                self.assertIn('"registered-reviewer"', role.read_text())

    def test_single_model_blocks_analysis_until_main_observation_matches(self):
        value = self.manage("set", request={"single_model": "one-model", "max_concurrent": 2})
        self.assertEqual(value["settings"]["main_model"], "one-model")
        self.assertEqual(value["settings"]["max_concurrent"], 2)
        self.assertEqual({spec["model"] for spec in value["settings"]["roles"].values()}, {"one-model"})
        self.assertFalse(self.manage("check")["analysis_can_start"])
        self.assertFalse(self.manage("check", "--observed-main", "other-model")["analysis_can_start"])
        check = self.manage("check", "--observed-main", "one-model", "--available-model", "one-model")
        self.assertTrue(check["analysis_can_start"])
        self.assertFalse(check["model_access_verified"])
        self.assertFalse(check["host_auxiliary_models_verified"])

    def test_role_patch_and_update_preserve_previous_choices_and_main_intent(self):
        self.manage("set", request={"single_model": "base-model"})
        value = self.manage("set", request={"roles": {"reviewer": "other-model"}})
        self.assertEqual(value["settings"]["mode"], "roles")
        self.assertEqual(value["settings"]["main_model"], "base-model")
        self.assertEqual(value["settings"]["roles"]["analyst"]["model"], "base-model")
        self.command("sh", self.source / "install.sh", "codex")
        self.assertEqual(self.manage("show"), {"ok": True, **value["settings"]})
        check = self.manage("check", "--observed-main", "base-model", "--available-model", "base-model")
        self.assertEqual(check["unavailable_roles"], ["reviewer"])
        self.assertFalse(check["analysis_can_start"])

    def test_main_only_selection_does_not_claim_session_was_switched(self):
        value = self.manage("set", request={"main_model": "selected-main"})
        self.assertEqual(value["settings"]["main_model"], "selected-main")
        self.assertFalse(value["settings"]["current_session_changed"])
        self.assertIsNone(value["settings"]["actual_main_model"])
        self.assertFalse(self.manage("check")["analysis_can_start"])

    def test_reset_returns_to_native_inheritance(self):
        self.manage("set", request={"single_model": "one-model"})
        reset = self.manage("reset")["settings"]
        self.assertEqual(reset["mode"], "client-default")
        self.assertIsNone(reset["main_model"])
        self.assertTrue(all(spec["model"] is None for spec in reset["roles"].values()))
        check = self.manage("check")
        self.assertTrue(check["analysis_can_start"])
        self.assertIsNone(check["main_model_matches"])
        self.assertFalse(check["role_activation_verified"])

    def test_invalid_requests_preserve_settings_and_registrations(self):
        before = (self.data / "registrations/codex.json").read_bytes()
        invalid = ({"roles": {"invented": "model"}}, {"single_model": "inherit"},
                   {"single_model": "model", "roles": {"reviewer": "other"}},
                   {"roles": {"reviewer": {"model": "model", "options": {"permissionMode": "bypass"}}}},
                   {"inherit": False}, {"max_concurrent": True},
                   {"roles": {"reviewer": "bad\nmodel"}}, {"unknown": "key"})
        for request in invalid:
            with self.subTest(request=request):
                self.assertFalse(self.manage("set", request=request, success=False)["ok"])
                self.assertEqual(before, (self.data / "registrations/codex.json").read_bytes())

    def test_user_edit_is_preserved_when_configuration_update_is_rejected(self):
        path = self.home / ".codex/agents/static_reviewer.toml"
        path.write_text("my manual edits")
        result = self.manage("set", request={"roles": {"reviewer": "model"}}, success=False)
        self.assertIn("modified kit registration", result["error"])
        self.assertEqual(path.read_text(), "my manual edits")

    def test_settings_work_after_checkout_is_deleted_without_changing_global_settings(self):
        personal = self.home / ".codex/config.toml"
        personal.write_text('model = "personal-main"\n')
        source_hash = personal.read_bytes()
        shutil.rmtree(self.source)
        self.manage("set", request={"single_model": "chosen-model"})
        self.assertEqual(personal.read_bytes(), source_hash)
        self.assertFalse((self.data / "runs").exists())

    def test_model_specific_options_are_applied_and_cleared_when_model_changes(self):
        self.manage("set", request={"roles": {"reviewer": {
            "model": "reasoning-model", "options": {"model_reasoning_effort": "high"}}}})
        role = self.home / ".codex/agents/static_reviewer.toml"
        self.assertIn('model_reasoning_effort = "high"', role.read_text())
        self.manage("set", request={"roles": {"reviewer": "other-model"}})
        self.assertNotIn("model_reasoning_effort", role.read_text())

    def test_concurrent_settings_change_during_preparation_is_preserved(self):
        package = Path(self.manifest()["package"])
        manifest = self.data / "registrations/codex.json"
        code = '''import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import manage
original_install = manage.installer.install
path = Path(sys.argv[2])
def concurrent(args, source):
    value = json.loads(path.read_text())
    value["model_preferences"] = {"mode": "roles", "main_model": "concurrent-selection"}
    path.write_text(json.dumps(value))
    return original_install(args, source=source)
manage.installer.install = concurrent
try:
    manage.apply_request("codex", {"single_model": "stale-selection"})
except ValueError as error:
    print(str(error))
else:
    raise AssertionError("stale configuration was applied")
'''
        result = self.command(sys.executable, "-c", code, package, manifest)
        self.assertIn("settings changed during preparation", result.stdout)
        current = self.manifest()
        self.assertEqual(current["model_preferences"]["main_model"], "concurrent-selection")
        self.assertTrue(all(spec["model"] is None for spec in current["role_models"].values()))


if __name__ == "__main__":
    unittest.main()
