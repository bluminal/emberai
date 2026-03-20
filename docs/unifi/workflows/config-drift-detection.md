# Detect Configuration Drift

## Intent

"I want to compare current config against a pre-change baseline."

## Prerequisites

- **Plugin:** `unifi` v0.2.0 or later
- **API privileges:** Read-only access for drift detection; read-write for saving baselines
- **Environment variables:** `UNIFI_LOCAL_HOST` and `UNIFI_LOCAL_KEY` must be configured
- **For saving baselines:** `UNIFI_WRITE_ENABLED=true` must be set

## Context

Run this workflow after a maintenance window, after another team member makes changes, or as part of a periodic configuration review. Drift detection compares the live network configuration against a saved baseline snapshot and highlights every difference.

Baselines capture device settings, VLAN configurations, firewall rules, port profiles, and wireless settings. Saving a baseline is a write operation (it stores a snapshot), but the drift comparison itself is read-only.

This workflow covers UniFi-side configuration only. For cross-vendor drift detection (UniFi + OPNsense), use `netex config --drift` from the umbrella plugin.

## Working Safely

This workflow includes one **optional write operation**: saving a baseline snapshot.

- **What it writes:** A JSON snapshot of the current configuration stored locally by the MCP server. No changes are made to the network itself.
- **Outage risk:** None. Saving a baseline is a passive read-and-store operation. It does not modify any device or network setting.
- **When to save:** Save a baseline before a planned change (pre-change baseline) and after verifying the change was successful (post-change baseline).

Saving a baseline requires `UNIFI_WRITE_ENABLED=true` and the `--apply` flag. Drift detection (`unifi config --drift`) is always read-only.

## Commands

### Step 1: Save a pre-change baseline

Before making changes, save a snapshot of the current configuration.

```
You: Save a config baseline for my network
```

```
EmberAI:

## Save Configuration Baseline

The following configuration will be captured:

| Category       | Items |
|----------------|-------|
| Devices        | 3     |
| VLANs          | 4     |
| Firewall rules | 8     |
| Port profiles  | 2     |
| Wireless SSIDs | 3     |

Save this baseline? This requires UNIFI_WRITE_ENABLED=true and --apply.
```

```
You: Yes, save it with --apply
```

```
EmberAI:

## Baseline Saved

| Field       | Value                          |
|-------------|--------------------------------|
| Baseline ID | baseline-20260319-143022       |
| Timestamp   | 2026-03-19T14:30:22Z           |
| Site        | default                        |
| Items       | 20 config objects captured     |

This baseline can be used as a reference for future drift detection.
```

### Step 2: Detect drift after changes

After changes have been made (by you or someone else), compare the current state against the baseline.

```
You: Check for config drift
```

```
EmberAI:

## Configuration Drift Report

Comparing current config against baseline-20260319-143022
(saved 2026-03-19T14:30:22Z, 4 hours ago)

### Summary
| Category       | Baseline | Current | Changed | Added | Removed |
|----------------|----------|---------|---------|-------|---------|
| Devices        | 3        | 3       | 1       | 0     | 0       |
| VLANs          | 4        | 5       | 0       | 1     | 0       |
| Firewall rules | 8        | 9       | 0       | 1     | 0       |
| Port profiles  | 2        | 2       | 1       | 0     | 0       |
| Wireless SSIDs | 3        | 3       | 0       | 0     | 0       |

Total drift: **4 changes** detected.

### Changes

#### VLAN Added
| Field    | Value              |
|----------|--------------------|
| Name     | Cameras            |
| VLAN ID  | 40                 |
| Subnet   | 192.168.40.0/24    |
| DHCP     | Yes                |
| Purpose  | corporate          |

#### Firewall Rule Added
| Field       | Value                          |
|-------------|--------------------------------|
| Action      | Block                          |
| Source      | 192.168.40.0/24 (Cameras)      |
| Destination | 192.168.1.0/24 (LAN)           |
| Protocol    | any                            |
| Log         | Yes                            |
| Position    | 5                              |

#### Device Changed: Office-Switch-16
| Setting        | Baseline          | Current            |
|----------------|-------------------|--------------------|
| Firmware       | 7.0.50.15116      | 7.0.72.15290       |
| Port 8 profile | Default           | Cameras-Trunk      |

#### Port Profile Changed: Cameras-Trunk
| Setting       | Baseline       | Current                |
|---------------|----------------|------------------------|
| Native VLAN   | (not present)  | 40                     |
| Tagged VLANs  | (not present)  | 1, 99                  |
```

### Step 3: Review and acknowledge

```
You: That looks correct -- those were the planned changes. Save a new baseline.
```

```
EmberAI:

## Baseline Saved

| Field       | Value                          |
|-------------|--------------------------------|
| Baseline ID | baseline-20260319-183512       |
| Timestamp   | 2026-03-19T18:35:12Z           |
| Site        | default                        |
| Items       | 22 config objects captured     |

Previous baseline (baseline-20260319-143022) is retained for future
comparison. Use `unifi config --drift --baseline baseline-20260319-143022`
to compare against a specific baseline.
```

## What to Look For

**Expected vs. unexpected drift:**
- After a planned maintenance window, all changes should be accounted for. Drift items that do not match the change plan indicate unauthorized or accidental changes.
- Firmware upgrades appearing as drift are expected if a firmware update was applied. However, unexpected firmware changes may indicate auto-update settings.

**Security-relevant drift:**
- New firewall rules, especially "pass any any" rules, require immediate review.
- Port profile changes on trunk ports can expose VLANs that were previously isolated.
- New port forwards (visible through the firewall posture audit) are not captured in the baseline but complement this workflow.

**VLAN changes:**
- A new VLAN added in UniFi should have a corresponding VLAN and firewall rules on the OPNsense gateway. Use `netex vlan audit` to verify cross-vendor consistency.

**Baseline age:**
- A very old baseline (weeks or months) will show a large number of changes. If this happens, review the drift report for security-relevant items and then save a fresh baseline.

## Next Steps

- [Firewall Posture Audit](firewall-posture-audit.md) -- audit the new firewall rules for shadow or exposure issues
- [Optimize WiFi](optimize-wifi.md) -- if wireless settings drifted from optimized values
- [MSP Fleet Digest](msp-fleet-digest.md) -- check drift across all managed sites

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "No baseline found" | No baseline has been saved yet | Save a baseline first with `unifi config --save --apply` |
| "UNIFI_WRITE_ENABLED is not set" | Write gate active for baseline save | Set `UNIFI_WRITE_ENABLED=true`; only needed for saving, not for drift detection |
| Drift report shows hundreds of changes | Baseline is very old or from a different site | Save a fresh baseline and use it as the new reference |
| Device firmware shows as drift | Firmware was updated since baseline | This is expected; save a new baseline after verifying the update |
| VLAN shows as changed but looks the same | Subnet or DHCP scope was modified | The diff compares all fields; a DHCP range change within the same VLAN counts as drift |
