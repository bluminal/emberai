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

## Phase 2+ Skills (Not Yet Implemented)

The following skill groups are defined in the plugin manifest but not yet implemented:

| Skill Group | Tools | Phase |
|-------------|-------|-------|
| wifi | `get_wlans`, `get_aps`, `get_channel_utilization`, `get_rf_scan`, `get_roaming_events`, `get_client_rf` | Phase 2 |
| traffic | `get_bandwidth`, `get_dpi_stats`, `get_port_stats`, `get_wan_usage` | Phase 2 |
| security | `get_firewall_rules`, `get_zbf_policies`, `get_acls`, `get_port_forwards`, `get_ids_alerts` | Phase 2 |
| config | `get_config_snapshot`, `diff_baseline`, `get_backup_state`, `save_baseline`, `create_port_profile` | Phase 2 |
| multisite | `list_all_sites`, `get_site_health`, `compare_sites`, `search_across_sites`, `get_vantage_points` | Phase 2 |
