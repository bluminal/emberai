# UniFi Commands Reference

Commands are the user-facing entry points to the unifi plugin. Each command orchestrates multiple tools from the [Skills Reference](skills.md) to produce a complete, severity-ranked report.

All Phase 1 commands are **read-only**. No command in this release modifies your network.

---

## `unifi scan`

Discover the full network topology for a UniFi site.

### What It Does

Calls the topology skill tools to build a complete inventory of your network:

1. Lists all devices (switches, APs, gateways) with model, IP, status, firmware, and uptime
2. Lists all VLANs/networks with ID, name, subnet, and DHCP status
3. Derives the uplink graph showing device-to-device connections with port and speed

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

### Example

```
You: Scan my UniFi network

EmberAI:

## Site Scan Complete
| Metric   | Value |
|----------|-------|
| Devices  | 3     |
| VLANs    | 4     |
| Uplinks  | 2     |

## Devices
| Name             | Model      | IP           | Status    | Firmware       | Uptime      |
|------------------|------------|--------------|-----------|----------------|-------------|
| USG-Gateway      | UXG-Max    | 192.168.1.1  | connected | 4.0.6.6754     | 20d 0h 7m   |
| Office-Switch-16 | USLITE16P  | 192.168.1.10 | connected | 7.0.50.15116   | 10d 0h 3m   |
| Office-AP-Main   | U6-Pro     | 192.168.1.20 | connected | 7.0.76.15293   | 20d 0h 7m   |

## VLANs
| Name       | VLAN ID | Subnet           | DHCP | Purpose   |
|------------|---------|------------------|------|-----------|
| Default    |         | 192.168.1.0/24   | Yes  | corporate |
| Guest      | 10      | 192.168.10.0/24  | Yes  | guest     |
| IoT        | 30      | 192.168.30.0/24  | Yes  | corporate |
| Management | 99      | 192.168.99.0/24  | Yes  | corporate |

## Uplinks
| Device -> Parent                     | Port | Speed  | Type |
|--------------------------------------|------|--------|------|
| Office-Switch-16 -> USG-Gateway      | 1    | 10 Gbps| wire |
| Office-AP-Main -> Office-Switch-16   | 1    | 1 Gbps | wire |
```

### Tools Called

- `unifi__topology__list_devices` -- device inventory
- `unifi__topology__get_vlans` -- VLAN/network configuration
- `unifi__topology__get_uplinks` -- uplink relationship graph

---

## `unifi health`

Run a comprehensive health check with severity-tiered findings.

### What It Does

Gathers health data from four sources and classifies findings into three severity tiers:

- **Critical** -- subsystem down, devices offline, WAN link failure
- **Warning** -- firmware updates available, elevated event activity
- **Informational** -- ISP metrics summary, device/client counts

If no critical or warning findings exist, the report shows a clean "All systems healthy" summary.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

### Example (Healthy)

```
You: Quick health check

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

### Example (With Findings)

```
You: Health check

EmberAI:

## Health Check
| Metric   | Value |
|----------|-------|
| Devices  | 3     |
| Clients  | 47    |
| Critical | 1     |
| Warnings | 1     |

## Findings

### Critical
- **WAN subsystem is degraded**: The WAN subsystem is reporting status
  'degraded' instead of 'ok'.
  Recommendation: Investigate WAN subsystem immediately.

### Warning
- **Firmware update available for 1 device(s)**: Devices with pending
  updates: USLITE16P (7.0.50.15116 -> 7.0.72.15290).
  Recommendation: Schedule firmware upgrades during a maintenance window.

### Informational
- **ISP metrics**: ISP: Example ISP, Latency: 8ms, Download: 423.7 Mbps,
  Upload: 38.2 Mbps, Drops: 0.
```

### Severity Tiers

| Tier | Triggers |
|------|----------|
| Critical | Any subsystem (WAN, LAN, WLAN, WWW) not reporting `ok`; devices offline |
| Warning | Firmware upgrades available; warning/critical events in the last 24 hours |
| Informational | ISP metrics summary (ISP name, latency, speed, drops) |

### Tools Called

- `unifi__health__get_site_health` -- subsystem status
- `unifi__health__get_events(hours=24)` -- recent events
- `unifi__health__get_firmware_status` -- firmware currency
- `unifi__health__get_isp_metrics` -- ISP connectivity

---

## `unifi diagnose`

Root-cause analysis for a specific device or client.

### What It Does

1. Searches for the target by MAC address, hostname, IP address, or device name
2. If the target is ambiguous (matches multiple devices or clients), asks for clarification
3. For **clients**: fetches client details, checks associated AP health, reviews related events, evaluates signal quality
4. For **devices**: fetches device health metrics (CPU, memory, temperature), reviews related events, checks firmware status
5. Returns a diagnostic report with findings ranked by severity and actionable recommendations

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | string | Yes | Device MAC/name/IP or client MAC/hostname/IP |
| `site_id` | string | No (default: `"default"`) | The UniFi site ID |

### Example (Client Diagnosis)

```
You: Diagnose the ring doorbell

EmberAI:

## Diagnosis: Front Door Camera
| Metric     | Value    |
|------------|----------|
| Type       | Client   |
| Connection | Wireless |
| IP         | 192.168.30.25 |

### Client Details
| Field    | Value              |
|----------|--------------------|
| MAC      | dc:a6:32:66:77:88  |
| Hostname | ring-doorbell      |
| IP       | 192.168.30.25      |
| VLAN     | IoT                |
| Connection | Wireless         |
| Uptime   | 2d 0h 0m           |
| AP       | e0:63:da:cc:55:66  |
| SSID     | HomeNet            |
| RSSI     | 25                 |

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

### Example (Ambiguous Target)

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

### Tools Called

- `unifi__clients__search_clients` -- find clients matching the target
- `unifi__topology__list_devices` -- find devices matching the target
- `unifi__clients__get_client` -- full client details (if client match)
- `unifi__health__get_device_health` -- device or AP health metrics
- `unifi__health__get_events(hours=24)` -- correlated events

---

## `unifi clients`

Inventory all connected clients with signal quality and traffic summary.

### What It Does

Lists all connected clients (wired and wireless) with:

- Hostname or MAC address
- IP address and VLAN
- Access point or switch port
- Connection type (wired/wireless, guest)
- Signal quality with human-readable rating (wireless only)
- Traffic summary (TX/RX bytes)

Supports filtering by VLAN and/or access point.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `vlan_id` | string | `null` | Filter by VLAN/network ID |
| `ap_id` | string | `null` | Filter by access point MAC address |

### Example

```
You: Show me all connected clients

EmberAI:

## Client Inventory
| Metric   | Value |
|----------|-------|
| Total    | 6     |
| Wireless | 4     |
| Wired    | 2     |
| Guests   | 1     |

## Connected Clients
| Name/MAC          | IP            | VLAN | AP/Port                          | Type             | Signal          | Traffic               |
|-------------------|---------------|------|----------------------------------|------------------|-----------------|-----------------------|
| macbook-pro-jdoe  | 192.168.1.101 | LAN  | e0:63:da:cc:55:66 (HomeNet)      | Wireless         | 56 (Excellent)  | TX: 2.7 GB / RX: 17.0 GB |
| pixel-8-jsmith    | 192.168.1.142 | LAN  | e0:63:da:cc:55:66 (HomeNet)      | Wireless         | 38 (Good)       | TX: 460.6 MB / RX: 1.2 GB |
| synology-nas      | 192.168.1.50  | LAN  | Port 4                           | Wired            |                 | TX: 772.2 GB / RX: 273.7 GB |
| iphone-guest-1    | 192.168.10.102| Guest| e0:63:da:cc:55:66 (Guest-Net)    | Wireless (Guest) | 32 (Fair)       | TX: 28.0 MB / RX: 183.9 MB |
| sonos-livingroom  | 192.168.30.12 | IoT  | Port 5                           | Wired            |                 | TX: 1.2 MB / RX: 79.1 MB |
| ring-doorbell     | 192.168.30.25 | IoT  | e0:63:da:cc:55:66 (HomeNet)      | Wireless         | 25 (Fair)       | TX: 79.1 MB / RX: 460.6 MB |
```

### Example (Filtered by VLAN)

```
You: Show clients on the IoT VLAN

EmberAI:

## Client Inventory
| Metric   | Value |
|----------|-------|
| Total    | 2     |
| Wireless | 1     |
| Wired    | 1     |

Filters: VLAN: 5f9a8b7c6d5e4f3a2b1c0003

## Connected Clients
| Name/MAC         | IP            | VLAN | AP/Port                     | Type     | Signal     | Traffic               |
|------------------|---------------|------|-----------------------------|----------|------------|-----------------------|
| sonos-livingroom | 192.168.30.12 | IoT  | Port 5                      | Wired    |            | TX: 1.2 MB / RX: 79.1 MB |
| ring-doorbell    | 192.168.30.25 | IoT  | e0:63:da:cc:55:66 (HomeNet) | Wireless | 25 (Fair)  | TX: 79.1 MB / RX: 460.6 MB |
```

### Signal Quality Ratings

| RSSI Range | Rating |
|------------|--------|
| >= 50 | Excellent |
| 35 -- 49 | Good |
| 20 -- 34 | Fair |
| < 20 | Poor |

### Tools Called

- `unifi__clients__list_clients` -- client inventory (with optional VLAN filter)
- AP filtering is applied client-side after fetching

---

## Phase 2+ Commands (Not Yet Implemented)

The following commands are planned for future releases. They are documented here for reference.

| Command | Intent | Phase |
|---------|--------|-------|
| `unifi wifi` | Analyze the wireless RF environment: channels, interference, roaming | Phase 2 |
| `unifi optimize` | Generate prioritized improvement recommendations | Phase 2 |
| `unifi secure` | Security posture audit (firewall rules, ACLs, port forwarding, IDS) | Phase 2 |
| `unifi compare` | Side-by-side comparison of two sites | Phase 2 |
| `unifi config` | Review config state and detect drift against baselines | Phase 2 |
| `unifi port-profile create` | Create a named switch port profile | Phase 2 |
| `unifi port-profile assign` | Assign a port profile to a switch port | Phase 2 |
