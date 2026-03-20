# UniFi Skills

Skills are the atomic MCP tools that commands orchestrate. Each skill maps to
a specific UniFi API operation.

## Skill Groups

| Group | Tools | Description | Status |
|-------|-------|-------------|--------|
| topology | `list_devices`, `get_device`, `get_vlans`, `get_uplinks` | Device discovery and network map | Available |
| health | `get_site_health`, `get_device_health`, `get_isp_metrics`, `get_events`, `get_firmware_status` | Status, uptime, firmware, events | Available |
| clients | `list_clients`, `get_client`, `get_client_traffic`, `search_clients` | Connected client inventory | Available |
| wifi | `get_wlans`, `get_aps`, `get_channel_utilization`, `get_rf_scan`, `get_roaming_events`, `get_client_rf` | Wireless RF environment analysis | Phase 2 |
| traffic | `get_bandwidth`, `get_dpi_stats`, `get_port_stats`, `get_wan_usage` | Network traffic analysis | Phase 2 |
| security | `get_firewall_rules`, `get_zbf_policies`, `get_acls`, `get_port_forwards`, `get_ids_alerts` | Security posture analysis | Phase 2 |
| config | `get_config_snapshot`, `diff_baseline`, `get_backup_state`, `save_baseline`, `create_port_profile` | Configuration management | Phase 2 |
| multisite | `list_all_sites`, `get_site_health`, `compare_sites`, `search_across_sites`, `get_vantage_points` | Cross-site fleet management | Phase 3 |

For detailed documentation of each tool including parameters, return types,
and API mappings, see the full [Skills Reference](../../unifi/skills.md).
