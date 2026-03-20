#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="${CLAUDE_PLUGIN_DATA:-$PLUGIN_DIR/.data}"
VENV_DIR="$DATA_DIR/.venv"

# Create venv and install on first run
if [ ! -d "$VENV_DIR" ]; then
    echo "[unifi] Creating virtual environment..." >&2
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -q -e "$PLUGIN_DIR"
    echo "[unifi] Installation complete." >&2
fi

# Run the MCP server
exec "$VENV_DIR/bin/python" -m unifi.server "$@"
