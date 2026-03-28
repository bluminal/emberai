# nextdns -- NextDNS Intelligence Plugin

NextDNS intelligence plugin for [EmberAI](https://github.com/bluminal/emberai). Provides DNS profile management, security posture auditing, analytics dashboards, query log analysis, and parental control configuration across NextDNS profiles via the NextDNS API.

Part of the [Netex](https://github.com/bluminal/emberai) plugin suite (unifi, opnsense, nextdns, netex).

## What It Does

The nextdns plugin covers the **DNS layer** of the network: DNS profile configuration, security settings (threat intelligence, AI-driven threat detection, Google Safe Browsing, cryptojacking protection), privacy controls (blocklists, native tracking protection), parental controls, analytics dashboards, and query log analysis. It does **not** manage routing, firewall rules, VPN tunnels, or physical network topology -- those belong to the [opnsense](../opnsense/) and [unifi](../unifi/) plugins.

## Features (Phase 1 -- v0.1.0)

### Commands

| Command | Description |
|---------|-------------|
| `nextdns scan` | Discover all DNS profiles and their configuration summary |
| `nextdns health` | Security posture assessment across profiles |
| `nextdns analytics` | Usage dashboard with query volume, block rates, top domains |
| `nextdns logs` | Search and display recent query logs |
| `nextdns secure` | Apply security hardening recommendations |

### Skill Groups (MCP Tools)

| Skill | Description |
|-------|-------------|
| profiles | Profile inventory and configuration management |
| analytics | Usage dashboards, top domains, device stats |
| logs | Query log access and search |
| security-posture | Security and privacy configuration auditing |

All Phase 1 read operations require only `NEXTDNS_API_KEY`. Write operations additionally require `NEXTDNS_WRITE_ENABLED=true`.

## Quick Install

### Prerequisites

- Python 3.12 or later
- A NextDNS API key from https://my.nextdns.io/account

### Install

```bash
pip install -e ./nextdns
```

### Configure

Set the required environment variables:

```bash
export NEXTDNS_API_KEY="your-api-key"    # From my.nextdns.io/account
```

Or create a `.env` file in the project root:

```env
NEXTDNS_API_KEY=your-api-key
```

### Run

```bash
# Start the MCP server (stdio transport)
nextdns-server

# Or run directly
python -m nextdns.server

# Health check
nextdns-server --check
```

## Documentation

- [Plugin Overview](../docs/nextdns/overview.md) -- architecture, API, authentication
- [SKILL.md](SKILL.md) -- plugin manifest with full tool signatures

## Development

```bash
# Install with dev dependencies
pip install -e "./nextdns[dev]"

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
nextdns/
  src/nextdns/
    api/              # HTTP client for NextDNS API
    agents/           # Command orchestrators
    models/           # Pydantic data models
    tools/            # MCP tool implementations
    server.py         # MCP server setup and entry point
  tests/
    fixtures/         # Test fixture data
    ...
  SKILL.md            # Plugin manifest (netex vendor contract)
  pyproject.toml
  README.md
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXTDNS_API_KEY` | Yes | API key from https://my.nextdns.io/account |
| `NEXTDNS_WRITE_ENABLED` | No | Set to `"true"` to enable write operations (default: `false`) |
| `NETEX_CACHE_TTL` | No | Override cache TTL in seconds (default: `300`) |

## License

MIT -- see [LICENSE](../LICENSE) for details.

## Author

[Bluminal Labs](https://bluminal.com)
