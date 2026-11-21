#!/bin/sh
# User-level skill installer. No sudo, shell-profile edits, or client login.
set -eu
umask 077

usage() {
    cat <<'USAGE'
Usage: sh install.sh {codex|claude-code|mistral-vibe|opencode|all} [--uninstall]
       sh install.sh CLIENT [--profile FILE] [--override FILE]

Installs a skill and three role agents for the selected client(s).
Run the same command to update. --uninstall preserves investigations and tools.
Optional: STATIC_ANALYSIS_KIT_HOME, STATIC_ANALYSIS_KIT_SOURCE,
          STATIC_ANALYSIS_KIT_REF (default: main).
USAGE
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    codex|claude-code|mistral-vibe|opencode|all) ;;
    *) usage >&2; exit 2 ;;
esac

kit_install_home=${STATIC_ANALYSIS_KIT_HOME:-${XDG_DATA_HOME:-"$HOME/.local/share"}/static-analysis-kit}
export STATIC_ANALYSIS_KIT_HOME="$kit_install_home"
export PYTHONDONTWRITEBYTECODE=1
# Validate before uv can create runtime directories, including when Python is
# absent. Repeat the check in Python before registering client files.
case "$kit_install_home" in
    /*) kit_install_check=$kit_install_home/runtime/python ;;
    *) kit_install_check=$PWD/$kit_install_home/runtime/python ;;
esac
while [ "$kit_install_check" != / ]; do
    if [ -L "$kit_install_check" ]; then
        echo "Symlink installation path: $kit_install_check" >&2; exit 1
    fi
    kit_install_check=${kit_install_check%/*}
    [ -n "$kit_install_check" ] || kit_install_check=/
done
kit_install_temp=$(mktemp -d "${TMPDIR:-/tmp}/static-kit-install.XXXXXXXX")
trap 'rm -rf "$kit_install_temp"' EXIT HUP INT TERM

kit_install_source=${STATIC_ANALYSIS_KIT_SOURCE:-}
if [ -z "$kit_install_source" ] && [ -f "$0" ]; then
    kit_install_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
    if [ -f "$kit_install_script_dir/scripts/install.py" ]; then
        kit_install_source=$kit_install_script_dir
    fi
fi
if [ -z "$kit_install_source" ]; then
    kit_install_ref=${STATIC_ANALYSIS_KIT_REF:-main}
    case "$kit_install_ref" in
        ''|*[!a-zA-Z0-9._/-]*) echo 'Invalid kit ref.' >&2; exit 2 ;;
    esac
    command -v curl >/dev/null 2>&1 || { echo 'curl is required.' >&2; exit 1; }
    curl -fLsS --retry 2 --connect-timeout 15 --max-time 180 \
        "https://codeload.github.com/caterpie-dad/static-analysis-kit/tar.gz/$kit_install_ref" \
        -o "$kit_install_temp/kit.tar.gz"
    mkdir "$kit_install_temp/source"
    tar -xzf "$kit_install_temp/kit.tar.gz" -C "$kit_install_temp/source" --strip-components=1
    kit_install_source=$kit_install_temp/source
fi
if [ ! -f "$kit_install_source/scripts/install.py" ]; then
    echo 'The selected kit source has no installer.' >&2; exit 1
fi

# 3.10 works if its TOML backport is already available; otherwise provision a
# private managed Python using Astral's official uv installer. No host pip use.
kit_install_python=
for kit_install_candidate in python3 python "$kit_install_home"/runtime/python/cpython-*/bin/python3; do
    if command -v "$kit_install_candidate" >/dev/null 2>&1 && \
       "$kit_install_candidate" -c 'import sys; assert sys.version_info >= (3, 10)
try: import tomllib
except ImportError:
    try: import tomli
    except ImportError: import pip._vendor.tomli' >/dev/null 2>&1; then
        kit_install_python=$(command -v "$kit_install_candidate")
        break
    fi
done
if [ -z "$kit_install_python" ]; then
    echo 'Preparing a private Python runtime...'
    kit_install_runtime=$kit_install_home/runtime
    if command -v uv >/dev/null 2>&1; then
        kit_install_uv=$(command -v uv)
    else
        # Keep uv in the temporary bootstrap directory; only managed Python is
        # persistent. uv's installer is prohibited from changing the user's PATH.
        command -v curl >/dev/null 2>&1 || { echo 'curl is required.' >&2; exit 1; }
        curl -fLsS --retry 2 --connect-timeout 15 --max-time 180 \
            https://astral.sh/uv/install.sh -o "$kit_install_temp/uv-install.sh"
        UV_INSTALL_DIR="$kit_install_temp/uv" UV_NO_MODIFY_PATH=1 sh "$kit_install_temp/uv-install.sh"
        kit_install_uv=$kit_install_temp/uv/uv
    fi
    export UV_PYTHON_INSTALL_DIR="$kit_install_runtime/python"
    export UV_CACHE_DIR="$kit_install_temp/uv-cache"
    "$kit_install_uv" --no-config python install 3.11 --no-bin
    kit_install_python=$("$kit_install_uv" --no-config python find --managed-python 3.11)
fi

"$kit_install_python" "$kit_install_source/scripts/install.py" "$@"
