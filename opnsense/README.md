# opnsense -- OPNsense Gateway Intelligence Plugin

Intelligent OPNsense firewall and router management for [EmberAI](https://github.com/bluminal/emberai). Query, analyze, and manage your OPNsense gateway through natural language -- from interface inventory and firewall audits to VPN health checks and DNS troubleshooting.

Part of the [Netex](https://github.com/bluminal/emberai) three-plugin suite (unifi, opnsense, netex). Works standalone or alongside the unifi plugin for full-stack network intelligence.

## What It Does

The opnsense plugin covers the **gateway layer** of your network through the OPNsense REST API:

- **Interface & VLAN management** -- inventory all interfaces, create VLAN interfaces atomically (interface + IP + DHCP scope in one step), manage DHCP reservations
- **Firewall rule analysis** -- list rules by interface, audit for shadowed and overly-broad rules, derive rulesets from inter-VLAN access matrices, manage aliases
- **Routing** -- static route table, gateway status with latency monitoring
- **VPN tunnel health** -- IPSec SA state and traffic counters, OpenVPN instance status, WireGuard peer handshakes and byte counters
- **DNS (Unbound)** -- host overrides, forwarder configuration, DNS-over-TLS status, live hostname resolution testing
- **DHCP (Kea)** -- active lease inventory per interface, static reservation management, batch reservation creation
- **IDS/IPS (Suricata)** -- alert queries by severity and time window, rule management, policy configuration
- **Diagnostics** -- ping, traceroute, ARP/NDP host discovery, LLDP neighbor table, DNS lookups
- **Firmware** -- version status, package inventory, upgrade availability
- **Security posture** -- certificate expiry tracking, NAT exposure review, comprehensive security audit

It does **not** manage switching, wireless SSIDs, or client WiFi associations -- those belong to the [unifi](../unifi/) plugin (edge layer). When both plugins are installed, the **netex** umbrella orchestrator coordinates cross-vendor workflows.

## Commands

| Command | Description |
|---------|-------------|
| `opnsense scan` | Full inventory of interfaces, VLANs, routes, VPN tunnels, firmware |
| `opnsense health` | Gateway health check -- WAN reachability, IDS alerts, cert expiry, firmware |
| `opnsense diagnose [target]` | Root-cause analysis for a host or interface -- ping, traceroute, firewall path |
| `opnsense firewall [--audit]` | Firewall rule listing; `--audit` adds shadow analysis and broad rule detection |
| `opnsense firewall policy-from-matrix` | Derive and apply firewall ruleset from an inter-VLAN access matrix |
| `opnsense vlan [--configure] [--audit]` | VLAN interface management with atomic creation workflow |
| `opnsense dhcp reserve-batch` | Create multiple static DHCP reservations in one confirmed workflow |
| `opnsense vpn [--tunnel name]` | VPN tunnel status -- IPSec, OpenVPN, WireGuard |
| `opnsense dns [hostname]` | DNS overrides, forwarders, optional resolution test |
| `opnsense secure` | Security posture audit -- IDS, certs, firewall exposure, NAT review |
| `opnsense firmware` | Firmware and package update status |

## Skill Groups (38 MCP Tools)

| Skill | Tools | Description |
|-------|-------|-------------|
| interfaces | 7 | Interface listing, VLAN management, DHCP leases and reservations |
| firewall | 7 | Rules, aliases, NAT, rule CRUD, alias CRUD |
| routing | 3 | Static routes and gateway status |
| vpn | 4 | IPSec, OpenVPN, WireGuard tunnel status |
| security | 4 | IDS/IPS alerts, rules, policy, certificate trust |
| services | 6 | DNS overrides/forwarders, DHCP leases, traffic shaping |
| diagnostics | 5 | Ping, traceroute, host discovery, LLDP, DNS lookup |
| firmware | 2 | Firmware status and package listing |

All tools follow the naming convention `opnsense__{skill}__{operation}` and are registered as MCP tools.

## Quick Install

### Prerequisites

- Python 3.12 or later
- Network access to an OPNsense instance (HTTPS)
- An OPNsense API key and secret (System > Access > Users > API keys)

### Install

```bash
pip install -e ./opnsense
```

### Configure

Set the required environment variables:

```bash
export OPNSENSE_HOST="https://192.168.1.1"   # Your OPNsense URL (include https://)
export OPNSENSE_API_KEY="your-api-key"        # API key (Basic Auth username)
export OPNSENSE_API_SECRET="your-api-secret"  # API secret (Basic Auth password)
```

Or create a `.env` file in the project root:

```env
OPNSENSE_HOST=https://192.168.1.1
OPNSENSE_API_KEY=your-api-key
OPNSENSE_API_SECRET=your-api-secret
```

For self-signed certificates (common for OPNsense):

```bash
export OPNSENSE_VERIFY_SSL="false"
```

### Run

```bash
# Start the MCP server (stdio transport)
opnsense-server

# Test connectivity
opnsense-server --check

# Or run directly
python -m opnsense.server
```

### Verify

After starting the server, test connectivity:

```bash
opnsense-server --check
```

Expected output on success:

```
[INFO] Configuration loaded successfully
[INFO] OPNsense API: connected (https://192.168.1.1)
[INFO] Health check passed
```

## Read-Only by Default

The opnsense plugin operates in **read-only mode** by default. All scan, health, and audit commands are read-only.

Write operations (VLAN creation, firewall rule changes, DHCP reservations) require three gates:

1. `OPNSENSE_WRITE_ENABLED` set to `"true"`
2. The `--apply` flag on the command
3. Explicit operator confirmation of the change plan

OPNsense additionally separates saving a config change from applying it -- the `reconfigure` step is always shown explicitly and requires separate confirmation.

## Documentation

- [Plugin Overview](https://bluminal.github.io/emberai/opnsense/overview/) -- architecture, API pattern, reconfigure model
- [Commands Reference](https://bluminal.github.io/emberai/opnsense/commands/) -- all 11 commands with parameters and examples
- [Skills Reference](https://bluminal.github.io/emberai/opnsense/skills/) -- all 38 MCP tools with signatures and return types
- [Authentication Setup](https://bluminal.github.io/emberai/getting-started/authentication/#opnsense-plugin) -- creating API keys and configuring SSL
- **Workflow Examples:**
    - [First-Time System Scan](https://bluminal.github.io/emberai/opnsense/workflows/first-time-scan/) -- inventory all interfaces, VLANs, routes, VPN tunnels
    - [Review Firewall Rules](https://bluminal.github.io/emberai/opnsense/workflows/review-firewall/) -- list rules, identify disabled or broadly permissive rules
    - [Check VPN Health](https://bluminal.github.io/emberai/opnsense/workflows/check-vpn-health/) -- verify IPSec SAs and WireGuard peers
    - [Troubleshoot DNS](https://bluminal.github.io/emberai/opnsense/workflows/troubleshoot-dns/) -- confirm Unbound resolves correctly
    - [DHCP Lease Audit](https://bluminal.github.io/emberai/opnsense/workflows/dhcp-lease-audit/) -- see all active Kea leases

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
    tools/            # MCP tool implementations (8 skill groups)
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
| `OPNSENSE_HOST` | Yes | URL of the OPNsense instance (include `https://`) |
| `OPNSENSE_API_KEY` | Yes | API key (Basic Auth username) |
| `OPNSENSE_API_SECRET` | Yes | API secret (Basic Auth password) |
| `OPNSENSE_WRITE_ENABLED` | No | Set to `"true"` to enable write operations (default: `false`) |
| `OPNSENSE_VERIFY_SSL` | No | Set to `"false"` for self-signed certs (default: `true`) |
| `NETEX_CACHE_TTL` | No | Override cache TTL in seconds (default: `300`) |

## License

MIT -- see [LICENSE](../LICENSE) for details.

## Author

[Bluminal Labs](https://bluminal.com)
