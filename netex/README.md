# netex -- Cross-Vendor Network Orchestration Umbrella

> **Netex is an assistant, not an autonomous agent. It will always ask before changing anything on your network.**

Cross-vendor network orchestration umbrella plugin for [EmberAI](https://github.com/bluminal/emberai). Coordinates installed vendor plugins (unifi, opnsense, and future vendors) to perform operations that span multiple network systems.

Part of the [Netex Suite](https://github.com/bluminal/emberai) three-plugin architecture (unifi, opnsense, netex).

## What It Does

The netex plugin is the **umbrella orchestrator** that coordinates vendor plugins to provide:

- **Unified topology** -- merge device graphs, VLANs, and routing from all installed plugins
- **Cross-vendor health** -- aggregate health findings across all network layers
- **Site provisioning** -- full site bootstrap from a YAML manifest (`provision-site`)
- **VLAN batch creation** -- multi-VLAN provisioning in a single workflow
- **Policy verification** -- test connectivity against an intended access policy
- **Security audits** -- cross-layer firewall, VPN, DNS, and isolation analysis via NetworkSecurityAgent
- **Policy synchronization** -- detect and reconcile configuration drift between vendors
- **DNS tracing** -- resolution path analysis across gateway and edge
- **VPN status** -- cross-layer VPN health with client correlation

netex does **not** talk to any vendor API directly. It discovers installed vendor plugins via the Plugin Registry and delegates all vendor-specific operations to them.

## Requirements

- At least one conforming vendor plugin must be installed (e.g., `unifi`, `opnsense`)
- Python 3.12+

## Quick Start

```bash
pip install netex

# Verify installation and plugin discovery
netex-server --check

# Start the MCP server
netex-server --transport stdio
```

## Commands

### Read-Only

| Command | Description |
|---|---|
| `netex topology` | Unified network topology across all vendors |
| `netex health` | Cross-vendor health report (severity-tiered) |
| `netex vlan audit` | VLAN consistency check (gateway vs edge) |
| `netex dns trace <hostname>` | DNS resolution path tracing |
| `netex vpn status` | VPN tunnel status with cross-layer correlation |
| `netex secure audit` | 10-domain security audit (NetworkSecurityAgent) |
| `netex verify-policy` | Test connectivity against manifest policy |

### Write (require confirmation)

| Command | Description |
|---|---|
| `netex network provision-site` | Full site bootstrap from YAML manifest |
| `netex vlan provision-batch` | Batch VLAN creation across gateway + edge |
| `netex policy sync` | Drift detection and corrective sync |

All write commands require: `NETEX_WRITE_ENABLED=true` + `--apply` flag + operator confirmation.

## Safety Model

Every write operation passes through two safety agents before the operator sees a plan:

- **OutageRiskAgent** -- Assesses whether proposed changes could sever your management session. Four tiers: CRITICAL, HIGH, MEDIUM, LOW.
- **NetworkSecurityAgent** -- Reviews the change plan for security issues across 7 finding categories.

See [Netex vs Autonomous](https://bluminal.github.io/emberai/netex/netex-vs-autonomous/) for the full safety philosophy.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NETEX_WRITE_ENABLED` | `false` | Enable cross-vendor write operations |
| `NETEX_CACHE_TTL` | `300` | TTL in seconds for cached responses |

## Documentation

- [Overview](https://bluminal.github.io/emberai/netex/overview/)
- [Abstract Data Model](https://bluminal.github.io/emberai/netex/abstract-model/)
- [Command Reference](https://bluminal.github.io/emberai/netex/commands/)
- [Connectivity Guide](https://bluminal.github.io/emberai/getting-started/connectivity/)
- [Workflow Examples](https://bluminal.github.io/emberai/netex/workflows/)

## License

MIT
