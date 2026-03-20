# Check WiFi Channel Utilization

> **Available in v0.1.1** -- The WiFi skill group (`unifi wifi`) is planned for Phase 2.
> This workflow documents the intended behavior. Phase 1 provides partial
> coverage through the health and clients tools described below.

## Intent

"I want to see which channels are congested across all APs."

## Prerequisites

- **Plugin:** `unifi` v0.1.1 or later (for full WiFi analysis)
- **API privileges:** Read-only access to the Local Gateway API
- **Environment variables:** `UNIFI_LOCAL_HOST` and `UNIFI_LOCAL_KEY` must be configured

For Phase 1 (v0.1.0), the following partial approach is available using existing tools.

## Context

Run this workflow when wireless clients report slow speeds, when you are planning AP placement, or after adding new APs to check for co-channel interference. Channel congestion is one of the most common causes of poor WiFi performance, especially in dense environments.

This workflow is entirely read-only. It uses passive data only -- the plugin never triggers an active RF scan.

This workflow does not cover WiFi optimization recommendations -- see `unifi optimize` (Phase 2) for channel and power adjustment suggestions.

## Commands

### Phase 1 (v0.1.0): Partial Coverage

In Phase 1, you can gather channel-related information from the device and client data:

#### Step 1: Scan for AP radio information

```
You: Scan my network and show me the AP details
```

The scan output includes device details. For APs, the fixture data shows radio configuration including channel assignments. You can also ask for specific device details:

```
You: Show me the details of Office-AP-Main
```

The device detail includes `radio_table` with channel, bandwidth, and transmit power for each radio band, and `radio_table_stats` with channel utilization, self-TX/RX, and client satisfaction per radio.

#### Step 2: Check client signal quality across APs

```
You: Show me all wireless clients
```

Review the Signal column in the client inventory. Clients with Fair or Poor signal on a given AP may benefit from a channel change or additional AP coverage.

### Phase 2 (v0.1.1): Full WiFi Analysis

When the WiFi skill group is available, the full workflow will use the `unifi wifi` command:

#### Step 1: Run WiFi analysis

```
You: Check WiFi channel utilization
```

This will call:
- `unifi__wifi__get_aps` -- list all APs with channel assignments
- `unifi__wifi__get_channel_utilization` -- per-AP channel utilization percentages
- `unifi__wifi__get_rf_scan` -- cached RF scan showing neighboring SSIDs

#### Step 2: Review channel utilization (expected output)

```
EmberAI:

## WiFi Channel Analysis

### 2.4 GHz Band
| AP               | Channel | Utilization | Interference | Clients | Satisfaction |
|------------------|---------|-------------|--------------|---------|--------------|
| Office-AP-Main   | 6       | 32%         | 12%          | 18      | 92           |
| Office-AP-Upstrs | 1       | 15%         | 5%           | 8       | 97           |

### 5 GHz Band
| AP               | Channel | Utilization | Interference | Clients | Satisfaction |
|------------------|---------|-------------|--------------|---------|--------------|
| Office-AP-Main   | 44      | 18%         | 3%           | 17      | 98           |
| Office-AP-Upstrs | 149     | 12%         | 2%           | 12      | 99           |

### Neighboring SSIDs (from RF scan)
| SSID             | Channel | Band  | RSSI | Security |
|------------------|---------|-------|------|----------|
| Neighbor-Net     | 6       | 2.4   | -72  | WPA3     |
| DIRECT-printer   | 6       | 2.4   | -68  | WPA2     |
| ApartmentWiFi    | 1       | 2.4   | -80  | WPA2     |
```

## What to Look For

**Channel utilization:**
- **< 30%** -- healthy, no action needed
- **30-60%** -- moderate congestion; acceptable if client satisfaction is high
- **> 60%** -- heavy congestion; consider changing channels or reducing AP count on that channel

**Interference percentage:**
- High interference with low self-TX/RX means most channel usage is from external sources (neighbors, non-WiFi devices). Changing channels may help.
- High self-TX/RX with low interference means your own network is the primary channel user. This is expected with many clients.

**Client satisfaction:**
- Per-AP satisfaction below 80 combined with high utilization is a strong signal to investigate channel changes.

**Neighboring SSIDs:**
- Multiple strong neighbors (RSSI > -70) on the same channel as your AP cause co-channel interference.
- On 2.4 GHz, only channels 1, 6, and 11 are non-overlapping. If all three are heavily occupied, consider steering clients to 5 GHz.

## Next Steps

- [Locate a Client](locate-client.md) -- diagnose a specific client with poor signal
- [Daily Health Check](daily-health-check.md) -- check overall AP health
- `unifi optimize` (Phase 2) -- get channel and power adjustment recommendations

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Channel utilization shows 0% | Radio stats not populated | Some AP models require a recent client association to populate radio stats |
| RF scan returns empty | No cached scan data available | The controller must have performed a background scan; this happens automatically on most AP models |
| Only 2.4 GHz data available | AP does not have 5 GHz radio or it is disabled | Check AP model capabilities and radio settings in the controller |
| Satisfaction score is "None" | AP model does not report satisfaction metrics | Older AP models may not expose this field |
