"""Vendor-neutral abstract data model for cross-vendor network operations.

When working across vendor plugins, use these vendor-neutral concepts.
Each concept maps to vendor-specific data at query time via the registry.

Model hierarchy (from PRD Appendix C.6):

    VLAN(id, name, subnet, dhcp_enabled)
    FirewallPolicy(src_zone, dst_zone, protocol, action)
    Route(destination, gateway, metric)
    VPNTunnel(type, peer, status, rx_bytes, tx_bytes)
    DNSRecord(hostname, domain, ip, ttl)
    DHCPLease(mac, ip, hostname, expiry, interface)
    NetworkTopology(nodes[], links[], vlans[])
    DNSProfile(id, name, vendor, security/privacy/logging state)
    DNSForwarderMapping(vlan_name, vlan_id, subnet, forwarder_target)
    DNSAnalyticsSummary(profile_id, query counts, top blocked)

Each model has a ``from_vendor(vendor_name, raw_data)`` class method for
mapping vendor-specific API data to the abstract representation.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FirewallAction(StrEnum):
    """Firewall rule action."""

    ALLOW = "allow"
    DENY = "deny"
    REJECT = "reject"
    LOG = "log"


class VPNType(StrEnum):
    """VPN tunnel type."""

    IPSEC = "ipsec"
    OPENVPN = "openvpn"
    WIREGUARD = "wireguard"
    TAILSCALE = "tailscale"


class VPNStatus(StrEnum):
    """VPN tunnel operational status."""

    UP = "up"
    DOWN = "down"
    CONNECTING = "connecting"
    ERROR = "error"


class TopologyNodeType(StrEnum):
    """Type of node in the network topology."""

    GATEWAY = "gateway"
    SWITCH = "switch"
    ACCESS_POINT = "access_point"
    CLIENT = "client"
    WAN = "wan"


# ---------------------------------------------------------------------------
# VLAN
# ---------------------------------------------------------------------------


class VLAN(BaseModel):
    """Vendor-neutral VLAN representation.

    Maps to:
        gateway plugin: VLAN interface + DHCP scope
        edge plugin: Network object + switch port profiles + SSID bindings
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    vlan_id: int = Field(description="802.1Q VLAN ID (1-4094)")
    name: str = Field(description="Human-readable VLAN name")
    subnet: str | None = Field(default=None, description="CIDR notation (e.g. 10.50.0.0/24)")
    dhcp_enabled: bool = Field(default=False, description="Whether DHCP is enabled on this VLAN")
    source_plugin: str = Field(default="", description="Plugin that provided this data")
    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Original vendor-specific data for debugging",
    )

    @classmethod
    def from_vendor(cls, vendor_name: str, raw_data: dict[str, Any]) -> VLAN:
        """Create a VLAN from vendor-specific API data.

        Parameters
        ----------
        vendor_name:
            Name of the vendor plugin (e.g. ``"unifi"``, ``"opnsense"``).
        raw_data:
            Raw API response data from the vendor plugin.

        Returns
        -------
        VLAN
            Vendor-neutral VLAN representation.
        """
        if vendor_name == "opnsense":
            return cls(
                vlan_id=int(raw_data.get("vlan", raw_data.get("vlanid", 0))),
                name=raw_data.get("descr", raw_data.get("description", "")),
                subnet=raw_data.get("subnet"),
                dhcp_enabled=raw_data.get("dhcp_enabled", False),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )
        elif vendor_name == "unifi":
            return cls(
                vlan_id=int(raw_data.get("vlan_id", raw_data.get("vlan", 0))),
                name=raw_data.get("name", ""),
                subnet=raw_data.get("ip_subnet", raw_data.get("subnet")),
                dhcp_enabled=raw_data.get("dhcpd_enabled", raw_data.get("dhcp_enabled", False)),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )
        else:
            # Generic fallback -- best effort mapping
            return cls(
                vlan_id=int(raw_data.get("vlan_id", raw_data.get("id", 0))),
                name=raw_data.get("name", ""),
                subnet=raw_data.get("subnet"),
                dhcp_enabled=raw_data.get("dhcp_enabled", False),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )


# ---------------------------------------------------------------------------
# FirewallPolicy
# ---------------------------------------------------------------------------


class FirewallPolicy(BaseModel):
    """Vendor-neutral firewall policy / rule representation.

    Maps to:
        gateway plugin: Firewall filter rule with interface scope
        edge plugin: ZBF zone policy or ACL rule
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    rule_id: str = Field(default="", description="Vendor-specific rule identifier")
    src_zone: str = Field(description="Source zone or interface")
    dst_zone: str = Field(description="Destination zone or interface")
    protocol: str = Field(default="any", description="Protocol (tcp, udp, icmp, any)")
    src_address: str = Field(default="any", description="Source address or network")
    dst_address: str = Field(default="any", description="Destination address or network")
    src_port: str = Field(default="any", description="Source port(s)")
    dst_port: str = Field(default="any", description="Destination port(s)")
    action: FirewallAction = Field(description="Rule action (allow, deny, reject, log)")
    enabled: bool = Field(default=True, description="Whether this rule is active")
    description: str = Field(default="", description="Rule description")
    sequence: int = Field(default=0, description="Rule evaluation order")
    source_plugin: str = Field(default="", description="Plugin that provided this data")
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_vendor(cls, vendor_name: str, raw_data: dict[str, Any]) -> FirewallPolicy:
        """Create a FirewallPolicy from vendor-specific API data."""
        if vendor_name == "opnsense":
            action_map = {
                "pass": FirewallAction.ALLOW,
                "block": FirewallAction.DENY,
                "reject": FirewallAction.REJECT,
            }
            return cls(
                rule_id=raw_data.get("uuid", ""),
                src_zone=raw_data.get("interface", ""),
                dst_zone=raw_data.get("destination", {}).get("network", "any"),
                protocol=raw_data.get("protocol", "any"),
                src_address=raw_data.get("source", {}).get("network", "any"),
                dst_address=raw_data.get("destination", {}).get("network", "any"),
                src_port=raw_data.get("source", {}).get("port", "any"),
                dst_port=raw_data.get("destination", {}).get("port", "any"),
                action=action_map.get(raw_data.get("type", "pass"), FirewallAction.ALLOW),
                enabled=raw_data.get("enabled", "1") == "1",
                description=raw_data.get("descr", ""),
                sequence=int(raw_data.get("sequence", 0)),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )
        elif vendor_name == "unifi":
            return cls(
                rule_id=raw_data.get("_id", ""),
                src_zone=raw_data.get("src_zone", raw_data.get("source_zone", "")),
                dst_zone=raw_data.get("dst_zone", raw_data.get("destination_zone", "")),
                protocol=raw_data.get("protocol", "any"),
                src_address=raw_data.get("src_address", "any"),
                dst_address=raw_data.get("dst_address", "any"),
                action=FirewallAction(raw_data.get("action", "allow")),
                enabled=raw_data.get("enabled", True),
                description=raw_data.get("name", raw_data.get("description", "")),
                sequence=int(raw_data.get("rule_index", 0)),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )
        else:
            return cls(
                rule_id=raw_data.get("id", ""),
                src_zone=raw_data.get("src_zone", ""),
                dst_zone=raw_data.get("dst_zone", ""),
                protocol=raw_data.get("protocol", "any"),
                action=FirewallAction(raw_data.get("action", "allow")),
                description=raw_data.get("description", ""),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


class Route(BaseModel):
    """Vendor-neutral static route representation.

    Maps to:
        gateway plugin: Static route entry
        edge plugin: Not applicable (UniFi does not manage routing)
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    destination: str = Field(description="Destination network in CIDR notation")
    gateway: str = Field(description="Next-hop gateway IP address")
    metric: int = Field(default=0, description="Route metric / priority")
    interface: str = Field(default="", description="Outbound interface")
    enabled: bool = Field(default=True, description="Whether this route is active")
    description: str = Field(default="", description="Route description")
    source_plugin: str = Field(default="", description="Plugin that provided this data")
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_vendor(cls, vendor_name: str, raw_data: dict[str, Any]) -> Route:
        """Create a Route from vendor-specific API data."""
        if vendor_name == "opnsense":
            return cls(
                destination=raw_data.get("network", ""),
                gateway=raw_data.get("gateway", ""),
                metric=int(raw_data.get("weight", raw_data.get("metric", 0))),
                interface=raw_data.get("interface", ""),
                enabled=raw_data.get("disabled", "0") != "1",
                description=raw_data.get("descr", ""),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )
        else:
            return cls(
                destination=raw_data.get("destination", raw_data.get("network", "")),
                gateway=raw_data.get("gateway", raw_data.get("next_hop", "")),
                metric=int(raw_data.get("metric", 0)),
                interface=raw_data.get("interface", ""),
                enabled=raw_data.get("enabled", True),
                description=raw_data.get("description", ""),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )


# ---------------------------------------------------------------------------
# VPNTunnel
# ---------------------------------------------------------------------------


class VPNTunnel(BaseModel):
    """Vendor-neutral VPN tunnel representation.

    Maps to:
        gateway plugin: IPSec SA / OpenVPN instance / WireGuard peer
        overlay plugin: Tailscale device peer (future)
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    tunnel_type: VPNType = Field(description="VPN technology type")
    peer: str = Field(description="Remote peer identifier (IP, hostname, or public key)")
    status: VPNStatus = Field(description="Current tunnel operational status")
    local_address: str = Field(default="", description="Local tunnel endpoint address")
    remote_address: str = Field(default="", description="Remote tunnel endpoint address")
    rx_bytes: int = Field(default=0, description="Bytes received through tunnel")
    tx_bytes: int = Field(default=0, description="Bytes transmitted through tunnel")
    uptime_seconds: int = Field(default=0, description="Tunnel uptime in seconds")
    description: str = Field(default="", description="Tunnel description")
    source_plugin: str = Field(default="", description="Plugin that provided this data")
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_vendor(cls, vendor_name: str, raw_data: dict[str, Any]) -> VPNTunnel:
        """Create a VPNTunnel from vendor-specific API data."""
        if vendor_name == "opnsense":
            # Determine VPN type from raw data
            vpn_type = VPNType.IPSEC
            if raw_data.get("type") == "wireguard":
                vpn_type = VPNType.WIREGUARD
            elif raw_data.get("type") == "openvpn":
                vpn_type = VPNType.OPENVPN

            # Map status
            status_str = raw_data.get("status", "down").lower()
            status_map = {
                "associated": VPNStatus.UP,
                "connected": VPNStatus.UP,
                "up": VPNStatus.UP,
                "down": VPNStatus.DOWN,
            }
            status = status_map.get(status_str, VPNStatus.DOWN)

            return cls(
                tunnel_type=vpn_type,
                peer=raw_data.get("remote-peer", raw_data.get("peer", "")),
                status=status,
                local_address=raw_data.get("local", ""),
                remote_address=raw_data.get("remote", ""),
                rx_bytes=int(raw_data.get("bytes-in", raw_data.get("rx_bytes", 0))),
                tx_bytes=int(raw_data.get("bytes-out", raw_data.get("tx_bytes", 0))),
                description=raw_data.get("description", raw_data.get("descr", "")),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )
        else:
            return cls(
                tunnel_type=VPNType(raw_data.get("type", "ipsec")),
                peer=raw_data.get("peer", ""),
                status=VPNStatus(raw_data.get("status", "down")),
                rx_bytes=int(raw_data.get("rx_bytes", 0)),
                tx_bytes=int(raw_data.get("tx_bytes", 0)),
                description=raw_data.get("description", ""),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )


# ---------------------------------------------------------------------------
# DNSRecord
# ---------------------------------------------------------------------------


class DNSRecord(BaseModel):
    """Vendor-neutral DNS record representation.

    Maps to:
        gateway plugin: Unbound host override
        edge plugin: Not applicable
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    hostname: str = Field(description="Host name (e.g. 'nas')")
    domain: str = Field(default="", description="Domain name (e.g. 'home.lan')")
    ip: str = Field(description="IP address the record resolves to")
    record_type: str = Field(default="A", description="DNS record type (A, AAAA, CNAME, etc.)")
    ttl: int = Field(default=3600, description="Time-to-live in seconds")
    description: str = Field(default="", description="Record description")
    source_plugin: str = Field(default="", description="Plugin that provided this data")
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_vendor(cls, vendor_name: str, raw_data: dict[str, Any]) -> DNSRecord:
        """Create a DNSRecord from vendor-specific API data."""
        if vendor_name == "opnsense":
            return cls(
                hostname=raw_data.get("hostname", raw_data.get("host", "")),
                domain=raw_data.get("domain", ""),
                ip=raw_data.get("server", raw_data.get("ip", "")),
                record_type=raw_data.get("rr", "A"),
                ttl=int(raw_data.get("ttl", 3600)),
                description=raw_data.get("descr", raw_data.get("description", "")),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )
        else:
            return cls(
                hostname=raw_data.get("hostname", ""),
                domain=raw_data.get("domain", ""),
                ip=raw_data.get("ip", raw_data.get("address", "")),
                record_type=raw_data.get("type", raw_data.get("record_type", "A")),
                ttl=int(raw_data.get("ttl", 3600)),
                description=raw_data.get("description", ""),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )


# ---------------------------------------------------------------------------
# DHCPLease
# ---------------------------------------------------------------------------


class DHCPLease(BaseModel):
    """Vendor-neutral DHCP lease representation.

    Maps to:
        gateway plugin: Kea lease record
        edge plugin: Client station record (IP/MAC correlation)
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    mac: str = Field(description="Client MAC address")
    ip: str = Field(description="Assigned IP address")
    hostname: str = Field(default="", description="Client-reported hostname")
    expiry: datetime | None = Field(default=None, description="Lease expiration time")
    interface: str = Field(default="", description="Server interface serving this lease")
    lease_type: str = Field(default="dynamic", description="Lease type (dynamic, static)")
    source_plugin: str = Field(default="", description="Plugin that provided this data")
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_vendor(cls, vendor_name: str, raw_data: dict[str, Any]) -> DHCPLease:
        """Create a DHCPLease from vendor-specific API data."""
        if vendor_name == "opnsense":
            expiry = raw_data.get("ends")
            if isinstance(expiry, str) and expiry:
                try:
                    expiry = datetime.fromisoformat(expiry)
                except ValueError:
                    expiry = None
            elif not isinstance(expiry, datetime):
                expiry = None

            return cls(
                mac=raw_data.get("mac", ""),
                ip=raw_data.get("address", raw_data.get("ip", "")),
                hostname=raw_data.get("hostname", ""),
                expiry=expiry,
                interface=raw_data.get("if", raw_data.get("interface", "")),
                lease_type=raw_data.get("type", "dynamic"),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )
        elif vendor_name == "unifi":
            return cls(
                mac=raw_data.get("mac", ""),
                ip=raw_data.get("ip", raw_data.get("fixed_ip", "")),
                hostname=raw_data.get("hostname", raw_data.get("name", "")),
                expiry=None,  # UniFi client records don't expose DHCP expiry
                interface=raw_data.get("network", ""),
                lease_type="dynamic",
                source_plugin=vendor_name,
                raw_data=raw_data,
            )
        else:
            return cls(
                mac=raw_data.get("mac", ""),
                ip=raw_data.get("ip", ""),
                hostname=raw_data.get("hostname", ""),
                interface=raw_data.get("interface", ""),
                source_plugin=vendor_name,
                raw_data=raw_data,
            )


# ---------------------------------------------------------------------------
# Network Topology
# ---------------------------------------------------------------------------


class TopologyNode(BaseModel):
    """A single node in the network topology graph."""

    model_config = ConfigDict(strict=True, populate_by_name=True)

    node_id: str = Field(description="Unique node identifier")
    name: str = Field(default="", description="Human-readable node name")
    node_type: TopologyNodeType = Field(description="Type of network node")
    ip: str = Field(default="", description="Management or primary IP address")
    mac: str = Field(default="", description="MAC address")
    source_plugin: str = Field(default="", description="Plugin that provided this data")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional vendor-specific metadata",
    )


class TopologyLink(BaseModel):
    """A link between two nodes in the network topology."""

    model_config = ConfigDict(strict=True, populate_by_name=True)

    source_id: str = Field(description="Source node identifier")
    target_id: str = Field(description="Target node identifier")
    link_type: str = Field(default="ethernet", description="Link type (ethernet, wireless, vpn)")
    speed_mbps: int | None = Field(default=None, description="Link speed in Mbps")
    source_plugin: str = Field(default="", description="Plugin that provided this data")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional vendor-specific metadata",
    )


class NetworkTopology(BaseModel):
    """Unified network topology assembled from all installed plugins.

    Each plugin contributes its layer:
        gateway layer: interfaces, routes, VPN tunnels, firewall zones
        edge layer: device graph, uplink relationships, wireless APs, clients
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    nodes: list[TopologyNode] = Field(default_factory=list, description="Topology nodes")
    links: list[TopologyLink] = Field(default_factory=list, description="Topology links")
    vlans: list[VLAN] = Field(default_factory=list, description="VLANs discovered across plugins")
    source_plugins: list[str] = Field(
        default_factory=list,
        description="Plugins that contributed data to this topology",
    )

    def merge(self, other: NetworkTopology) -> NetworkTopology:
        """Merge another topology into this one, returning a new instance.

        Nodes and links from both topologies are combined. Duplicate node IDs
        from the ``other`` topology are skipped (first-seen wins).
        """
        existing_node_ids = {n.node_id for n in self.nodes}
        new_nodes = [n for n in other.nodes if n.node_id not in existing_node_ids]

        existing_vlan_ids = {(v.vlan_id, v.source_plugin) for v in self.vlans}
        new_vlans = [
            v for v in other.vlans if (v.vlan_id, v.source_plugin) not in existing_vlan_ids
        ]

        merged_plugins = list(dict.fromkeys(self.source_plugins + other.source_plugins))

        return NetworkTopology(
            nodes=self.nodes + new_nodes,
            links=self.links + other.links,
            vlans=self.vlans + new_vlans,
            source_plugins=merged_plugins,
        )


# ---------------------------------------------------------------------------
# DNS Profile (cross-vendor DNS filtering)
# ---------------------------------------------------------------------------


class DNSProfile(BaseModel):
    """Vendor-neutral DNS filtering profile.

    Maps to:
        dns plugin: NextDNS profile with security/privacy/parental config
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    id: str = Field(description="Profile identifier")
    name: str = Field(description="Human-readable profile name")
    vendor: str = Field(default="", description="DNS vendor (e.g. 'nextdns')")
    security_enabled_count: int = Field(
        default=0,
        description="Number of security toggles currently enabled",
    )
    security_total: int = Field(
        default=12,
        description="Total number of security toggles available",
    )
    blocklist_count: int = Field(
        default=0,
        description="Number of active privacy blocklists",
    )
    denylist_count: int = Field(
        default=0,
        description="Number of custom deny-list entries",
    )
    allowlist_count: int = Field(
        default=0,
        description="Number of custom allow-list entries",
    )
    logging_enabled: bool = Field(
        default=False,
        description="Whether query logging is active",
    )
    parental_control_active: bool = Field(
        default=False,
        description="Whether parental controls are active",
    )

    @classmethod
    def from_vendor(cls, vendor: str, data: dict[str, Any]) -> DNSProfile:
        """Create a DNSProfile from vendor-specific API data.

        Parameters
        ----------
        vendor:
            Vendor identifier (e.g. ``"nextdns"``).
        data:
            Raw profile summary data from the vendor API.

        Returns
        -------
        DNSProfile
            Vendor-neutral DNS profile representation.

        Raises
        ------
        ValueError
            If the vendor is not recognised.
        """
        if vendor == "nextdns":
            return cls(
                id=data.get("id", ""),
                name=data.get("name", ""),
                vendor=vendor,
                security_enabled_count=data.get("security_enabled_count", 0),
                security_total=data.get("security_total", 12),
                blocklist_count=data.get("blocklist_count", 0),
                denylist_count=data.get("denylist_count", 0),
                allowlist_count=data.get("allowlist_count", 0),
                logging_enabled=data.get("logging_enabled", False),
                parental_control_active=data.get("parental_control_active", False),
            )
        raise ValueError(f"Unknown DNS vendor: {vendor}")


# ---------------------------------------------------------------------------
# DNS Forwarder Mapping
# ---------------------------------------------------------------------------


class DNSForwarderMapping(BaseModel):
    """Maps a network subnet/VLAN to an upstream DNS endpoint.

    Used to correlate gateway-layer DNS forwarder configuration (e.g.
    OPNsense Unbound forwarders) with dns-layer profiles (e.g. NextDNS).
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    vlan_name: str = Field(description="Human-readable VLAN name")
    vlan_id: int = Field(description="802.1Q VLAN ID")
    subnet: str = Field(description="CIDR notation (e.g. '10.0.50.0/24')")
    forwarder_target: str = Field(
        description="Upstream DNS endpoint (e.g. 'dns.nextdns.io/abc123')",
    )
    dns_profile_id: str | None = Field(
        default=None,
        description="DNS profile ID extracted from forwarder target, if applicable",
    )
    dns_profile_name: str | None = Field(
        default=None,
        description="DNS profile name, if resolved",
    )

    @property
    def is_nextdns(self) -> bool:
        """Return True if the forwarder target is a NextDNS endpoint."""
        return "nextdns.io" in self.forwarder_target


# ---------------------------------------------------------------------------
# DNS Analytics Summary
# ---------------------------------------------------------------------------


class DNSAnalyticsSummary(BaseModel):
    """Summary of DNS analytics across a single profile.

    Aggregated view of query volume, block rate, and top blocked domains
    for use in cross-vendor security dashboards and audit reports.
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    profile_id: str = Field(description="DNS profile identifier")
    profile_name: str = Field(default="", description="Human-readable profile name")
    total_queries: int = Field(default=0, description="Total DNS queries observed")
    blocked_queries: int = Field(default=0, description="Number of blocked queries")
    allowed_queries: int = Field(default=0, description="Number of allowed queries")
    block_percentage: float = Field(
        default=0.0,
        description="Percentage of queries that were blocked",
    )
    top_blocked_domains: list[str] = Field(
        default_factory=list,
        description="Most frequently blocked domain names",
    )
