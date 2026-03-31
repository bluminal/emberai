# nextdns -- NextDNS Intelligence Plugin

NextDNS intelligence plugin for [EmberAI](https://github.com/bluminal/emberai). Provides DNS profile management, security posture auditing, analytics dashboards, query log analysis, and parental control configuration across NextDNS profiles via the NextDNS API.

Part of the [Netex](https://github.com/bluminal/emberai) plugin suite (unifi, opnsense, nextdns, netex).

## What It Does

The nextdns plugin covers the **DNS layer** of the network: DNS profile configuration, security settings (threat intelligence, AI-driven threat detection, Google Safe Browsing, cryptojacking protection), privacy controls (blocklists, native tracking protection), parental controls, analytics dashboards, and query log analysis. It does **not** manage routing, firewall rules, VPN tunnels, or physical network topology -- those belong to the [opnsense](../opnsense/) and [unifi](../unifi/) plugins.

## Features (Phase 1 -- v0.1.0)

### Commands

| Command | Description |
|---------|-------------|
| `nextdns profiles` | Discover all DNS profiles and their configuration summary |
| `nextdns analytics` | Usage dashboard with query volume, block rates, top domains |
| `nextdns audit` | Security posture audit with severity-tiered findings |
| `nextdns logs` | Search, stream, download, and clear DNS query logs |
| `nextdns manage` | Profile configuration management (create, update, delete, configure) |

### Skill Groups (42 MCP Tools)

| Skill | Read Tools | Write Tools | Description |
|-------|-----------|-------------|-------------|
| profiles | 8 | 12 | Profile inventory, configuration, and lifecycle management |
| analytics | 11 | 0 | Usage dashboards, top domains, devices, protocols, encryption |
| logs | 3 | 1 | Query log search, streaming, download, and clearing |
| security-posture | 2 | 0 | Security auditing and profile comparison |

### Key Capabilities

- **Profile management** -- list, inspect, create, rename, and delete profiles
- **Security auditing** -- audit all 12 security toggles, detect weaknesses, compare profiles
- **Privacy controls** -- manage blocklists, native tracking protection, disguised trackers
- **Parental controls** -- SafeSearch, YouTube restricted mode, service/category blocking, bypass prevention
- **Analytics** -- query volume, block rates, top domains, device activity, encryption status, DNSSEC
- **Log analysis** -- search by domain/device/status, live polling, bulk download
- **Bulk operations** -- apply security/privacy templates across multiple profiles

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

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXTDNS_API_KEY` | Yes | -- | API key from https://my.nextdns.io/account |
| `NEXTDNS_WRITE_ENABLED` | No | `false` | Set to `"true"` to enable write operations |
| `NETEX_CACHE_TTL` | No | `300` | Override cache TTL in seconds |

### Write Safety Model

All write operations follow a three-gate safety model:

1. **Env var gate:** `NEXTDNS_WRITE_ENABLED` must be `"true"`
2. **Apply flag gate:** `--apply` must be present
3. **Operator confirmation:** Change plan must be confirmed before execution

Destructive operations have additional safety gates:

| Operation | Additional Flag | Reason |
|-----------|----------------|--------|
| Profile deletion | `--delete-profile` | Irreversible loss of all profile configuration |
| Log clearing | `--clear-logs` | Irreversible loss of all stored DNS query logs |

## Documentation

- [Plugin Overview](../docs/nextdns/overview.md) -- architecture, API, authentication
- [Commands Reference](../docs/nextdns/commands.md) -- all 5 commands with parameters and examples
- [Skills Reference](../docs/nextdns/skills.md) -- all 37 MCP tools documented
- [Authentication Setup](../docs/getting-started/authentication.md) -- API key configuration
- [Workflow Examples](../docs/nextdns/workflows/) -- step-by-step guides
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
      profiles.py     # 8 profile read tools
      profile_writes.py # 12 write tools
      analytics.py    # 11 analytics tools
      logs.py         # 4 log tools
      security_posture.py # 2 security posture tools
    server.py         # MCP server setup and entry point
  tests/
    fixtures/         # Test fixture data
    ...
  SKILL.md            # Plugin manifest (netex vendor contract)
  pyproject.toml
  README.md
```

## License

MIT -- see [LICENSE](../LICENSE) for details.

## Author

[Bluminal Labs](https://bluminal.com)
