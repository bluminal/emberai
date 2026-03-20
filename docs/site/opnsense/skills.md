# OPNsense Skills Reference

Skills are groups of MCP tools that provide direct access to the OPNsense REST API. Each tool makes a single API call and returns normalized data.

All tools follow the naming convention: `opnsense__{skill}__{operation}`

## Skill Groups

| Skill | Tools | Description |
|-------|-------|-------------|
| [interfaces](#interfaces) | 7 | Interface listing, VLAN management, DHCP leases and reservations |
| [firewall](#firewall) | 7 | Rules, aliases, NAT, rule management |
| [routing](#routing) | 3 | Static routes and gateway status |
| [vpn](#vpn) | 4 | IPsec, OpenVPN, WireGuard tunnel status |
| [security](#security) | 4 | IDS/IPS alerts, rules, policy, certificates |
| [services](#services) | 6 | DNS overrides/forwarders, DHCP leases, traffic shaping |
| [diagnostics](#diagnostics) | 5 | Ping, traceroute, host discovery, LLDP, DNS lookup |
| [firmware](#firmware) | 2 | Firmware status and package listing |

**Total: 38 tools** across 8 skill groups.

Read operations are always permitted. Write operations require `OPNSENSE_WRITE_ENABLED=true` and operator confirmation.

For full tool documentation with parameters, return types, and API endpoints, see the [complete reference](../../opnsense/skills.md).

## interfaces

| Tool | Type | Description |
|------|------|-------------|
| `opnsense__interfaces__list_interfaces` | Read | List all interfaces with IP, status, type |
| `opnsense__interfaces__list_vlan_interfaces` | Read | List VLAN interfaces with tag and parent |
| `opnsense__interfaces__configure_vlan` | Write | Atomic VLAN creation (interface + IP + DHCP) |
| `opnsense__interfaces__add_vlan_interface` | Write | Create a VLAN interface definition |
| `opnsense__interfaces__add_dhcp_reservation` | Write | Create a static DHCP reservation |
| `opnsense__interfaces__get_dhcp_leases` | Read | List active DHCP leases |
| `opnsense__interfaces__add_dhcp_subnet` | Write | Create a DHCP subnet |

## firewall

| Tool | Type | Description |
|------|------|-------------|
| `opnsense__firewall__list_rules` | Read | List firewall filter rules |
| `opnsense__firewall__get_rule` | Read | Get full details for a single rule |
| `opnsense__firewall__list_aliases` | Read | List all firewall aliases |
| `opnsense__firewall__list_nat_rules` | Read | List NAT/port forwarding rules |
| `opnsense__firewall__add_rule` | Write | Create a new firewall rule |
| `opnsense__firewall__toggle_rule` | Write | Enable or disable a rule |
| `opnsense__firewall__add_alias` | Write | Create a new firewall alias |

## routing

| Tool | Type | Description |
|------|------|-------------|
| `opnsense__routing__list_routes` | Read | List static routes |
| `opnsense__routing__list_gateways` | Read | List gateways with status and latency |
| `opnsense__routing__add_route` | Write | Create a static route |

## vpn

| Tool | Type | Description |
|------|------|-------------|
| `opnsense__vpn__list_ipsec_sessions` | Read | List IPSec security associations |
| `opnsense__vpn__list_openvpn_instances` | Read | List OpenVPN instances |
| `opnsense__vpn__list_wireguard_peers` | Read | List WireGuard peers |
| `opnsense__vpn__get_vpn_status` | Read | Aggregate VPN status summary |

## security

| Tool | Type | Description |
|------|------|-------------|
| `opnsense__security__get_ids_alerts` | Read | Query IDS/IPS alerts |
| `opnsense__security__get_ids_rules` | Read | List IDS/IPS rules |
| `opnsense__security__get_ids_policy` | Read | Get IDS/IPS policy config |
| `opnsense__security__get_certificates` | Read | List certificates with expiry |

## services

| Tool | Type | Description |
|------|------|-------------|
| `opnsense__services__get_dns_overrides` | Read | List DNS host overrides |
| `opnsense__services__get_dns_forwarders` | Read | List DNS forwarders |
| `opnsense__services__resolve_hostname` | Read | Test hostname resolution |
| `opnsense__services__add_dns_override` | Write | Create a DNS host override |
| `opnsense__services__get_dhcp_leases4` | Read | List DHCPv4 leases |
| `opnsense__services__get_traffic_shaper` | Read | Get traffic shaper config |

## diagnostics

| Tool | Type | Description |
|------|------|-------------|
| `opnsense__diagnostics__run_ping` | Read | Ping a host |
| `opnsense__diagnostics__run_traceroute` | Read | Traceroute to a host |
| `opnsense__diagnostics__run_host_discovery` | Read | ARP/NDP host discovery |
| `opnsense__diagnostics__get_lldp_neighbors` | Read | LLDP neighbor table |
| `opnsense__diagnostics__dns_lookup` | Read | DNS record lookup |

## firmware

| Tool | Type | Description |
|------|------|-------------|
| `opnsense__firmware__get_status` | Read | Firmware version and upgrade status |
| `opnsense__firmware__list_packages` | Read | Installed packages with update status |
