"""Offline checks for client-neutral capability and public-catalog reporting."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


KIT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("portable_capabilities", KIT / "scripts/capabilities.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class CatalogChecks(unittest.TestCase):
    def test_unselected_clients_do_not_read_native_caches(self):
        with mock.patch.object(probe, "_probe_tools", return_value=[]), \
                mock.patch.object(probe.Path, "home", side_effect=AssertionError("implicit cache read")):
            for client in (None, "claude-code", "mistral-vibe", "opencode"):
                result = probe._report(client=client)
                self.assertEqual(result["schema_version"], 2)
                self.assertEqual(result["model_catalog"]["source"], "none")
                self.assertFalse(result["model_catalog"]["catalog_file_present"])
                self.assertFalse(result["model_catalog"]["access_confirmed"])
                self.assertIsNone(result["model_catalog"]["current_session_model"])

    def test_codex_cache_is_explicit_and_keeps_non_account_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            cache = home / ".codex/models_cache.json"
            cache.parent.mkdir()
            cache.write_text(json.dumps({"models": [{"slug": "future/vendor-model"}]}))
            with mock.patch.object(probe.Path, "home", return_value=home):
                result = probe._model_catalog(client="codex")
            self.assertEqual(result["client"], "codex")
            self.assertTrue(result["catalog_file_present"])
            self.assertTrue(result["catalog_parsed"])
            self.assertTrue(result["catalog_format_supported"])
            self.assertEqual(result["models"], [{"identifiers": ["future/vendor-model"]}])
            self.assertFalse(result["access_tested"])
            self.assertFalse(result["access_confirmed"])

    def test_public_catalog_projects_only_documented_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "public.json"
            path.write_text(json.dumps({"schema_version": 1, "access_confirmed": True,
                                       "id": "not-a-model", "settings": {"context_window": 8192},
                                       "current_session_model": "untrusted-claim", "models": [{
                "id": "company/new-model#custom", "provider": "company",
                "reasoning_efforts": ["native-budget", "native-budget", {"level": "adaptive"}],
                "api_key": "secret-value", "base_url": "https://private.example/",
                "description": "not-an-identifier", "access_confirmed": True}]}))
            result = probe._model_catalog("opencode", model_catalog_path=str(path))
            self.assertEqual(result["models"], [{
                "identifiers": ["company/new-model#custom"], "provider": "company",
                "supported_reasoning_levels": ["native-budget", "adaptive"]}])
            self.assertFalse(result["access_confirmed"])
            self.assertIsNone(result["current_session_model"])
            self.assertNotIn("secret-value", json.dumps(result))
            self.assertNotIn("private.example", json.dumps(result))

    def test_mapping_keys_are_not_limited_to_a_vendor_prefix(self):
        result = probe._model_records({"models": {
            "company/custom-next": {"reasoning_efforts": ["budgeted"]},
            "another/custom": {},
        }, "credentials": {"api_key": "not-a-model"}})
        self.assertEqual(result, [
            {"identifiers": ["another/custom"]},
            {"identifiers": ["company/custom-next"], "supported_reasoning_levels": ["budgeted"]},
        ])
        self.assertEqual(probe._model_records({"credentials": {"api_key": "secret"}}), [])

    def test_catalog_failures_do_not_become_access_or_raw_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "metadata.json"
            missing = probe._model_catalog(model_catalog_path=str(path))
            self.assertEqual(missing["catalog_error"], "missing")
            cases = [
                (b"secret-token-is-not-json", "malformed_json", False),
                (b"\xff", "unreadable", False),
                (b'{"providers": {"private": {"api_key": "secret"}}}', "unsupported_format", True),
                (b'{"schema_version": 99, "models": []}', "unsupported_format", True),
                (b'{"schema_version": true, "models": []}', "unsupported_format", True),
            ]
            for content, error, parsed in cases:
                with self.subTest(error=error, content=content):
                    path.write_bytes(content)
                    result = probe._model_catalog(model_catalog_path=str(path))
                    self.assertTrue(result["catalog_file_present"])
                    self.assertEqual(result["catalog_error"], error)
                    self.assertEqual(result["catalog_parsed"], parsed)
                    self.assertFalse(result["catalog_format_supported"])
                    self.assertEqual(result["models"], [])
                    self.assertFalse(result["access_confirmed"])
                    self.assertNotIn("secret", json.dumps(result))
            path.write_bytes(b" " * (probe.MAX_CATALOG_BYTES + 1))
            result = probe._model_catalog(model_catalog_path=str(path))
            self.assertEqual(result["catalog_error"], "too_large")
            self.assertFalse(result["catalog_parsed"])

    def test_catalog_size_limit_and_duplicate_records(self):
        data = {"models": [{"id": "model-{:04}".format(index)} for index in range(700)]}
        result = probe._model_records(data)
        self.assertEqual(len(result), probe.MAX_MODELS)
        self.assertEqual(probe._model_records({"models": [{"id": "same"}, {"id": "same"}]}),
                         [{"identifiers": ["same"]}])

    def test_legacy_cache_option_is_codex_only_and_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache.json"
            cache.write_text('{"models": [{"slug": "custom-model"}]}')
            output = Path(temporary) / "output.json"
            with mock.patch.object(probe, "_probe_tools", return_value=[]):
                with contextlib.redirect_stdout(io.StringIO()) as stream:
                    self.assertEqual(probe.main(["--model-cache", str(cache)]), 0)
                self.assertEqual(json.loads(stream.getvalue())["selected_client"], "codex")
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        probe.main(["--client", "opencode", "--model-cache", str(cache)])
                self.assertEqual(probe.main(["--client", "opencode", "--output", str(output)]), 0)
                original = output.read_bytes()
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        probe.main(["--output", str(output)])
                self.assertEqual(output.read_bytes(), original)

    def test_version_queries_cover_clients_in_an_empty_temporary_directory(self):
        calls = []

        def version(path, args, cwd=None):
            self.assertTrue(Path(cwd).is_dir())
            self.assertEqual(list(Path(cwd).iterdir()), [])
            self.assertNotEqual(Path(cwd), Path.cwd())
            calls.append((Path(path).name, args, cwd))
            return "example-version", None

        with mock.patch.object(probe.shutil, "which", side_effect=lambda name: "/tools/" + name), \
                mock.patch.object(probe, "_version", side_effect=version):
            tools = probe._probe_tools()
        for command in probe.CLIENT_COMMANDS.values():
            self.assertTrue(any(name == command and args == ("--version",) for name, args, _ in calls))
        self.assertTrue(all(entry["version"] == "example-version" for entry in tools))
        self.assertTrue(all(not Path(cwd).exists() for _, _, cwd in calls))


if __name__ == "__main__":
    unittest.main()
