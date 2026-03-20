# Optimize a Congested WiFi Environment

## Intent

"I want to optimize a congested WiFi environment with RF scan and roaming analysis."

## Prerequisites

- **Plugin:** `unifi` v0.2.0 or later
- **API privileges:** Read-only access for analysis; read-write for applying changes
- **Environment variables:** `UNIFI_LOCAL_HOST` and `UNIFI_LOCAL_KEY` must be configured
- **For applying changes:** `UNIFI_WRITE_ENABLED=true` must be set

## Context

Run this workflow when wireless clients report slow speeds, high latency, or frequent disconnects, especially in environments with many APs, dense client populations, or significant neighbor interference. The workflow uses RF scan data and roaming analysis to generate prioritized channel and power recommendations.

This workflow uses `unifi wifi` for the RF environment analysis and `unifi optimize` for generating and optionally applying recommendations. The analysis phase is read-only. Applying recommendations requires the write safety gate.

This workflow does not cover wired connectivity issues -- see [Diagnose Client Complaint](diagnose-client-complaint.md) for wired path analysis.

## Working Safely

This workflow includes **optional write operations** when using `unifi optimize --apply`:

- **What changes:** Channel assignments, transmit power levels, and minimum RSSI thresholds on APs. These settings affect all clients connected to the modified APs.
- **Outage risk:** Changing an AP's channel causes a brief disconnection (2-5 seconds) for all clients on that AP. Clients will automatically reconnect. The OutageRiskAgent assesses each proposed change and flags APs that carry critical clients or high client counts.
- **Before applying:** Have out-of-band access to the network (console access, wired connection) in case a channel change causes unexpected interference patterns. Review the change plan carefully -- each AP change is listed individually.
- **Rollback:** Channel and power changes take effect immediately. To revert, run the optimize workflow again with the previous settings, or restore from a config backup.

All write operations require `UNIFI_WRITE_ENABLED=true` and the `--apply` flag. Without these, the workflow produces recommendations only.

## Commands

### Step 1: Analyze the wireless environment

Start with a comprehensive WiFi analysis.

```
You: Analyze my WiFi environment
```

```
EmberAI:

## WiFi Environment Analysis

### 2.4 GHz Band
| AP               | Channel | Width | Tx Power | Utilization | Interference | Clients | Satisfaction |
|------------------|---------|-------|----------|-------------|--------------|---------|--------------|
| Office-AP-Main   | 6       | HT20  | 17 dBm   | 68%         | 42%          | 22      | 71           |
| Office-AP-Upstrs | 6       | HT20  | 23 dBm   | 55%         | 38%          | 14      | 78           |
| Warehouse-AP     | 1       | HT20  | 23 dBm   | 12%         | 4%           | 3       | 96           |

### 5 GHz Band
| AP               | Channel | Width | Tx Power | Utilization | Interference | Clients | Satisfaction |
|------------------|---------|-------|----------|-------------|--------------|---------|--------------|
| Office-AP-Main   | 44      | VHT80 | 20 dBm   | 22%         | 5%           | 18      | 94           |
| Office-AP-Upstrs | 44      | VHT80 | 23 dBm   | 18%         | 3%           | 11      | 96           |
| Warehouse-AP     | 149     | VHT80 | 23 dBm   | 8%          | 1%           | 2       | 99           |

### Neighboring SSIDs (from RF scan)
| SSID             | Channel | Band  | RSSI | Security |
|------------------|---------|-------|------|----------|
| NextDoor-5G      | 44      | 5     | -68  | WPA3     |
| Apartment-WiFi   | 6       | 2.4   | -55  | WPA2     |
| DIRECT-HP-Print  | 6       | 2.4   | -62  | WPA2     |
| CoffeeShop       | 1       | 2.4   | -72  | WPA2     |

### Roaming Analysis (last 24 hours)
| Metric                    | Value |
|---------------------------|-------|
| Total roaming events      | 47    |
| Successful roams          | 38    |
| Failed roams (fallback)   | 9     |
| Avg roam time             | 340ms |
| Sticky clients (no roam)  | 6     |

### Findings

#### Critical
- **Co-channel interference on 2.4 GHz channel 6**: Office-AP-Main and
  Office-AP-Upstrs are both on channel 6 with high utilization (68% and
  55%). Combined with strong neighbor interference (42% and 38%), this
  creates significant co-channel contention.

#### Warning
- **5 GHz co-channel overlap**: Office-AP-Main and Office-AP-Upstrs share
  channel 44/VHT80, causing self-interference. With a strong neighbor
  (-68 dBm) also on channel 44, separation is recommended.

- **High roam failure rate**: 9 of 47 roaming events failed (19%). Clients
  are falling back to the original AP instead of completing the roam.

#### Informational
- **6 sticky clients detected**: These clients remain connected to a
  distant AP despite a closer AP being available. Minimum RSSI thresholds
  may help.
```

### Step 2: Generate optimization recommendations

```
You: Generate optimization recommendations
```

```
EmberAI:

## Optimization Recommendations

Sorted by impact (highest first):

### 1. Separate 2.4 GHz channels (Critical -- High Impact)
| AP               | Current Channel | Recommended | Reason                        |
|------------------|-----------------|-------------|-------------------------------|
| Office-AP-Main   | 6               | 1           | Move to least-congested 2.4G  |
| Office-AP-Upstrs | 6               | 11          | Separate from Main + neighbor |

Expected improvement: 25-35% reduction in channel utilization on both APs.

### 2. Separate 5 GHz channels (Warning -- Medium Impact)
| AP               | Current Channel | Recommended | Reason                     |
|------------------|-----------------|-------------|----------------------------|
| Office-AP-Upstrs | 44/VHT80        | 149/VHT80   | Avoid co-channel with Main |

Expected improvement: 5-10% reduction in 5 GHz interference.

### 3. Reduce 2.4 GHz transmit power (Warning -- Medium Impact)
| AP               | Current Power | Recommended | Reason                        |
|------------------|---------------|-------------|-------------------------------|
| Office-AP-Upstrs | 23 dBm        | 17 dBm      | Match Main; reduce cell overlap|

Expected improvement: Better roaming behavior between the two office APs.

### 4. Set minimum RSSI threshold (Informational -- Low Impact)
| AP               | Current Min RSSI | Recommended | Reason                    |
|------------------|------------------|-------------|---------------------------|
| Office-AP-Main   | None             | -75 dBm     | Disconnect sticky clients |
| Office-AP-Upstrs | None             | -75 dBm     | Force roam to closer AP   |

Expected improvement: 6 sticky clients will roam to closer APs.

---

To apply these changes, run:
  unifi optimize --apply

This requires UNIFI_WRITE_ENABLED=true. Each change will be presented
for confirmation before execution. Channel changes cause a brief (2-5s)
disconnection for affected clients.
```

### Step 3: Apply changes (optional)

If you are satisfied with the recommendations:

```
You: Apply the WiFi optimizations
```

```
EmberAI:

## OutageRiskAgent Assessment

| Change                           | Risk  | Affected Clients | Notes                        |
|----------------------------------|-------|------------------|------------------------------|
| Office-AP-Main: Ch 6 -> 1       | Low   | 22               | Brief disconnect (~3s)       |
| Office-AP-Upstrs: Ch 6 -> 11    | Low   | 14               | Brief disconnect (~3s)       |
| Office-AP-Upstrs: 5G Ch 44->149 | Low   | 11               | Brief disconnect (~3s)       |
| Office-AP-Upstrs: Power 23->17  | None  | 14               | No disconnect                |
| Min RSSI threshold changes       | None  | 6 sticky clients | Will be kicked; auto-reconnect|

Overall risk: **Low** -- no management sessions transit affected ports.

Proceed with all 5 changes? (yes/no)
```

## What to Look For

**Channel utilization:**
- Below 30% is healthy. Above 60% is problematic.
- Compare self-utilization vs. interference. High interference with low self-utilization means external sources are the problem.

**Co-channel interference:**
- On 2.4 GHz, only channels 1, 6, and 11 are non-overlapping. Two of your own APs on the same channel is the most common optimization target.
- On 5 GHz, VHT80 channels use 80 MHz of bandwidth. Ensure your APs use different 80 MHz blocks.

**Roaming analysis:**
- Roam failure rate above 10% indicates clients are having trouble transitioning between APs. Common causes: mismatched power levels, missing minimum RSSI thresholds, or incompatible fast roaming settings.
- Sticky clients (those that never roam despite low signal) benefit from minimum RSSI thresholds.

**Satisfaction scores:**
- Per-AP satisfaction below 80 combined with high utilization is a strong optimization signal.
- Satisfaction above 90 across all APs means the environment is already well-tuned.

## Next Steps

- [Check WiFi Channels](check-wifi-channels.md) -- for ongoing channel monitoring after optimization
- [Diagnose Client Complaint](diagnose-client-complaint.md) -- if specific clients still have issues after optimization
- [Config Drift Detection](config-drift-detection.md) -- save a baseline after optimization to detect future drift

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "UNIFI_WRITE_ENABLED is not set" | Write safety gate is active | Set `UNIFI_WRITE_ENABLED=true` in the environment; re-run with `--apply` |
| RF scan data is empty | No cached scan available on the controller | Wait for the controller to perform a background scan (automatic on most AP models) |
| Satisfaction scores show "None" | AP model does not report satisfaction | Older AP models do not expose this metric; rely on utilization and RSSI instead |
| Recommendations conflict with each other | Unusual AP layout or extreme neighbor density | Apply recommendations one at a time and re-analyze between changes |
| Client disconnects last longer than 5 seconds | Client driver slow to reassociate | This is client-side behavior; ensure clients support 802.11r (fast roaming) if available |
| Optimization made things worse | New channel has unexpected interference | Re-run the analysis to see the new RF environment; revert by applying the previous channel manually |
