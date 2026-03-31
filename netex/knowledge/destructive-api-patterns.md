# Destructive API Patterns — Read-Modify-Write Safety

**Severity:** critical
**Triggers:** port override, switch config, device config, PUT, update device, write operation, bulk update, array replacement

## Problem

Several vendor APIs use **PUT endpoints that replace entire configuration arrays** rather than merging or patching individual entries. Sending a PUT with a partial array silently deletes all entries not included in the payload. This can cause network-wide outages.

Known destructive PUT patterns:

### UniFi Controller — `port_overrides`

`PUT /api/s/{site}/rest/device/{id}` with `{"port_overrides": [...]}` **replaces all port overrides** on the switch. If only one port is included, all other ports lose their VLAN assignments, PoE settings, trunk profiles, and link aggregation groups.

**Impact:** Network-wide outage. Trunk ports between switches lose VLAN tagging, downstream switches and APs go offline, all segmented VLANs collapse to default.

### OPNsense — Alias Content

`PUT` to alias endpoints replaces the content array. Sending a partial list removes existing entries.

## Mandatory Safety Pattern

All write operations that modify arrays on vendor APIs MUST follow the read-modify-write pattern:

1. **READ** the current full state of the object being modified
2. **VALIDATE** the read was successful and contains the expected data
3. **MODIFY** only the specific entries that need to change
4. **VERIFY** the modified array has >= the same number of entries as the original (unless intentionally removing entries with operator confirmation)
5. **WRITE** the complete modified array back
6. **CONFIRM** the write succeeded and the resulting state matches expectations

## Pre-Write Checks

Before any write operation that modifies an array:

- Log the current array size: "Current port_overrides: 12 entries"
- Log what will change: "Modifying port 4: poe_mode auto -> off"
- If the resulting array is smaller than the original, **STOP and ask the operator**: "This operation would remove {N} port overrides. Confirm?"

## OutageRiskAgent Integration

The netex OutageRiskAgent should flag any write operation that:
- Modifies switch port configurations (affects physical network fabric)
- Changes trunk port profiles (affects inter-switch and switch-to-gateway links)
- Modifies link aggregation groups (affects redundant switch interconnects)
- Alters PoE settings on ports with connected APs or switches (power cycle downstream devices)

These operations should be classified as **CRITICAL** outage risk.

## Never Use Direct API Calls for Array Modifications

Plugin tools should encapsulate the read-modify-write pattern so that callers cannot accidentally send destructive partial updates. The tool layer must:
- Accept only the specific field(s) being changed (e.g., `port_idx=4, poe_mode="auto"`)
- Internally fetch the full current state
- Apply the change to the fetched state
- Write the complete state back
- Never expose raw PUT endpoints that accept full arrays to the operator
