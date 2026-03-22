#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="${CLAUDE_PLUGIN_DATA:-$PLUGIN_DIR/.data}"
VENV_DIR="$DATA_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    if command -v uv &>/dev/null; then
        echo "[netex] Installing with uv..." >&2
        uv venv "$VENV_DIR" --python python3 -q 2>/dev/null
        uv pip install -q -e "$PLUGIN_DIR" --python "$VENV_DIR/bin/python" 2>/dev/null
    else
        echo "[netex] Installing with pip (install uv for faster setup)..." >&2
        python3 -m venv "$VENV_DIR"
        "$VENV_DIR/bin/pip" install -q -e "$PLUGIN_DIR"
    fi
    echo "[netex] Ready." >&2
fi

exec "$VENV_DIR/bin/python" -m netex "$@"
