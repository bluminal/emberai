# Netex Suite

[![unifi](https://github.com/bluminal/emberai/actions/workflows/unifi.yml/badge.svg)](https://github.com/bluminal/emberai/actions/workflows/unifi.yml)
[![opnsense](https://github.com/bluminal/emberai/actions/workflows/opnsense.yml/badge.svg)](https://github.com/bluminal/emberai/actions/workflows/opnsense.yml)
[![netex](https://github.com/bluminal/emberai/actions/workflows/netex.yml/badge.svg)](https://github.com/bluminal/emberai/actions/workflows/netex.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Talk to your network infrastructure in natural language through Claude Code.**

Netex Suite is a collection of MCP server plugins that give Claude Code deep visibility into your network -- UniFi access points, OPNsense firewalls, VLANs, VPN tunnels, DNS, DHCP, and more. Ask questions, run diagnostics, and make changes conversationally, with a safety model designed for production networks.

[Full Documentation](https://bluminal.github.io/emberai) · [Getting Started](https://bluminal.github.io/emberai/getting-started/installation/) · [Report an Issue](https://github.com/bluminal/emberai/issues)

---

## Install

```
/plugin install bluminal/emberai:unifi
/plugin install bluminal/emberai:opnsense
/plugin install bluminal/emberai:netex
```

Install whichever plugins match your stack. Each works independently. The `netex` umbrella plugin auto-discovers installed vendor plugins and coordinates operations that span multiple systems.

---

## What You Can Do

Once installed, you can talk to your network the way you'd talk to a senior network engineer. Here are a few examples.

### Diagnose a connectivity issue

> "The security cameras on VLAN 40 can't reach their NVR. Can you trace the path and check for firewall blocks?"

Claude inspects your UniFi topology, identifies the relevant VLAN interfaces on OPNsense, checks firewall rules for inter-VLAN traffic, and reports exactly where the traffic is being dropped -- with the specific rule that's blocking it.

### Audit your firewall posture

> "Review all my firewall rules and flag anything that looks too permissive or redundant."

Claude pulls every rule across your OPNsense interfaces, analyzes them for overly broad source/destination ranges, shadowed rules that never match, and missing egress restrictions. You get a prioritized list of findings with recommended fixes.

### Provision a new site end-to-end

> "Provision the new remote office: create VLANs for corporate, IoT, and guest, set up firewall isolation, configure DHCP scopes, and enable the guest WiFi with client isolation."

Claude builds a change plan covering both your UniFi controller and OPNsense gateway, runs it through the OutageRiskAgent and NetworkSecurityAgent for safety review, then presents the full plan for your approval before touching anything.

---

## Plugins

### unifi (v0.1.0)

UniFi network intelligence. Connects to your UniFi gateway's local API or the Cloud Site Manager.

- Topology discovery and device inventory
- Site and device health monitoring
- WiFi channel utilization and RF analysis
- Client search, location, and traffic inspection
- Firmware status across your fleet
- Security audit (firewall rules, ACLs, port forwards, zone-based policies)
- Configuration drift detection with baseline snapshots
- Write operations: create networks, WLANs, port profiles

[UniFi Plugin Docs](https://bluminal.github.io/emberai/unifi/overview/)

### opnsense (v0.2.0)

OPNsense gateway intelligence. Full coverage of the OPNsense REST API.

- Interface and VLAN management
- Firewall rule analysis and creation
- Static routing and gateway monitoring
- VPN tunnel status (IPsec, WireGuard, OpenVPN)
- DNS management (Unbound) with DNS-over-TLS forwarding
- DHCP configuration and lease audit (dnsmasq and Kea)
- IDS/IPS management (Suricata) with alert triage
- Live diagnostics (ping, traceroute, DNS lookup, packet capture)
- Firmware and plugin management

[OPNsense Plugin Docs](https://bluminal.github.io/emberai/opnsense/overview/)

### netex (v0.3.0)

Cross-vendor orchestration umbrella. Coordinates installed vendor plugins to perform operations that span multiple systems.

- Unified topology map across all vendors
- Cross-vendor health dashboard
- VLAN provisioning that touches both switch and firewall in one operation
- Policy verification and compliance checking
- Security audit across your entire stack
- Post-change policy sync to ensure consistency
- Site provisioning workflows

[Netex Plugin Docs](https://bluminal.github.io/emberai/netex/overview/)

---

## Safety Model

Networks are critical infrastructure. Netex Suite is built around a **human-in-the-loop** assistant model -- not an autonomous agent. Every write operation goes through a three-step gate:

1. **Environment variable** -- Write operations are disabled by default. You must explicitly set the plugin's write-enable variable to `"true"`.
2. **`--apply` flag** -- The command must include an explicit apply flag. Without it, you get a dry-run preview.
3. **Operator confirmation** -- Claude presents the full change plan and waits for your approval before executing.

On top of that, the netex umbrella runs two safety agents before every change plan:

- **OutageRiskAgent** -- Analyzes whether the proposed change could cause an outage, identifies blast radius, and flags high-risk operations.
- **NetworkSecurityAgent** -- Reviews the change for security implications: overly permissive rules, exposed management interfaces, missing isolation boundaries.

Both agents must pass before the change plan is presented to you. If either flags a concern, you see the warning alongside the plan.

[Write Safety Reference](https://bluminal.github.io/emberai/reference/write-safety/)

---

## Configuration

### UniFi Plugin

| Variable | Purpose |
|----------|---------|
| `UNIFI_LOCAL_HOST` | IP or hostname of your UniFi gateway |
| `UNIFI_LOCAL_KEY` | API key for local gateway access |
| `UNIFI_API_KEY` | API key for Cloud V1 / Site Manager |
| `UNIFI_WRITE_ENABLED` | Set to `"true"` to enable write operations (default: disabled) |

### OPNsense Plugin

| Variable | Purpose |
|----------|---------|
| `OPNSENSE_HOST` | OPNsense instance URL (include scheme, e.g. `https://10.0.0.1`) |
| `OPNSENSE_API_KEY` | API key (Basic Auth username) |
| `OPNSENSE_API_SECRET` | API secret (Basic Auth password) |
| `OPNSENSE_VERIFY_SSL` | Set to `"false"` for self-signed certificates |
| `OPNSENSE_WRITE_ENABLED` | Set to `"true"` to enable write operations (default: disabled) |

### Netex Umbrella

| Variable | Purpose |
|----------|---------|
| `NETEX_WRITE_ENABLED` | Set to `"true"` to enable cross-vendor write operations (default: disabled) |

[Full Environment Variable Reference](https://bluminal.github.io/emberai/reference/environment-variables/)

---

## Architecture

```
netex (orchestration umbrella)
  |
  |-- Vendor Plugin Contract v1.0.0
  |      |
  |      |-- unifi plugin
  |      |      └── UniFi Gateway API
  |      |
  |      |-- opnsense plugin
  |      |      └── OPNsense REST API
  |      |
  |      └── (your plugin here)
  |
  |-- OutageRiskAgent
  └── NetworkSecurityAgent
```

Each plugin is an independent MCP server with its own `pyproject.toml`, test suite, and release cycle. The `netex` umbrella discovers vendor plugins dynamically through Python entry points -- it never hardcodes vendor names.

The [Vendor Plugin Contract v1.0.0](contract/v1.0.0/VENDOR_PLUGIN_CONTRACT.md) defines the interface any conforming plugin must implement. If you manage network equipment not yet covered, you can build a plugin and netex will orchestrate it alongside the rest.

---

## Project Structure

```
emberai/
  unifi/          # UniFi network intelligence plugin
  opnsense/       # OPNsense gateway intelligence plugin
  netex/          # Cross-vendor orchestration umbrella
  contract/       # Vendor Plugin Contract specification
  docs/           # Documentation site (MkDocs Material)
```

## Plugin Knowledge Base

Each plugin can maintain a `knowledge/` directory containing operational lessons learned -- gotchas, platform-specific behaviors, and hard-won debugging knowledge that isn't derivable from code or documentation alone.

```
opnsense/
  knowledge/
    INDEX.md              # Manifest of all knowledge entries (always loaded)
    multi-wan.md          # Loaded when working with gateways/failover
    vlan-creation.md      # Loaded when creating VLANs
```

### Convention

**INDEX.md** is referenced from the plugin's SKILL.md and kept lightweight -- one line per entry with trigger keywords and a file path. It is always loaded into context so the AI knows what knowledge exists.

**Knowledge files** contain the detailed operational knowledge. Each has YAML frontmatter with `triggers` (keywords that indicate the file should be read) and `severity` (how critical the knowledge is). Files are read on-demand, only when the current task matches a trigger.

```yaml
---
title: Multi-WAN Gateway Groups & Failover
triggers: [gateway, failover, multi-wan, wan2, policy routing, gateway group]
severity: critical
created: 2026-03-24
---

Content here...
```

### When to add knowledge

Add a knowledge entry when you discover something that:
- Caused an outage or service disruption
- Took significant debugging to identify
- Is a platform-specific behavior not documented in vendor docs
- Would affect anyone attempting the same configuration
- Cannot be derived from reading the code or API documentation

### Severity levels

- **critical** -- Can cause outages. Must be read before making changes in this area.
- **important** -- Significant gotcha. Should be read to avoid wasted time.
- **informational** -- Useful context. Read if you want deeper understanding.

---

## Development

Each plugin is independently installable with its own virtual environment.

```bash
cd unifi
uv sync --group dev
uv run pytest
uv run ruff check .
uv run mypy src/
```

All plugins enforce:
- **80% test coverage** minimum (`pytest` + `coverage`)
- **Strict type checking** (`mypy --strict`)
- **Linting** (`ruff`)
- **Async test support** (`pytest-asyncio`)

---

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

If you're building a new vendor plugin, start with the [Vendor Plugin Contract v1.0.0](contract/v1.0.0/VENDOR_PLUGIN_CONTRACT.md) to understand the interface your plugin needs to implement.

---

## License

[MIT](LICENSE)
