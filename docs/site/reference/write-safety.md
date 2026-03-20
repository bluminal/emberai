# Write Safety

Every write operation across all three Netex plugins is protected by a three-step safety gate. This page documents the mechanics in detail.

!!! danger "Required reading before enabling write operations"
    Network changes can result in outages that disconnect you from your ability
    to correct them. Never make changes to a network you cannot reach through
    an out-of-band path (serial console, IPMI/iDRAC, a separate management VLAN
    on a different physical interface, or physical access). Netex will assess
    this risk for you, but it cannot guarantee your recovery path — only you can
    verify that.

## The Three-Step Gate

All three conditions must be satisfied before any write operation executes. If any step fails, the operation stops safely.

### Step 1: Environment Variable

The plugin's write-enable environment variable must be set to `"true"`:

| Plugin | Variable |
|--------|----------|
| unifi | `UNIFI_WRITE_ENABLED=true` |
| opnsense | `OPNSENSE_WRITE_ENABLED=true` |
| netex | `NETEX_WRITE_ENABLED=true` |

**When disabled (default):** The tool returns an error message explaining that write operations are not enabled for this plugin, and tells the operator which variable to set.

```
Write operations are not enabled for the unifi plugin.
Set UNIFI_WRITE_ENABLED=true to enable write operations.
```

**Design rationale:** This gate prevents accidental writes in environments where the plugin is deployed for monitoring only. It is an explicit opt-in at the infrastructure level.

### Step 2: The `--apply` Flag

The command must include the `--apply` flag to indicate the operator intends to execute changes, not just preview them.

**Without `--apply` (dry run):** The tool constructs and presents the full change plan — including the OutageRiskAgent assessment, security review, and rollback plan — but does not execute any steps. This is the default behavior for all write-capable commands.

```
Dry run — no changes will be made.

Change Plan:
  1. Create VLAN 30 (IoT) on USW-Pro-24-PoE
  2. Assign ports 5-8 to VLAN 30
  3. Create WiFi network "IoT" on VLAN 30

To execute this plan, re-run with --apply.
```

**Design rationale:** Every write-capable command is safe to run without `--apply`. Operators can preview plans freely without risk.

### Step 3: Operator Confirmation

After the plan is presented (with `--apply`), the operator must explicitly confirm before execution begins. The confirmation prompt includes the total scope of the change:

```
This plan contains 3 steps across 1 system (UniFi).
Outage Risk: LOW — no infrastructure in your session path is affected.

Confirm to proceed, or tell me what to change.
```

**Without confirmation:** Nothing is executed. The operator can modify the plan, cancel entirely, or ask questions before deciding.

**Design rationale:** This is the final human-in-the-loop gate. The operator sees the complete plan with risk assessment before committing to any change.

## What Happens at Each Gate

| Scenario | Step 1 (env var) | Step 2 (--apply) | Step 3 (confirm) | Result |
|----------|-----------------|------------------|-------------------|--------|
| Read-only monitoring | Disabled | N/A | N/A | Writes blocked with clear error |
| Plan preview | Enabled | Not set | N/A | Full plan shown, no execution |
| Ready but not confirmed | Enabled | Set | Not given | Plan shown, waiting for operator |
| Full execution | Enabled | Set | Confirmed | Changes executed |

## Plan Presentation Format

When a write-capable command is invoked (with or without `--apply`), the plan is always presented in this order:

1. **Outage Risk Assessment** — from the OutageRiskAgent
2. **Security Review** — from the NetworkSecurityAgent (netex umbrella only)
3. **Change Plan** — numbered steps in dependency order
4. **Rollback Plan** — what will be reversed if execution fails or is manually triggered

Each step in the change plan includes:

- The target system and component
- The specific API operation
- The expected before and after state
- Whether the step is reversible

## Rollback Behavior

### Automatic Rollback Presentation

Every change plan includes a rollback section that describes how to reverse each step. The rollback plan is presented *before* execution, so the operator knows the recovery path.

### On Execution Failure

If a step fails during execution:

1. **Execution stops immediately** — no subsequent steps run
2. **Netex reports** exactly which steps completed successfully and which failed
3. **Netex asks the operator**: "Should I attempt rollback, or leave the current state for you to assess manually?"

Netex never attempts automatic rollback. The operator always decides, because:

- The failure itself may have left the network in a state where rollback is unsafe
- The operator may prefer to fix the issue manually rather than rolling back
- A partial rollback could be worse than the partial completion

### OPNsense-Specific: Write vs. Reconfigure

OPNsense has an additional safety layer: writing a configuration change and applying it to the live system are always separate operations.

1. **Write** — saves the configuration change to OPNsense's config store
2. **Reconfigure** — applies the saved configuration to the live system

A write without a reconfigure has no effect on live traffic. This gives the operator a window to review the configuration before it takes effect. Netex always makes this distinction explicit in the change plan.

## Cross-Plugin Writes (Netex Umbrella)

When the netex umbrella orchestrates a cross-vendor write (e.g., creating a VLAN on both OPNsense and UniFi), all three plugin-level gates must be satisfied:

- `NETEX_WRITE_ENABLED=true` (umbrella gate)
- `OPNSENSE_WRITE_ENABLED=true` (gateway gate)
- `UNIFI_WRITE_ENABLED=true` (edge gate)

The umbrella presents a single unified plan covering both systems, with one OutageRiskAgent assessment and one confirmation. The operator does not need to confirm each system separately.

## See Also

- [Safety & Human Supervision](../getting-started/safety.md) — the full interaction model
- [Environment Variables](environment-variables.md) — all configuration variables
