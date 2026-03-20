# OPNsense Skills Reference

Skills are groups of MCP tools that provide direct access to the OPNsense REST API. Each tool makes a single API call and returns normalized data. Tools are called by [commands](commands.md) through agent orchestrators, but can also be called individually.

All tools follow the naming convention: `opnsense__{skill}__{operation}`

---

## interfaces

Interface discovery, VLAN management, and DHCP operations. Seven tools covering interface listing, VLAN CRUD, DHCP leases, reservations, and subnet management.

### `opnsense__interfaces__list_interfaces`

List all interfaces (physical, VLAN, loopback, tunnel) on the OPNsense instance.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all interfaces |

**Returns:** `list[dict]` -- interface inventory

Each interface includes:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Interface identifier (e.g., `igc0`, `igc1_vlan10`) |
| `description` | string | Human-readable name (e.g., `WAN`, `LAN`, `Guest`) |
| `ip` | string or None | Assigned IP address |
| `subnet` | string or None | Subnet mask in CIDR notation |
| `type` | string | Interface type: `physical`, `vlan`, `loopback`, `openvpn`, `wireguard` |
| `enabled` | bool | Whether the interface is enabled |
| `vlan_id` | int or None | VLAN tag (VLAN interfaces only) |

**API:** `GET /api/interfaces/overview/export`

---

### `opnsense__interfaces__list_vlan_interfaces`

List all VLAN interfaces with tag, parent interface, and description.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all VLAN interfaces |

**Returns:** `list[dict]` -- VLAN interface inventory

Each VLAN interface includes:

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | VLAN interface UUID |
| `tag` | int | VLAN tag (e.g., 10, 20, 99) |
| `if` | string | Underlying interface name (e.g., `igc1`) |
| `description` | string | VLAN description |
| `parent_if` | string | Parent interface identifier |
| `pcp` | int or None | Priority Code Point value |

**API:** `GET /api/interfaces/vlan/searchItem`

---

### `opnsense__interfaces__configure_vlan` (write)

Atomic VLAN configuration: creates a VLAN interface, assigns a static IP, and optionally creates a DHCP scope in a single confirmed workflow with one reconfigure at the end.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tag` | int | *required* | VLAN tag (e.g., 30) |
| `parent_if` | string | *required* | Parent interface (e.g., `igc1`) |
| `ip` | string | *required* | Static IP for the VLAN interface |
| `subnet` | string | *required* | Subnet in CIDR notation |
| `dhcp_range_from` | string | None | DHCP pool start address |
| `dhcp_range_to` | string | None | DHCP pool end address |
| `description` | string | None | VLAN description |

**Write safety:** Requires `OPNSENSE_WRITE_ENABLED=true` and `apply=True`. Interface changes carry the highest outage risk.

**Returns:** `dict` -- created resources

| Field | Type | Description |
|-------|------|-------------|
| `vlan_uuid` | string | Created VLAN interface UUID |
| `interface_name` | string | Assigned interface name |
| `dhcp_uuid` | string or None | Created DHCP subnet UUID (if DHCP was configured) |

---

### `opnsense__interfaces__add_vlan_interface` (write)

Create a VLAN interface definition. Use `configure_vlan` for new workflows -- this tool is retained for cases where only the VLAN definition is needed without IP or DHCP.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tag` | int | *required* | VLAN tag |
| `parent_if` | string | *required* | Parent interface |
| `description` | string | None | VLAN description |

**Write safety:** Requires `OPNSENSE_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict` -- `{uuid}`

**Reconfigure:** `POST /api/interfaces/vlan/reconfigure`

---

### `opnsense__interfaces__add_dhcp_reservation` (write)

Create a static DHCP reservation (Kea).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interface` | string | *required* | Interface for the reservation |
| `mac` | string | *required* | Client MAC address |
| `ip` | string | *required* | Reserved IP address |
| `hostname` | string | None | Client hostname |

**Write safety:** Requires `OPNSENSE_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict` -- `{uuid}`

**Reconfigure:** `POST /api/kea/ctrl_agent/restart`

**API:** `POST /api/kea/dhcpv4/addReservation`

---

### `opnsense__interfaces__get_dhcp_leases`

List active DHCP leases (Kea), optionally filtered by interface.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interface` | string | None | Filter leases by interface |

**Returns:** `list[dict]` -- active DHCP leases

Each lease includes:

| Field | Type | Description |
|-------|------|-------------|
| `mac` | string | Client MAC address |
| `ip` | string | Leased IP address |
| `hostname` | string or None | Client hostname |
| `expiry` | string | Lease expiry timestamp |
| `state` | string | Lease state (e.g., `active`, `expired`) |
| `interface` | string | Interface the lease is on |

**API:** `GET /api/kea/leases4/search`

---

### `opnsense__interfaces__add_dhcp_subnet` (write)

Create a DHCP subnet configuration for an interface.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interface` | string | *required* | Interface for the DHCP subnet |
| `subnet` | string | *required* | Subnet in CIDR notation |
| `range_from` | string | *required* | Pool start address |
| `range_to` | string | *required* | Pool end address |
| `dns_servers` | list[string] | *required* | DNS server addresses |

**Write safety:** Requires `OPNSENSE_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict` -- `{uuid}`

**Reconfigure:** `POST /api/kea/ctrl_agent/restart`

---

## firewall

Firewall rule management and analysis. Seven tools covering rule listing, inspection, alias management, NAT, and rule CRUD.

### `opnsense__firewall__list_rules`

List all firewall filter rules, optionally filtered by interface.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interface` | string | None | Filter rules by interface name |

**Returns:** `list[dict]` -- firewall rules

Each rule includes:

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | Rule UUID |
| `description` | string | Rule description |
| `action` | string | `pass`, `block`, or `reject` |
| `enabled` | bool | Whether the rule is enabled |
| `direction` | string | `in` or `out` |
| `protocol` | string | Protocol (e.g., `TCP`, `UDP`, `*`) |
| `source` | string | Source address, alias, or `*` |
| `destination` | string | Destination address, alias, or `*` |
| `log` | bool | Whether matches are logged |
| `position` | int | Rule evaluation order |

**API:** `GET /api/firewall/filter/searchRule`

---

### `opnsense__firewall__get_rule`

Get full details for a single firewall rule by UUID.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `uuid` | string | *required* | Rule UUID |

**Returns:** `dict` -- full rule object including all fields and metadata

---

### `opnsense__firewall__list_aliases`

List all firewall aliases (named groups of addresses, networks, or ports).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all aliases |

**Returns:** `list[dict]` -- alias inventory

Each alias includes:

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | Alias UUID |
| `name` | string | Alias name (e.g., `LAN_net`, `RFC1918`) |
| `type` | string | Alias type: `host`, `network`, `port`, `url` |
| `description` | string | Alias description |
| `content` | list[string] | Alias values (CIDRs, IPs, port ranges, URLs) |

**API:** `GET /api/firewall/alias/searchItem`

---

### `opnsense__firewall__list_nat_rules`

List all source NAT rules.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all NAT rules |

**Returns:** `list[dict]` -- NAT rules

Each rule includes:

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | NAT rule UUID |
| `description` | string | Rule description |
| `interface` | string | Applied interface |
| `protocol` | string | Protocol |
| `src` | string | Source address |
| `dst` | string | Destination address |
| `target` | string | NAT target address |
| `target_port` | string | NAT target port |
| `enabled` | bool | Whether the rule is enabled |

**API:** `GET /api/firewall/s_nat/searchRule`

---

### `opnsense__firewall__add_rule` (write)

Create a new firewall filter rule.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interface` | string | *required* | Interface to apply the rule on |
| `action` | string | *required* | `pass`, `block`, or `reject` |
| `src` | string | *required* | Source address or alias |
| `dst` | string | *required* | Destination address or alias |
| `protocol` | string | *required* | Protocol (e.g., `TCP`, `UDP`, `*`) |
| `description` | string | *required* | Rule description |
| `position` | int | None | Position in rule order (default: append) |

**Write safety:** Requires `OPNSENSE_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict` -- `{uuid}`

**Reconfigure:** `POST /api/firewall/filter/apply`

!!! warning "Rule position matters"
    Firewall rules are evaluated in order. Before adding a rule, the plugin
    checks the current rule list and shows where the new rule will be inserted.
    A rule in the wrong position may be shadowed or may shadow other rules.

---

### `opnsense__firewall__toggle_rule` (write)

Enable or disable an existing firewall rule.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `uuid` | string | *required* | Rule UUID |
| `enabled` | bool | *required* | Enable (`true`) or disable (`false`) the rule |

**Write safety:** Requires `OPNSENSE_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict` -- `{changed}`

**Reconfigure:** `POST /api/firewall/filter/apply`

---

### `opnsense__firewall__add_alias` (write)

Create a new firewall alias (named group for use in rules).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | string | *required* | Alias name |
| `type` | string | *required* | Alias type: `host`, `network`, `port`, `url` |
| `content` | list[string] | *required* | Alias values (CIDRs, IPs, port ranges, URLs) |
| `description` | string | None | Alias description |

**Write safety:** Requires `OPNSENSE_WRITE_ENABLED=true` and `apply=True`. Required before any rule that references a named alias.

**Returns:** `dict` -- `{uuid}`

**Reconfigure:** `POST /api/firewall/alias/reconfigure`

**API:** `POST /api/firewall/alias/addItem`

---

## routing

Static routing and gateway management. Three tools covering route listing, gateway status, and route creation.

### `opnsense__routing__list_routes`

List all static routes.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all routes |

**Returns:** `list[dict]` -- route table

Each route includes:

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | Route UUID |
| `network` | string | Destination network in CIDR notation |
| `gateway` | string | Gateway name |
| `description` | string | Route description |
| `disabled` | bool | Whether the route is disabled |

**API:** `GET /api/routes/routes/searchRoute`

---

### `opnsense__routing__list_gateways`

List all gateways with status and latency metrics.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all gateways |

**Returns:** `list[dict]` -- gateway status

Each gateway includes:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Gateway name (e.g., `WAN_GW`) |
| `interface` | string | Associated interface |
| `gateway` | string | Gateway IP address |
| `monitor` | string | Monitor IP address |
| `status` | string | Status: `online`, `offline`, `none` |
| `priority` | int | Gateway priority |
| `rtt_ms` | float or None | Round-trip time in milliseconds |

**API:** `GET /api/routes/gateway/status`

---

### `opnsense__routing__add_route` (write)

Create a new static route.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `network` | string | *required* | Destination network in CIDR notation |
| `gateway` | string | *required* | Gateway name |
| `description` | string | *required* | Route description |

**Write safety:** Requires `OPNSENSE_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict` -- `{uuid}`

**Reconfigure:** `POST /api/routes/routes/reconfigure`

---

## vpn

VPN tunnel status and management. Four tools covering IPSec, OpenVPN, WireGuard, and aggregate status.

### `opnsense__vpn__list_ipsec_sessions`

List all IPSec security associations with status and traffic counters.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all IPSec sessions |

**Returns:** `list[dict]` -- IPSec sessions

Each session includes:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Session identifier |
| `description` | string | Tunnel description |
| `status` | string | `established`, `connecting`, `down` |
| `local_ts` | string | Local traffic selector (subnet) |
| `remote_ts` | string | Remote traffic selector (subnet) |
| `rx_bytes` | int | Received bytes |
| `tx_bytes` | int | Transmitted bytes |
| `established_at` | string or None | Establishment timestamp |

**API:** `GET /api/ipsec/sessions/search`

---

### `opnsense__vpn__list_openvpn_instances`

List all OpenVPN instances with status and connected clients.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all OpenVPN instances |

**Returns:** `list[dict]` -- OpenVPN instances

Each instance includes:

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | Instance UUID |
| `description` | string | Instance description |
| `role` | string | `server` or `client` |
| `dev_type` | string | Device type (e.g., `tun`, `tap`) |
| `protocol` | string | Protocol (e.g., `UDP`, `TCP`) |
| `port` | int | Listening port |
| `enabled` | bool | Whether the instance is enabled |
| `connected_clients` | int or None | Number of connected clients (server mode) |

**API:** `GET /api/openvpn/instances/search`

---

### `opnsense__vpn__list_wireguard_peers`

List all WireGuard peers with handshake and traffic data.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all WireGuard peers |

**Returns:** `list[dict]` -- WireGuard peers

Each peer includes:

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | Peer UUID |
| `name` | string | Peer name |
| `public_key` | string | Peer public key |
| `endpoint` | string or None | Peer endpoint (IP:port) |
| `allowed_ips` | list[string] | Allowed IP ranges |
| `last_handshake` | string or None | Last handshake timestamp |
| `rx_bytes` | int or None | Received bytes |
| `tx_bytes` | int or None | Transmitted bytes |

**API:** `GET /api/wireguard/client/search`

---

### `opnsense__vpn__get_vpn_status`

Get aggregate VPN status across all protocols.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Returns aggregate VPN status |

**Returns:** `dict` -- VPN status summary

| Field | Type | Description |
|-------|------|-------------|
| `ipsec` | dict | `{up: int, down: int}` -- IPSec SA counts |
| `openvpn` | dict | `{instances: list}` -- OpenVPN instance summaries |
| `wireguard` | dict | `{peers: list}` -- WireGuard peer summaries |

---

## security

IDS/IPS (Suricata) and certificate management. Four tools covering alert queries, rule management, policy configuration, and certificate trust.

### `opnsense__security__get_ids_alerts`

Query IDS/IPS alerts from Suricata, optionally filtered by time window and severity.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `hours` | int | `24` | Number of hours to look back |
| `severity` | string | `"all"` | Filter: `"high"`, `"medium"`, `"low"`, or `"all"` |

**Returns:** `list[dict]` -- IDS alerts

Each alert includes:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | Alert timestamp |
| `signature` | string | IDS rule signature |
| `category` | string | Alert category (e.g., `ET SCAN`, `ET POLICY`) |
| `severity` | string | Severity level |
| `src_ip` | string | Source IP address |
| `dst_ip` | string | Destination IP address |
| `proto` | string | Network protocol |
| `action` | string | Action taken: `alert` or `drop` |

**API:** `GET /api/ids/service/queryAlerts`

---

### `opnsense__security__get_ids_rules`

List IDS/IPS rules, optionally filtered by category or keyword.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filter` | string | None | Filter string for rule search |

**Returns:** `list[dict]` -- IDS rules

Each rule includes:

| Field | Type | Description |
|-------|------|-------------|
| `sid` | int | Signature ID |
| `msg` | string | Rule message/description |
| `category` | string | Rule category |
| `enabled` | bool | Whether the rule is enabled |
| `action` | string | Rule action: `alert` or `drop` |

**API:** `GET /api/ids/rule/searchRule`

---

### `opnsense__security__get_ids_policy`

Get the current IDS/IPS (Suricata) policy configuration.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Returns current IDS policy |

**Returns:** `dict` -- IDS policy

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | bool | Whether IDS/IPS is enabled |
| `interfaces` | list[string] | Interfaces with IDS inspection |
| `block_mode` | bool | Whether blocking (IPS) mode is active |
| `alert_only_mode` | bool | Whether alert-only (IDS) mode is active |
| `ruleset_count` | int | Number of loaded rulesets |
| `last_update` | string | Last ruleset update timestamp |

**API:** `GET /api/ids/settings/getSettings`

---

### `opnsense__security__get_certificates`

List all certificates in the trust store with expiry status.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all certificates |

**Returns:** `list[dict]` -- certificate inventory

Each certificate includes:

| Field | Type | Description |
|-------|------|-------------|
| `cn` | string | Common Name |
| `san` | list[string] | Subject Alternative Names |
| `issuer` | string | Certificate issuer |
| `not_before` | string | Valid from date |
| `not_after` | string | Expiry date |
| `days_until_expiry` | int | Days until certificate expires |
| `in_use_for` | list[string] | Services using this certificate (e.g., `OpenVPN`, `Web UI`) |

**API:** `GET /api/trust/cert/search`

---

## services

DNS, DHCP, and traffic shaping services. Six tools covering Unbound DNS, Kea DHCP leases, and traffic shaper configuration.

### `opnsense__services__get_dns_overrides`

List all Unbound DNS host overrides.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all host overrides |

**Returns:** `list[dict]` -- DNS host overrides

Each override includes:

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | Override UUID |
| `hostname` | string | Hostname (e.g., `nas`) |
| `domain` | string | Domain (e.g., `home.local`) |
| `ip` | string | IP address to resolve to |
| `description` | string | Override description |

**API:** `GET /api/unbound/host/searchHost`

---

### `opnsense__services__get_dns_forwarders`

List all DNS forwarder configurations.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all forwarders |

**Returns:** `list[dict]` -- DNS forwarders

Each forwarder includes:

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | Forwarder UUID |
| `server` | string | DNS server address |
| `port` | int | DNS server port |
| `domain` | string or None | Domain restriction (if any) |
| `dot_enabled` | bool | Whether DNS-over-TLS is enabled |

**API:** `GET /api/unbound/forward/searchForward`

---

### `opnsense__services__resolve_hostname`

Resolve a hostname using Unbound to verify DNS is working correctly.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `hostname` | string | *required* | Hostname to resolve |

**Returns:** `dict` -- resolution result

| Field | Type | Description |
|-------|------|-------------|
| `hostname` | string | Queried hostname |
| `ip` | string | Resolved IP address |
| `ttl` | int | Time-to-live in seconds |
| `source` | string | Resolution source (e.g., `local override`, `forwarded`) |

**API:** `GET /api/unbound/diagnostics/lookup/{hostname}`

---

### `opnsense__services__add_dns_override` (write)

Create a new DNS host override in Unbound.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `hostname` | string | *required* | Hostname |
| `domain` | string | *required* | Domain |
| `ip` | string | *required* | IP address to resolve to |
| `description` | string | None | Override description |

**Write safety:** Requires `OPNSENSE_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict` -- `{uuid}`

**Reconfigure:** `POST /api/unbound/service/reconfigure`

---

### `opnsense__services__get_dhcp_leases4`

List active DHCPv4 leases (Kea), optionally filtered by interface.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interface` | string | None | Filter leases by interface |

**Returns:** `list[dict]` -- active DHCP leases

Each lease includes:

| Field | Type | Description |
|-------|------|-------------|
| `mac` | string | Client MAC address |
| `ip` | string | Leased IP address |
| `hostname` | string or None | Client hostname |
| `expiry` | string | Lease expiry timestamp |
| `state` | string | Lease state |

**API:** `GET /api/kea/leases4/search`

---

### `opnsense__services__get_traffic_shaper`

Get the current traffic shaping configuration -- pipes, queues, and their settings.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Returns traffic shaper configuration |

**Returns:** `dict` -- traffic shaper settings

| Field | Type | Description |
|-------|------|-------------|
| `pipes` | list[dict] | Shaper pipes with bandwidth, burst, delay |
| `queues` | list[dict] | Shaper queues with pipe, weight, mask |

Each pipe:

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | Pipe UUID |
| `bandwidth` | string | Bandwidth limit (e.g., `100Mbit`) |
| `burst` | string | Burst size |
| `delay` | int | Delay in milliseconds |
| `description` | string | Pipe description |

Each queue:

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | Queue UUID |
| `pipe` | string | Associated pipe UUID |
| `weight` | int | Queue weight |
| `mask` | string | Queue mask |
| `description` | string | Queue description |

**API:** `GET /api/trafficshaper/settings/getSettings`

---

## diagnostics

Live diagnostic tools. Five tools covering ping, traceroute, host discovery, LLDP neighbor discovery, and DNS lookup.

### `opnsense__diagnostics__run_ping`

Ping a host from the OPNsense instance.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | string | *required* | Target hostname or IP address |
| `count` | int | `5` | Number of ping packets |
| `source_ip` | string | None | Source IP for the ping |

**Returns:** `dict` -- ping results

| Field | Type | Description |
|-------|------|-------------|
| `host` | string | Target host |
| `packets_sent` | int | Number of packets sent |
| `packets_recv` | int | Number of packets received |
| `loss_pct` | float | Packet loss percentage |
| `rtt_avg_ms` | float | Average round-trip time in milliseconds |
| `output` | string | Raw ping output |

**API:** `POST /api/diagnostics/interface/getPing`

---

### `opnsense__diagnostics__run_traceroute`

Run a traceroute from the OPNsense instance to a target host.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | string | *required* | Target hostname or IP address |
| `max_hops` | int | `30` | Maximum number of hops |

**Returns:** `dict` -- traceroute results

| Field | Type | Description |
|-------|------|-------------|
| `host` | string | Target host |
| `hops` | list[dict] | Traceroute hops |

Each hop:

| Field | Type | Description |
|-------|------|-------------|
| `hop` | int | Hop number |
| `ip` | string | Hop IP address |
| `hostname` | string or None | Hop hostname (if resolvable) |
| `rtt_ms` | float | Round-trip time in milliseconds |

**API:** `POST /api/diagnostics/interface/getTrace`

---

### `opnsense__diagnostics__run_host_discovery`

Run an ARP/NDP host discovery scan on an interface.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interface` | string | *required* | Interface to scan |

**Returns:** `list[dict]` -- discovered hosts

Each host includes:

| Field | Type | Description |
|-------|------|-------------|
| `ip` | string | Discovered IP address |
| `mac` | string | MAC address |
| `hostname` | string or None | Hostname (if resolvable) |
| `last_seen` | string | Last seen timestamp |

**Note:** Discovery scans run asynchronously. The tool starts the scan and polls for results.

**API:** `POST /api/hostdiscovery/scan/start` + `GET /api/hostdiscovery/scan/result`

---

### `opnsense__diagnostics__get_lldp_neighbors`

Get LLDP neighbor table showing what devices are connected to each port.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interface` | string | None | Filter to a specific interface |

**Returns:** `list[dict]` -- LLDP neighbors

Each neighbor includes:

| Field | Type | Description |
|-------|------|-------------|
| `local_port` | string | Local interface name |
| `neighbor_system` | string | Neighbor system name |
| `neighbor_port` | string | Neighbor port identifier |
| `neighbor_ip` | string or None | Neighbor management IP |
| `neighbor_capabilities` | string | Neighbor capabilities (e.g., `Bridge, Router`) |
| `ttl` | int | Time-to-live in seconds |

**API:** `GET /api/diagnostics/interface/getLldpNeighbors`

!!! tip "Physical topology verification"
    LLDP neighbor data is essential for verifying physical topology and
    identifying which device is connected to each port. Use this tool
    during port assignment workflows to confirm cabling before making changes.

---

### `opnsense__diagnostics__dns_lookup`

Perform a DNS lookup from the OPNsense instance.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `hostname` | string | *required* | Hostname to look up |
| `record_type` | string | `"A"` | DNS record type (e.g., `A`, `AAAA`, `MX`, `PTR`) |

**Returns:** `list[dict]` -- DNS records

Each record includes:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Queried name |
| `type` | string | Record type |
| `value` | string | Record value |
| `ttl` | int | Time-to-live in seconds |

**API:** `GET /api/diagnostics/dns/reverseResolve`

---

## firmware

Firmware and package management. Two read-only tools for checking version status and listing installed packages.

### `opnsense__firmware__get_status`

Get the current firmware version and check for available upgrades.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Checks firmware status |

**Returns:** `dict` -- firmware status

| Field | Type | Description |
|-------|------|-------------|
| `current_version` | string | Currently installed OPNsense version |
| `latest_version` | string | Latest available version |
| `upgrade_available` | bool | Whether an upgrade is available |
| `last_check` | string | Timestamp of last update check |
| `changelog_url` | string or None | URL to the changelog for the available upgrade |

**API:** `GET /api/core/firmware/status`

---

### `opnsense__firmware__list_packages`

List all installed packages with version and update status.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Lists all packages |

**Returns:** `list[dict]` -- package inventory

Each package includes:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Package name |
| `version` | string | Installed version |
| `latest_version` | string | Latest available version |
| `needs_update` | bool | Whether an update is available |
| `description` | string | Package description |

**API:** `GET /api/core/firmware/info`
