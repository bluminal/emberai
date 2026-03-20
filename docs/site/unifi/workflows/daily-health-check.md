# Daily Health Check

## Intent

"I want to confirm all devices are up, no firmware alerts, ISP metrics clean."

## Prerequisites

- **Plugin:** `unifi` v0.1.0 or later
- **API privileges:** Read-only access to the Local Gateway API
- **Environment variables:** `UNIFI_LOCAL_HOST` and `UNIFI_LOCAL_KEY` must be configured

## Context

Run this workflow as part of a morning routine or after any network event (ISP outage, power event, firmware upgrade). It takes a few seconds and gives you a complete picture of network health without requiring you to log into the UniFi controller.

The health check is entirely read-only. It gathers data from four sources: subsystem status, recent events (last 24 hours), firmware currency, and ISP metrics. Findings are classified by severity so that critical issues are never buried.

This workflow does not diagnose individual devices -- use [Locate a Client](locate-client.md) or `unifi diagnose` for targeted troubleshooting.

## Commands

### Step 1: Run the health check

```
You: Quick health check
```

### Step 2: Review findings (healthy network)

```
EmberAI:

## Health Check
| Metric  | Value |
|---------|-------|
| Devices | 3     |
| Clients | 47    |

All systems healthy -- 3 device(s) online, 47 client(s) connected.

## Findings

### Informational
- **ISP metrics**: ISP: Example ISP, Latency: 8ms, Download: 423.7 Mbps,
  Upload: 38.2 Mbps, Drops: 0.
```

### Alternative: Review findings (issues detected)

```
EmberAI:

## Health Check
| Metric   | Value |
|----------|-------|
| Devices  | 3     |
| Clients  | 47    |
| Critical | 2     |
| Warnings | 1     |

## Findings

### Critical
- **WAN subsystem is degraded**: The WAN subsystem is reporting status
  'degraded' instead of 'ok'.
  Recommendation: Investigate WAN subsystem immediately.

- **1 device(s) offline**: 1 device(s) are disconnected and not responding.
  Recommendation: Check physical connections and power for offline devices.

### Warning
- **Firmware update available for 1 device(s)**: Devices with pending
  updates: USLITE16P (7.0.50.15116 -> 7.0.72.15290).
  Recommendation: Schedule firmware upgrades during a maintenance window.

### Informational
- **ISP metrics**: ISP: Example ISP, Latency: 42ms, Download: 210.3 Mbps,
  Upload: 18.1 Mbps, Drops: 3.
```

### Step 3: Drill into specific issues (if needed)

```
You: Diagnose Office-Switch-16
```

This triggers a targeted diagnosis using `unifi diagnose` -- see the diagnose command for full output format.

## What to Look For

**Summary header:**
- **Device count** -- should match your expected inventory. A drop in device count means something went offline.
- **Client count** -- unusually low client counts at peak hours may indicate an AP problem.

**Critical findings (act immediately):**
- **Subsystem down** -- WAN, LAN, WLAN, or WWW subsystem not reporting `ok`. This typically means a major service is impacted.
- **Devices offline** -- one or more devices are not responding. Check power, cabling, and physical access.

**Warning findings (schedule attention):**
- **Firmware updates** -- devices with pending updates. Plan a maintenance window to apply them. See [Firmware Update Status](firmware-update-status.md).
- **Warning events** -- recent events with warning or critical severity in the last 24 hours. These may indicate transient issues (PoE overloads, brief disconnections).

**Informational findings (for awareness):**
- **ISP metrics** -- latency, download/upload speeds, and drop count. Compare against your expected ISP performance. A latency spike or increasing drop count may warrant an ISP call.

## Next Steps

- [Firmware Update Status](firmware-update-status.md) -- get detailed firmware status if updates are pending
- [Locate a Client](locate-client.md) -- investigate a specific client if user complaints arise
- [First-Time Site Scan](first-time-scan.md) -- re-scan topology if devices were added or removed

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Health check returns "unknown" for all subsystems | API endpoint not responding correctly | Verify `UNIFI_LOCAL_HOST` points to the correct gateway; try accessing the controller UI directly |
| 0 devices and 0 clients | Wrong site ID | Try with `site_id="default"` or list sites first |
| ISP metrics show "None" for all fields | WAN subsystem data not available | Speed test may not have run recently; check if the controller has speed test enabled |
| Event data missing | Events older than the query window | The default window is 24 hours; events older than that are not returned |
| Firmware status shows no upgrades but controller shows updates | Firmware data served from device endpoint | The plugin reads firmware state from the device stat endpoint; verify the controller has checked for updates recently |
