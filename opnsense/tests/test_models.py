"""Tests for OPNsense Pydantic models.

Covers model validation, field aliases, strict mode, optional fields,
and round-trip parsing of representative OPNsense API responses.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from opnsense.models import (
    Alias,
    Certificate,
    DHCPLease,
    DNSOverride,
    FirewallRule,
    FirmwareStatus,
    Gateway,
    IDSAlert,
    IPSecSession,
    Interface,
    NATRule,
    OpenVPNInstance,
    Route,
    VLANInterface,
    WireGuardPeer,
)


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class TestInterface:
    def test_basic_parse(self) -> None:
        iface = Interface(name="igb0", description="LAN", enabled=True)
        assert iface.name == "igb0"
        assert iface.description == "LAN"
        assert iface.enabled is True

    def test_alias_mapping(self) -> None:
        data = {
            "name": "igb1",
            "addr4": "192.168.1.1",
            "subnet4": "24",
            "type": "ethernet",
            "vlan_tag": 10,
        }
        iface = Interface.model_validate(data)
        assert iface.ip == "192.168.1.1"
        assert iface.subnet == "24"
        assert iface.if_type == "ethernet"
        assert iface.vlan_id == 10

    def test_optional_vlan_id_defaults_none(self) -> None:
        iface = Interface(name="igb0")
        assert iface.vlan_id is None

    def test_populate_by_name(self) -> None:
        iface = Interface(name="igb0", ip="10.0.0.1", if_type="ethernet")
        assert iface.ip == "10.0.0.1"
        assert iface.if_type == "ethernet"


# ---------------------------------------------------------------------------
# VLANInterface
# ---------------------------------------------------------------------------


class TestVLANInterface:
    def test_basic_parse_with_aliases(self) -> None:
        data = {
            "uuid": "abc-123",
            "tag": 100,
            "if": "vlan100",
            "descr": "Guest VLAN",
            "vlanif": "igb0",
            "pcp": 3,
        }
        vlan = VLANInterface.model_validate(data)
        assert vlan.uuid == "abc-123"
        assert vlan.tag == 100
        assert vlan.if_ == "vlan100"
        assert vlan.description == "Guest VLAN"
        assert vlan.parent_if == "igb0"
        assert vlan.pcp == 3

    def test_pcp_optional(self) -> None:
        data = {
            "uuid": "def-456",
            "tag": 20,
            "if": "vlan20",
            "vlanif": "igb1",
        }
        vlan = VLANInterface.model_validate(data)
        assert vlan.pcp is None

    def test_populate_by_name(self) -> None:
        vlan = VLANInterface(
            uuid="x", tag=10, if_="vlan10", parent_if="igb0",
        )
        assert vlan.if_ == "vlan10"


# ---------------------------------------------------------------------------
# FirewallRule
# ---------------------------------------------------------------------------


class TestFirewallRule:
    def test_basic_parse(self) -> None:
        rule = FirewallRule(uuid="rule-1", action="pass")
        assert rule.uuid == "rule-1"
        assert rule.action == "pass"
        assert rule.enabled is True

    def test_alias_mapping(self) -> None:
        data = {
            "uuid": "rule-2",
            "action": "block",
            "ipprotocol": "TCP",
            "source_net": "192.168.1.0/24",
            "destination_net": "10.0.0.0/8",
            "sequence": 5,
        }
        rule = FirewallRule.model_validate(data)
        assert rule.protocol == "TCP"
        assert rule.source == "192.168.1.0/24"
        assert rule.destination == "10.0.0.0/8"
        assert rule.position == 5


class TestAlias:
    def test_basic_parse(self) -> None:
        data = {
            "uuid": "alias-1",
            "name": "trusted_hosts",
            "type": "host",
            "description": "Trusted hosts list",
            "content": "10.0.0.1,10.0.0.2",
        }
        alias = Alias.model_validate(data)
        assert alias.uuid == "alias-1"
        assert alias.name == "trusted_hosts"
        assert alias.alias_type == "host"
        assert alias.content == "10.0.0.1,10.0.0.2"


class TestNATRule:
    def test_basic_parse(self) -> None:
        data = {
            "uuid": "nat-1",
            "description": "Web server NAT",
            "interface": "wan",
            "target": "192.168.1.100",
            "target_port": "443",
        }
        nat = NATRule.model_validate(data)
        assert nat.uuid == "nat-1"
        assert nat.target == "192.168.1.100"
        assert nat.target_port == "443"
        assert nat.enabled is True


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class TestRoute:
    def test_basic_parse(self) -> None:
        data = {
            "uuid": "route-1",
            "network": "10.0.0.0/8",
            "gateway": "WAN_GW",
            "descr": "Corporate network",
        }
        route = Route.model_validate(data)
        assert route.uuid == "route-1"
        assert route.network == "10.0.0.0/8"
        assert route.gateway == "WAN_GW"
        assert route.description == "Corporate network"
        assert route.disabled is False


class TestGateway:
    def test_basic_parse(self) -> None:
        data = {
            "name": "WAN_GW",
            "address": "203.0.113.1",
            "interface": "igb0",
            "status": "online",
            "delay": 5.2,
        }
        gw = Gateway.model_validate(data)
        assert gw.name == "WAN_GW"
        assert gw.gateway == "203.0.113.1"
        assert gw.status == "online"
        assert gw.rtt_ms == 5.2

    def test_rtt_ms_optional(self) -> None:
        gw = Gateway(name="GW1")
        assert gw.rtt_ms is None


# ---------------------------------------------------------------------------
# VPN
# ---------------------------------------------------------------------------


class TestIPSecSession:
    def test_basic_parse(self) -> None:
        data = {
            "id": "ipsec-1",
            "description": "Site-to-site",
            "connected": "connected",
            "local-ts": "10.0.0.0/24",
            "remote-ts": "10.1.0.0/24",
            "bytes-in": 1024,
            "bytes-out": 2048,
        }
        session = IPSecSession.model_validate(data)
        assert session.session_id == "ipsec-1"
        assert session.status == "connected"
        assert session.local_ts == "10.0.0.0/24"
        assert session.rx_bytes == 1024
        assert session.tx_bytes == 2048


class TestWireGuardPeer:
    def test_basic_parse(self) -> None:
        data = {
            "uuid": "wg-1",
            "name": "Mobile phone",
            "pubkey": "abc123pubkey==",
            "tunneladdress": "10.10.0.2/32",
        }
        peer = WireGuardPeer.model_validate(data)
        assert peer.uuid == "wg-1"
        assert peer.public_key == "abc123pubkey=="
        assert peer.allowed_ips == "10.10.0.2/32"
        assert peer.endpoint is None


class TestOpenVPNInstance:
    def test_basic_parse(self) -> None:
        data = {
            "uuid": "ovpn-1",
            "description": "Remote access",
            "role": "server",
            "proto": "udp",
            "port": 1194,
            "clients": 5,
        }
        instance = OpenVPNInstance.model_validate(data)
        assert instance.uuid == "ovpn-1"
        assert instance.role == "server"
        assert instance.protocol == "udp"
        assert instance.port == 1194
        assert instance.connected_clients == 5


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


class TestDHCPLease:
    def test_basic_parse(self) -> None:
        data = {
            "hw_address": "aa:bb:cc:dd:ee:ff",
            "address": "192.168.1.50",
            "hostname": "desktop-pc",
            "state": "active",
        }
        lease = DHCPLease.model_validate(data)
        assert lease.mac == "aa:bb:cc:dd:ee:ff"
        assert lease.ip == "192.168.1.50"
        assert lease.hostname == "desktop-pc"
        assert lease.state == "active"


class TestDNSOverride:
    def test_basic_parse(self) -> None:
        data = {
            "uuid": "dns-1",
            "hostname": "nas",
            "domain": "home.local",
            "server": "192.168.1.200",
            "description": "NAS host override",
        }
        override = DNSOverride.model_validate(data)
        assert override.uuid == "dns-1"
        assert override.hostname == "nas"
        assert override.domain == "home.local"
        assert override.ip == "192.168.1.200"


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class TestIDSAlert:
    def test_basic_parse(self) -> None:
        data = {
            "timestamp": "2026-03-19T10:00:00Z",
            "alert": "ET SCAN Nmap Scripting Engine",
            "alert_cat": "Attempted Information Leak",
            "alert_sev": 1,
            "src_ip": "10.0.0.5",
            "dest_ip": "10.0.0.1",
            "proto": "TCP",
            "action": "drop",
        }
        alert = IDSAlert.model_validate(data)
        assert alert.timestamp == "2026-03-19T10:00:00Z"
        assert alert.signature == "ET SCAN Nmap Scripting Engine"
        assert alert.category == "Attempted Information Leak"
        assert alert.severity == 1
        assert alert.action == "drop"


class TestCertificate:
    def test_basic_parse(self) -> None:
        data = {
            "cn": "fw.home.local",
            "san": ["fw.home.local", "192.168.1.1"],
            "issuer": "OPNsense Self-Signed CA",
            "valid_from": "2025-01-01",
            "valid_to": "2026-01-01",
            "days_left": 287,
            "in_use": ["webgui", "openvpn"],
        }
        cert = Certificate.model_validate(data)
        assert cert.cn == "fw.home.local"
        assert len(cert.san) == 2
        assert cert.days_until_expiry == 287
        assert "webgui" in cert.in_use_for

    def test_defaults(self) -> None:
        cert = Certificate(cn="test.local")
        assert cert.san == []
        assert cert.in_use_for == []
        assert cert.days_until_expiry is None


# ---------------------------------------------------------------------------
# Firmware
# ---------------------------------------------------------------------------


class TestFirmwareStatus:
    def test_basic_parse(self) -> None:
        data = {
            "product_version": "24.7.1",
            "product_latest": "24.7.2",
            "upgrade_available": True,
            "last_check": "2026-03-19T09:00:00Z",
            "changelog": "https://opnsense.org/changelog/24.7.2",
        }
        fw = FirmwareStatus.model_validate(data)
        assert fw.current_version == "24.7.1"
        assert fw.latest_version == "24.7.2"
        assert fw.upgrade_available is True
        assert fw.changelog_url == "https://opnsense.org/changelog/24.7.2"

    def test_no_upgrade(self) -> None:
        data = {
            "product_version": "24.7.2",
        }
        fw = FirmwareStatus.model_validate(data)
        assert fw.upgrade_available is False
        assert fw.changelog_url is None


# ---------------------------------------------------------------------------
# Strict mode enforcement
# ---------------------------------------------------------------------------


class TestStrictMode:
    """Verify that strict mode rejects incorrect types."""

    def test_interface_rejects_int_for_name(self) -> None:
        with pytest.raises(ValidationError):
            Interface(name=123)  # type: ignore[arg-type]

    def test_firewall_rule_rejects_int_for_uuid(self) -> None:
        with pytest.raises(ValidationError):
            FirewallRule(uuid=123, action="pass")  # type: ignore[arg-type]

    def test_vlan_interface_rejects_str_for_tag(self) -> None:
        with pytest.raises(ValidationError):
            VLANInterface(  # type: ignore[arg-type]
                uuid="x", tag="ten", if_="vlan10", parent_if="igb0",
            )


# ---------------------------------------------------------------------------
# Re-export completeness
# ---------------------------------------------------------------------------


class TestReExports:
    """Verify all models are re-exported from opnsense.models."""

    def test_all_models_importable(self) -> None:
        from opnsense.models import __all__

        expected = {
            "Alias",
            "Certificate",
            "DHCPLease",
            "DNSOverride",
            "FirewallRule",
            "FirmwareStatus",
            "Gateway",
            "IDSAlert",
            "IPSecSession",
            "Interface",
            "NATRule",
            "OpenVPNInstance",
            "Route",
            "VLANInterface",
            "WireGuardPeer",
        }
        assert set(__all__) == expected
