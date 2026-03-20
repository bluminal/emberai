# unifi -- UniFi Network Intelligence Plugin

UniFi network intelligence plugin for [EmberAI](https://github.com/bluminal/emberai). Provides topology discovery, health monitoring, client management, and diagnostic analysis for UniFi network deployments via the Local Gateway API.

Part of the [Netex](https://github.com/bluminal/emberai) three-plugin suite (unifi, opnsense, netex).

## What It Does

The unifi plugin covers the **edge layer** of the network: switches, access points, wireless SSIDs, client associations, VLANs on switch ports, and site-level health. It does **not** manage routing, firewall rules, VPN tunnels, or DNS -- those belong to the [opnsense](../opnsense/) plugin (gateway layer).

## Features (Phase 1 -- v0.1.0)

### Commands

| Command | Description |
|---------|-------------|
| `unifi scan` | Discover all devices, VLANs, and uplink topology for a site |
| `unifi health` | Comprehensive health check with severity-tiered findings |
| `unifi clients` | Inventory all connected clients with signal quality and traffic |
| `unifi diagnose` | Root-cause analysis for a specific device or client |

### Skill Groups (MCP Tools)

| Skill | Tools | Description |
|-------|-------|-------------|
| topology | 4 | Device discovery, VLAN listing, uplink graph |
| health | 5 | Site health, device health, ISP metrics, events, firmware |
| clients | 4 | Client listing, details, traffic, search |

All Phase 1 operations are **read-only**. Write operations are planned for Phase 2.

## Quick Install

### Prerequisites

- Python 3.12 or later
- Network access to a UniFi Local Gateway
- A UniFi API key with site admin access

### Install

```bash
pip install -e ./unifi
```

### Configure

Set the required environment variables:

```bash
export UNIFI_LOCAL_HOST="192.168.1.1"    # Your UniFi gateway IP
export UNIFI_LOCAL_KEY="your-api-key"     # Local Gateway API key
```

Or create a `.env` file in the project root:

```env
UNIFI_LOCAL_HOST=192.168.1.1
UNIFI_LOCAL_KEY=your-api-key
```

### Run

```bash
# Start the MCP server (stdio transport)
unifi-server

# Or run directly
python -m unifi.server
```

## Documentation

- [Plugin Overview](../docs/unifi/overview.md) -- architecture, API tiers, authentication
- [Commands Reference](../docs/unifi/commands.md) -- all commands with examples
- [Skills Reference](../docs/unifi/skills.md) -- individual MCP tool documentation
- **Workflow Examples:**
  - [First-Time Site Scan](../docs/unifi/workflows/first-time-scan.md)
  - [Daily Health Check](../docs/unifi/workflows/daily-health-check.md)
  - [Locate a Client](../docs/unifi/workflows/locate-client.md)
  - [Check WiFi Channels](../docs/unifi/workflows/check-wifi-channels.md) (Phase 2)
  - [Firmware Update Status](../docs/unifi/workflows/firmware-update-status.md)

## Development

```bash
# Install with dev dependencies
pip install -e "./unifi[dev]"

# Run tests
pytest

# Run tests with coverage
coverage run -m pytest && coverage report

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

### Project Structure

```
unifi/
  src/unifi/
    api/              # HTTP client for UniFi APIs
    agents/           # Command orchestrators (topology, health, clients, diagnose)
    models/           # Pydantic data models
    tools/            # MCP tool implementations
    output.py         # Report formatting (OX formatters)
    server.py         # MCP server setup and entry point
    ask.py            # AskUserQuestion patterns
  tests/
    fixtures/         # Test fixture data (anonymized)
    ...
  SKILL.md            # Plugin manifest (netex vendor contract)
  pyproject.toml
  README.md
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `UNIFI_LOCAL_HOST` | Yes | IP or hostname of the UniFi Local Gateway |
| `UNIFI_LOCAL_KEY` | Yes | API key for the Local Gateway |
| `UNIFI_API_KEY` | Phase 2 | API key for Cloud V1 / Site Manager EA |
| `UNIFI_WRITE_ENABLED` | No | Set to `"true"` to enable write operations (default: `false`) |
| `NETEX_CACHE_TTL` | No | Override cache TTL in seconds (default: `300`) |

## License

MIT -- see [LICENSE](../LICENSE) for details.

## Author

[Bluminal Labs](https://bluminal.com)
