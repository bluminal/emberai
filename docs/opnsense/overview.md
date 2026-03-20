# OPNsense Plugin Overview

The **opnsense** plugin provides gateway intelligence for OPNsense firewall and router deployments. It covers the **gateway layer** of the network: interfaces, VLAN interfaces, routing table, firewall rules and aliases, NAT, VPN tunnels, DNS resolver (Unbound), DHCP server (Kea), IDS/IPS (Suricata), traffic shaping, and system diagnostics.

## What the Plugin Covers

- **Interface management** -- inventory all interfaces (physical, VLAN, loopback), IP addressing, and link status
- **Firewall rules** -- rule listing, alias management, NAT/DNAT, shadow analysis, policy-from-matrix derivation
- **Routing** -- static routes, gateway status and latency, dynamic routing
- **VPN tunnels** -- IPSec session state, OpenVPN instances, WireGuard peer status and handshakes
- **DNS (Unbound)** -- host overrides, forwarders, DNS-over-TLS status, hostname resolution
- **DHCP (Kea)** -- active leases, static reservations, subnet management
- **IDS/IPS (Suricata)** -- alert queries, rule management, policy configuration
- **Diagnostics** -- ping, traceroute, host discovery, LLDP neighbors, DNS lookup
- **Firmware** -- version status, package inventory, upgrade availability

## What the Plugin Does NOT Cover

The opnsense plugin is scoped to the gateway layer. It does **not** manage:

- **Switching** -- VLAN trunking on switch ports, port profiles, PoE
- **Wireless SSIDs** -- WiFi network configuration, AP radio settings, channel optimization
- **Client WiFi associations** -- client signal quality, roaming, band steering

These belong to the **unifi** plugin (edge layer). When both plugins are installed, the **netex** umbrella orchestrator coordinates cross-vendor workflows such as end-to-end VLAN provisioning and policy auditing.

## API Architecture

The plugin communicates with OPNsense through its local REST API.

| Property | Detail |
|----------|--------|
| Base URL pattern | `{OPNSENSE_HOST}/api/{module}/{controller}/{command}` |
| Authentication | HTTP Basic Auth -- API key as username, API secret as password |
| Read operations | HTTP GET -- always permitted |
| Write operations | HTTP POST -- gated by `OPNSENSE_WRITE_ENABLED` |
| Response format | Flat JSON or `{result, changed}` for action endpoints |
| Rate limits | No published rate limit |

### Core API Modules

| Module | Controllers | Capability |
|--------|-------------|------------|
| interfaces | assignments, loopback, vlan, vxlan, overview | Interface assignments, VLAN interface CRUD |
| firewall | alias, alias_util, category, d_nat, filter, s_nat | Firewall rules, NAT/DNAT, aliases, filter categories |
| routes | routes | Static route CRUD |
| diagnostics | dns, interface, network_insight, packet_capture, ping, traceroute | Live diagnostics |
| ids | policy, rule, ruleset, service, settings | Suricata IDS/IPS management |
| ipsec | connections, key_pairs, pool, sessions | IPSec tunnel CRUD and session status |
| openvpn | clients, export, instances, service | OpenVPN instances and client management |
| wireguard | client, general, server, service | WireGuard peer/server CRUD |
| unbound | alias, dot, forward, host, general, dnsbl, acl | Unbound DNS resolver |
| kea | ctrl_agent, dhcpv4, dhcpv6, leases4, leases6 | Modern DHCP server (Kea) |
| core/firmware | firmware | Firmware updates, package management |
| hostdiscovery | scan | ARP/NDP-based host discovery |
| trafficshaper | pipe, queue, rule | Traffic shaping |

## The Reconfigure Pattern

OPNsense separates saving a configuration change from applying it to the running system. This is a critical architectural concept that affects every write operation.

**Step 1: Save** -- A POST to a `set` or `add` endpoint stores the change in the configuration file. The running system is **not** affected.

**Step 2: Reconfigure** -- A separate POST to the `reconfigure` endpoint pushes the saved configuration to the live system. This is the point of no return.

```
POST /api/firewall/filter/addRule     <- saves the rule to config
POST /api/firewall/filter/apply       <- applies to the live firewall
```

The plugin always models these as two explicit steps in any write plan. Dry-run mode (without `--apply`) shows both steps but skips the reconfigure call entirely. The operator always sees the reconfigure step and must confirm it before execution.

!!! warning "Reconfigure is the point of no return"
    Never call reconfigure without explicit operator confirmation. A misconfigured
    firewall reconfigure can sever the operator's connection to the system being
    managed. The plugin enforces this through the three-step write safety gate.

## Architecture

The plugin is structured in three layers:

```
Commands (user-facing)
  opnsense scan, opnsense health, opnsense firewall, opnsense vpn, ...
    |
Agents (orchestration)
  scan agent, health agent, firewall agent, vpn agent, ...
    |
Tools (MCP tools -- direct API calls)
  interfaces skill (7 tools), firewall skill (7 tools), routing skill (3 tools), ...
```

**Tools** are thin MCP-registered functions that make a single API call and return normalized data. Each tool follows the naming convention `opnsense__{skill}__{operation}`.

**Agents** orchestrate multiple tools to produce a complete report. For example, the health agent calls gateway status, IDS alerts, firmware status, WAN reachability, and certificate expiry, then classifies findings by severity.

**Commands** are the user-facing entry points. Each command delegates to an agent function and returns a formatted report.

## Authentication

The plugin requires the following environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPNSENSE_HOST` | Yes | URL of the OPNsense instance (include scheme, e.g., `https://192.168.1.1`) |
| `OPNSENSE_API_KEY` | Yes | API key (used as HTTP Basic Auth username) |
| `OPNSENSE_API_SECRET` | Yes | API secret (used as HTTP Basic Auth password) |

Optional variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPNSENSE_WRITE_ENABLED` | `false` | Set to `"true"` to enable write operations |
| `OPNSENSE_VERIFY_SSL` | `true` | Set to `"false"` to skip TLS verification for self-signed certs |
| `NETEX_CACHE_TTL` | `300` | Override TTL for cached responses (seconds) |

On startup, the plugin verifies all required variables are set. If any are missing, it reports which variable is absent and what it is used for, without attempting any API calls.

!!! note "API key privileges"
    The API key inherits the Effective Privileges of its owning user in
    OPNsense. Insufficient privileges return HTTP 403. When a 403 is received,
    the plugin tells the operator which resource requires access and where to
    grant it (System > Access > Users > Effective Privileges).

## Read-Only by Default

The opnsense plugin operates in **read-only mode** by default. All scan, health, and audit commands are read-only.

Write operations (VLAN creation, firewall rule changes, DHCP reservations, etc.) require:

1. `OPNSENSE_WRITE_ENABLED` set to `"true"`
2. The `--apply` flag on the command
3. Explicit operator confirmation of the change plan
4. A separate confirmation for the reconfigure step

See [Commands](commands.md) for the full command reference and [Skills](skills.md) for individual tool documentation.

## Related Documentation

- [Commands Reference](commands.md) -- all commands with examples
- [Skills Reference](skills.md) -- individual MCP tool documentation
- [Workflows](workflows/) -- step-by-step workflow examples
