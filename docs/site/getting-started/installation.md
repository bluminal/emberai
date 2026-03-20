# Installation

This guide covers installing the **unifi** plugin — the first plugin in the Netex suite. The OPNsense and Netex umbrella plugins will be available in later releases.

## Prerequisites

- **Python 3.12 or later** — check with `python3 --version`
- **Claude Code** or **Claude CoWork** — Netex plugins run as MCP servers inside Claude's tool ecosystem

## Install the UniFi Plugin

### From PyPI

```bash
pip install unifi
```

### From Source (Development)

Clone the repository and install in editable mode:

```bash
git clone https://github.com/bluminal/emberai.git
cd emberai
pip install -e "./unifi"
```

For development dependencies (testing, linting, type checking):

```bash
pip install -e "./unifi" --group dev
```

## Configure as an MCP Server

Add the unifi plugin to your Claude Code MCP settings. The configuration goes in your Claude Code settings file (typically `~/.claude/settings.json` or the project-level `.claude/settings.json`):

```json
{
  "mcpServers": {
    "unifi": {
      "command": "unifi-server",
      "args": ["--transport", "stdio"]
    }
  }
}
```

## Verify the Installation

Run the built-in health check to confirm the server starts and can reach your UniFi controller:

```bash
unifi-server --check
```

A successful check prints connection status and exits with code 0. If it fails, the output will indicate what went wrong — typically a missing environment variable or unreachable controller.

!!! tip "Set up authentication first"
    The health check requires API credentials. If you haven't configured them yet,
    see [Authentication](authentication.md) for how to create and set your API keys.

## What's Installed

The `unifi` package provides:

| Component | Description |
|-----------|-------------|
| `unifi-server` | CLI entry point — starts the MCP server |
| `unifi.server` | MCP server module with tool registration |
| `unifi.tools` | MCP tool implementations (topology, health, clients, commands) |
| `unifi.api` | Async HTTP client for UniFi Local Gateway, Cloud V1, and Site Manager APIs |
| `unifi.models` | Pydantic data models (strict mode) |
| `unifi.agents` | OutageRiskAgent and diagnostic agents |

## Next Steps

- [Authentication](authentication.md) — create API keys and configure environment variables
- [Quick Start](quick-start.md) — run your first network scan
- [Safety & Human Supervision](safety.md) — understand the human-in-the-loop model
