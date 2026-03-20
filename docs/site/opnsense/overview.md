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

These belong to the [unifi plugin](../unifi/overview.md) (edge layer). When both plugins are installed, the **netex** umbrella orchestrator coordinates cross-vendor workflows.

## Architecture

The plugin communicates with OPNsense through its local REST API using HTTP Basic Auth with an API key and secret pair.

All endpoints follow the pattern: `{OPNSENSE_HOST}/api/{module}/{controller}/{command}`

- **GET** requests are read operations (always permitted)
- **POST** requests are write operations (gated by `OPNSENSE_WRITE_ENABLED`)

### The Reconfigure Pattern

OPNsense separates saving a configuration change from applying it. A write stores the change in config but does NOT activate it. A separate `reconfigure` call applies it to the live system. The plugin always models these as two explicit steps.

## Getting Started

1. [Install the plugin](../getting-started/installation.md)
2. [Configure authentication](../getting-started/authentication.md#opnsense-plugin)
3. [Run your first scan](../getting-started/quick-start.md)

## Documentation

- [Commands Reference](commands.md) -- all commands with examples
- [Skills Reference](skills.md) -- individual MCP tool documentation
- [Workflows](workflows/first-time-scan.md) -- step-by-step workflow examples
