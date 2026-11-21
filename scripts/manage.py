#!/usr/bin/env python3
"""Agent-facing model settings: JSON requests, owned registrations, no model calls."""

import argparse
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True

import install as installer
from runtime_config import RENDERERS, ROLES, resolve_configuration


ROOT = Path(__file__).resolve().parents[1]
MAX_REQUEST = 65536


def text(value, label):
    if (not isinstance(value, str) or not value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("{} must be a nonempty single-line model reference".format(label))
    return value


def context(client):
    marker = ROOT / ".installation.json"
    if marker.exists():
        metadata = json.loads(marker.read_text(encoding="utf-8"))
        base = installer.safe_path(metadata["data_root"])
    else:
        base = installer.safe_path(os.environ.get("STATIC_ANALYSIS_KIT_HOME", str(
            Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "static-analysis-kit")))
    path = base / "registrations" / (client + ".json")
    raw = installer.current(path)
    if raw is None:
        raise ValueError("kit is not installed for {}; install the skill first".format(client))
    saved = json.loads(raw)
    if not isinstance(saved, dict) or saved.get("schema_version") != 1 or saved.get("client") != client:
        raise ValueError("invalid installation registration")
    package = installer.safe_path(saved["package"])
    if not package.is_dir():
        raise ValueError("installed package is missing; reinstall the kit")
    return base, package, saved, path, raw


def settings(client, saved):
    preferences = saved.get("model_preferences") or {}
    return {"client": client, "mode": preferences.get("mode", "client-default"),
            "main_model": preferences.get("main_model"),
            "roles": saved["role_models"],
            "max_concurrent": saved.get("max_concurrent", preferences.get("max_concurrent", 3)),
            "model_access_verified": False, "actual_main_model": None,
            "current_session_changed": False, "role_activation_verified": False,
            "host_auxiliary_models_verified": False}


def read_request(value):
    if value == "-":
        content = sys.stdin.read(MAX_REQUEST + 1)
    else:
        with Path(value).open(encoding="utf-8") as handle:
            content = handle.read(MAX_REQUEST + 1)
    if len(content) > MAX_REQUEST:
        raise ValueError("model settings request is too large")
    result = json.loads(content)
    if not isinstance(result, dict) or not result or set(result) - {
            "single_model", "main_model", "roles", "max_concurrent", "inherit"}:
        raise ValueError("unknown or empty model settings request")
    return result


def apply_request(client, request):
    base, package, old, manifest, original_manifest = context(client)
    args = argparse.Namespace(profile=None, override=None)
    resolved = installer.resolve_install_profile(package, client, args, old)
    preferences = copy.deepcopy(old.get("model_preferences") or {
        "mode": "client-default", "main_model": None})
    if "inherit" in request:
        if request != {"inherit": True}:
            raise ValueError("inherit reset cannot be combined with model overrides")
        resolved = resolve_configuration(package, client)
        preferences = {"mode": "client-default", "main_model": None}
    elif "single_model" in request:
        if set(request) - {"single_model", "max_concurrent"}:
            raise ValueError("single_model cannot be combined with per-role overrides")
        model = text(request["single_model"], "single_model")
        if model in {"inherit", "current"}:
            raise ValueError("single-model mode requires the exact observed model ID or registered preset")
        for role, spec in resolved["roles"].items():
            spec.update(alias="selected_" + role, model=model, options={})
        preferences = {"mode": "single", "main_model": model}
    else:
        roles = request.get("roles", {})
        if not isinstance(roles, dict) or set(roles) - set(ROLES):
            raise ValueError("unknown role in model settings request")
        if not roles and "main_model" not in request and "max_concurrent" not in request:
            raise ValueError("no model settings changes requested")
        for role, choice in roles.items():
            choice = {"model": choice} if isinstance(choice, str) else choice
            if not isinstance(choice, dict) or "model" not in choice or set(choice) - {"model", "options"}:
                raise ValueError("role choice requires model and optional native options")
            model = text(choice["model"], role)
            spec = resolved["roles"][role]
            inherited = model == "inherit"
            options = choice.get("options", spec["options"] if model == spec["model"] else {})
            if not isinstance(options, dict):
                raise ValueError("role options must be an object")
            if inherited and options:
                raise ValueError("per-role options require an exact model reference")
            spec.update(alias="inherit" if inherited else "selected_" + role,
                        model=None if inherited else model, options=options)
        if "main_model" in request:
            main = text(request["main_model"], "main_model")
            preferences["main_model"] = None if main == "inherit" else main
        if roles or "main_model" in request:
            preferences["mode"] = "roles"
    if "max_concurrent" in request:
        limit = request["max_concurrent"]
        if type(limit) is not int or not 1 <= limit <= 64:
            raise ValueError("max_concurrent must be an integer from 1 to 64")
        resolved["max_concurrent"] = limit
    preferences["max_concurrent"] = resolved["max_concurrent"]
    # Use the installer transaction and its ownership checks. Profiles are an
    # internal serialization detail; users supply neither TOML nor file paths.
    with tempfile.TemporaryDirectory(prefix="static-kit-settings-") as directory:
        profile = Path(directory) / "profile.toml"
        profile.write_text(installer.model_profile(resolved), encoding="utf-8")
        args = argparse.Namespace(client=client, uninstall=False, profile=profile,
                                 override=None, model_preferences=preferences,
                                 expected_manifest=original_manifest)
        previous = os.environ.get("STATIC_ANALYSIS_KIT_HOME")
        os.environ["STATIC_ANALYSIS_KIT_HOME"] = str(base)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                installer.install(args, source=package)
        finally:
            if previous is None:
                os.environ.pop("STATIC_ANALYSIS_KIT_HOME", None)
            else:
                os.environ["STATIC_ANALYSIS_KIT_HOME"] = previous
    _, _, updated, _, _ = context(client)
    return {"saved": True, "native_registrations_updated": True,
            "settings": settings(client, updated),
            "activation": "Use explicit per-delegation model selection if supported; otherwise reload native role definitions. Main session selection belongs to the host client."}


def check_models(client, observed_main, available):
    _, _, saved, _, _ = context(client)
    result = settings(client, saved)
    desired = result["main_model"]
    match = None if desired is None or observed_main is None else observed_main == desired
    unsupported = []
    if available is not None:
        unsupported = [role for role, spec in result["roles"].items()
                       if spec["model"] is not None and spec["model"] not in available]
    result.update(actual_main_model=observed_main, main_model_matches=match,
                  unavailable_roles=unsupported, available_models_checked=available is not None,
                  analysis_can_start=not unsupported and (desired is None or match is True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    groups = parser.add_subparsers(dest="group", required=True)
    models = groups.add_parser("models")
    actions = models.add_subparsers(dest="action", required=True)
    for action in ("show", "set", "reset", "check"):
        sub = actions.add_parser(action)
        sub.add_argument("--client", choices=list(RENDERERS), required=True)
        if action == "set":
            sub.add_argument("--request", default="-", help="Agent JSON request path or stdin")
        if action == "check":
            sub.add_argument("--observed-main", help="Exact model reference observed through the host, not an assumed default")
            sub.add_argument("--available-model", action="append", default=None)
    args = parser.parse_args()
    try:
        if args.action == "show":
            result = settings(args.client, context(args.client)[2])
        elif args.action == "check":
            result = check_models(args.client, args.observed_main, args.available_model)
        else:
            request = {"inherit": True} if args.action == "reset" else read_request(args.request)
            result = apply_request(args.client, request)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
