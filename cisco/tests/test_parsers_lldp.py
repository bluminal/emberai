"""Tests for the ``show lldp neighbors`` CLI parser.

Covers:
- Full fixture parsing with all neighbors
- Empty neighbor table
"""

from __future__ import annotations

from cisco.parsers.lldp import parse_show_lldp_neighbors

# ---------------------------------------------------------------------------
# parse_show_lldp_neighbors -- full fixture
# ---------------------------------------------------------------------------


class TestParseLldpNeighbors:
    """Parse full show lldp neighbors output."""

    def test_parse_lldp_neighbors_count(self, show_lldp_neighbors_output: str) -> None:
        neighbors = parse_show_lldp_neighbors(show_lldp_neighbors_output)
        assert len(neighbors) == 2

    def test_usw_pro_neighbor(self, show_lldp_neighbors_output: str) -> None:
        neighbors = parse_show_lldp_neighbors(show_lldp_neighbors_output)
        usw = next(n for n in neighbors if n.remote_device == "USW-Pro-24-PoE")
        assert usw.local_port == "gi24"
        assert usw.remote_port == "52"
        assert usw.capabilities == "B"

    def test_opnsense_neighbor(self, show_lldp_neighbors_output: str) -> None:
        neighbors = parse_show_lldp_neighbors(show_lldp_neighbors_output)
        opn = next(n for n in neighbors if n.remote_device == "OPNsense.local")
        assert opn.local_port == "gi23"
        assert opn.remote_port == "igb2"
        assert opn.capabilities == "R"

    def test_remote_ip_is_none(self, show_lldp_neighbors_output: str) -> None:
        """show lldp neighbors summary does not include IPs."""
        neighbors = parse_show_lldp_neighbors(show_lldp_neighbors_output)
        for n in neighbors:
            assert n.remote_ip is None

    def test_all_local_ports_are_gi(self, show_lldp_neighbors_output: str) -> None:
        neighbors = parse_show_lldp_neighbors(show_lldp_neighbors_output)
        for n in neighbors:
            assert n.local_port.startswith("gi")


# ---------------------------------------------------------------------------
# Empty neighbor table
# ---------------------------------------------------------------------------


class TestParseLldpEmpty:
    """Parse empty show lldp neighbors output."""

    def test_parse_lldp_empty(self, show_lldp_neighbors_empty_output: str) -> None:
        neighbors = parse_show_lldp_neighbors(show_lldp_neighbors_empty_output)
        assert neighbors == []


# ---------------------------------------------------------------------------
# Edge cases for uncovered lines
# ---------------------------------------------------------------------------


class TestParseLldpEdgeCases:
    """Edge cases to cover lines 67, 72, 76."""

    def test_lines_before_table_are_skipped(self) -> None:
        """Line 67: lines before the table header are ignored."""
        raw = (
            "System capability supported: Bridge, Router\n"
            "Port ID subtype: Local\n"
            "Port ID: gi1\n"
            "\n"
            "    Device ID         Local Intf     Hold-time  Capability      Port ID\n"
            "    ---------------   ----------     ---------  ----------      ----------\n"
            "    USW-Pro-24-PoE    gi24           120        B               52\n"
        )
        neighbors = parse_show_lldp_neighbors(raw)
        assert len(neighbors) == 1
        assert neighbors[0].remote_device == "USW-Pro-24-PoE"

    def test_blank_lines_within_table_are_skipped(self) -> None:
        """Line 72: blank lines within the table body are skipped."""
        raw = (
            "    Device ID         Local Intf     Hold-time  Capability      Port ID\n"
            "    ---------------   ----------     ---------  ----------      ----------\n"
            "    USW-Pro-24-PoE    gi24           120        B               52\n"
            "\n"
            "    OPNsense.local    gi23           120        R               igb2\n"
        )
        neighbors = parse_show_lldp_neighbors(raw)
        assert len(neighbors) == 2

    def test_non_matching_lines_in_table_are_skipped(self) -> None:
        """Line 76: lines that don't match the regex are skipped."""
        raw = (
            "    Device ID         Local Intf     Hold-time  Capability      Port ID\n"
            "    ---------------   ----------     ---------  ----------      ----------\n"
            "    USW-Pro-24-PoE    gi24           120        B               52\n"
            "    This is some random non-matching line\n"
            "    OPNsense.local    gi23           120        R               igb2\n"
        )
        neighbors = parse_show_lldp_neighbors(raw)
        assert len(neighbors) == 2
