# MSP Fleet Health Digest

## Intent

"I want a cross-site health summary across all managed sites, sorted by severity."

## Prerequisites

- **Plugin:** `unifi` v0.2.0 or later
- **API privileges:** Cloud V1 or Site Manager API key with access to all managed sites
- **Environment variables:** `UNIFI_API_KEY` must be configured (cloud/Site Manager access)
- **Network access:** The MCP server must be able to reach `api.ui.com`

## Context

Run this workflow as a daily or weekly routine to get a severity-ranked health overview across all managed UniFi sites. This is designed for managed service providers (MSPs) and multi-site operators who need to triage issues across their fleet without logging into each site individually.

The digest pulls health data from every site, sorts findings by severity (critical first), and presents a consolidated view. You can then drill into any site that needs attention using `unifi health` with a specific site ID.

This workflow is entirely read-only across all sites. No changes are made to any network. For cross-vendor fleet analysis that includes OPNsense gateways, use `netex health` from the umbrella plugin.

## Commands

### Step 1: Generate the fleet digest

```
You: Give me a fleet health digest across all sites
```

```
EmberAI:

## Fleet Health Digest
| Metric          | Value |
|-----------------|-------|
| Sites           | 5     |
| Total devices   | 23    |
| Total clients   | 187   |
| Sites with issues | 2   |

### Sites Sorted by Severity

#### Sites with Critical Findings
| Site            | Devices | Clients | Critical | Warning | Status   |
|-----------------|---------|---------|----------|---------|----------|
| Warehouse-East  | 4       | 12      | 1        | 1       | Degraded |

Critical findings:
- **WAN subsystem degraded** -- The WAN subsystem at Warehouse-East is
  reporting status 'degraded'. ISP connectivity may be interrupted.
  Recommendation: Check WAN link and ISP status at this site.
- **Warning: 2 devices need firmware updates** -- USW-Lite-8 and U6-Lite
  have pending firmware upgrades.

#### Sites with Warning Findings
| Site            | Devices | Clients | Critical | Warning | Status   |
|-----------------|---------|---------|----------|---------|----------|
| Office-HQ       | 6       | 82      | 0        | 2       | Healthy  |

Warning findings:
- **Firmware update available for 1 device** -- USW-Pro-24 (7.0.50 -> 7.0.72).
- **Elevated event activity** -- 14 warning-level events in the last 24
  hours (above the 10-event threshold). Most frequent: EVT_WU_Roam (8).

#### Healthy Sites
| Site              | Devices | Clients | Status  |
|-------------------|---------|---------|---------|
| Office-Branch     | 5       | 45      | Healthy |
| Retail-Downtown   | 4       | 38      | Healthy |
| Remote-Lab        | 4       | 10      | Healthy |
```

### Step 2: Drill into a specific site

```
You: Show me the full health report for Warehouse-East
```

```
EmberAI:

## Health Check: Warehouse-East
| Metric   | Value |
|----------|-------|
| Devices  | 4     |
| Clients  | 12    |
| Critical | 1     |
| Warnings | 1     |

## Devices
| Name             | Model      | IP           | Status    | Firmware       | Uptime      |
|------------------|------------|--------------|-----------|----------------|-------------|
| WH-Gateway       | UXG-Lite   | 10.20.1.1    | connected | 4.0.6.6754     | 5d 2h 10m   |
| WH-Switch-8      | USLITE8    | 10.20.1.10   | connected | 7.0.50.15116   | 5d 2h 8m    |
| WH-AP-Floor      | U6-Lite    | 10.20.1.20   | connected | 7.0.60.15200   | 5d 2h 7m    |
| WH-AP-Office     | U6-Lite    | 10.20.1.21   | connected | 7.0.60.15200   | 5d 2h 7m    |

## Findings

### Critical
- **WAN subsystem is degraded**: The WAN subsystem is reporting status
  'degraded' instead of 'ok'. ISP metrics: Latency: 142ms, Download:
  18.2 Mbps (contract: 100 Mbps), Upload: 3.1 Mbps, Drops: 3.
  Recommendation: Contact ISP or check WAN cabling at this site. Latency
  and throughput are significantly degraded.

### Warning
- **Firmware update available for 2 device(s)**: WH-Switch-8
  (7.0.50.15116 -> 7.0.72.15290), WH-AP-Floor (7.0.60.15200 -> 7.0.76.15293).
  Recommendation: Schedule firmware upgrades during a maintenance window.

### Informational
- **ISP metrics**: ISP: Regional Telecom, Latency: 142ms, Download:
  18.2 Mbps, Upload: 3.1 Mbps, Drops: 3.
```

### Step 3: Compare two sites

```
You: Compare Warehouse-East with Office-HQ
```

```
EmberAI:

## Site Comparison: Warehouse-East vs Office-HQ

| Metric          | Warehouse-East | Office-HQ |
|-----------------|----------------|-----------|
| Devices         | 4              | 6         |
| Clients         | 12             | 82        |
| WAN Status      | degraded       | ok        |
| LAN Status      | ok             | ok        |
| WLAN Status     | ok             | ok        |
| VLANs           | 2              | 4         |
| ISP Latency     | 142ms          | 6ms       |
| ISP Download    | 18.2 Mbps      | 487.2 Mbps|
| Firmware issues | 2 devices      | 1 device  |

### Key Differences
- **WAN health**: Warehouse-East WAN is degraded with significantly
  higher latency and lower throughput than Office-HQ.
- **Scale**: Office-HQ serves 7x more clients with 50% more devices.
- **Network segmentation**: Office-HQ has 4 VLANs vs 2 at Warehouse-East.
  Consider adding IoT and Guest VLANs at the warehouse.
```

## What to Look For

**Fleet-level triage:**
- Sites with critical findings should be addressed first. A degraded WAN subsystem means users at that site are likely experiencing connectivity issues right now.
- Sites with only warning findings (firmware updates, elevated events) can be addressed during scheduled maintenance.
- Healthy sites need no immediate action but should still receive periodic firmware updates.

**Cross-site patterns:**
- The same firmware version showing warnings across multiple sites indicates a fleet-wide update is needed. Coordinate a batch firmware upgrade.
- Similar event patterns (e.g., frequent roaming events) across multiple sites may indicate a systemic WiFi configuration issue.

**ISP metrics:**
- Compare ISP metrics across sites to identify underperforming connections. A site with 142ms latency when others show 6ms has an ISP or WAN link problem.
- Watch for download speeds significantly below the contracted rate.

**Client distribution:**
- Sites with very few clients relative to device count may be over-provisioned.
- Sites with very high client-to-AP ratios may need additional APs.

## Next Steps

- [Daily Health Check](daily-health-check.md) -- deep-dive into a specific site's health
- [Firewall Posture Audit](firewall-posture-audit.md) -- audit security posture at sites with findings
- [Firmware Update Status](firmware-update-status.md) -- plan a fleet-wide firmware update

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "UNIFI_API_KEY is not set" | Cloud/Site Manager API key not configured | Generate a key at unifi.ui.com and set `UNIFI_API_KEY` |
| Only 1 site returned | API key scope limited to one site | Generate a new API key with account-level access |
| Site shows 0 clients | Site is offline or no devices adopted | Check physical connectivity and device adoption status at the site |
| Rate limit error (429) | Too many sites queried too quickly | The Site Manager API has a 100 req/min limit; the plugin batches requests but very large fleets (50+ sites) may hit this limit |
| Some sites missing from digest | API key does not have access to all sites | Verify the API key's site permissions in the UniFi cloud console |
