# UniFi Plugin Overview

The **unifi** plugin provides network intelligence for UniFi deployments. It covers the **edge layer** of the network: switches, access points, wireless SSIDs, client associations, VLANs on switch ports, and site-level health.

## What the Plugin Covers

- **Topology discovery** -- inventory all devices (switches, APs, gateways), VLANs, and uplink relationships
- **Health monitoring** -- subsystem health (WAN, LAN, WLAN, WWW), device-level CPU/memory/temperature, ISP metrics
- **Client management** -- connected client inventory, signal quality, traffic counters, search by MAC/hostname/IP
- **Firmware tracking** -- current vs. available firmware versions across all devices
- **Event log** -- recent network events filtered by time window and severity
- **Diagnostics** -- root-cause analysis for individual devices or clients, correlating health, events, and topology

## What the Plugin Does NOT Cover

The unifi plugin is scoped to the edge layer. It does **not** manage:

- **Routing and gateways** -- static routes, dynamic routing, gateway configuration
- **Firewall rules** -- zone-based firewall, ACLs, NAT, port forwarding
- **VPN tunnels** -- IPSec, WireGuard, OpenVPN
- **DNS** -- Unbound, overrides, blocklists

These belong to the **opnsense** plugin (gateway layer). When both plugins are installed, the **netex** umbrella orchestrator coordinates cross-vendor workflows.

## API Tiers

The plugin communicates with UniFi infrastructure through three API tiers:

| Tier | Base URL | Authentication | Rate Limit | Phase |
|------|----------|---------------|------------|-------|
| Local Gateway | `{UNIFI_LOCAL_HOST}/proxy/network/` | `X-API-KEY` | None | Phase 1 (current) |
| Cloud V1 | `api.ui.com/v1/` | `X-API-KEY` | 10,000 req/min | Phase 2 |
| Site Manager EA | `api.ui.com/ea/` | `X-API-KEY` | 100 req/min | Phase 2 |

Phase 1 uses the **Local Gateway API** exclusively. This requires network access to the UniFi gateway (typically at `192.168.1.1` or a custom hostname). Cloud V1 and Site Manager EA tiers will be added in Phase 2 for multi-site and fleet-level operations.

Response envelopes differ by tier. The plugin normalizes all three into a consistent internal schema. Raw envelope fields (`httpStatusCode`, `traceId`, `totalCount`) are never exposed to the operator.

## Architecture

The plugin is structured in three layers:

```
Commands (user-facing)
  unifi scan, unifi health, unifi clients, unifi diagnose
    |
Agents (orchestration)
  topology agent, health agent, clients agent, diagnose agent
    |
Tools (MCP tools -- direct API calls)
  topology skill (4 tools), health skill (5 tools), clients skill (4 tools)
```

**Tools** are thin MCP-registered functions that make a single API call and return normalized data. Each tool follows the naming convention `unifi__{skill}__{operation}`.

**Agents** orchestrate multiple tools to produce a complete report. For example, the health agent calls `get_site_health`, `get_events`, `get_firmware_status`, and `get_isp_metrics`, then classifies findings by severity.

**Commands** are the user-facing entry points. Each command delegates to an agent function and returns a formatted report.

## Authentication

The plugin requires the following environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `UNIFI_LOCAL_HOST` | Yes | IP or hostname of the UniFi Local Gateway (e.g., `192.168.1.1`) |
| `UNIFI_LOCAL_KEY` | Yes | API key for the Local Gateway |
| `UNIFI_API_KEY` | Phase 2 | API key for Cloud V1 and Site Manager EA |

Optional variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_WRITE_ENABLED` | `false` | Set to `"true"` to enable write operations |
| `NETEX_CACHE_TTL` | `300` | Override TTL for cached responses (seconds) |

On startup, the plugin verifies all required variables are set. If any are missing, it reports which variable is absent and what it is used for, without attempting any API calls.

## Read-Only by Default

The unifi plugin operates in **read-only mode** by default. All Phase 1 commands (`scan`, `health`, `clients`, `diagnose`) are read-only.

Write operations (available in Phase 2+) require:

1. `UNIFI_WRITE_ENABLED` set to `"true"`
2. The `--apply` flag on the command
3. Explicit operator confirmation of the change plan

See [Commands](commands.md) for the full command reference and [Skills](skills.md) for individual tool documentation.

## Related Documentation

- [Commands Reference](commands.md) -- all Phase 1 commands with examples
- [Skills Reference](skills.md) -- individual MCP tool documentation
- [Workflows](workflows/) -- step-by-step workflow examples
