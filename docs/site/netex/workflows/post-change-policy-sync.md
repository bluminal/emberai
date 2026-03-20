# Post-Change Policy Sync and Validation

> **Difficulty:** Advanced | **Time:** 15-20 minutes | **Risk:** Read-only (audit), Write (sync)

## Problem Statement

After a maintenance window or a series of manual changes across your gateway and edge systems, you need to verify that the network's actual state matches the intended policy. Configuration drift between OPNsense and UniFi is common after manual changes, especially when changes are made to one system but not the other.

## Prerequisites

- Netex umbrella plugin installed
- OPNsense and UniFi plugins installed and authenticated
- Write access needed only if you want to apply corrections

## Workflow

### Step 1: Run Policy Sync in Dry-Run Mode

```
"netex policy sync --dry-run"
```

This compares the actual state of both systems across four domains:

1. **VLAN Definitions** -- Do the same VLANs exist on both gateway and edge?
2. **DNS Search Domains** -- Are DNS configurations consistent?
3. **Firewall Zone Naming** -- Do interface/zone names match across systems?
4. **Firmware State** -- Are both systems current on patches?

### Step 2: Review the Drift Report

Example output:

```
## Policy Sync Report

**Plugins:** 1 gateway, 1 edge

### VLAN Definitions
- DRIFT: VLAN 30 (iot) exists on gateway but not on edge
- DRIFT: VLAN 70 (testing) exists on edge but not on gateway
- OK: VLANs 10, 20, 50, 60 consistent across both systems

### DNS Search Domains
- DRIFT: Gateway search domain is "home.lan", edge has no search domain set
- Recommended: Set edge search domain to "home.lan"

### Firewall Zone Naming
- OK: All zone names consistent

### Firmware State
- WARNING: Gateway firmware 2 versions behind
- OK: Edge firmware current
```

### Step 3: Decide What to Fix

Review each drift item and decide:
- **Fix on gateway**: Create the missing VLAN interface
- **Fix on edge**: Create the missing network object
- **Ignore**: Intentional difference (e.g., testing VLAN only needed on edge)

### Step 4: Apply Corrections (if needed)

```
"netex policy sync --apply"
```

This enters the three-phase confirmation flow:
- Phase 1: Resolves current state
- Phase 2: Presents corrective change plan
- Phase 3: Executes with operator confirmation

### Step 5: Verify After Sync

```
"netex vlan audit"
```

Confirm all VLANs are now consistent across both layers.

```
"netex secure audit"
```

Run a security audit to ensure the corrections did not introduce any security gaps.

## When to Run This Workflow

- **After manual changes**: Any time you manually configure something on OPNsense or UniFi
- **After a maintenance window**: Especially if changes were made to both systems
- **Weekly/monthly hygiene**: Catch slow drift before it causes issues
- **After firmware updates**: Verify configurations survived the update

## Working Safely

The dry-run mode is entirely read-only. Applying corrections requires `NETEX_WRITE_ENABLED=true` and the `--apply` flag. Each correction is assessed by the OutageRiskAgent before execution.

> **Required safety notice:** Network changes can result in outages that disconnect you from your ability to correct them. Never make changes to a network you cannot reach through an out-of-band path (serial console, IPMI/iDRAC, a separate management VLAN on a different physical interface, or physical access). Netex will assess this risk for you, but it cannot guarantee your recovery path -- only you can verify that.

## Related Workflows

- [VLAN Audit](vlan-audit.md)
- [Unified Health Check](unified-health.md)
- [New Site Onboarding](new-site-onboarding.md)
