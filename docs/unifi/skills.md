# UniFi Skills Reference

Skills are groups of MCP tools that provide direct access to the UniFi API. Each tool makes a single API call and returns normalized data. Tools are called by [commands](commands.md) through agent orchestrators, but can also be called individually.

All tools follow the naming convention: `unifi__{skill}__{operation}`

---

## topology

Discovers and models the network graph. Four tools for listing devices, inspecting individual devices, enumerating VLANs, and deriving the uplink topology.

### `unifi__topology__list_devices`

List all devices (switches, APs, gateways) for a UniFi site.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- device inventory

Each device includes:

| Field | Type | Description |
|-------|------|-------------|
| `device_id` | string | Internal device ID |
| `name` | string | Device name |
| `model` | string | Hardware model (e.g., `U6-Pro`, `USLITE16P`) |
| `mac` | string | MAC address |
| `ip` | string | IP address |
| `status` | string | Connection state: `connected`, `disconnected`, `pending_adoption`, `upgrading`, etc. |
| `uptime` | int | Uptime in seconds |
| `firmware` | string | Current firmware version |
| `product_line` | string | Product line identifier |
| `is_console` | bool | Whether this device is the console/gateway |

**API:** `GET {local}/api/s/{site}/stat/device`

---

### `unifi__topology__get_device`

Get detailed information for a single device, including port table, uplink info, VLAN assignments, radio table (for APs), and configuration.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `device_id` | string | *required* | The device MAC address or ID |
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `dict` -- full device details (fields vary by device type)

Additional fields beyond `list_devices`:

| Field | Type | Description |
|-------|------|-------------|
| `port_table` | list | Switch port details (switches only) |
| `uplink` | dict | Uplink connection details |
| `radio_table` | list | Radio configuration (APs only) |
| `config_network` | dict | Network configuration |

**API:** `GET {local}/api/s/{site}/stat/device/{mac}`

---

### `unifi__topology__get_vlans`

List all VLANs/networks configured for a UniFi site. Filters out WAN-purpose networks and returns only LAN/VLAN entries.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- VLAN inventory

Each VLAN includes:

| Field | Type | Description |
|-------|------|-------------|
| `vlan_id` | int or None | VLAN tag (None for default/untagged LAN) |
| `name` | string | Network name |
| `subnet` | string | IP subnet in CIDR notation |
| `purpose` | string | Network purpose (`corporate`, `guest`, etc.) |
| `dhcp_enabled` | bool | Whether DHCP is enabled |
| `domain_name` | string | DNS domain name |

**API:** `GET {local}/api/s/{site}/rest/networkconf`

---

### `unifi__topology__get_uplinks`

Derive the uplink graph showing device-to-device connections. Built from the `uplink` and `port_table` fields of all devices. Devices without an uplink (root gateways) or with self-referencing uplinks are excluded.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- uplink relationships

Each uplink includes:

| Field | Type | Description |
|-------|------|-------------|
| `device_id` | string | Child device ID |
| `device_name` | string | Child device name |
| `device_mac` | string | Child device MAC |
| `uplink_device_id` | string | Parent device ID |
| `uplink_device_name` | string | Parent device name |
| `uplink_device_mac` | string | Parent device MAC |
| `uplink_port` | int | Port number on the parent device |
| `uplink_type` | string | Connection type (e.g., `wire`) |
| `speed` | int | Link speed in Mbps |

**API:** Derived from `GET {local}/api/s/{site}/stat/device` (uplink fields)

---

## health

Device and site health monitoring. Five tools covering subsystem health, device-level metrics, ISP connectivity, event retrieval, and firmware status.

### `unifi__health__get_site_health`

Get aggregate health status for all subsystems (WAN, LAN, WLAN, WWW) at a site.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `dict` -- aggregated site health

| Field | Type | Description |
|-------|------|-------------|
| `wan_status` | string | WAN subsystem status (`ok`, `degraded`, etc.) |
| `lan_status` | string | LAN subsystem status |
| `wlan_status` | string | WLAN subsystem status |
| `www_status` | string | Internet/WWW subsystem status |
| `device_count` | int | Total device count |
| `adopted_count` | int | Number of adopted devices |
| `offline_count` | int | Number of offline/disconnected devices |
| `client_count` | int | Connected client count |

**API:** `GET {local}/api/s/{site}/stat/health`

---

### `unifi__health__get_device_health`

Get health metrics for a single device: uptime, CPU, memory, temperature, satisfaction, and firmware status.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `device_id` | string | *required* | The device MAC address or ID |
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `dict` -- device health metrics

| Field | Type | Description |
|-------|------|-------------|
| `device_id` | string | Device ID |
| `name` | string | Device name |
| `mac` | string | MAC address |
| `model` | string | Hardware model |
| `status` | string | Connection state |
| `uptime` | int | Uptime in seconds |
| `cpu_usage_pct` | float or None | CPU usage percentage |
| `mem_usage_pct` | float or None | Memory usage percentage |
| `temperature_c` | float or None | Temperature in Celsius |
| `satisfaction` | int or None | Client satisfaction score (0-100) |
| `upgrade_available` | bool | Whether a firmware upgrade is available |
| `current_firmware` | string | Current firmware version |
| `upgrade_firmware` | string | Available upgrade version (empty if none) |

**API:** `GET {local}/api/s/{site}/stat/device/{mac}`

---

### `unifi__health__get_isp_metrics`

Get ISP connectivity metrics from the WAN subsystem health data.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `dict` -- ISP metrics

| Field | Type | Description |
|-------|------|-------------|
| `wan_ip` | string | Public WAN IP address |
| `isp_name` | string | ISP name |
| `isp_organization` | string | ISP organization |
| `latency_ms` | int or None | Latency in milliseconds |
| `speedtest_ping_ms` | int or None | Speed test ping |
| `download_mbps` | float or None | Download speed in Mbps |
| `upload_mbps` | float or None | Upload speed in Mbps |
| `speedtest_lastrun` | int or None | Last speed test timestamp (epoch) |
| `uptime_seconds` | int or None | WAN uptime in seconds |
| `drops` | int or None | Number of WAN drops |
| `tx_bytes_rate` | int or None | Current transmit rate (bytes/sec) |
| `rx_bytes_rate` | int or None | Current receive rate (bytes/sec) |
| `wan_status` | string | WAN status |

**API:** `GET {local}/api/s/{site}/stat/health` (WAN subsystem)

---

### `unifi__health__get_events`

Get recent network events, optionally filtered by time window and severity. Returns alarms, state changes, and notifications from the site event log.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `hours` | int | `24` | Number of hours to look back |
| `severity` | string | `"all"` | Filter: `"critical"`, `"warning"`, `"info"`, or `"all"` |

**Returns:** `list[dict]` -- events

Each event includes:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | Event timestamp |
| `type` | string | Event type (e.g., `EVT_WU_Connected`, `EVT_SW_PoeOverload`) |
| `severity` | string | Event severity |
| `device_id` | string or None | Related device MAC |
| `client_mac` | string or None | Related client MAC |
| `message` | string | Human-readable event message |
| `subsystem` | string | Subsystem (wan, lan, wlan, ips) |

**API:** `GET {local}/api/s/{site}/stat/event`

---

### `unifi__health__get_firmware_status`

Get firmware upgrade status for all devices at a site. Returns each device's current firmware version, latest available version, and whether an upgrade is available.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- firmware status per device

Each entry includes:

| Field | Type | Description |
|-------|------|-------------|
| `device_id` | string | Device ID |
| `name` | string | Device name |
| `mac` | string | MAC address |
| `model` | string | Hardware model |
| `current_version` | string | Currently installed firmware |
| `latest_version` | string | Latest available firmware (empty if up to date) |
| `upgrade_available` | bool | Whether an upgrade is available |
| `product_line` | string | Product line |

**API:** `GET {local}/api/s/{site}/stat/device`

---

## clients

Connected client inventory and profiling. Four tools for listing, inspecting, searching, and analyzing traffic for connected clients.

### `unifi__clients__list_clients`

List all connected clients (wired and wireless) for a UniFi site. Optionally filter by VLAN/network ID.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `vlan_id` | string or None | `null` | Optional VLAN/network ID to filter by |

**Returns:** `list[dict]` -- client inventory

Each client includes:

| Field | Type | Description |
|-------|------|-------------|
| `client_mac` | string | Client MAC address |
| `hostname` | string or None | Client hostname |
| `ip` | string | IP address |
| `vlan_id` | string | VLAN/network ID |
| `ap_id` | string or None | Associated AP MAC (wireless only) |
| `port_id` | int or None | Switch port (wired only) |
| `connection_type` | string | Connection type |
| `is_wired` | bool | Whether the client is wired |
| `is_guest` | bool | Whether the client is on a guest network |
| `uptime` | int | Connection uptime in seconds |
| `rssi` | int or None | Signal strength (wireless only) |
| `ssid` | string or None | Connected SSID (wireless only) |
| `tx_bytes` | int | Transmitted bytes |
| `rx_bytes` | int | Received bytes |

**API:** `GET {local}/api/s/{site}/stat/sta`

---

### `unifi__clients__get_client`

Get detailed information for a single client by MAC address. Returns full client details including AP association, SSID, signal strength, traffic counters, OS detection, and vendor information.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `client_mac` | string | *required* | The client's MAC address |
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `dict` -- full client details

Additional fields beyond `list_clients`:

| Field | Type | Description |
|-------|------|-------------|
| `first_seen` | int | First seen timestamp (epoch) |
| `last_seen` | int | Last seen timestamp (epoch) |
| `os_name` | string or None | Detected operating system |
| `device_vendor` | string or None | Device vendor (OUI lookup) |
| `is_blocked` | bool | Whether the client is blocked |

**API:** `GET {local}/api/s/{site}/stat/sta/{mac}`

---

### `unifi__clients__get_client_traffic`

Get traffic statistics for a single client by MAC address. Returns transmit/receive byte and packet counters, and DPI (Deep Packet Inspection) data if available.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `client_mac` | string | *required* | The client's MAC address |
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `dict` -- traffic statistics

| Field | Type | Description |
|-------|------|-------------|
| `client_mac` | string | Client MAC address |
| `hostname` | string or None | Client hostname |
| `ip` | string or None | IP address |
| `tx_bytes` | int | Total transmitted bytes |
| `rx_bytes` | int | Total received bytes |
| `tx_packets` | int | Total transmitted packets |
| `rx_packets` | int | Total received packets |
| `dpi_stats` | list or None | Deep packet inspection data (if available) |

**API:** `GET {local}/api/s/{site}/stat/user/{mac}`

---

### `unifi__clients__search_clients`

Search connected clients by partial match on MAC, hostname, IP, or name (alias). Performs case-insensitive substring matching across multiple fields. Fetches all clients for the site and filters client-side.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | *required* | Search string to match |
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- matching clients (same shape as `list_clients`)

**Matching behavior:** Case-insensitive partial match against:
- `mac`
- `hostname`
- `ip`
- `name` (alias)

**API:** `GET {local}/api/s/{site}/stat/sta` (client-side filter)

---

## wifi

Wireless RF environment analysis. Six tools covering SSIDs, AP radio configuration, channel utilization, RF scanning, roaming events, and per-client RF metrics.

### `unifi__wifi__get_wlans`

List all wireless networks (SSIDs) configured for a site.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- SSID inventory

Each SSID includes:

| Field | Type | Description |
|-------|------|-------------|
| `ssid_id` | string | Internal SSID ID |
| `name` | string | SSID name (broadcast name) |
| `enabled` | bool | Whether the SSID is enabled |
| `security` | string | Security mode (e.g., `wpa2`, `wpa3`, `open`) |
| `vlan_id` | int or None | VLAN assignment for this SSID |
| `band_steering` | string | Band steering mode (`prefer_5g`, `balanced`, `off`) |
| `hide_ssid` | bool | Whether the SSID is hidden |
| `guest_policy` | bool | Whether guest portal is enabled |

**API:** `GET {local}/api/s/{site}/rest/wlanconf`

---

### `unifi__wifi__get_aps`

List all access points with radio configuration for each band.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- AP inventory with radio details

Each AP includes:

| Field | Type | Description |
|-------|------|-------------|
| `ap_id` | string | AP device ID |
| `name` | string | AP name |
| `mac` | string | MAC address |
| `model` | string | Hardware model |
| `status` | string | Connection state |
| `radios` | list | Radio configuration per band |

Each radio entry:

| Field | Type | Description |
|-------|------|-------------|
| `band` | string | Radio band (`2.4GHz`, `5GHz`, `6GHz`) |
| `channel` | int | Current channel |
| `channel_width` | string | Channel width (e.g., `HT20`, `VHT80`) |
| `tx_power` | int | Transmit power in dBm |
| `min_rssi` | int or None | Minimum RSSI threshold (if set) |

**API:** `GET {local}/api/s/{site}/stat/device` (AP devices only)

---

### `unifi__wifi__get_channel_utilization`

Get channel utilization percentages for all APs.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- per-AP per-band utilization

Each entry includes:

| Field | Type | Description |
|-------|------|-------------|
| `ap_name` | string | AP name |
| `ap_mac` | string | AP MAC address |
| `band` | string | Radio band |
| `channel` | int | Current channel |
| `utilization_pct` | float | Total channel utilization percentage |
| `self_tx_pct` | float | Self-transmit utilization |
| `self_rx_pct` | float | Self-receive utilization |
| `interference_pct` | float | External interference percentage |
| `client_count` | int | Number of clients on this radio |
| `satisfaction` | int or None | Client satisfaction score (0-100) |

**API:** `GET {local}/api/s/{site}/stat/device` (radio_table_stats)

---

### `unifi__wifi__get_rf_scan`

Get cached RF scan results showing neighboring SSIDs detected by each AP.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `ap_mac` | string | `null` | Filter to a specific AP (default: all APs) |

**Returns:** `list[dict]` -- neighboring SSIDs

Each entry includes:

| Field | Type | Description |
|-------|------|-------------|
| `ap_name` | string | Detecting AP name |
| `ssid` | string | Neighboring SSID name |
| `bssid` | string | Neighboring BSSID |
| `channel` | int | Neighboring channel |
| `band` | string | Radio band |
| `rssi` | int | Signal strength of neighbor (dBm) |
| `security` | string | Security mode |
| `last_seen` | string | Timestamp of last detection |

**API:** `GET {local}/api/s/{site}/stat/device` (scan_table)

---

### `unifi__wifi__get_roaming_events`

Get client roaming events over a time window.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `hours` | int | `24` | Number of hours to look back |

**Returns:** `dict` -- roaming analysis summary

| Field | Type | Description |
|-------|------|-------------|
| `total_roams` | int | Total roaming attempts |
| `successful` | int | Successful roams |
| `failed` | int | Failed roams (client fell back to original AP) |
| `avg_roam_time_ms` | float | Average time to complete a roam |
| `sticky_clients` | int | Clients that never roamed despite low signal |
| `events` | list | Individual roaming events |

Each event:

| Field | Type | Description |
|-------|------|-------------|
| `client_mac` | string | Roaming client MAC |
| `from_ap` | string | Source AP name |
| `to_ap` | string | Destination AP name |
| `success` | bool | Whether the roam completed |
| `roam_time_ms` | int | Time to complete the roam |
| `timestamp` | string | Event timestamp |

**API:** `GET {local}/api/s/{site}/stat/event` (EVT_WU_Roam events)

---

### `unifi__wifi__get_client_rf`

Get detailed RF metrics for a specific wireless client.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `client_mac` | string | *required* | Client MAC address |
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `dict` -- client RF details

| Field | Type | Description |
|-------|------|-------------|
| `client_mac` | string | Client MAC address |
| `rssi` | int | Current RSSI |
| `noise_floor` | int | Noise floor (dBm) |
| `snr` | int | Signal-to-noise ratio |
| `tx_rate` | int | Current transmit rate (Mbps) |
| `rx_rate` | int | Current receive rate (Mbps) |
| `channel` | int | Channel the client is on |
| `band` | string | Connected band |
| `tx_retries_pct` | float | Transmit retry percentage |
| `satisfaction` | int or None | Client satisfaction score |

**API:** `GET {local}/api/s/{site}/stat/sta/{mac}` (RF fields)

---

## traffic

Network traffic analysis. Four tools covering bandwidth, deep packet inspection, per-port statistics, and WAN usage.

### `unifi__traffic__get_bandwidth`

Get aggregate bandwidth statistics for a site over a time window.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `hours` | int | `24` | Number of hours to look back |
| `resolution` | string | `"hourly"` | Data resolution: `"5min"`, `"hourly"`, `"daily"` |

**Returns:** `dict` -- bandwidth time series

| Field | Type | Description |
|-------|------|-------------|
| `total_tx_bytes` | int | Total transmitted bytes |
| `total_rx_bytes` | int | Total received bytes |
| `peak_tx_bps` | int | Peak transmit rate (bits/sec) |
| `peak_rx_bps` | int | Peak receive rate (bits/sec) |
| `time_series` | list | Data points at the specified resolution |

**API:** `GET {local}/api/s/{site}/stat/report/hourly.site`

---

### `unifi__traffic__get_dpi_stats`

Get Deep Packet Inspection (DPI) statistics showing traffic by application category.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- traffic by application category

Each entry includes:

| Field | Type | Description |
|-------|------|-------------|
| `category` | string | Application category (e.g., `"Streaming"`, `"Social Media"`) |
| `app_name` | string | Application name (e.g., `"YouTube"`, `"Netflix"`) |
| `tx_bytes` | int | Transmitted bytes for this category |
| `rx_bytes` | int | Received bytes for this category |
| `client_count` | int | Number of clients using this category |

**API:** `GET {local}/api/s/{site}/stat/sitedpi`

---

### `unifi__traffic__get_port_stats`

Get per-port traffic statistics for a specific switch.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `device_id` | string | *required* | Switch device MAC or ID |
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- per-port statistics

Each entry includes:

| Field | Type | Description |
|-------|------|-------------|
| `port_idx` | int | Port number |
| `name` | string | Port name/label |
| `speed` | int | Negotiated link speed (Mbps) |
| `tx_bytes` | int | Transmitted bytes |
| `rx_bytes` | int | Received bytes |
| `tx_packets` | int | Transmitted packets |
| `rx_packets` | int | Received packets |
| `poe_power_w` | float or None | PoE power draw (watts) |
| `profile` | string | Assigned port profile name |

**API:** `GET {local}/api/s/{site}/stat/device/{mac}` (port_table)

---

### `unifi__traffic__get_wan_usage`

Get WAN interface traffic statistics and ISP usage.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `hours` | int | `24` | Number of hours to look back |

**Returns:** `dict` -- WAN usage summary

| Field | Type | Description |
|-------|------|-------------|
| `total_tx_bytes` | int | Total WAN transmitted bytes |
| `total_rx_bytes` | int | Total WAN received bytes |
| `current_tx_bps` | int | Current transmit rate (bits/sec) |
| `current_rx_bps` | int | Current receive rate (bits/sec) |
| `wan_ip` | string | Current WAN IP address |
| `isp_name` | string | ISP name |

**API:** `GET {local}/api/s/{site}/stat/health` (WAN subsystem)

---

## security

Security posture analysis. Five tools covering firewall rules, zone-based firewall policies, access control lists, port forwarding, and IDS/IPS alerts.

### `unifi__security__get_firewall_rules`

List all firewall filter rules for a site.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- firewall rules

Each rule includes:

| Field | Type | Description |
|-------|------|-------------|
| `rule_id` | string | Rule identifier |
| `name` | string | Rule name/description |
| `action` | string | `pass`, `block`, or `reject` |
| `enabled` | bool | Whether the rule is enabled |
| `source` | string | Source address or group |
| `destination` | string | Destination address or group |
| `protocol` | string | Protocol (`TCP`, `UDP`, `ICMP`, `any`) |
| `port` | string or None | Port number or range |
| `direction` | string | `in` or `out` |
| `interface` | string | Applied interface |

**API:** `GET {local}/api/s/{site}/rest/firewallrule`

---

### `unifi__security__get_zbf_policies`

List all zone-based firewall policies.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- ZBF policies

Each policy includes:

| Field | Type | Description |
|-------|------|-------------|
| `policy_id` | string | Policy identifier |
| `source_zone` | string | Source zone name |
| `destination_zone` | string | Destination zone name |
| `action` | string | `allow` or `block` |
| `description` | string | Policy description |
| `enabled` | bool | Whether the policy is enabled |

**API:** `GET {local}/api/s/{site}/rest/firewallgroup` + zone configuration

---

### `unifi__security__get_acls`

List all access control list rules.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- ACL rules

Each ACL entry includes:

| Field | Type | Description |
|-------|------|-------------|
| `acl_id` | string | ACL identifier |
| `action` | string | `pass` or `block` |
| `source` | string | Source network or address |
| `destination` | string | Destination network or address |
| `protocol` | string | Protocol |
| `port` | string or None | Port or range |
| `enabled` | bool | Whether the ACL is enabled |
| `log` | bool | Whether matches are logged |
| `position` | int | ACL evaluation order |

**API:** `GET {local}/api/s/{site}/rest/firewallrule` (ACL-type rules)

---

### `unifi__security__get_port_forwards`

List all port forwarding (DNAT) rules.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `list[dict]` -- port forwarding rules

Each rule includes:

| Field | Type | Description |
|-------|------|-------------|
| `forward_id` | string | Forward rule identifier |
| `name` | string | Rule description |
| `enabled` | bool | Whether the forward is enabled |
| `external_port` | int | External (WAN-facing) port |
| `internal_ip` | string | Internal destination IP |
| `internal_port` | int | Internal destination port |
| `protocol` | string | Protocol (`TCP`, `UDP`, `TCP/UDP`) |
| `source` | string | Source restriction (default: `any`) |

**API:** `GET {local}/api/s/{site}/rest/portforward`

---

### `unifi__security__get_ids_alerts`

Get IDS/IPS alerts from the UniFi Intrusion Detection System.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `hours` | int | `24` | Number of hours to look back |
| `severity` | string | `"all"` | Filter: `"high"`, `"medium"`, `"low"`, or `"all"` |

**Returns:** `list[dict]` -- IDS alerts

Each alert includes:

| Field | Type | Description |
|-------|------|-------------|
| `alert_id` | string | Alert identifier |
| `timestamp` | string | Alert timestamp |
| `signature` | string | IDS rule signature |
| `category` | string | Alert category |
| `severity` | string | Severity level |
| `src_ip` | string | Source IP |
| `dst_ip` | string | Destination IP |
| `protocol` | string | Network protocol |
| `action` | string | Action taken (`alert`, `drop`) |

**API:** `GET {local}/api/s/{site}/stat/ips/event`

---

## config

Configuration management. Three read tools and two write tools covering snapshots, drift detection, backup state, baseline saving, and port profile creation.

### `unifi__config__get_config_snapshot`

Capture a read-only snapshot of the current site configuration.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `dict` -- configuration snapshot

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | Snapshot timestamp |
| `devices` | list | Device configurations |
| `vlans` | list | VLAN/network configurations |
| `firewall_rules` | list | Firewall rule set |
| `port_profiles` | list | Port profile definitions |
| `wireless` | list | SSID configurations |
| `settings` | dict | Site-level settings |

**API:** Multiple endpoints aggregated

---

### `unifi__config__diff_baseline`

Compare current configuration against a stored baseline.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `baseline_id` | string | `null` | Baseline to compare against (default: most recent) |

**Returns:** `dict` -- drift report

| Field | Type | Description |
|-------|------|-------------|
| `baseline_id` | string | The baseline compared against |
| `baseline_timestamp` | string | When the baseline was saved |
| `total_changes` | int | Total number of drift items |
| `changes` | list | Individual change entries |

Each change entry:

| Field | Type | Description |
|-------|------|-------------|
| `category` | string | Config category (e.g., `"devices"`, `"vlans"`) |
| `change_type` | string | `"added"`, `"removed"`, or `"modified"` |
| `item_name` | string | Name of the changed item |
| `field` | string or None | Specific field that changed (for modifications) |
| `old_value` | any | Previous value (modifications and removals) |
| `new_value` | any | Current value (modifications and additions) |

**API:** Computed from snapshot comparison

---

### `unifi__config__get_backup_state`

Get the current backup/restore state for the site.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |

**Returns:** `dict` -- backup state

| Field | Type | Description |
|-------|------|-------------|
| `auto_backup_enabled` | bool | Whether automatic backups are enabled |
| `last_backup_time` | string or None | Timestamp of the last backup |
| `backup_count` | int | Number of stored backups |
| `cloud_backup` | bool | Whether cloud backup is enabled |

**API:** `GET {local}/api/s/{site}/stat/backup`

---

### `unifi__config__save_baseline` (write)

Save the current configuration as a named baseline snapshot.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site_id` | string | `"default"` | The UniFi site ID |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `UNIFI_WRITE_ENABLED=true` and `apply=True`. This stores a snapshot locally -- it does not modify the network.

**Returns:** `dict` -- saved baseline metadata

| Field | Type | Description |
|-------|------|-------------|
| `baseline_id` | string | Generated baseline identifier |
| `timestamp` | string | Save timestamp |
| `item_count` | int | Number of config objects captured |

---

### `unifi__config__create_port_profile` (write)

Create a named switch port profile.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | string | *required* | Profile name |
| `native_vlan` | int | `null` | Native VLAN ID |
| `tagged_vlans` | list[int] | `[]` | Tagged VLAN IDs |
| `poe` | bool | `true` | Enable PoE |
| `site_id` | string | `"default"` | The UniFi site ID |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `UNIFI_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict` -- created profile details

| Field | Type | Description |
|-------|------|-------------|
| `profile_id` | string | Created profile identifier |
| `name` | string | Profile name |
| `native_vlan` | int or None | Native VLAN |
| `tagged_vlans` | list[int] | Tagged VLANs |

**API:** `POST {local}/api/s/{site}/rest/portconf`

---

## Phase 3+ Skills (Not Yet Implemented)

The following skill group is defined in the plugin manifest but not yet implemented:

| Skill Group | Tools | Phase |
|-------------|-------|-------|
| multisite | `list_all_sites`, `get_site_health`, `compare_sites`, `search_across_sites`, `get_vantage_points` | Phase 3 |
