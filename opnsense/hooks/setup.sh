#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${CLAUDE_PLUGIN_DATA:-$PLUGIN_DIR/.data}"
VENV_DIR="$DATA_DIR/.venv"

if [ -d "$VENV_DIR" ]; then
    echo '{"systemMessage": "opnsense plugin: dependencies already installed."}'
    exit 0
fi

if command -v uv &>/dev/null; then
    uv venv "$VENV_DIR" --python python3 -q 2>/dev/null
    uv pip install -q -e "$PLUGIN_DIR" --python "$VENV_DIR/bin/python" 2>/dev/null
else
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -q -e "$PLUGIN_DIR"
fi

echo '{"systemMessage": "opnsense plugin: dependencies installed. Configure OPNSENSE_HOST, OPNSENSE_API_KEY, and OPNSENSE_API_SECRET to connect."}'
