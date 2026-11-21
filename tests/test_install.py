"""User-level install/update/removal behavior, with no real client or model calls."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "scripts"))
import install as installer
sys.path.pop(0)


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="static-kit-install-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "kit source"
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

    def run_install(self, *arguments, success=True, env=None):
        result = subprocess.run(["sh", str(self.source / "install.sh"), *arguments],
            env=env or self.env, cwd=self.base, capture_output=True, text=True, timeout=60)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def manifest(self, client):
        return json.loads((self.data / "registrations" / (client + ".json")).read_text())

    def test_all_clients_are_discoverable_without_editing_existing_settings(self):
        preserved = {}
        for relative in (".codex/config.toml", ".claude/settings.json", ".vibe/config.toml",
                         ".config/opencode/opencode.json"):
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("personal configuration")
            preserved[path] = path.read_bytes()
        self.run_install("all")
        for client in installer.RENDERERS:
            manifest = self.manifest(client)
            self.assertEqual(len(manifest["files"]), 5)
            package = Path(manifest["package"])
            self.assertTrue((package / "START_HERE.md").is_file())
            self.assertFalse(manifest["model_access_verified"])
            for name, expected in manifest["files"].items():
                self.assertEqual(installer.sha(Path(name).read_bytes()), expected)
            role_paths = [Path(p) for p in manifest["files"] if "/agents/" in p]
            self.assertEqual(len(role_paths), 3)
            for path in role_paths:
                text = path.read_text()
                self.assertIn(str(package), text)
                self.assertNotIn(str(self.source), text)
        self.assertTrue(all(p.read_bytes() == data for p, data in preserved.items()))

    def test_installed_core_survives_checkout_removal_and_uses_external_run_directory(self):
        self.run_install("codex")
        package = Path(self.manifest("codex")["package"])
        shutil.rmtree(self.source)
        target = self.base / "webapp"
        target.mkdir()
        (target / "app.py").write_text("print('source only')\n")
        before = installer.package_files(package)
        result = subprocess.run([sys.executable, str(package / "scripts/workspace.py"),
            "init", "--target", str(target)], env=self.env, cwd=self.base,
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        runs = list((self.data / "runs").iterdir())
        self.assertEqual(len(runs), 1)
        self.assertTrue((runs[0] / "evidence/source-inventory.json").is_file())
        self.assertEqual(before, installer.package_files(package))
        self.assertFalse((package / "runs").exists())
        check = subprocess.run([sys.executable, str(package / "scripts/check_kit.py"),
            "--run", str(runs[0])], env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        tool = subprocess.run([sys.executable, str(package / "scripts/install_python_tool.py"),
            "--package", "example-tool", "--version", "1.0", "--plan"],
            env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(tool.returncode, 0, tool.stderr)
        self.assertEqual(Path(json.loads(tool.stdout)["destination"]),
                         self.data / "tools/python/example-tool/1.0")

    def test_reinstall_update_and_uninstall_preserve_records_and_other_client(self):
        self.run_install("all")
        initial = self.manifest("codex")
        self.run_install("all")
        self.assertEqual(self.manifest("codex"), initial)
        record = self.data / "runs/old/CHECKPOINT.md"
        record.parent.mkdir(parents=True)
        record.write_text("resume here")
        with (self.source / "README.md").open("a") as handle:
            handle.write("\nNew kit documentation.\n")
        self.run_install("codex")
        self.assertNotEqual(initial["package"], self.manifest("codex")["package"])
        self.assertEqual(initial["package"], self.manifest("claude-code")["package"])
        owned = list(self.manifest("codex")["files"])
        self.run_install("codex", "--uninstall")
        self.assertTrue(all(not Path(p).exists() for p in owned))
        self.assertTrue((self.home / ".claude/skills/system-static-analysis/SKILL.md").exists())
        self.assertEqual(record.read_text(), "resume here")
        self.assertTrue(Path(initial["package"]).is_dir())
        self.run_install("all", "--uninstall")
        self.run_install("all", "--uninstall")

    def test_all_preflight_prevents_partial_registration_on_user_file_collision(self):
        path = self.home / ".config/opencode/agents/static_reviewer.md"
        path.parent.mkdir(parents=True)
        path.write_text("my agent")
        self.run_install("all", success=False)
        self.assertEqual(path.read_text(), "my agent")
        self.assertFalse((self.home / ".codex/skills/system-static-analysis/SKILL.md").exists())
        self.assertFalse((self.data / "registrations").exists())

    def test_modified_registration_blocks_update_and_uninstall(self):
        self.run_install("claude-code")
        path = self.home / ".claude/agents/static_reviewer.md"
        path.write_text("my edits")
        self.run_install("claude-code", success=False)
        self.run_install("claude-code", "--uninstall", success=False)
        self.assertEqual(path.read_text(), "my edits")

    def test_symlink_directory_is_not_followed(self):
        external = self.base / "external"
        external.mkdir()
        (self.home / ".codex").symlink_to(external, target_is_directory=True)
        self.run_install("codex", success=False)
        self.assertEqual(list(external.iterdir()), [])

    def test_custom_client_home_and_data_home(self):
        env = dict(self.env, CODEX_HOME=str(self.home / "custom codex"),
                   STATIC_ANALYSIS_KIT_HOME=str(self.base / "kit data"))
        self.run_install("codex", env=env)
        self.assertTrue((self.home / "custom codex/skills/system-static-analysis/SKILL.md").exists())
        self.assertTrue((self.base / "kit data/registrations/codex.json").exists())
        self.run_install("codex", "--uninstall", env=env)

    def test_explicit_model_profile_is_applied_only_to_role_agents(self):
        profile = self.base / "models.local.toml"
        profile.write_text('schema_version = 1\n[roles]\nreviewer = "custom"\n'
                           '[clients.codex.models]\ncustom = "registered-model"\n')
        self.run_install("codex", "--override", str(profile))
        manifest = self.manifest("codex")
        self.assertEqual(manifest["role_models"]["reviewer"]["model"], "registered-model")
        self.assertIn('model = "registered-model"',
                      (self.home / ".codex/agents/static_reviewer.toml").read_text())
        self.assertFalse(any(Path(manifest["package"]).rglob("*.local.toml")))
        profile.unlink()
        self.run_install("codex")
        self.assertEqual(self.manifest("codex")["role_models"], manifest["role_models"])
        self.run_install("codex", "--profile", str(self.source / "profiles/default.toml"))
        self.assertIsNone(self.manifest("codex")["role_models"]["reviewer"]["model"])

    def test_failed_write_rolls_back_existing_files(self):
        first, second = self.base / "first", self.base / "second"
        first.write_bytes(b"before")
        original = installer.atomic_write
        def failing(path, content, **kwargs):
            if path == second:
                raise OSError("simulated disk failure")
            original(path, content, **kwargs)
        with mock.patch.object(installer, "atomic_write", side_effect=failing):
            with self.assertRaises(OSError):
                installer.write_transaction({first: b"after", second: b"new"})
        self.assertEqual(first.read_bytes(), b"before")
        self.assertFalse(second.exists())

    def test_file_changed_after_preflight_is_not_overwritten(self):
        path = self.base / "owned"
        path.write_bytes(b"owned bytes")
        originals = {path: path.read_bytes()}
        path.write_bytes(b"concurrent user edit")
        with self.assertRaises(ValueError):
            installer.write_transaction({path: b"new kit bytes"}, originals)
        self.assertEqual(path.read_bytes(), b"concurrent user edit")

    def test_runtime_symlink_is_rejected_before_dependency_bootstrap(self):
        external = self.base / "external runtime"
        external.mkdir()
        self.data.mkdir(parents=True)
        (self.data / "runtime").symlink_to(external, target_is_directory=True)
        self.run_install("codex", success=False)
        self.assertEqual(list(external.iterdir()), [])

    def test_piped_bootstrap_downloads_complete_archive(self):
        archive = self.base / "release.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(self.source, arcname="static-analysis-kit-main")
        binaries = self.base / "bin"
        binaries.mkdir()
        curl = binaries / "curl"
        curl.write_text('#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\n'
                        'cp "$KIT_TEST_ARCHIVE" "$2"\n')
        curl.chmod(0o755)
        env = dict(self.env, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                   KIT_TEST_ARCHIVE=str(archive))
        result = subprocess.run(["sh", "-s", "--", "all"], input=(self.source / "install.sh").read_text(),
            env=env, cwd=self.base, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list((self.data / "registrations").glob("*.json"))), 4)

    def test_missing_python_provisions_private_runtime_with_uv(self):
        binaries = self.base / "runtime bin"
        binaries.mkdir()
        for name in ("python3", "python"):
            path = binaries / name
            path.write_text("#!/bin/sh\nexit 1\n")
            path.chmod(0o755)
        uv = binaries / "uv"
        uv.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$KIT_TEST_UV_LOG"\n'
                      'case "$*" in\n'
                      '*"python install"*) mkdir -p "$UV_PYTHON_INSTALL_DIR";;\n'
                      '*"python find"*) printf "%s\\n" "$KIT_TEST_PYTHON";;\n'
                      '*) exit 2;;\nesac\n')
        uv.chmod(0o755)
        log = self.base / "uv.log"
        env = dict(self.env, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                   KIT_TEST_UV_LOG=str(log), KIT_TEST_PYTHON=sys.executable)
        self.run_install("codex", env=env)
        self.assertTrue((self.data / "runtime/python").is_dir())
        self.assertIn("--no-config python install 3.11 --no-bin", log.read_text())
        self.assertIn("--no-config python find --managed-python 3.11", log.read_text())
        self.assertTrue((self.data / "registrations/codex.json").exists())


if __name__ == "__main__":
    unittest.main()
