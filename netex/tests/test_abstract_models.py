# SPDX-License-Identifier: MIT
"""Tests for the vendor-neutral abstract data model."""

from __future__ import annotations

import pytest

from netex.models.abstract import (
    VLAN,
    DHCPLease,
    DNSAnalyticsSummary,
    DNSForwarderMapping,
    DNSProfile,
    DNSRecord,
    FirewallAction,
    FirewallPolicy,
    NetworkTopology,
    Route,
    TopologyLink,
    TopologyNode,
    TopologyNodeType,
    VPNStatus,
    VPNTunnel,
    VPNType,
)

# ---------------------------------------------------------------------------
# VLAN
# ---------------------------------------------------------------------------


class TestVLAN:
    def test_basic_construction(self) -> None:
        vlan = VLAN(vlan_id=50, name="Guest")
        assert vlan.vlan_id == 50
        assert vlan.name == "Guest"
        assert vlan.subnet is None
        assert vlan.dhcp_enabled is False

    def test_full_construction(self) -> None:
        vlan = VLAN(
            vlan_id=50,
            name="Guest",
            subnet="10.50.0.0/24",
            dhcp_enabled=True,
            source_plugin="opnsense",
        )
        assert vlan.subnet == "10.50.0.0/24"
        assert vlan.dhcp_enabled is True
        assert vlan.source_plugin == "opnsense"

    def test_from_vendor_opnsense(self) -> None:
        raw = {"vlan": 50, "descr": "Guest VLAN", "subnet": "10.50.0.0/24", "dhcp_enabled": True}
        vlan = VLAN.from_vendor("opnsense", raw)
        assert vlan.vlan_id == 50
        assert vlan.name == "Guest VLAN"
        assert vlan.subnet == "10.50.0.0/24"
        assert vlan.dhcp_enabled is True
        assert vlan.source_plugin == "opnsense"

    def test_from_vendor_unifi(self) -> None:
        raw = {"vlan_id": 30, "name": "IoT", "ip_subnet": "10.30.0.0/24", "dhcpd_enabled": True}
        vlan = VLAN.from_vendor("unifi", raw)
        assert vlan.vlan_id == 30
        assert vlan.name == "IoT"
        assert vlan.subnet == "10.30.0.0/24"
        assert vlan.dhcp_enabled is True
        assert vlan.source_plugin == "unifi"

    def test_from_vendor_generic(self) -> None:
        raw = {"id": 10, "name": "Main", "subnet": "10.10.0.0/24"}
        vlan = VLAN.from_vendor("custom", raw)
        assert vlan.vlan_id == 10
        assert vlan.name == "Main"
        assert vlan.source_plugin == "custom"

    def test_serialization_roundtrip(self) -> None:
        vlan = VLAN(vlan_id=50, name="Test", subnet="10.50.0.0/24", dhcp_enabled=True)
        data = vlan.model_dump()
        restored = VLAN.model_validate(data)
        assert restored.vlan_id == vlan.vlan_id
        assert restored.name == vlan.name
        assert restored.subnet == vlan.subnet

    def test_json_roundtrip(self) -> None:
        vlan = VLAN(vlan_id=50, name="Test")
        json_str = vlan.model_dump_json()
        restored = VLAN.model_validate_json(json_str)
        assert restored.vlan_id == 50

    def test_raw_data_preserved(self) -> None:
        raw = {"vlan": 50, "descr": "Guest", "extra_field": "preserved"}
        vlan = VLAN.from_vendor("opnsense", raw)
        assert vlan.raw_data["extra_field"] == "preserved"


# ---------------------------------------------------------------------------
# FirewallPolicy
# ---------------------------------------------------------------------------


class TestFirewallPolicy:
    def test_basic_construction(self) -> None:
        policy = FirewallPolicy(
            src_zone="LAN",
            dst_zone="WAN",
            action=FirewallAction.ALLOW,
        )
        assert policy.src_zone == "LAN"
        assert policy.dst_zone == "WAN"
        assert policy.action == FirewallAction.ALLOW
        assert policy.protocol == "any"

    def test_from_vendor_opnsense(self) -> None:
        raw = {
            "uuid": "abc-123",
            "interface": "opt1",
            "type": "pass",
            "source": {"network": "10.50.0.0/24"},
            "destination": {"network": "any"},
            "protocol": "tcp",
            "enabled": "1",
            "descr": "Allow guest outbound",
            "sequence": 10,
        }
        policy = FirewallPolicy.from_vendor("opnsense", raw)
        assert policy.rule_id == "abc-123"
        assert policy.src_zone == "opt1"
        assert policy.action == FirewallAction.ALLOW
        assert policy.protocol == "tcp"
        assert policy.enabled is True
        assert policy.sequence == 10
        assert policy.source_plugin == "opnsense"

    def test_from_vendor_opnsense_block(self) -> None:
        raw = {"type": "block", "interface": "wan", "source": {}, "destination": {}}
        policy = FirewallPolicy.from_vendor("opnsense", raw)
        assert policy.action == FirewallAction.DENY

    def test_from_vendor_unifi(self) -> None:
        raw = {
            "_id": "uni-456",
            "src_zone": "IoT",
            "dst_zone": "LAN",
            "action": "deny",
            "name": "Block IoT to LAN",
            "enabled": True,
        }
        policy = FirewallPolicy.from_vendor("unifi", raw)
        assert policy.rule_id == "uni-456"
        assert policy.action == FirewallAction.DENY
        assert policy.description == "Block IoT to LAN"
        assert policy.source_plugin == "unifi"

    def test_serialization_roundtrip(self) -> None:
        policy = FirewallPolicy(
            src_zone="LAN",
            dst_zone="WAN",
            action=FirewallAction.ALLOW,
            protocol="tcp",
        )
        data = policy.model_dump()
        restored = FirewallPolicy.model_validate(data)
        assert restored.action == FirewallAction.ALLOW


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


class TestRoute:
    def test_basic_construction(self) -> None:
        route = Route(destination="10.0.0.0/8", gateway="192.168.1.1")
        assert route.destination == "10.0.0.0/8"
        assert route.gateway == "192.168.1.1"
        assert route.metric == 0

    def test_from_vendor_opnsense(self) -> None:
        raw = {
            "network": "10.20.0.0/24",
            "gateway": "192.168.1.1",
            "weight": 100,
            "interface": "igb0",
            "disabled": "0",
            "descr": "Site-to-site route",
        }
        route = Route.from_vendor("opnsense", raw)
        assert route.destination == "10.20.0.0/24"
        assert route.gateway == "192.168.1.1"
        assert route.metric == 100
        assert route.enabled is True
        assert route.source_plugin == "opnsense"

    def test_from_vendor_opnsense_disabled(self) -> None:
        raw = {"network": "10.0.0.0/8", "gateway": "0.0.0.0", "disabled": "1"}
        route = Route.from_vendor("opnsense", raw)
        assert route.enabled is False

    def test_from_vendor_generic(self) -> None:
        raw = {"destination": "0.0.0.0/0", "next_hop": "10.0.0.1", "metric": 50}
        route = Route.from_vendor("custom", raw)
        assert route.destination == "0.0.0.0/0"
        assert route.gateway == "10.0.0.1"
        assert route.metric == 50

    def test_serialization_roundtrip(self) -> None:
        route = Route(destination="10.0.0.0/8", gateway="192.168.1.1", metric=100)
        data = route.model_dump()
        restored = Route.model_validate(data)
        assert restored.metric == 100


# ---------------------------------------------------------------------------
# VPNTunnel
# ---------------------------------------------------------------------------


class TestVPNTunnel:
    def test_basic_construction(self) -> None:
        tunnel = VPNTunnel(
            tunnel_type=VPNType.WIREGUARD,
            peer="peer-key-123",
            status=VPNStatus.UP,
        )
        assert tunnel.tunnel_type == VPNType.WIREGUARD
        assert tunnel.peer == "peer-key-123"
        assert tunnel.status == VPNStatus.UP

    def test_from_vendor_opnsense_ipsec(self) -> None:
        raw = {
            "remote-peer": "203.0.113.1",
            "status": "associated",
            "bytes-in": 1000,
            "bytes-out": 2000,
            "description": "Site-to-site IPSec",
        }
        tunnel = VPNTunnel.from_vendor("opnsense", raw)
        assert tunnel.tunnel_type == VPNType.IPSEC
        assert tunnel.peer == "203.0.113.1"
        assert tunnel.status == VPNStatus.UP
        assert tunnel.rx_bytes == 1000
        assert tunnel.tx_bytes == 2000

    def test_from_vendor_opnsense_wireguard(self) -> None:
        raw = {"type": "wireguard", "peer": "wg-peer", "status": "up"}
        tunnel = VPNTunnel.from_vendor("opnsense", raw)
        assert tunnel.tunnel_type == VPNType.WIREGUARD
        assert tunnel.status == VPNStatus.UP

    def test_from_vendor_generic(self) -> None:
        raw = {"type": "wireguard", "peer": "my-peer", "status": "down"}
        tunnel = VPNTunnel.from_vendor("custom", raw)
        assert tunnel.tunnel_type == VPNType.WIREGUARD
        assert tunnel.status == VPNStatus.DOWN

    def test_serialization_roundtrip(self) -> None:
        tunnel = VPNTunnel(
            tunnel_type=VPNType.IPSEC,
            peer="test",
            status=VPNStatus.UP,
            rx_bytes=100,
            tx_bytes=200,
        )
        data = tunnel.model_dump()
        restored = VPNTunnel.model_validate(data)
        assert restored.rx_bytes == 100


# ---------------------------------------------------------------------------
# DNSRecord
# ---------------------------------------------------------------------------


class TestDNSRecord:
    def test_basic_construction(self) -> None:
        record = DNSRecord(hostname="nas", ip="192.168.1.10")
        assert record.hostname == "nas"
        assert record.ip == "192.168.1.10"
        assert record.record_type == "A"
        assert record.ttl == 3600

    def test_from_vendor_opnsense(self) -> None:
        raw = {"hostname": "nas", "domain": "home.lan", "server": "192.168.1.10", "rr": "A"}
        record = DNSRecord.from_vendor("opnsense", raw)
        assert record.hostname == "nas"
        assert record.domain == "home.lan"
        assert record.ip == "192.168.1.10"
        assert record.record_type == "A"
        assert record.source_plugin == "opnsense"

    def test_from_vendor_generic(self) -> None:
        raw = {"hostname": "srv", "address": "10.0.0.5", "type": "AAAA"}
        record = DNSRecord.from_vendor("custom", raw)
        assert record.ip == "10.0.0.5"
        assert record.record_type == "AAAA"

    def test_serialization_roundtrip(self) -> None:
        record = DNSRecord(hostname="test", ip="1.2.3.4", domain="example.com")
        data = record.model_dump()
        restored = DNSRecord.model_validate(data)
        assert restored.domain == "example.com"


# ---------------------------------------------------------------------------
# DHCPLease
# ---------------------------------------------------------------------------


class TestDHCPLease:
    def test_basic_construction(self) -> None:
        lease = DHCPLease(mac="aa:bb:cc:dd:ee:ff", ip="192.168.1.100")
        assert lease.mac == "aa:bb:cc:dd:ee:ff"
        assert lease.ip == "192.168.1.100"
        assert lease.hostname == ""
        assert lease.expiry is None

    def test_from_vendor_opnsense(self) -> None:
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "address": "192.168.1.100",
            "hostname": "laptop",
            "if": "igb1",
            "type": "dynamic",
        }
        lease = DHCPLease.from_vendor("opnsense", raw)
        assert lease.mac == "aa:bb:cc:dd:ee:ff"
        assert lease.ip == "192.168.1.100"
        assert lease.hostname == "laptop"
        assert lease.interface == "igb1"
        assert lease.source_plugin == "opnsense"

    def test_from_vendor_unifi(self) -> None:
        raw = {"mac": "11:22:33:44:55:66", "ip": "10.0.0.50", "name": "phone", "network": "IoT"}
        lease = DHCPLease.from_vendor("unifi", raw)
        assert lease.ip == "10.0.0.50"
        assert lease.hostname == "phone"
        assert lease.interface == "IoT"

    def test_from_vendor_with_iso_expiry(self) -> None:
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "address": "192.168.1.100",
            "hostname": "test",
            "ends": "2026-03-20T12:00:00",
        }
        lease = DHCPLease.from_vendor("opnsense", raw)
        assert lease.expiry is not None
        assert lease.expiry.year == 2026

    def test_from_vendor_with_invalid_expiry(self) -> None:
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "address": "192.168.1.100",
            "ends": "not-a-date",
        }
        lease = DHCPLease.from_vendor("opnsense", raw)
        assert lease.expiry is None


# ---------------------------------------------------------------------------
# NetworkTopology
# ---------------------------------------------------------------------------


class TestNetworkTopology:
    def test_empty_topology(self) -> None:
        topo = NetworkTopology()
        assert topo.nodes == []
        assert topo.links == []
        assert topo.vlans == []
        assert topo.source_plugins == []

    def test_with_nodes_and_links(self) -> None:
        node = TopologyNode(node_id="gw-1", name="Gateway", node_type=TopologyNodeType.GATEWAY)
        link = TopologyLink(source_id="gw-1", target_id="sw-1")
        topo = NetworkTopology(nodes=[node], links=[link], source_plugins=["opnsense"])
        assert len(topo.nodes) == 1
        assert len(topo.links) == 1

    def test_merge_topologies(self) -> None:
        topo1 = NetworkTopology(
            nodes=[
                TopologyNode(
                    node_id="gw-1",
                    name="Gateway",
                    node_type=TopologyNodeType.GATEWAY,
                )
            ],
            vlans=[VLAN(vlan_id=10, name="LAN", source_plugin="opnsense")],
            source_plugins=["opnsense"],
        )
        topo2 = NetworkTopology(
            nodes=[
                TopologyNode(node_id="sw-1", name="Switch", node_type=TopologyNodeType.SWITCH),
                TopologyNode(
                    node_id="gw-1",
                    name="Gateway-dup",
                    node_type=TopologyNodeType.GATEWAY,
                ),
            ],
            links=[TopologyLink(source_id="gw-1", target_id="sw-1")],
            vlans=[VLAN(vlan_id=10, name="LAN", source_plugin="unifi")],
            source_plugins=["unifi"],
        )
        merged = topo1.merge(topo2)
        # gw-1 duplicate should be skipped
        assert len(merged.nodes) == 2
        assert len(merged.links) == 1
        # VLAN 10 from different plugins should both be included
        assert len(merged.vlans) == 2
        assert set(merged.source_plugins) == {"opnsense", "unifi"}

    def test_merge_preserves_order(self) -> None:
        topo1 = NetworkTopology(source_plugins=["a"])
        topo2 = NetworkTopology(source_plugins=["b", "a"])
        merged = topo1.merge(topo2)
        assert merged.source_plugins == ["a", "b"]

    def test_serialization_roundtrip(self) -> None:
        topo = NetworkTopology(
            nodes=[TopologyNode(node_id="n1", name="N1", node_type=TopologyNodeType.SWITCH)],
            links=[TopologyLink(source_id="n1", target_id="n2")],
            vlans=[VLAN(vlan_id=10, name="Test")],
            source_plugins=["test"],
        )
        data = topo.model_dump()
        restored = NetworkTopology.model_validate(data)
        assert len(restored.nodes) == 1
        assert restored.nodes[0].node_id == "n1"


# ---------------------------------------------------------------------------
# DNSProfile
# ---------------------------------------------------------------------------


class TestDNSProfile:
    def test_basic_construction(self) -> None:
        profile = DNSProfile(id="abc123", name="Home")
        assert profile.id == "abc123"
        assert profile.name == "Home"
        assert profile.vendor == ""
        assert profile.security_enabled_count == 0
        assert profile.security_total == 12
        assert profile.logging_enabled is False

    def test_full_construction(self) -> None:
        profile = DNSProfile(
            id="abc123",
            name="Main",
            vendor="nextdns",
            security_enabled_count=10,
            security_total=12,
            blocklist_count=5,
            denylist_count=2,
            allowlist_count=1,
            logging_enabled=True,
            parental_control_active=True,
        )
        assert profile.vendor == "nextdns"
        assert profile.security_enabled_count == 10
        assert profile.blocklist_count == 5
        assert profile.parental_control_active is True

    def test_from_vendor_nextdns(self) -> None:
        data = {
            "id": "xyz789",
            "name": "IoT Profile",
            "security_enabled_count": 8,
            "security_total": 12,
            "blocklist_count": 3,
            "denylist_count": 1,
            "allowlist_count": 0,
            "logging_enabled": True,
            "parental_control_active": False,
        }
        profile = DNSProfile.from_vendor("nextdns", data)
        assert profile.id == "xyz789"
        assert profile.name == "IoT Profile"
        assert profile.vendor == "nextdns"
        assert profile.security_enabled_count == 8
        assert profile.logging_enabled is True

    def test_from_vendor_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown DNS vendor"):
            DNSProfile.from_vendor("cloudflare", {"id": "test", "name": "test"})

    def test_serialization_roundtrip(self) -> None:
        profile = DNSProfile(
            id="abc", name="Test", vendor="nextdns", security_enabled_count=12
        )
        data = profile.model_dump()
        restored = DNSProfile.model_validate(data)
        assert restored.id == "abc"
        assert restored.vendor == "nextdns"
        assert restored.security_enabled_count == 12


# ---------------------------------------------------------------------------
# DNSForwarderMapping
# ---------------------------------------------------------------------------


class TestDNSForwarderMapping:
    def test_basic_construction(self) -> None:
        mapping = DNSForwarderMapping(
            vlan_name="IoT",
            vlan_id=50,
            subnet="10.0.50.0/24",
            forwarder_target="dns.nextdns.io/abc123",
        )
        assert mapping.vlan_name == "IoT"
        assert mapping.vlan_id == 50
        assert mapping.subnet == "10.0.50.0/24"
        assert mapping.forwarder_target == "dns.nextdns.io/abc123"
        assert mapping.dns_profile_id is None
        assert mapping.dns_profile_name is None

    def test_is_nextdns_true(self) -> None:
        mapping = DNSForwarderMapping(
            vlan_name="IoT",
            vlan_id=50,
            subnet="10.0.50.0/24",
            forwarder_target="dns.nextdns.io/abc123",
        )
        assert mapping.is_nextdns is True

    def test_is_nextdns_false(self) -> None:
        mapping = DNSForwarderMapping(
            vlan_name="Guest",
            vlan_id=60,
            subnet="10.0.60.0/24",
            forwarder_target="1.1.1.1",
        )
        assert mapping.is_nextdns is False

    def test_with_profile_ids(self) -> None:
        mapping = DNSForwarderMapping(
            vlan_name="Main",
            vlan_id=10,
            subnet="10.0.10.0/24",
            forwarder_target="dns.nextdns.io/abc123",
            dns_profile_id="abc123",
            dns_profile_name="Home",
        )
        assert mapping.dns_profile_id == "abc123"
        assert mapping.dns_profile_name == "Home"

    def test_serialization_roundtrip(self) -> None:
        mapping = DNSForwarderMapping(
            vlan_name="Test",
            vlan_id=99,
            subnet="10.0.99.0/24",
            forwarder_target="dns.nextdns.io/xyz",
        )
        data = mapping.model_dump()
        restored = DNSForwarderMapping.model_validate(data)
        assert restored.vlan_id == 99
        assert restored.is_nextdns is True


# ---------------------------------------------------------------------------
# DNSAnalyticsSummary
# ---------------------------------------------------------------------------


class TestDNSAnalyticsSummary:
    def test_basic_construction(self) -> None:
        summary = DNSAnalyticsSummary(profile_id="abc123")
        assert summary.profile_id == "abc123"
        assert summary.profile_name == ""
        assert summary.total_queries == 0
        assert summary.blocked_queries == 0
        assert summary.block_percentage == 0.0
        assert summary.top_blocked_domains == []

    def test_full_construction(self) -> None:
        summary = DNSAnalyticsSummary(
            profile_id="abc123",
            profile_name="Home",
            total_queries=10000,
            blocked_queries=1500,
            allowed_queries=8500,
            block_percentage=15.0,
            top_blocked_domains=["ads.example.com", "tracker.example.com"],
        )
        assert summary.total_queries == 10000
        assert summary.block_percentage == 15.0
        assert len(summary.top_blocked_domains) == 2

    def test_serialization_roundtrip(self) -> None:
        summary = DNSAnalyticsSummary(
            profile_id="test",
            profile_name="Test",
            total_queries=100,
            blocked_queries=20,
            allowed_queries=80,
            block_percentage=20.0,
            top_blocked_domains=["bad.example.com"],
        )
        data = summary.model_dump()
        restored = DNSAnalyticsSummary.model_validate(data)
        assert restored.total_queries == 100
        assert restored.top_blocked_domains == ["bad.example.com"]
