# Unified Network Health Check

> **Difficulty:** Basic | **Time:** 5-10 minutes | **Risk:** Read-only

## Problem Statement

You want a single view of your entire network's health across all layers -- gateway, edge, wireless -- without switching between vendor dashboards. This is the first command most operators run after installing netex.

## Prerequisites

- Netex umbrella plugin installed
- At least one vendor plugin installed (opnsense, unifi, or both)

## Workflow

### Step 1: Run the Unified Health Check

```
"netex health"
```

Netex queries all installed plugins via `registry.tools_for_skill("health")` and `registry.tools_for_skill("diagnostics")`, then merges the results into a unified report.

### Step 2: Read the Report

The report is organized by severity tier, not by vendor:

**CRITICAL and HIGH findings always appear first**, regardless of which vendor plugin produced them. This ensures you see the most important issues immediately.

Example output structure:

```
## Network Health Report

**Plugins queried:** opnsense (gateway), unifi (edge)

### [!!!] CRITICAL
- [opnsense] Firmware 3 versions behind -- known CVE in current version
- [unifi] AP-Garage offline for 4 hours

### [!!] HIGH
- [opnsense] WAN interface utilization at 95% sustained
- [unifi] Switch USW-24 has 2 ports in error state

### [!] Warning
- [opnsense] DNS forwarder not using DoT
- [unifi] 3 clients on legacy 2.4 GHz with poor RSSI

### [i] Informational
- [opnsense] 14 days uptime, 4 VPN tunnels active
- [unifi] 47 clients connected across 3 APs
```

### Step 3: Drill Down

For any finding that needs investigation, use the vendor-specific command:

```
"opnsense firmware check"
"Show me details on the offline AP"
```

## Site-Specific Health

If your UniFi deployment has multiple sites:

```
"netex health --site ridgeline"
```

Filters the health check to a specific site while still including gateway-level data.

## Working Safely

This workflow is entirely read-only. No changes are made to the network.

## Related Workflows

- [VLAN Audit](vlan-audit.md)
- [Topology Map](topology.md)
