# Firmware Update Status

## Intent

"I want to list all devices with pending updates before a maintenance window."

## Prerequisites

- **Plugin:** `unifi` v0.1.0 or later
- **API privileges:** Read-only access to the Local Gateway API
- **Environment variables:** `UNIFI_LOCAL_HOST` and `UNIFI_LOCAL_KEY` must be configured

## Context

Run this workflow before a scheduled maintenance window, after receiving a notification about new firmware releases, or as part of a periodic compliance check. Knowing which devices need updates -- and what versions are available -- lets you plan the upgrade sequence and estimate downtime.

This workflow is entirely read-only. It does not initiate firmware upgrades. Firmware upgrades must be performed through the UniFi controller UI or API (write operations planned for Phase 2).

Firmware updates can temporarily disrupt connected clients while the device reboots. Plan upgrades during low-traffic periods and update devices in dependency order: gateway first, then switches, then APs.

## Working Safely

While this workflow is read-only, it is typically a precursor to firmware upgrades which are write operations. Before performing actual upgrades:

- **Upgrade order matters.** Update the gateway before switches, and switches before APs. Updating in the wrong order can cause temporary connectivity issues.
- **Ensure out-of-band access.** If a gateway firmware upgrade fails, you may lose network access. Have serial console or physical access available.
- **One device at a time.** Avoid upgrading all devices simultaneously. Stagger upgrades to maintain connectivity during the process.
- **Check release notes.** Some firmware versions have known issues or require intermediate upgrades. Check Ubiquiti's release notes before proceeding.

## Commands

### Step 1: Run a health check to see firmware status

The `unifi health` command includes firmware status as part of its findings:

```
You: Health check
```

```
EmberAI:

## Health Check
| Metric   | Value |
|----------|-------|
| Devices  | 3     |
| Clients  | 47    |
| Warnings | 1     |

## Findings

### Warning
- **Firmware update available for 1 device(s)**: Devices with pending
  updates: USLITE16P (7.0.50.15116 -> 7.0.72.15290).
  Recommendation: Schedule firmware upgrades during a maintenance window.

### Informational
- **ISP metrics**: ISP: Example ISP, Latency: 8ms, Download: 423.7 Mbps,
  Upload: 38.2 Mbps, Drops: 0.
```

### Step 2: Get detailed device information

For a detailed view of the device that needs an update:

```
You: Diagnose Office-Switch-16
```

```
EmberAI:

## Diagnosis: Office-Switch-16
| Metric | Value     |
|--------|-----------|
| Type   | Device    |
| Model  | USLITE16P |
| Status | connected |

### Device Details
| Field       | Value          |
|-------------|----------------|
| MAC         | 74:ac:b9:bb:33:44 |
| Name        | Office-Switch-16  |
| Model       | USLITE16P         |
| Status      | connected         |
| Firmware    | 7.0.50.15116      |
| Uptime      | 10d 0h 3m         |
| CPU         | 3.2%              |
| Memory      | 28.7%             |
| Temperature | 42C               |

### Diagnostic Findings

#### Informational
- **Firmware upgrade available**: Current: 7.0.50.15116,
  Available: 7.0.72.15290.
  Recommendation: Schedule firmware upgrade during a maintenance window.
```

### Step 3: Scan to see the full inventory with firmware versions

```
You: Scan my network
```

Review the Firmware column in the Devices table for a fleet-wide view of firmware versions.

## What to Look For

**Firmware update findings:**
- The health check reports firmware updates as **Warning** severity. Devices that are up to date do not generate a finding.
- Each finding includes the **current version** and **available version**, so you can assess the size of the update.

**Device health before upgrading:**
- Check CPU, memory, and temperature before upgrading. A device under heavy load or thermal stress should be stabilized before applying a firmware update.
- Verify the device is `connected` -- do not attempt to upgrade a device in `disconnected` or `heartbeat_missed` state.

**Uptime considerations:**
- Devices with very long uptimes (30+ days) have been stable. Upgrading may introduce new behavior -- verify release notes.
- Devices with very short uptimes may have recently rebooted due to instability. Investigate before adding a firmware change on top of an existing problem.

**Fleet consistency:**
- Multiple devices of the same model should ideally run the same firmware version. Inconsistent versions can cause interoperability issues, especially between switches and APs.

## Next Steps

- [Daily Health Check](daily-health-check.md) -- run a post-upgrade health check to verify everything is still healthy
- [First-Time Site Scan](first-time-scan.md) -- re-scan after upgrades to verify device inventory and uplink topology are intact
- [Locate a Client](locate-client.md) -- check client connectivity after an AP firmware upgrade

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| No firmware findings in health check | All devices are up to date | No action needed -- your firmware is current |
| Firmware version shows but no "upgrade available" | Controller has not checked for updates | Check for updates manually in the UniFi controller UI |
| Health check shows upgrade but controller does not | Stale firmware data from the API | The plugin reads firmware state from the device stat endpoint; the controller may have a more recent check |
| Multiple devices show different versions of the same firmware | Partial upgrade -- some devices updated, others not | Complete the upgrade for remaining devices in the next maintenance window |
