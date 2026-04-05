"""Tests for interface and switchport CLI parsers.

Covers:
- parse_show_interfaces_status -- port count, up/down states
- Down ports with "--" fields handled correctly
- parse_show_switchport -- trunk mode, allowed VLANs, native VLAN
- parse_show_switchport -- access mode, access VLAN
"""

from __future__ import annotations

from cisco.parsers.interfaces import parse_show_interfaces_status, parse_show_switchport

# ---------------------------------------------------------------------------
# parse_show_interfaces_status -- full fixture
# ---------------------------------------------------------------------------


class TestParseInterfacesStatus:
    """Parse show interfaces status output."""

    def test_parse_interfaces_count(self, show_interfaces_status_output: str) -> None:
        ports = parse_show_interfaces_status(show_interfaces_status_output)
        assert len(ports) == 24  # gi1 through gi24

    def test_up_ports_count(self, show_interfaces_status_output: str) -> None:
        ports = parse_show_interfaces_status(show_interfaces_status_output)
        up_ports = [p for p in ports if p.status == "Up"]
        # gi1, gi2, gi3, gi5, gi6, gi23, gi24 = 7 up
        assert len(up_ports) == 7

    def test_down_ports_count(self, show_interfaces_status_output: str) -> None:
        ports = parse_show_interfaces_status(show_interfaces_status_output)
        down_ports = [p for p in ports if p.status == "Down"]
        assert len(down_ports) == 17

    def test_gi1_up_with_speed(self, show_interfaces_status_output: str) -> None:
        ports = parse_show_interfaces_status(show_interfaces_status_output)
        gi1 = next(p for p in ports if p.id == "gi1")
        assert gi1.status == "Up"
        assert gi1.speed == "1000"
        assert gi1.duplex == "Full"

    def test_gi5_100mbps(self, show_interfaces_status_output: str) -> None:
        ports = parse_show_interfaces_status(show_interfaces_status_output)
        gi5 = next(p for p in ports if p.id == "gi5")
        assert gi5.status == "Up"
        assert gi5.speed == "100"

    def test_port_ids_are_strings(self, show_interfaces_status_output: str) -> None:
        ports = parse_show_interfaces_status(show_interfaces_status_output)
        for port in ports:
            assert isinstance(port.id, str)
            assert port.id.startswith("gi")


# ---------------------------------------------------------------------------
# Down ports with "--" fields
# ---------------------------------------------------------------------------


class TestParseInterfacesDownPorts:
    """Verify "--" fields on down ports are handled correctly."""

    def test_down_port_speed_is_dash(self, show_interfaces_status_output: str) -> None:
        ports = parse_show_interfaces_status(show_interfaces_status_output)
        gi4 = next(p for p in ports if p.id == "gi4")
        assert gi4.status == "Down"
        # Speed should be handled -- either "--" or "unknown"
        assert gi4.speed in ("--", "unknown")

    def test_down_port_duplex_is_dash(self, show_interfaces_status_output: str) -> None:
        ports = parse_show_interfaces_status(show_interfaces_status_output)
        gi7 = next(p for p in ports if p.id == "gi7")
        assert gi7.status == "Down"
        assert gi7.duplex in ("--", "unknown")


# ---------------------------------------------------------------------------
# parse_show_switchport -- trunk mode
# ---------------------------------------------------------------------------


class TestParseSwitchportTrunk:
    """Parse trunk port switchport output."""

    def test_trunk_port_id(self, show_switchport_trunk_output: str) -> None:
        detail = parse_show_switchport(show_switchport_trunk_output)
        assert detail.id == "gi24"

    def test_trunk_mode(self, show_switchport_trunk_output: str) -> None:
        detail = parse_show_switchport(show_switchport_trunk_output)
        assert detail.mode == "Trunk"

    def test_trunk_native_vlan(self, show_switchport_trunk_output: str) -> None:
        detail = parse_show_switchport(show_switchport_trunk_output)
        assert detail.native_vlan == 1

    def test_trunk_allowed_vlans(self, show_switchport_trunk_output: str) -> None:
        detail = parse_show_switchport(show_switchport_trunk_output)
        # Should include VLAN 1 (native, untagged) and VLANs 10-80 (tagged)
        assert 1 in detail.trunk_allowed_vlans
        assert 10 in detail.trunk_allowed_vlans
        assert 20 in detail.trunk_allowed_vlans
        assert 30 in detail.trunk_allowed_vlans
        assert 40 in detail.trunk_allowed_vlans
        assert 50 in detail.trunk_allowed_vlans
        assert 60 in detail.trunk_allowed_vlans
        assert 70 in detail.trunk_allowed_vlans
        assert 80 in detail.trunk_allowed_vlans
        assert len(detail.trunk_allowed_vlans) == 9


# ---------------------------------------------------------------------------
# parse_show_switchport -- access mode
# ---------------------------------------------------------------------------


class TestParseSwitchportAccess:
    """Parse access port switchport output."""

    def test_access_port_id(self, show_switchport_access_output: str) -> None:
        detail = parse_show_switchport(show_switchport_access_output)
        assert detail.id == "gi3"

    def test_access_mode(self, show_switchport_access_output: str) -> None:
        detail = parse_show_switchport(show_switchport_access_output)
        assert detail.mode == "Access"

    def test_access_native_vlan(self, show_switchport_access_output: str) -> None:
        detail = parse_show_switchport(show_switchport_access_output)
        assert detail.native_vlan == 10

    def test_access_vlan_membership(self, show_switchport_access_output: str) -> None:
        detail = parse_show_switchport(show_switchport_access_output)
        # Access port should only be member of VLAN 10
        assert 10 in detail.trunk_allowed_vlans
        assert len(detail.trunk_allowed_vlans) == 1
