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

## `unifi wifi`

Analyze the wireless RF environment: channels, interference, roaming, and band steering.

### What It Does

Gathers data from all access points and presents a comprehensive wireless environment analysis:

1. Lists all APs with channel assignments, transmit power, and bandwidth settings per band
2. Reports channel utilization and interference percentages per AP per band
3. Performs an RF scan showing neighboring SSIDs with channel, RSSI, and security
4. Analyzes roaming events over the last 24 hours -- success rate, average roam time, sticky clients
5. Reports per-AP client satisfaction scores

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `ssid` | string | `null` | Filter analysis to a specific SSID |

### Example

```
You: Check my WiFi environment

EmberAI:

## WiFi Environment Analysis

### 2.4 GHz Band
| AP               | Channel | Width | Tx Power | Utilization | Interference | Clients | Satisfaction |
|------------------|---------|-------|----------|-------------|--------------|---------|--------------|
| Office-AP-Main   | 6       | HT20  | 17 dBm   | 32%         | 12%          | 18      | 92           |
| Office-AP-Upstrs | 1       | HT20  | 23 dBm   | 15%         | 5%           | 8       | 97           |

### 5 GHz Band
| AP               | Channel | Width | Tx Power | Utilization | Interference | Clients | Satisfaction |
|------------------|---------|-------|----------|-------------|--------------|---------|--------------|
| Office-AP-Main   | 44      | VHT80 | 20 dBm   | 18%         | 3%           | 17      | 98           |
| Office-AP-Upstrs | 149     | VHT80 | 23 dBm   | 12%         | 2%           | 12      | 99           |

### Neighboring SSIDs (from RF scan)
| SSID             | Channel | Band  | RSSI | Security |
|------------------|---------|-------|------|----------|
| Neighbor-Net     | 6       | 2.4   | -72  | WPA3     |
| DIRECT-printer   | 6       | 2.4   | -68  | WPA2     |

### Roaming Analysis (last 24 hours)
| Metric                    | Value |
|---------------------------|-------|
| Total roaming events      | 23    |
| Successful roams          | 21    |
| Failed roams (fallback)   | 2     |
| Avg roam time             | 210ms |
| Sticky clients (no roam)  | 3     |
```

### Tools Called

- `unifi__wifi__get_wlans` -- SSID configuration
- `unifi__wifi__get_aps` -- AP list with radio configuration
- `unifi__wifi__get_channel_utilization` -- per-AP channel utilization
- `unifi__wifi__get_rf_scan` -- neighboring SSID scan results
- `unifi__wifi__get_roaming_events` -- roaming event history
- `unifi__wifi__get_client_rf` -- per-client RF metrics (when SSID filter is used)

---

## `unifi optimize`

Generate prioritized improvement recommendations for the wireless environment. With `--apply`, queue confirmed changes.

### What It Does

Analyzes the WiFi environment (using all `wifi` skill tools) plus traffic patterns, security configuration, and config state to produce a prioritized list of recommendations:

1. Channel optimization (separate co-channel APs, avoid congested channels)
2. Transmit power adjustments (balance cell coverage, reduce overlap)
3. Minimum RSSI thresholds (disconnect sticky clients)
4. Band steering recommendations (push dual-band clients to 5 GHz)
5. SSID consolidation suggestions

Without `--apply`, the command produces the recommendation plan only. With `--apply`, each recommendation is presented individually for operator confirmation before execution.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `apply` | bool | `false` | Execute confirmed changes (requires `UNIFI_WRITE_ENABLED=true`) |

### Write Safety

This command can modify AP settings when `--apply` is used:

- **Env var gate:** `UNIFI_WRITE_ENABLED` must be set to `"true"`
- **Apply flag gate:** `--apply` must be present
- **Operator confirmation:** Each change is presented for individual confirmation
- **OutageRiskAgent:** Assesses the outage risk of each proposed change before confirmation

### Example

```
You: Generate WiFi optimization recommendations

EmberAI:

## Optimization Recommendations

### 1. Separate 2.4 GHz channels (High Impact)
| AP               | Current | Recommended | Reason                    |
|------------------|---------|-------------|---------------------------|
| Office-AP-Upstrs | 6       | 11          | Co-channel with Main AP   |

### 2. Set minimum RSSI threshold (Low Impact)
| AP               | Current | Recommended | Reason                    |
|------------------|---------|-------------|---------------------------|
| Office-AP-Main   | None    | -75 dBm     | 3 sticky clients detected |

To apply: run `unifi optimize --apply` with UNIFI_WRITE_ENABLED=true.
```

### Tools Called

- All `wifi` skill tools (see `unifi wifi` above)
- `unifi__traffic__get_bandwidth` -- traffic patterns
- `unifi__security__get_firewall_rules` -- security context
- `unifi__config__get_config_snapshot` -- current config state

---

## `unifi secure`

Security posture audit: firewall rules, zone-based firewall policies, ACLs, port forwarding, and IDS/IPS trend.

### What It Does

Enumerates all security configuration and produces a risk-ranked findings report:

1. Lists all zone-based firewall (ZBF) policies with source/destination zones and actions
2. Lists all access control list (ACL) rules with source, destination, protocol, and port
3. Lists all port forwarding rules with external/internal mappings
4. Summarizes IDS/IPS alerts from the last 24 hours by severity
5. Performs shadow analysis to detect rules that never match due to ordering
6. Flags overly permissive rules and exposed IoT devices

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

### Example

```
You: Audit our firewall posture

EmberAI:

## Security Posture Audit

### Summary
| Metric            | Value |
|-------------------|-------|
| ZBF Policies      | 6     |
| ACL Rules         | 4     |
| Port Forwards     | 2     |
| IDS Alerts (24h)  | 7     |

### Findings

#### Warning
- **Port forward to IoT VLAN**: Port 32400 is forwarded to 192.168.30.60
  (IoT VLAN). IoT devices are less hardened than LAN devices.
  Recommendation: Move the service to LAN or add IDS monitoring.

#### Informational
- **2 port forwards active**: External ports 443 and 32400 are exposed.
  Recommendation: Verify each forward is still needed.
```

### Tools Called

- `unifi__security__get_firewall_rules` -- firewall filter rules
- `unifi__security__get_zbf_policies` -- zone-based firewall policies
- `unifi__security__get_acls` -- access control lists
- `unifi__security__get_port_forwards` -- port forwarding rules
- `unifi__security__get_ids_alerts` -- IDS/IPS alert summary
- `unifi__wifi__get_rf_scan` -- rogue AP detection

---

## `unifi config`

Review configuration state and detect drift against stored baselines.

### What It Does

Captures a snapshot of the current configuration (devices, VLANs, firewall rules, port profiles, wireless settings) and optionally compares it against a previously saved baseline:

1. Without `--drift`: Shows the current configuration state and backup status
2. With `--drift`: Diffs the current state against the most recent baseline and highlights additions, removals, and modifications
3. With `--save --apply`: Saves the current state as a new baseline snapshot

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `drift` | bool | `false` | Compare against baseline |
| `baseline` | string | `null` | Specific baseline ID to compare against (default: most recent) |
| `save` | bool | `false` | Save current state as a new baseline (requires write gate) |
| `apply` | bool | `false` | Required with `--save` to execute the save (requires `UNIFI_WRITE_ENABLED=true`) |

### Write Safety

The `--save` flag stores a configuration snapshot locally. It does not modify the network.

- **Env var gate:** `UNIFI_WRITE_ENABLED` must be set to `"true"`
- **Apply flag gate:** `--apply` must be present
- **Outage risk:** None -- this is a read-and-store operation

### Example

```
You: Check for configuration drift

EmberAI:

## Configuration Drift Report

Comparing against baseline-20260315-091200 (4 days ago)

### Summary
| Category       | Changed | Added | Removed |
|----------------|---------|-------|---------|
| Devices        | 1       | 0     | 0       |
| VLANs          | 0       | 1     | 0       |
| Firewall rules | 0       | 1     | 0       |

Total drift: 3 changes detected.

### Changes

#### VLAN Added: Cameras (VLAN 40)
- Subnet: 192.168.40.0/24
- DHCP: Yes

#### Device Changed: Office-Switch-16
- Firmware: 7.0.50.15116 -> 7.0.72.15290
```

### Tools Called

- `unifi__config__get_config_snapshot` -- current configuration state
- `unifi__config__diff_baseline` -- drift comparison (when `--drift` is used)
- `unifi__config__get_backup_state` -- backup status
- `unifi__config__save_baseline` -- save snapshot (when `--save --apply` is used)

---

## `unifi port-profile create`

Create a named switch port profile in UniFi.

### What It Does

Creates a port profile that defines VLAN assignment for switch ports:

1. Verifies that referenced VLANs exist on the site
2. Creates the profile with the specified native VLAN and tagged VLANs
3. Presents the change plan for operator confirmation before execution

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Profile name (e.g., `"Trunk-AP"`, `"Cameras-Only"`) |
| `native_vlan` | int | No | Native (untagged) VLAN ID |
| `tagged_vlans` | list[int] | No | Tagged VLAN IDs to include on the trunk |
| `poe` | bool | No | Enable PoE on ports using this profile |
| `site_id` | string | No (default: `"default"`) | The UniFi site ID |
| `apply` | bool | No (default: `false`) | Execute the create (requires `UNIFI_WRITE_ENABLED=true`) |

### Write Safety

- **Env var gate:** `UNIFI_WRITE_ENABLED` must be set to `"true"`
- **Apply flag gate:** `--apply` must be present
- **Operator confirmation:** The change plan is presented before execution

### Example

```
You: Create a port profile called Trunk-AP with native VLAN 10 and tagged VLANs 30, 50, 60

EmberAI:

## Port Profile Create Plan

| Setting      | Value            |
|--------------|------------------|
| Name         | Trunk-AP         |
| Native VLAN  | 10 (Guest)       |
| Tagged VLANs | 30 (IoT), 50 (Cameras), 60 (Servers) |
| PoE          | Enabled          |

All referenced VLANs exist on this site.

Apply this profile? Requires --apply and UNIFI_WRITE_ENABLED=true.
```

### Tools Called

- `unifi__topology__get_vlans` -- verify VLANs exist
- `unifi__config__create_port_profile` -- create the profile

---

## `unifi port-profile assign`

Assign a named port profile to a specific port on a UniFi switch.

### What It Does

1. Identifies the target switch and port (by port number or description)
2. Runs the OutageRiskAgent to assess whether the port carries the operator's management session or critical infrastructure traffic
3. Shows the current profile vs. proposed profile for the port
4. Applies the change after operator confirmation

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `switch` | string | Yes | Switch name, MAC, or IP |
| `port` | int | Yes | Port number on the switch |
| `profile` | string | Yes | Name of the port profile to assign |
| `site_id` | string | No (default: `"default"`) | The UniFi site ID |
| `apply` | bool | No (default: `false`) | Execute the assignment (requires `UNIFI_WRITE_ENABLED=true`) |

### Write Safety

- **Env var gate:** `UNIFI_WRITE_ENABLED` must be set to `"true"`
- **Apply flag gate:** `--apply` must be present
- **OutageRiskAgent:** Assesses whether the port change could disconnect the operator. Ports connected to the gateway or carrying the management VLAN are flagged as high-risk.
- **CAUTION:** Never assign a profile to the port connected to OPNsense until all VLAN configuration on OPNsense is complete and verified.

### Example

```
You: Assign Trunk-AP profile to port 8 on Office-Switch-16

EmberAI:

## Port Profile Assignment Plan

| Field           | Value              |
|-----------------|--------------------|
| Switch          | Office-Switch-16   |
| Port            | 8                  |
| Current profile | Default            |
| New profile     | Trunk-AP           |

### OutageRiskAgent Assessment
| Risk   | Notes                                        |
|--------|----------------------------------------------|
| Low    | Port 8 is not the uplink port. No management |
|        | sessions transit this port.                   |

Apply this change? Requires --apply and UNIFI_WRITE_ENABLED=true.
```

### Tools Called

- `unifi__topology__get_device` -- identify the switch and port
- OutageRiskAgent -- assess management session risk
- `unifi__topology__assign_port_profile` -- apply the profile

---

## Phase 3+ Commands (Not Yet Implemented)

The following commands are planned for future releases.

| Command | Intent | Phase |
|---------|--------|-------|
| `unifi compare` | Side-by-side comparison of two sites | Phase 3 |
