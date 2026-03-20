# Abstract Data Model

The Netex abstract data model provides vendor-neutral representations of common network concepts. When netex queries data from vendor plugins, it maps vendor-specific API responses to these models, enabling cross-vendor comparison, reporting, and orchestration.

## Model Hierarchy

```
VLAN(vlan_id, name, subnet, dhcp_enabled)
FirewallPolicy(src_zone, dst_zone, protocol, action)
Route(destination, gateway, metric)
VPNTunnel(type, peer, status, rx_bytes, tx_bytes)
DNSRecord(hostname, domain, ip, ttl)
DHCPLease(mac, ip, hostname, expiry, interface)
NetworkTopology(nodes[], links[], vlans[])
```

## VLAN

The most commonly used model. Represents an 802.1Q VLAN across vendor boundaries.

| Field | Type | Description |
|---|---|---|
| `vlan_id` | int | 802.1Q VLAN ID (1-4094) |
| `name` | str | Human-readable VLAN name |
| `subnet` | str | CIDR notation (e.g. 10.50.0.0/24) |
| `dhcp_enabled` | bool | Whether DHCP is enabled |
| `source_plugin` | str | Plugin that provided this data |

### Vendor Mapping

| Field | OPNsense API | UniFi API |
|---|---|---|
| vlan_id | `vlan` or `vlanid` | `vlan_id` or `vlan` |
| name | `descr` or `description` | `name` |
| subnet | `subnet` | `ip_subnet` or `subnet` |
| dhcp_enabled | `dhcp_enabled` | `dhcpd_enabled` |

## FirewallPolicy

Represents a firewall rule in vendor-neutral terms.

| Field | Type | Description |
|---|---|---|
| `rule_id` | str | Vendor-specific rule identifier |
| `src_zone` | str | Source zone or interface |
| `dst_zone` | str | Destination zone or interface |
| `protocol` | str | Protocol (tcp, udp, icmp, any) |
| `src_address` | str | Source address or network |
| `dst_address` | str | Destination address or network |
| `action` | FirewallAction | allow, deny, reject, log |
| `enabled` | bool | Whether the rule is active |
| `sequence` | int | Rule evaluation order |

### FirewallAction Enum

- `allow` -- Pass traffic (OPNsense: "pass")
- `deny` -- Silently drop traffic (OPNsense: "block")
- `reject` -- Drop with ICMP response (OPNsense: "reject")
- `log` -- Log and pass (for audit rules)

## Route

Represents a static route entry.

| Field | Type | Description |
|---|---|---|
| `destination` | str | Destination network in CIDR |
| `gateway` | str | Next-hop gateway IP |
| `metric` | int | Route metric / priority |
| `interface` | str | Outbound interface |
| `enabled` | bool | Whether the route is active |

## VPNTunnel

Represents a VPN tunnel or peer.

| Field | Type | Description |
|---|---|---|
| `tunnel_type` | VPNType | ipsec, openvpn, wireguard, tailscale |
| `peer` | str | Remote peer identifier |
| `status` | VPNStatus | up, down, connecting, error |
| `rx_bytes` | int | Received bytes |
| `tx_bytes` | int | Transmitted bytes |
| `uptime_seconds` | int | Tunnel uptime |

## DNSRecord

Represents a DNS record (e.g., Unbound host override).

| Field | Type | Description |
|---|---|---|
| `hostname` | str | Host name (e.g., "nas") |
| `domain` | str | Domain name (e.g., "home.lan") |
| `ip` | str | Resolved IP address |
| `record_type` | str | A, AAAA, CNAME, etc. |
| `ttl` | int | Time-to-live in seconds |

## DHCPLease

Represents a DHCP lease record.

| Field | Type | Description |
|---|---|---|
| `mac` | str | Client MAC address |
| `ip` | str | Assigned IP address |
| `hostname` | str | Client-reported hostname |
| `expiry` | datetime | Lease expiration |
| `interface` | str | Serving interface |
| `lease_type` | str | dynamic or static |

## NetworkTopology

A unified topology assembled from all installed plugins.

| Field | Type | Description |
|---|---|---|
| `nodes` | list[TopologyNode] | Network nodes (gateway, switch, AP, client) |
| `links` | list[TopologyLink] | Links between nodes |
| `vlans` | list[VLAN] | VLANs discovered across plugins |
| `source_plugins` | list[str] | Plugins that contributed data |

The topology supports merging: `topology_a.merge(topology_b)` combines nodes and links from both, deduplicating by node ID.

## from_vendor Pattern

Every model provides a `from_vendor(vendor_name, raw_data)` class method for mapping vendor-specific API data:

```python
# OPNsense VLAN interface response -> abstract VLAN
vlan = VLAN.from_vendor("opnsense", {
    "vlan": 50,
    "descr": "Guest",
    "subnet": "10.50.0.0/24",
    "dhcp_enabled": True,
})

# UniFi network response -> abstract VLAN
vlan = VLAN.from_vendor("unifi", {
    "vlan_id": 50,
    "name": "Guest",
    "ip_subnet": "10.50.0.0/24",
    "dhcpd_enabled": True,
})
```

Both produce the same abstract VLAN, enabling direct comparison regardless of source vendor.
