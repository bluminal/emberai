"""Tests for Cisco SG-300 Pydantic models.

Covers:
- SwitchInfo creation and fields
- VLAN model
- Port model (interface status)
- MACEntry -- MAC address stored as-is (normalization is in parsers)
- LLDPNeighbor
- InterfaceCounters (via PortDetail)
- Strict mode enforcement
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cisco.models import (
    VLAN,
    InterfaceCounters,
    LLDPNeighbor,
    MACEntry,
    Port,
    PortDetail,
    SwitchInfo,
)

# ---------------------------------------------------------------------------
# SwitchInfo
# ---------------------------------------------------------------------------


class TestSwitchInfoCreation:
    """SwitchInfo model creation and field access."""

    def test_basic_creation(self) -> None:
        info = SwitchInfo(
            hostname="CiscoSG300",
            model="SG-300 V01",
            firmware_version="3.0.0.37",
            serial_number="",
            uptime_seconds=0,
            mac_address="d8:b3:70:c9:e9:07",
        )
        assert info.hostname == "CiscoSG300"
        assert info.model == "SG-300 V01"
        assert info.firmware_version == "3.0.0.37"
        assert info.mac_address == "d8:b3:70:c9:e9:07"

    def test_empty_serial_and_uptime(self) -> None:
        info = SwitchInfo(
            hostname="test",
            model="SG-300",
            firmware_version="3.0.0.37",
            serial_number="",
            uptime_seconds=0,
            mac_address="00:00:00:00:00:00",
        )
        assert info.serial_number == ""
        assert info.uptime_seconds == 0

    def test_mac_address_validation_rejects_empty(self) -> None:
        """Empty MAC address is rejected by the validator."""
        with pytest.raises(ValidationError):
            SwitchInfo(
                hostname="test",
                model="SG-300",
                firmware_version="1.0",
                serial_number="",
                uptime_seconds=0,
                mac_address="",
            )

    def test_all_fields_required(self) -> None:
        """All fields on SwitchInfo are required (strict mode)."""
        info = SwitchInfo(
            hostname="h",
            model="m",
            firmware_version="1.0",
            serial_number="s",
            uptime_seconds=100,
            mac_address="aa:bb:cc:dd:ee:ff",
        )
        assert info.uptime_seconds == 100


# ---------------------------------------------------------------------------
# VLAN
# ---------------------------------------------------------------------------


class TestVlanModel:
    """VLAN model creation and validation."""

    def test_basic_creation(self) -> None:
        vlan = VLAN(id=10, name="Admin", ports=["gi3"], tagged_ports=[])
        assert vlan.id == 10
        assert vlan.name == "Admin"
        assert vlan.ports == ["gi3"]
        assert vlan.tagged_ports == []

    def test_empty_ports(self) -> None:
        vlan = VLAN(id=20, name="Management", ports=[], tagged_ports=[])
        assert vlan.ports == []

    def test_multiple_ports(self) -> None:
        vlan = VLAN(
            id=60,
            name="IoT",
            ports=["gi5", "gi6", "gi7", "gi8"],
            tagged_ports=["gi1", "gi24"],
        )
        assert len(vlan.ports) == 4
        assert len(vlan.tagged_ports) == 2

    def test_strict_rejects_string_for_id(self) -> None:
        with pytest.raises(ValidationError):
            VLAN(id="ten", name="Admin", ports=[], tagged_ports=[])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------


class TestPortModel:
    """Port model creation and validation."""

    def test_basic_creation(self) -> None:
        port = Port(
            id="gi1",
            name="gi1",
            status="Up",
            speed="1000",
            duplex="Full",
            vlan_id=None,
            mode="",
            description="",
        )
        assert port.id == "gi1"
        assert port.status == "Up"
        assert port.speed == "1000"

    def test_down_port(self) -> None:
        port = Port(
            id="gi4",
            name="gi4",
            status="Down",
            speed="unknown",
            duplex="unknown",
            vlan_id=None,
            mode="",
            description="",
        )
        assert port.status == "Down"

    def test_port_with_vlan(self) -> None:
        port = Port(
            id="gi3",
            name="gi3",
            status="Up",
            speed="1000",
            duplex="Full",
            vlan_id=10,
            mode="Access",
            description="Admin AP",
        )
        assert port.vlan_id == 10
        assert port.mode == "Access"
        assert port.description == "Admin AP"

    def test_optional_vlan_id(self) -> None:
        port = Port(
            id="gi1",
            name="gi1",
            status="Up",
            speed="1000",
            duplex="Full",
            vlan_id=None,
            mode="Trunk",
            description="",
        )
        assert port.vlan_id is None


# ---------------------------------------------------------------------------
# PortDetail (extends Port with trunk info)
# ---------------------------------------------------------------------------


class TestPortDetail:
    """PortDetail model for switchport detail."""

    def test_trunk_port(self) -> None:
        detail = PortDetail(
            id="gi24",
            name="gi24",
            status="Up",
            speed="1000",
            duplex="Full",
            vlan_id=1,
            mode="Trunk",
            description="Uplink to UniFi USW",
            trunk_allowed_vlans=[1, 10, 20, 30, 40, 50, 60, 70, 80],
            native_vlan=1,
        )
        assert detail.mode == "Trunk"
        assert detail.native_vlan == 1
        assert 10 in detail.trunk_allowed_vlans
        assert len(detail.trunk_allowed_vlans) == 9

    def test_access_port(self) -> None:
        detail = PortDetail(
            id="gi3",
            name="gi3",
            status="Up",
            speed="1000",
            duplex="Full",
            vlan_id=10,
            mode="Access",
            description="Admin AP",
            trunk_allowed_vlans=[10],
            native_vlan=10,
        )
        assert detail.mode == "Access"
        assert detail.native_vlan == 10

    def test_inherits_from_port(self) -> None:
        detail = PortDetail(
            id="gi1",
            name="gi1",
            status="Up",
            speed="1000",
            duplex="Full",
            vlan_id=None,
            mode="Trunk",
            description="",
            trunk_allowed_vlans=[],
            native_vlan=None,
        )
        assert isinstance(detail, Port)


# ---------------------------------------------------------------------------
# MACEntry
# ---------------------------------------------------------------------------


class TestMacEntryModel:
    """MACEntry model -- MAC address stored as-is (normalization in parsers)."""

    def test_basic_creation(self) -> None:
        entry = MACEntry(
            mac="00:08:a2:09:78:fa",
            vlan_id=1,
            interface="gi24",
            entry_type="Dynamic",
        )
        assert entry.mac == "00:08:a2:09:78:fa"
        assert entry.vlan_id == 1
        assert entry.interface == "gi24"
        assert entry.entry_type == "Dynamic"

    def test_static_entry(self) -> None:
        entry = MACEntry(
            mac="5c:47:5e:90:81:8b",
            vlan_id=60,
            interface="gi5",
            entry_type="Static",
        )
        assert entry.entry_type == "Static"

    def test_mac_normalization_colon(self) -> None:
        """Colon-separated MAC is normalized to lowercase."""
        entry = MACEntry(
            mac="D8:B3:70:C9:E9:07",
            vlan_id=1,
            interface="gi1",
            entry_type="Dynamic",
        )
        assert entry.mac == "d8:b3:70:c9:e9:07"

    def test_mac_normalization_dash(self) -> None:
        """Dash-separated MAC is normalized."""
        entry = MACEntry(
            mac="D8-B3-70-C9-E9-07",
            vlan_id=1,
            interface="gi1",
            entry_type="Dynamic",
        )
        assert entry.mac == "d8:b3:70:c9:e9:07"

    def test_mac_normalization_dot(self) -> None:
        """Cisco dot notation MAC is normalized."""
        entry = MACEntry(
            mac="d8b3.70c9.e907",
            vlan_id=1,
            interface="gi1",
            entry_type="Dynamic",
        )
        assert entry.mac == "d8:b3:70:c9:e9:07"

    def test_strict_rejects_int_for_mac(self) -> None:
        with pytest.raises((ValidationError, AttributeError)):
            MACEntry(
                mac=123456,  # type: ignore[arg-type]
                vlan_id=1,
                interface="gi1",
                entry_type="Dynamic",
            )


# ---------------------------------------------------------------------------
# LLDPNeighbor
# ---------------------------------------------------------------------------


class TestLldpNeighbor:
    """LLDPNeighbor model creation."""

    def test_basic_creation(self) -> None:
        neighbor = LLDPNeighbor(
            local_port="gi24",
            remote_device="USW-Pro-24-PoE",
            remote_port="52",
            capabilities="B",
            remote_ip=None,
        )
        assert neighbor.local_port == "gi24"
        assert neighbor.remote_device == "USW-Pro-24-PoE"
        assert neighbor.remote_port == "52"
        assert neighbor.capabilities == "B"
        assert neighbor.remote_ip is None

    def test_router_capability(self) -> None:
        neighbor = LLDPNeighbor(
            local_port="gi23",
            remote_device="OPNsense.local",
            remote_port="igb2",
            capabilities="R",
            remote_ip=None,
        )
        assert neighbor.capabilities == "R"

    def test_optional_remote_ip(self) -> None:
        neighbor = LLDPNeighbor(
            local_port="gi1",
            remote_device="test",
            remote_port="eth0",
            capabilities="B",
            remote_ip="10.0.0.1",
        )
        assert neighbor.remote_ip == "10.0.0.1"


# ---------------------------------------------------------------------------
# InterfaceCounters
# ---------------------------------------------------------------------------


class TestInterfaceCounters:
    """InterfaceCounters model for per-port traffic stats."""

    def test_basic_creation(self) -> None:
        counters = InterfaceCounters(
            port="gi1",
            rx_bytes=1000000,
            tx_bytes=500000,
            rx_packets=10000,
            tx_packets=5000,
            rx_errors=0,
            tx_errors=0,
            rx_discards=0,
            tx_discards=0,
        )
        assert counters.port == "gi1"
        assert counters.rx_bytes == 1000000
        assert counters.tx_bytes == 500000
        assert counters.rx_packets == 10000
        assert counters.tx_packets == 5000

    def test_with_errors(self) -> None:
        counters = InterfaceCounters(
            port="gi5",
            rx_bytes=0,
            tx_bytes=0,
            rx_packets=0,
            tx_packets=0,
            rx_errors=42,
            tx_errors=3,
            rx_discards=10,
            tx_discards=1,
        )
        assert counters.rx_errors == 42
        assert counters.tx_errors == 3
        assert counters.rx_discards == 10
        assert counters.tx_discards == 1

    def test_strict_rejects_string_for_bytes(self) -> None:
        with pytest.raises(ValidationError):
            InterfaceCounters(
                port="gi1",
                rx_bytes="lots",  # type: ignore[arg-type]
                tx_bytes=0,
                rx_packets=0,
                tx_packets=0,
                rx_errors=0,
                tx_errors=0,
                rx_discards=0,
                tx_discards=0,
            )


# ---------------------------------------------------------------------------
# Re-export completeness
# ---------------------------------------------------------------------------


class TestReExports:
    """Verify all models are re-exported from cisco.models."""

    def test_all_models_importable(self) -> None:
        from cisco.models import __all__

        expected = {
            "InterfaceCounters",
            "LLDPNeighbor",
            "MACAddress",
            "MACEntry",
            "Port",
            "PortDetail",
            "SwitchInfo",
            "VLAN",
            "normalize_mac",
        }
        assert set(__all__) == expected
