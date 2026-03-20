# Netex Overview

Netex is the umbrella orchestrator in the three-plugin Netex Suite for the EmberAI marketplace. It coordinates installed vendor plugins to perform cross-vendor network operations that no single plugin can achieve alone.

## What Netex Does

Netex treats your entire network as a single system, even when it spans multiple vendor platforms. Instead of switching between OPNsense and UniFi dashboards, you describe what you want and netex figures out which tools to call on which systems, in what order, with safety checks at every step.

### Core Capabilities

| Capability | Description | Command |
|---|---|---|
| Unified topology | Single view of gateway + edge + wireless | `netex topology` |
| Unified health | Severity-tiered health across all vendors | `netex health` |
| VLAN audit | Cross-vendor VLAN consistency check | `netex vlan audit` |
| Site provisioning | Full site bootstrap from YAML manifest | `netex network provision-site` |
| Policy verification | Test connectivity against intended policy | `netex verify-policy` |
| Batch VLAN creation | Multi-VLAN provisioning in one workflow | `netex vlan provision-batch` |
| Security audit | 10-domain security assessment | `netex secure audit` |
| Policy sync | Cross-vendor drift detection and correction | `netex policy sync` |
| DNS tracing | Resolution path analysis | `netex dns trace` |
| VPN status | Cross-layer VPN health | `netex vpn status` |

### What Netex Does NOT Do

- Netex does not replace vendor plugins. It coordinates them.
- Netex does not make autonomous changes. Every write requires explicit operator confirmation.
- Netex does not store network configuration. It queries live state from vendor plugins.
- Netex does not require all vendor plugins. It works with whatever is installed.

## Architecture

Netex operates at the top of a two-layer plugin model:

```
+---------------------------------------------------+
|  netex (umbrella)                                  |
|  - Plugin Registry (discovers installed plugins)   |
|  - Abstract Data Model (vendor-neutral concepts)   |
|  - OutageRiskAgent (pre-change risk assessment)    |
|  - NetworkSecurityAgent (security review)          |
|  - Workflow State Machine (rollback support)       |
+---------------------------------------------------+
         |                         |
+------------------+    +------------------+
|  opnsense        |    |  unifi           |
|  (gateway layer) |    |  (edge layer)    |
+------------------+    +------------------+
```

Each vendor plugin conforms to the **Vendor Plugin Contract v1.0.0**, which specifies:
- Standard skill groups (topology, health, firewall, etc.)
- Consistent tool naming (`vendor__skill__operation`)
- Plugin metadata for registry discovery

## Key Design Principles

### Human-in-the-Loop

Netex is an **assistant**, not an autonomous agent. Every change follows a three-phase confirmation model:

1. **Resolve** -- Gather state, resolve assumptions, assess risk
2. **Plan** -- Present the change plan with security review and rollback
3. **Execute** -- Only after explicit operator confirmation

### Pre-Change Safety Gates

Every write operation passes through two safety agents:

- **OutageRiskAgent** -- Assesses whether the proposed changes could sever the operator's management session. Four risk tiers: CRITICAL, HIGH, MEDIUM, LOW.
- **NetworkSecurityAgent** -- Reviews the change plan for security issues across seven finding categories.

### Graceful Degradation

Netex works with whatever vendor plugins are installed:
- Only OPNsense? Netex provides gateway-layer commands.
- Only UniFi? Netex provides edge-layer commands.
- Both? Netex provides full cross-vendor orchestration.
- Neither? Netex reports no plugins found and suggests installation.

## Getting Started

1. Install netex: `pip install netex`
2. Install at least one vendor plugin: `pip install opnsense` and/or `pip install unifi`
3. Configure vendor plugin credentials (see vendor plugin docs)
4. Run the health check: `netex --check`
5. Try the first command: `netex health`

See the [Getting Started guide](../getting-started/connectivity.md) for detailed setup instructions.
