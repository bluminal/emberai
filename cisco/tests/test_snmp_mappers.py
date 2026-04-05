"""Tests for SNMP result mappers.

All tests use synthetic SNMP walk data that mimics pysnmp output format.
No real SNMP connections are made.

Covers:
- _extract_index() -- OID suffix extraction
- _index_walk() -- build {index: value} dict from walk results
- _to_int() -- SNMP value to int coercion (including failures)
- _to_str() -- SNMP value to str coercion (with and without prettyPrint)
- map_interface_counters() -- IF-MIB walks to InterfaceCounters models
- map_mac_table() -- Q-BRIDGE-MIB walk to MACEntry models
- map_lldp_neighbors() -- LLDP-MIB walks to LLDPNeighbor models
- Edge cases: empty walks, missing columns, malformed OID indices
"""

from __future__ import annotations

from unittest.mock import MagicMock

from cisco.models import InterfaceCounters, LLDPNeighbor, MACEntry
from cisco.snmp.mappers import (
    _extract_index,
    _index_walk,
    _to_int,
    _to_str,
    map_interface_counters,
    map_lldp_neighbors,
    map_mac_table,
)
from cisco.snmp.oids import IF_MIB, LLDP_MIB, Q_BRIDGE_MIB

# ---------------------------------------------------------------------------
# Helpers for building mock SNMP data
# ---------------------------------------------------------------------------


def _mock_snmp_val(value: object) -> MagicMock:
    """Create a mock SNMP value that supports int() and prettyPrint()."""
    mock = MagicMock()
    mock.__int__ = lambda self: int(value)  # type: ignore[arg-type]
    mock.__str__ = lambda self: str(value)
    mock.prettyPrint = MagicMock(return_value=str(value))
    return mock


def _walk_rows(
    base_oid: str,
    entries: dict[str, object],
) -> list[tuple[str, MagicMock]]:
    """Build a mock walk result list from {index: value} mapping."""
    return [(f"{base_oid}.{idx}", _mock_snmp_val(v)) for idx, v in entries.items()]


# ---------------------------------------------------------------------------
# _extract_index
# ---------------------------------------------------------------------------


class TestExtractIndex:
    """Extract trailing index from a full OID."""

    def test_simple_index(self) -> None:
        assert _extract_index("1.3.6.1.2.1.2.2.1.2.10101", "1.3.6.1.2.1.2.2.1.2") == "10101"

    def test_compound_index(self) -> None:
        result = _extract_index(
            "1.0.8802.1.1.2.1.4.1.1.9.0.49.1",
            "1.0.8802.1.1.2.1.4.1.1.9",
        )
        assert result == "0.49.1"

    def test_no_match_returns_full_oid(self) -> None:
        """When base_oid doesn't match, the full OID is returned."""
        result = _extract_index("1.3.6.1.2.1.999.1", "1.3.6.1.2.1.2.2.1.2")
        assert result == "1.3.6.1.2.1.999.1"

    def test_exact_match_no_dot_returns_full_oid(self) -> None:
        """Base OID equals the full OID (no trailing dot) returns the OID itself."""
        result = _extract_index("1.3.6.1.2.1.2.2.1.2", "1.3.6.1.2.1.2.2.1.2")
        assert result == "1.3.6.1.2.1.2.2.1.2"


# ---------------------------------------------------------------------------
# _index_walk
# ---------------------------------------------------------------------------


class TestIndexWalk:
    """Build {index: value} dict from walk results."""

    def test_basic_indexing(self) -> None:
        walk_data = [
            ("1.3.6.1.2.1.2.2.1.2.1", "val1"),
            ("1.3.6.1.2.1.2.2.1.2.2", "val2"),
        ]
        result = _index_walk(walk_data, "1.3.6.1.2.1.2.2.1.2")
        assert result == {"1": "val1", "2": "val2"}

    def test_empty_walk(self) -> None:
        assert _index_walk([], "1.3.6.1.2.1.2.2.1.2") == {}


# ---------------------------------------------------------------------------
# _to_int
# ---------------------------------------------------------------------------


class TestToInt:
    """SNMP value to int coercion."""

    def test_normal_int(self) -> None:
        mock = _mock_snmp_val(42)
        assert _to_int(mock) == 42

    def test_zero(self) -> None:
        mock = _mock_snmp_val(0)
        assert _to_int(mock) == 0

    def test_large_counter(self) -> None:
        mock = _mock_snmp_val(4294967295)
        assert _to_int(mock) == 4294967295

    def test_non_numeric_returns_zero(self) -> None:
        assert _to_int("not a number") == 0

    def test_none_returns_zero(self) -> None:
        assert _to_int(None) == 0

    def test_plain_int(self) -> None:
        """Plain Python int works too."""
        assert _to_int(100) == 100


# ---------------------------------------------------------------------------
# _to_str
# ---------------------------------------------------------------------------


class TestToStr:
    """SNMP value to str coercion."""

    def test_with_pretty_print(self) -> None:
        mock = MagicMock()
        mock.prettyPrint.return_value = "GigabitEthernet1/0/1"
        assert _to_str(mock) == "GigabitEthernet1/0/1"

    def test_without_pretty_print(self) -> None:
        """Falls back to str() when prettyPrint is not available."""
        assert _to_str("plain string") == "plain string"

    def test_int_value(self) -> None:
        assert _to_str(42) == "42"


# ---------------------------------------------------------------------------
# map_interface_counters
# ---------------------------------------------------------------------------


class TestMapInterfaceCounters:
    """Convert IF-MIB walk results to InterfaceCounters models."""

    def _build_walk_data(self) -> dict[str, list[tuple[str, MagicMock]]]:
        """Build realistic IF-MIB walk data for 2 interfaces."""
        return {
            "ifDescr": _walk_rows(IF_MIB.ifDescr, {"1": "gi1", "2": "gi2"}),
            "ifInOctets": _walk_rows(IF_MIB.ifInOctets, {"1": 1000, "2": 2000}),
            "ifOutOctets": _walk_rows(IF_MIB.ifOutOctets, {"1": 500, "2": 1500}),
            "ifInErrors": _walk_rows(IF_MIB.ifInErrors, {"1": 0, "2": 3}),
            "ifOutErrors": _walk_rows(IF_MIB.ifOutErrors, {"1": 0, "2": 1}),
            "ifInDiscards": _walk_rows(IF_MIB.ifInDiscards, {"1": 0, "2": 5}),
            "ifOutDiscards": _walk_rows(IF_MIB.ifOutDiscards, {"1": 0, "2": 2}),
            "ifInUcastPkts": _walk_rows(IF_MIB.ifInUcastPkts, {"1": 100, "2": 200}),
            "ifOutUcastPkts": _walk_rows(IF_MIB.ifOutUcastPkts, {"1": 50, "2": 150}),
        }

    def test_maps_two_interfaces(self) -> None:
        results = map_interface_counters(self._build_walk_data())
        assert len(results) == 2

    def test_returns_interface_counters_models(self) -> None:
        results = map_interface_counters(self._build_walk_data())
        assert all(isinstance(r, InterfaceCounters) for r in results)

    def test_port_names_extracted(self) -> None:
        results = map_interface_counters(self._build_walk_data())
        ports = [r.port for r in results]
        assert "gi1" in ports
        assert "gi2" in ports

    def test_counter_values_mapped_correctly(self) -> None:
        results = map_interface_counters(self._build_walk_data())
        gi1 = next(r for r in results if r.port == "gi1")
        assert gi1.rx_bytes == 1000
        assert gi1.tx_bytes == 500
        assert gi1.rx_errors == 0
        assert gi1.tx_errors == 0
        assert gi1.rx_discards == 0
        assert gi1.tx_discards == 0
        assert gi1.rx_packets == 100
        assert gi1.tx_packets == 50

    def test_second_interface_values(self) -> None:
        results = map_interface_counters(self._build_walk_data())
        gi2 = next(r for r in results if r.port == "gi2")
        assert gi2.rx_bytes == 2000
        assert gi2.tx_bytes == 1500
        assert gi2.rx_errors == 3
        assert gi2.tx_errors == 1

    def test_empty_walk_data(self) -> None:
        results = map_interface_counters({})
        assert results == []

    def test_missing_counter_columns_default_to_zero(self) -> None:
        """If a counter column is missing, values default to 0."""
        walk_data = {
            "ifDescr": _walk_rows(IF_MIB.ifDescr, {"1": "gi1"}),
            # All other columns are missing
        }
        results = map_interface_counters(walk_data)
        assert len(results) == 1
        gi1 = results[0]
        assert gi1.port == "gi1"
        assert gi1.rx_bytes == 0
        assert gi1.tx_bytes == 0
        assert gi1.rx_errors == 0
        assert gi1.tx_errors == 0
        assert gi1.rx_packets == 0
        assert gi1.tx_packets == 0

    def test_sorted_by_index(self) -> None:
        """Results are sorted by interface index."""
        walk_data = {
            "ifDescr": _walk_rows(IF_MIB.ifDescr, {"3": "gi3", "1": "gi1", "2": "gi2"}),
        }
        results = map_interface_counters(walk_data)
        assert [r.port for r in results] == ["gi1", "gi2", "gi3"]


# ---------------------------------------------------------------------------
# map_mac_table
# ---------------------------------------------------------------------------


class TestMapMacTable:
    """Convert Q-BRIDGE-MIB walk results to MACEntry models."""

    def _build_walk_data(self) -> list[tuple[str, MagicMock]]:
        """Build realistic dot1qTpFdbPort walk data.

        OID format: <base>.<vlan_id>.<mac_byte1>.<mac_byte2>...<mac_byte6>
        Value: bridge port number
        """
        base = Q_BRIDGE_MIB.dot1qTpFdbPort
        return [
            # VLAN 1, MAC 00:08:a2:09:78:fa on port 5
            (f"{base}.1.0.8.162.9.120.250", _mock_snmp_val(5)),
            # VLAN 10, MAC aa:bb:cc:dd:ee:ff on port 12
            (f"{base}.10.170.187.204.221.238.255", _mock_snmp_val(12)),
        ]

    def test_maps_two_entries(self) -> None:
        results = map_mac_table(self._build_walk_data())
        assert len(results) == 2

    def test_returns_mac_entry_models(self) -> None:
        results = map_mac_table(self._build_walk_data())
        assert all(isinstance(r, MACEntry) for r in results)

    def test_vlan_id_extracted(self) -> None:
        results = map_mac_table(self._build_walk_data())
        vlans = {r.vlan_id for r in results}
        assert vlans == {1, 10}

    def test_mac_address_normalized(self) -> None:
        results = map_mac_table(self._build_walk_data())
        # MAC bytes 0,8,162,9,120,250 -> 00:08:a2:09:78:fa
        entry_v1 = next(r for r in results if r.vlan_id == 1)
        assert entry_v1.mac == "00:08:a2:09:78:fa"

    def test_mac_address_second_entry(self) -> None:
        results = map_mac_table(self._build_walk_data())
        # MAC bytes 170,187,204,221,238,255 -> aa:bb:cc:dd:ee:ff
        entry_v10 = next(r for r in results if r.vlan_id == 10)
        assert entry_v10.mac == "aa:bb:cc:dd:ee:ff"

    def test_port_index_mapped(self) -> None:
        results = map_mac_table(self._build_walk_data())
        entry_v1 = next(r for r in results if r.vlan_id == 1)
        assert entry_v1.interface == "5"

    def test_entry_type_is_dynamic(self) -> None:
        results = map_mac_table(self._build_walk_data())
        assert all(r.entry_type == "dynamic" for r in results)

    def test_empty_walk(self) -> None:
        results = map_mac_table([])
        assert results == []

    def test_malformed_index_skipped(self) -> None:
        """Entries with wrong number of index components are skipped."""
        base = Q_BRIDGE_MIB.dot1qTpFdbPort
        walk_data = [
            # Only 5 parts instead of 7 (vlan + 6 MAC bytes)
            (f"{base}.1.0.8.162.9.120", _mock_snmp_val(5)),
        ]
        results = map_mac_table(walk_data)
        assert results == []

    def test_non_numeric_index_skipped(self) -> None:
        """Entries with non-numeric index components are skipped."""
        base = Q_BRIDGE_MIB.dot1qTpFdbPort
        walk_data = [
            (f"{base}.abc.0.8.162.9.120.250", _mock_snmp_val(5)),
        ]
        results = map_mac_table(walk_data)
        assert results == []


# ---------------------------------------------------------------------------
# map_lldp_neighbors
# ---------------------------------------------------------------------------


class TestMapLLDPNeighbors:
    """Convert LLDP-MIB walk results to LLDPNeighbor models."""

    def _build_walk_data(self) -> dict[str, list[tuple[str, MagicMock]]]:
        """Build realistic LLDP walk data.

        LLDP index format: <base>.<time_mark>.<local_port>.<remote_index>
        """
        return {
            "lldpRemSysName": [
                (f"{LLDP_MIB.lldpRemSysName}.0.49.1", _mock_snmp_val("switch-core")),
                (f"{LLDP_MIB.lldpRemSysName}.0.50.1", _mock_snmp_val("ap-office")),
            ],
            "lldpRemPortId": [
                (f"{LLDP_MIB.lldpRemPortId}.0.49.1", _mock_snmp_val("ge-0/0/1")),
                (f"{LLDP_MIB.lldpRemPortId}.0.50.1", _mock_snmp_val("eth0")),
            ],
        }

    def test_maps_two_neighbors(self) -> None:
        results = map_lldp_neighbors(self._build_walk_data())
        assert len(results) == 2

    def test_returns_lldp_neighbor_models(self) -> None:
        results = map_lldp_neighbors(self._build_walk_data())
        assert all(isinstance(r, LLDPNeighbor) for r in results)

    def test_remote_device_names(self) -> None:
        results = map_lldp_neighbors(self._build_walk_data())
        names = {r.remote_device for r in results}
        assert names == {"switch-core", "ap-office"}

    def test_remote_port_ids(self) -> None:
        results = map_lldp_neighbors(self._build_walk_data())
        core = next(r for r in results if r.remote_device == "switch-core")
        assert core.remote_port == "ge-0/0/1"

    def test_local_port_extracted_from_compound_key(self) -> None:
        """local_port is the second component of the LLDP index."""
        results = map_lldp_neighbors(self._build_walk_data())
        core = next(r for r in results if r.remote_device == "switch-core")
        assert core.local_port == "49"

    def test_capabilities_default_empty(self) -> None:
        results = map_lldp_neighbors(self._build_walk_data())
        assert all(r.capabilities == "" for r in results)

    def test_empty_walk_data(self) -> None:
        results = map_lldp_neighbors({})
        assert results == []

    def test_empty_remote_device_skipped(self) -> None:
        """Neighbors with empty remote device name are skipped."""
        walk_data = {
            "lldpRemSysName": [
                (f"{LLDP_MIB.lldpRemSysName}.0.49.1", _mock_snmp_val("")),
            ],
            "lldpRemPortId": [
                (f"{LLDP_MIB.lldpRemPortId}.0.49.1", _mock_snmp_val("ge-0/0/1")),
            ],
        }
        results = map_lldp_neighbors(walk_data)
        assert results == []

    def test_malformed_compound_key_skipped(self) -> None:
        """Index with fewer than 3 components is skipped."""
        walk_data = {
            "lldpRemSysName": [
                # Only 2 components instead of 3
                (f"{LLDP_MIB.lldpRemSysName}.49", _mock_snmp_val("bad-entry")),
            ],
            "lldpRemPortId": [],
        }
        results = map_lldp_neighbors(walk_data)
        assert results == []

    def test_missing_port_id_defaults_empty(self) -> None:
        """When lldpRemPortId has no matching entry, remote_port is empty."""
        walk_data = {
            "lldpRemSysName": [
                (f"{LLDP_MIB.lldpRemSysName}.0.49.1", _mock_snmp_val("orphan-switch")),
            ],
            "lldpRemPortId": [],
        }
        results = map_lldp_neighbors(walk_data)
        assert len(results) == 1
        assert results[0].remote_port == ""

    def test_sorted_by_compound_key(self) -> None:
        """Results are sorted by compound key."""
        walk_data = {
            "lldpRemSysName": [
                (f"{LLDP_MIB.lldpRemSysName}.0.50.1", _mock_snmp_val("second")),
                (f"{LLDP_MIB.lldpRemSysName}.0.49.1", _mock_snmp_val("first")),
            ],
            "lldpRemPortId": [],
        }
        results = map_lldp_neighbors(walk_data)
        assert results[0].remote_device == "first"
        assert results[1].remote_device == "second"
