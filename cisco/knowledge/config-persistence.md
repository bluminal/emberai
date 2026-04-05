# Config Persistence Model

**Severity:** critical
**Triggers:** write operations, save config, rollback

## Overview

The Cisco SG-300 has a fundamentally different configuration model from
platforms with candidate configs or commit/rollback (such as Junos or
OPNsense). Understanding this model is critical for safe write operations.

## Key Facts

1. **There is NO candidate configuration.** There is no staging area.
2. **There is NO commit/rollback mechanism.** No `rollback confirmed`.
3. **CLI commands take effect IMMEDIATELY when entered.** The moment you
   type `switchport access vlan 100` on an interface, that port moves to
   VLAN 100. There is no "apply" step at the device level.
4. **Running-config is the live configuration.** It reflects the current
   operational state of the switch.
5. **Startup-config is the saved configuration.** It is loaded on boot.

## Persistence: running-config vs startup-config

```
  CLI command entered
        |
        v
  running-config (LIVE, in RAM)
        |
        | write memory
        v
  startup-config (PERSISTENT, in flash)
```

- `write memory` copies running-config to startup-config.
- If you do NOT run `write memory`, a reboot restores startup-config
  (the last explicitly saved state).
- `copy running-config startup-config` is an alias for `write memory`.

## Safety Strategy

Because changes are live-on-entry with no rollback, the plugin implements
the following safety pattern for ALL write operations:

### Before Every Write

1. **Capture `show running-config`** -- store a pre-change snapshot.
2. **Validate the planned change** -- verify preconditions (e.g., VLAN
   exists before assigning a port to it).
3. **Check for operator session risk** -- if the write could affect the
   port or VLAN carrying the SSH management session, warn and require
   explicit confirmation.

### After Every Write

4. **Verify the change** -- re-read the relevant config section and
   confirm the intended change took effect.
5. **Report the result** -- show before/after diff to the operator.
6. **Do NOT auto-save** -- never run `write memory` automatically.
   Saving is always a separate, explicit operator action.

### Saving (write memory)

7. **Only save when the operator explicitly confirms** -- the `save_config`
   tool is a separate action, never bundled with a write.
8. **Verify before saving** -- run `detect_drift` to show the operator
   exactly what unsaved changes exist before persisting them.

## Recovery Options

If a write operation goes wrong:

### Option A: Manual Reversal (preferred)
Manually issue the inverse CLI command(s) to undo the change. For example:
- Wrong VLAN? Re-assign the correct VLAN to the port.
- Wrong trunk config? Re-apply the correct trunk allowed VLANs.

### Option B: Reboot to Last Saved State (nuclear option)
If you have NOT run `write memory` since the bad change, rebooting the
switch restores startup-config. This is a full service interruption and
should only be used as a last resort.

**WARNING:** If you DID run `write memory` after the bad change, the bad
config is now in startup-config and a reboot will NOT help. You must
manually reverse the changes or restore from a known-good config backup.

## Critical Rules

- **NEVER batch-save after multiple unverified changes.** Verify each
  change individually before moving to the next.
- **NEVER auto-save.** The operator must always explicitly request
  `save_config` / `write memory`.
- **NEVER assume a reboot will fix things** if `write memory` has been
  run since the last known-good state.
- **ConfigBackup utility** stores last N snapshots in memory for quick
  comparison, but these are NOT persisted across plugin restarts.
