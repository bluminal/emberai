# opnsense -- OPNsense Gateway Intelligence Plugin

OPNsense gateway intelligence plugin for [EmberAI](https://github.com/bluminal/emberai). Provides interface and VLAN management, firewall rule analysis, static routing, VPN tunnel status, DNS (Unbound), DHCP (Kea), IDS/IPS (Suricata), traffic shaping, live diagnostics, and firmware management via the OPNsense REST API.

Part of the [Netex](https://github.com/bluminal/emberai) three-plugin suite (unifi, opnsense, netex).

## What It Does

The opnsense plugin covers the **gateway layer** of the network: interfaces, VLAN interfaces, routing table, firewall rules and aliases, NAT, VPN tunnels, DNS resolver (Unbound), DHCP server (Kea), IDS/IPS (Suricata), traffic shaping, and system diagnostics. It does **not** manage switching, wireless SSIDs, or client WiFi associations -- those belong to the [unifi](../unifi/) plugin (edge layer).

## Features (Phase 2 -- v0.2.0)

### Commands

| Command | Description |
|---------|-------------|
| `opnsense scan` | Full inventory of interfaces, VLANs, routes, VPN tunnels, firmware |
| `opnsense health` | Gateway health check with WAN reachability, IDS alerts, cert expiry |
| `opnsense diagnose` | Root-cause analysis for a host or interface |
| `opnsense firewall` | Firewall rule listing and audit (shadow analysis, broad rules) |
| `opnsense vlan` | VLAN interface management with atomic configure workflow |
| `opnsense vpn` | VPN tunnel status (IPsec, OpenVPN, WireGuard) |
| `opnsense dns` | DNS overrides, forwarders, and hostname resolution |
| `opnsense secure` | Security posture audit (IDS, certs, NAT exposure) |
| `opnsense firmware` | Firmware and package update status |

### Skill Groups (MCP Tools)

| Skill | Tools | Description |
|-------|-------|-------------|
| interfaces | 6 | Interface listing, VLAN management, DHCP leases and reservations |
| firewall | 7 | Rules, aliases, NAT, rule management |
| routing | 3 | Static routes and gateway status |
| vpn | 4 | IPsec, OpenVPN, WireGuard tunnel status |
| security | 4 | IDS/IPS alerts, rules, policy, certificates |
| services | 6 | DNS overrides/forwarders, DHCP leases, traffic shaping |
| diagnostics | 5 | Ping, traceroute, host discovery, LLDP, DNS lookup |
| firmware | 2 | Firmware status and package listing |

Read operations are always permitted. Write operations require `OPNSENSE_WRITE_ENABLED=true` and operator confirmation.

## Quick Install

### Prerequisites

- Python 3.12 or later
- Network access to an OPNsense instance
- An OPNsense API key and secret (System > Access > Users > API keys)

### Install

```bash
pip install -e ./opnsense
```

### Configure

Set the required environment variables:

```bash
export OPNSENSE_HOST="https://192.168.1.1"   # Your OPNsense host
export OPNSENSE_API_KEY="your-api-key"        # API key (Basic Auth username)
export OPNSENSE_API_SECRET="your-api-secret"  # API secret (Basic Auth password)
```

Or create a `.env` file in the project root:

```env
OPNSENSE_HOST=https://192.168.1.1
OPNSENSE_API_KEY=your-api-key
OPNSENSE_API_SECRET=your-api-secret
```

### Run

```bash
# Start the MCP server (stdio transport)
opnsense-server

# Run a health check
opnsense-server --check

# Or run directly
python -m opnsense.server
```

## Documentation

- [Plugin Overview](../docs/opnsense/overview.md) -- architecture, API pattern, authentication
- [Commands Reference](../docs/opnsense/commands.md) -- all commands with examples
- [Skills Reference](../docs/opnsense/skills.md) -- individual MCP tool documentation

## Development

```bash
# Install with dev dependencies
pip install -e "./opnsense[dev]"

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
opnsense/
  src/opnsense/
    api/              # HTTP client for OPNsense REST API
    agents/           # Command orchestrators (scan, health, firewall, etc.)
    models/           # Pydantic data models
    tools/            # MCP tool implementations
    server.py         # MCP server setup and entry point
  tests/
    ...
  SKILL.md            # Plugin manifest (netex vendor contract)
  pyproject.toml
  README.md
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPNSENSE_HOST` | Yes | IP or hostname of the OPNsense instance |
| `OPNSENSE_API_KEY` | Yes | API key (Basic Auth username) |
| `OPNSENSE_API_SECRET` | Yes | API secret (Basic Auth password) |
| `OPNSENSE_WRITE_ENABLED` | No | Set to `"true"` to enable write operations (default: `false`) |
| `OPNSENSE_VERIFY_SSL` | No | Set to `"false"` for self-signed certs (default: `true`) |
| `NETEX_CACHE_TTL` | No | Override cache TTL in seconds (default: `300`) |

## License

MIT -- see [LICENSE](../LICENSE) for details.

## Author

[Bluminal Labs](https://bluminal.com)
