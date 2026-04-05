"""Tests for the ``show mac address-table`` CLI parser.

Covers:
- Full fixture parsing with all entries
- Empty MAC table
- MAC address normalization (various formats)
- Static vs Dynamic entry type
"""

from __future__ import annotations

from cisco.parsers.mac_table import _normalize_mac, parse_show_mac_address_table

# ---------------------------------------------------------------------------
# parse_show_mac_address_table -- full fixture
# ---------------------------------------------------------------------------


class TestParseMacTable:
    """Parse full show mac address-table output."""

    def test_parse_mac_table_count(self, show_mac_address_table_output: str) -> None:
        entries = parse_show_mac_address_table(show_mac_address_table_output)
        assert len(entries) == 10

    def test_first_entry(self, show_mac_address_table_output: str) -> None:
        entries = parse_show_mac_address_table(show_mac_address_table_output)
        first = entries[0]
        assert first.vlan_id == 1
        assert first.mac == "00:08:a2:09:78:fa"
        assert first.entry_type == "Dynamic"
        assert first.interface == "gi24"

    def test_vlan_10_entry(self, show_mac_address_table_output: str) -> None:
        entries = parse_show_mac_address_table(show_mac_address_table_output)
        vlan10 = [e for e in entries if e.vlan_id == 10]
        assert len(vlan10) == 1
        assert vlan10[0].mac == "1c:0b:8b:70:ae:b4"
        assert vlan10[0].interface == "gi3"

    def test_vlan_60_entries(self, show_mac_address_table_output: str) -> None:
        entries = parse_show_mac_address_table(show_mac_address_table_output)
        vlan60 = [e for e in entries if e.vlan_id == 60]
        assert len(vlan60) == 3

    def test_all_macs_are_lowercase_colon_separated(
        self, show_mac_address_table_output: str
    ) -> None:
        entries = parse_show_mac_address_table(show_mac_address_table_output)
        for entry in entries:
            # Should be lowercase, colon-separated
            assert entry.mac == entry.mac.lower()
            assert ":" in entry.mac
            # Exactly 5 colons = 6 hex pairs
            assert entry.mac.count(":") == 5


# ---------------------------------------------------------------------------
# Empty MAC table
# ---------------------------------------------------------------------------


class TestParseMacTableEmpty:
    """Parse empty show mac address-table output."""

    def test_parse_mac_table_empty(self, show_mac_address_table_empty_output: str) -> None:
        entries = parse_show_mac_address_table(show_mac_address_table_empty_output)
        assert entries == []


# ---------------------------------------------------------------------------
# MAC address normalization
# ---------------------------------------------------------------------------


class TestMacAddressNormalization:
    """Test various MAC address formats normalize correctly."""

    def test_colon_format_lowercase(self) -> None:
        assert _normalize_mac("00:08:a2:09:78:fa") == "00:08:a2:09:78:fa"

    def test_colon_format_uppercase(self) -> None:
        assert _normalize_mac("00:08:A2:09:78:FA") == "00:08:a2:09:78:fa"

    def test_dash_format(self) -> None:
        assert _normalize_mac("00-08-A2-09-78-FA") == "00:08:a2:09:78:fa"

    def test_dot_format(self) -> None:
        assert _normalize_mac("0008.a209.78fa") == "00:08:a2:09:78:fa"

    def test_no_separator_format(self) -> None:
        assert _normalize_mac("0008a20978fa") == "00:08:a2:09:78:fa"

    def test_mixed_case(self) -> None:
        assert _normalize_mac("D8:B3:70:C9:E9:07") == "d8:b3:70:c9:e9:07"


# ---------------------------------------------------------------------------
# Static vs Dynamic entry type
# ---------------------------------------------------------------------------


class TestStaticVsDynamic:
    """Verify entry_type is correctly parsed."""

    def test_dynamic_entries(self, show_mac_address_table_output: str) -> None:
        entries = parse_show_mac_address_table(show_mac_address_table_output)
        dynamic = [e for e in entries if e.entry_type == "Dynamic"]
        assert len(dynamic) == 9

    def test_static_entry(self, show_mac_address_table_output: str) -> None:
        entries = parse_show_mac_address_table(show_mac_address_table_output)
        static = [e for e in entries if e.entry_type == "Static"]
        assert len(static) == 1
        assert static[0].mac == "5c:47:5e:90:81:8b"
        assert static[0].interface == "gi5"
        assert static[0].vlan_id == 60


# ---------------------------------------------------------------------------
# Edge cases for uncovered lines
# ---------------------------------------------------------------------------


class TestParseMacTableEdgeCases:
    """Edge cases to cover line 100 (non-matching lines)."""

    def test_non_matching_lines_skipped(self) -> None:
        """Line 100: lines that don't match either regex are skipped."""
        raw = (
            "          Aging Time: 300 sec\n"
            "\n"
            "    Vlan    Mac Address         Type        Port\n"
            "    ----    -----------         ----        ----\n"
            "     1      00:08:a2:09:78:fa   Dynamic     gi24\n"
            "    This is a random non-matching line\n"
            "     10     1c:0b:8b:70:ae:b4   Dynamic     gi3\n"
        )
        entries = parse_show_mac_address_table(raw)
        assert len(entries) == 2

    def test_total_line_skipped(self) -> None:
        """Footer 'Total Mac Addresses' line is skipped."""
        raw = (
            "    Vlan    Mac Address         Type        Port\n"
            "    ----    -----------         ----        ----\n"
            "     1      00:08:a2:09:78:fa   Dynamic     gi24\n"
            "\n"
            "Total Mac Addresses for this criterion: 1\n"
        )
        entries = parse_show_mac_address_table(raw)
        assert len(entries) == 1
