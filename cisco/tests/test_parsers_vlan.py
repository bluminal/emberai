"""Tests for the ``show vlan`` CLI parser.

Covers:
- Full fixture parsing with all VLANs
- Port range expansion (gi1-8 -> [gi1, gi2, ..., gi8])
- VLANs with no ports (empty port list)
- Empty output (only default VLAN)
"""

from __future__ import annotations

from cisco.parsers.vlan import _expand_port_range, _parse_port_list, parse_show_vlan

# ---------------------------------------------------------------------------
# parse_show_vlan -- full fixture
# ---------------------------------------------------------------------------


class TestParseVlans:
    """Parse full show vlan output."""

    def test_parse_vlans_count(self, show_vlan_output: str) -> None:
        vlans = parse_show_vlan(show_vlan_output)
        assert len(vlans) == 9  # VLANs 1, 10, 20, 30, 40, 50, 60, 70, 80

    def test_default_vlan_parsed(self, show_vlan_output: str) -> None:
        vlans = parse_show_vlan(show_vlan_output)
        default = next(v for v in vlans if v.id == 1)
        assert default.name == "default"

    def test_vlan_10_admin(self, show_vlan_output: str) -> None:
        vlans = parse_show_vlan(show_vlan_output)
        admin = next(v for v in vlans if v.id == 10)
        assert admin.name == "Admin"
        assert "gi3" in admin.ports

    def test_vlan_60_iot_ports(self, show_vlan_output: str) -> None:
        vlans = parse_show_vlan(show_vlan_output)
        iot = next(v for v in vlans if v.id == 60)
        assert iot.name == "IoT"
        # gi5-8 should expand to [gi5, gi6, gi7, gi8]
        assert "gi5" in iot.ports
        assert "gi6" in iot.ports
        assert "gi7" in iot.ports
        assert "gi8" in iot.ports
        assert len(iot.ports) == 4

    def test_vlan_ids_are_integers(self, show_vlan_output: str) -> None:
        vlans = parse_show_vlan(show_vlan_output)
        for vlan in vlans:
            assert isinstance(vlan.id, int)

    def test_all_expected_vlan_ids(self, show_vlan_output: str) -> None:
        vlans = parse_show_vlan(show_vlan_output)
        vlan_ids = {v.id for v in vlans}
        assert vlan_ids == {1, 10, 20, 30, 40, 50, 60, 70, 80}


# ---------------------------------------------------------------------------
# Port range expansion
# ---------------------------------------------------------------------------


class TestParseVlansPortRanges:
    """Port range expansion tests."""

    def test_expand_single_port(self) -> None:
        assert _expand_port_range("gi1") == ["gi1"]

    def test_expand_port_range(self) -> None:
        result = _expand_port_range("gi1-8")
        assert result == [f"gi{i}" for i in range(1, 9)]

    def test_expand_po_range(self) -> None:
        result = _expand_port_range("Po1-8")
        assert result == [f"Po{i}" for i in range(1, 9)]

    def test_default_vlan_port_expansion(self, show_vlan_output: str) -> None:
        """Default VLAN ports gi1-2,gi4-22,Po1-8 should expand correctly."""
        vlans = parse_show_vlan(show_vlan_output)
        default = next(v for v in vlans if v.id == 1)
        # gi1-2 -> gi1, gi2
        assert "gi1" in default.ports
        assert "gi2" in default.ports
        # gi4-22 -> gi4 through gi22
        assert "gi4" in default.ports
        assert "gi22" in default.ports
        # Po1-8 -> Po1 through Po8
        assert "Po1" in default.ports
        assert "Po8" in default.ports

    def test_parse_port_list_comma_separated(self) -> None:
        result = _parse_port_list("gi1-2,gi4-22,Po1-8")
        assert "gi1" in result
        assert "gi2" in result
        assert "gi4" in result
        assert "Po1" in result

    def test_parse_port_list_empty(self) -> None:
        assert _parse_port_list("") == []
        assert _parse_port_list("   ") == []


# ---------------------------------------------------------------------------
# VLANs with no ports
# ---------------------------------------------------------------------------


class TestParseVlansEmptyPorts:
    """VLANs with no member ports."""

    def test_management_vlan_no_ports(self, show_vlan_output: str) -> None:
        vlans = parse_show_vlan(show_vlan_output)
        mgmt = next(v for v in vlans if v.id == 20)
        assert mgmt.name == "Management"
        assert mgmt.ports == []

    def test_guest_vlan_no_ports(self, show_vlan_output: str) -> None:
        vlans = parse_show_vlan(show_vlan_output)
        guest = next(v for v in vlans if v.id == 50)
        assert guest.name == "Guest"
        assert guest.ports == []


# ---------------------------------------------------------------------------
# Empty output (only default VLAN)
# ---------------------------------------------------------------------------


class TestParseVlansEmptyOutput:
    """Only the default VLAN is present."""

    def test_parse_vlans_empty_output(self, show_vlan_empty_output: str) -> None:
        vlans = parse_show_vlan(show_vlan_empty_output)
        assert len(vlans) == 1
        assert vlans[0].id == 1
        assert vlans[0].name == "default"

    def test_empty_output_default_ports(self, show_vlan_empty_output: str) -> None:
        vlans = parse_show_vlan(show_vlan_empty_output)
        default = vlans[0]
        # gi1-24,Po1-8 should all be expanded
        assert "gi1" in default.ports
        assert "gi24" in default.ports
        assert "Po1" in default.ports
        assert "Po8" in default.ports


# ---------------------------------------------------------------------------
# Edge cases for uncovered lines
# ---------------------------------------------------------------------------


class TestParseVlanEdgeCases:
    """Edge cases to cover lines 113, 119."""

    def test_header_and_separator_lines_skipped(self) -> None:
        """Line 113-115: VLAN and ---- header lines are skipped."""
        raw = (
            "VLAN    Name                             Ports"
            "                       Type     Authorization\n"
            "----    -------------------------------- "
            "--------------------------- -------- -------------\n"
            " 1      default                          gi1-24,Po1-8"
            "                    Default  Required\n"
        )
        vlans = parse_show_vlan(raw)
        assert len(vlans) == 1
        assert vlans[0].id == 1

    def test_non_matching_lines_skipped(self) -> None:
        """Line 119: lines that don't match the regex are skipped."""
        raw = (
            "VLAN    Name                             Ports"
            "                       Type     Authorization\n"
            "----    -------------------------------- "
            "--------------------------- -------- -------------\n"
            " 1      default                          gi1-24,Po1-8"
            "                    Default  Required\n"
            "This is some garbage line that shouldn't match\n"
            " 10     Admin                            gi3"
            "                         Static   Required\n"
        )
        vlans = parse_show_vlan(raw)
        assert len(vlans) == 2
        assert vlans[0].id == 1
        assert vlans[1].id == 10
