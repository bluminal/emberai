# Skill Groups Reference

Skill groups categorize the capabilities that vendor plugins provide.
The Plugin Registry indexes plugins by skill group, enabling queries
like `registry.plugins_with_skill("firewall")`.

## Network Roles

Roles describe the network layer a plugin operates on:

| Role | Description | Example Plugins |
|---|---|---|
| `gateway` | Manages routing, firewall, VPN, DNS, DHCP | opnsense |
| `edge` | Manages switching, ports, VLANs on switch fabric | unifi |
| `wireless` | Manages wireless APs, SSIDs, client associations | unifi |
| `overlay` | Manages overlay networks (Tailscale, ZeroTier) | (future) |
| `dns` | DNS filtering and analytics -- profile management, security posture, query analytics, log analysis | nextdns |
| `monitoring` | Provides monitoring and observability | (future) |

## Skill Groups

Skills describe specific capabilities within a plugin:

| Skill Group | Description | Typical Tools |
|---|---|---|
| `topology` | Device graph, uplinks, VLAN mapping | `list_devices`, `get_vlans` |
| `health` | Health monitoring, status checks | `get_health`, `check_status` |
| `wifi` | Wireless analysis, SSID management | `list_ssids`, `scan_channels` |
| `clients` | Client listing, identification | `list_clients`, `get_client` |
| `traffic` | Traffic analysis, DPI data | `get_traffic_stats` |
| `security` | Security audit, ZBF policies | `get_zbf_policies`, `audit` |
| `config` | Configuration management | `get_config`, `backup` |
| `multisite` | Multi-site management | `list_sites`, `scan_sites` |
| `interfaces` | Interface and VLAN management | `list_interfaces`, `add_vlan` |
| `firewall` | Firewall rule management | `list_rules`, `add_rule` |
| `routing` | Static/dynamic routing | `list_routes`, `add_route` |
| `vpn` | VPN tunnel management | `get_vpn_status`, `add_tunnel` |
| `services` | DNS, DHCP, NTP services | `get_dns_overrides`, `get_leases` |
| `diagnostics` | Live diagnostics (ping, traceroute) | `run_ping`, `run_traceroute` |
| `firmware` | Firmware/package management | `get_status`, `list_packages` |
| `profiles` | DNS profile management | `list_profiles`, `get_profile`, `get_security`, `get_privacy`, `get_parental_control`, `get_denylist`, `get_allowlist`, `get_settings` |
| `analytics` | DNS analytics and usage dashboards | `get_status`, `get_top_domains`, `get_block_reasons`, `get_devices`, `get_protocols`, `get_encryption`, `get_destinations`, `get_ips`, `get_query_types`, `get_ip_versions`, `get_dnssec` |
| `logs` | DNS query log access and analysis | `search`, `stream`, `download`, `clear` |
| `security-posture` | DNS security posture auditing | `audit`, `compare` |

## Mapping Skills to Roles

Plugins typically map skills to roles as follows:

- **Gateway role**: interfaces, firewall, routing, vpn, services, diagnostics, firmware, security
- **Edge role**: topology, health, wifi, clients, traffic, security, config, multisite
- **Wireless role**: wifi, clients
- **DNS role**: profiles, analytics, logs, security-posture

A single plugin may declare multiple roles and skills.
