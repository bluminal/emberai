# Locate a Client

## Intent

"I want to find a device by hostname, IP, or MAC and see its AP, VLAN, signal, and traffic."

## Prerequisites

- **Plugin:** `unifi` v0.1.0 or later
- **API privileges:** Read-only access to the Local Gateway API
- **Environment variables:** `UNIFI_LOCAL_HOST` and `UNIFI_LOCAL_KEY` must be configured

## Context

Use this workflow when someone reports a connectivity problem, when you need to find where a specific device is connected, or when you want to check the signal quality and traffic of a particular client. The workflow combines client listing with targeted diagnosis.

You can search by any identifier: hostname, IP address, MAC address, or the alias you set in the UniFi controller. Partial matches work -- searching for "macbook" will find "macbook-pro-jdoe".

This workflow is entirely read-only. It does not modify client settings or network configuration.

## Commands

### Step 1: Search for the client

You can start with either the `clients` command to browse or `diagnose` to go directly to a specific target.

**Option A: Browse all clients**

```
You: Show me all connected clients
```

```
EmberAI:

## Client Inventory
| Metric   | Value |
|----------|-------|
| Total    | 6     |
| Wireless | 4     |
| Wired    | 2     |
| Guests   | 1     |

## Connected Clients
| Name/MAC          | IP            | VLAN | AP/Port                          | Type             | Signal         | Traffic                  |
|-------------------|---------------|------|----------------------------------|------------------|----------------|--------------------------|
| macbook-pro-jdoe  | 192.168.1.101 | LAN  | e0:63:da:cc:55:66 (HomeNet)      | Wireless         | 56 (Excellent) | TX: 2.7 GB / RX: 17.0 GB  |
| pixel-8-jsmith    | 192.168.1.142 | LAN  | e0:63:da:cc:55:66 (HomeNet)      | Wireless         | 38 (Good)      | TX: 460.6 MB / RX: 1.2 GB |
| synology-nas      | 192.168.1.50  | LAN  | Port 4                           | Wired            |                | TX: 772.2 GB / RX: 273.7 GB |
| iphone-guest-1    | 192.168.10.102| Guest| e0:63:da:cc:55:66 (Guest-Net)    | Wireless (Guest) | 32 (Fair)      | TX: 28.0 MB / RX: 183.9 MB |
| sonos-livingroom  | 192.168.30.12 | IoT  | Port 5                           | Wired            |                | TX: 1.2 MB / RX: 79.1 MB  |
| ring-doorbell     | 192.168.30.25 | IoT  | e0:63:da:cc:55:66 (HomeNet)      | Wireless         | 25 (Fair)      | TX: 79.1 MB / RX: 460.6 MB |
```

**Option B: Filter by VLAN**

```
You: Show me clients on the IoT VLAN
```

**Option C: Go directly to diagnosis**

```
You: Diagnose the ring doorbell
```

### Step 2: Diagnose a specific client

Once you have identified the client of interest, run a targeted diagnosis:

```
You: Diagnose ring-doorbell
```

```
EmberAI:

## Diagnosis: Front Door Camera
| Metric     | Value         |
|------------|---------------|
| Type       | Client        |
| Connection | Wireless      |
| IP         | 192.168.30.25 |

### Client Details
| Field      | Value              |
|------------|--------------------|
| MAC        | dc:a6:32:66:77:88  |
| Hostname   | ring-doorbell      |
| IP         | 192.168.30.25      |
| VLAN       | IoT                |
| Connection | Wireless           |
| Uptime     | 2d 0h 0m           |
| AP         | e0:63:da:cc:55:66  |
| SSID       | HomeNet            |
| RSSI       | 25                 |

### Associated AP Health
| Field  | Value          |
|--------|----------------|
| Name   | Office-AP-Main |
| Status | connected      |
| Uptime | 20d 0h 7m      |
| CPU    | 8.1%           |
| Memory | 34.2%          |

### Diagnostic Findings

#### Warning
- **Fair signal quality**: RSSI is 25, indicating marginal signal. The client
  may experience intermittent issues.
  Recommendation: Consider repositioning the AP or client, or adding an
  additional AP for better coverage.

- **1 disconnect event(s) in the last 24 hours**: The client has disconnected
  1 time(s) recently. This may indicate signal issues, roaming problems, or
  AP instability.
  Recommendation: Check signal strength at the client's location and AP logs.
```

### Step 3: Handle ambiguous search results

If your search term matches multiple devices or clients, EmberAI will ask for clarification:

```
You: Diagnose 192.168.1

EmberAI:

## Assumption Resolution

The following was determined from the API:
- Search term: '192.168.1'

The following needs clarification:
- **Which target did you mean?** Multiple matches found. Please specify the
  exact MAC address or provide a more specific identifier:
  - Device: USG-Gateway (MAC: f0:9f:c2:aa:11:22, IP: 192.168.1.1)
  - Device: Office-Switch-16 (MAC: 74:ac:b9:bb:33:44, IP: 192.168.1.10)
  - Client: macbook-pro-jdoe (MAC: a4:83:e7:11:22:33, IP: 192.168.1.101)
```

Respond with the exact MAC address or a more specific identifier to proceed.

## What to Look For

**Signal quality (wireless clients):**
- **Excellent (RSSI >= 50)** -- strong signal, no issues expected
- **Good (RSSI 35-49)** -- adequate signal for most uses
- **Fair (RSSI 20-34)** -- marginal signal; may experience intermittent drops or slow speeds
- **Poor (RSSI < 20)** -- very weak signal; expect frequent disconnections

**AP health (wireless clients):**
- **Status** -- the associated AP should be `connected`. Any other status explains the client's connectivity problems.
- **CPU/Memory** -- high CPU (>80%) or memory (>85%) on the AP can impact all wireless clients.

**Disconnect events:**
- One or two disconnects in 24 hours may be normal (roaming, sleep/wake).
- Frequent disconnects (5+) combined with fair/poor signal strongly suggests a coverage gap.

**Traffic counters:**
- Asymmetric traffic (very high RX, very low TX) is normal for streaming devices (cameras, media players).
- Zero traffic on a device that should be active may indicate a connectivity issue beyond signal quality.

## Next Steps

- [Daily Health Check](daily-health-check.md) -- check overall network health if multiple clients are affected
- [Check WiFi Channels](check-wifi-channels.md) -- investigate channel congestion if signal quality is the issue (Phase 2)
- [Firmware Update Status](firmware-update-status.md) -- check if the AP firmware is current

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "No device or client matching 'X' was found" | Client not currently connected, or search term does not match | Verify the client is online; try searching by MAC address instead |
| Client shows but diagnosis fails | Client disconnected between search and diagnosis | Re-run the diagnosis; the client may have reconnected |
| AP health shows "unknown" for CPU/Memory | Device health endpoint returned incomplete data | Some older AP models do not report system stats |
| RSSI shows "N/A" for a wireless client | Client stat endpoint did not include RSSI data | This can happen briefly after a client roams or reassociates |
| Traffic shows "0 B" for an active client | Traffic counters reset after reconnection | Wait for the client to generate some traffic, then re-check |
