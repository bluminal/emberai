# netex -- Cross-Vendor Network Orchestration Umbrella

Cross-vendor network orchestration umbrella plugin for [EmberAI](https://github.com/bluminal/emberai). Coordinates installed vendor plugins (unifi, opnsense, and future vendors) to perform operations that span multiple network systems.

Part of the [Netex](https://github.com/bluminal/emberai) three-plugin suite (unifi, opnsense, netex).

## What It Does

The netex plugin is the **umbrella orchestrator** that coordinates vendor plugins to provide:

- **Unified topology** -- merge device graphs, VLANs, and routing from all installed plugins
- **Cross-vendor health** -- aggregate health findings across all network layers
- **VLAN provisioning** -- end-to-end VLAN creation across gateway and edge in one workflow
- **Security audits** -- cross-layer firewall, VPN, DNS, and isolation analysis
- **Policy synchronization** -- detect and reconcile configuration drift between vendors

netex does **not** talk to any vendor API directly. It discovers installed vendor plugins via the Plugin Registry and delegates all vendor-specific operations to them.

## Requirements

- At least one conforming vendor plugin must be installed (e.g., `unifi`, `opnsense`)
- Python 3.12+

## Quick Start

```bash
pip install netex

# Verify installation
netex-server --check

# Start the MCP server
netex-server --transport stdio
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NETEX_WRITE_ENABLED` | `false` | Enable cross-vendor write operations |
| `NETEX_CACHE_TTL` | `300` | TTL in seconds for cached responses |
