# Cross-Vendor VLAN Audit

> **Difficulty:** Basic | **Time:** 10-15 minutes | **Risk:** Read-only

## Problem Statement

You want to verify that your VLAN definitions are consistent across the gateway (OPNsense) and edge (UniFi) layers. Drift between these systems is a common source of connectivity issues -- a VLAN that exists on the switch but not on the gateway will have no routing.

## Prerequisites

- Netex umbrella plugin installed
- Gateway plugin (opnsense) and edge plugin (unifi) installed
- Both plugins authenticated and operational

## Workflow

### Step 1: Run the VLAN Audit

```
"netex vlan audit"
```

Netex queries both plugins:
- `opnsense__interfaces__list_vlan_interfaces` -- VLANs on the gateway
- `unifi__topology__get_vlans` -- VLANs on the edge (UniFi networks)

It merges the results using the abstract VLAN model and compares.

### Step 2: Review the Drift Report

The audit produces a table showing each VLAN and its state on each layer:

```
### VLAN Consistency Report

| VLAN ID | Name        | Gateway | Edge   | DHCP | Status    |
|---------|-------------|---------|--------|------|-----------|
| 10      | management  | OK      | OK     | Yes  | Consistent |
| 20      | trusted     | OK      | OK     | Yes  | Consistent |
| 30      | iot         | OK      | MISSING| Yes  | DRIFT     |
| 50      | guest       | OK      | OK     | Yes  | Consistent |
| 99      | cameras     | MISSING | OK     | No   | DRIFT     |
```

**DRIFT** status means the VLAN exists on one layer but not the other:
- Gateway only: traffic reaches the gateway but the switch does not tag it
- Edge only: the switch tags traffic but the gateway has no interface to route it

### Step 3: Investigate Drift

For each drifted VLAN:

```
"Show me details for VLAN 30 on both systems"
```

Common causes:
- VLAN created on one system but not the other during manual provisioning
- VLAN deleted from one system during cleanup
- VLAN ID mismatch (same name, different ID)

### Step 4: Remediate (if needed)

```
"Create VLAN 30 (iot, 10.30.0.0/24) on the edge"
```

Or use the batch provisioning command:

```
"netex vlan provision-batch" with the corrected manifest
```

### Step 5: Filter by VLAN

To audit a single VLAN:

```
"netex vlan audit --vlan 30"
```

## Working Safely

The audit workflow is read-only. Remediation requires explicit write commands with `--apply`.

## Related Workflows

- [Unified Health Check](unified-health.md)
- [Topology Map](topology.md)
- [Cross-VLAN Troubleshooting](cross-vlan-troubleshooting.md)
