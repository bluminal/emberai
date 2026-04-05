# SPDX-License-Identifier: MIT
"""Mappers that convert raw SNMP walk results into Pydantic models.

Each mapper function takes pre-fetched walk data (keyed by OID column)
and correlates rows by their interface index (the trailing OID component)
to produce typed model instances.

Usage::

    from cisco.snmp.oids import IF_MIB, Q_BRIDGE_MIB, LLDP_MIB
    from cisco.snmp.mappers import (
        map_interface_counters,
        map_mac_table,
        map_lldp_neighbors,
    )

    # Fetch walks via SNMP client, then map:
    counters = map_interface_counters({
        "ifDescr": await client.walk(IF_MIB.ifDescr),
        "ifInOctets": await client.walk(IF_MIB.ifInOctets),
        ...
    })
"""

from __future__ import annotations

import logging
from typing import Any

from cisco.models import InterfaceCounters, LLDPNeighbor, MACEntry
from cisco.models.validators import normalize_mac

logger = logging.getLogger(__name__)


def _extract_index(oid: str, base_oid: str) -> str:
    """Extract the trailing index component(s) from a full OID.

    Parameters
    ----------
    oid:
        Full OID string returned by an SNMP walk
        (e.g. ``"1.3.6.1.2.1.2.2.1.2.10101"``).
    base_oid:
        The base (column) OID that was walked
        (e.g. ``"1.3.6.1.2.1.2.2.1.2"``).

    Returns
    -------
    str
        The index portion (e.g. ``"10101"``).
    """
    prefix = base_oid + "."
    if oid.startswith(prefix):
        return oid[len(prefix) :]
    return oid


def _index_walk(
    walk_results: list[tuple[str, Any]],
    base_oid: str,
) -> dict[str, Any]:
    """Build an {index: value} dict from a raw walk result list.

    Parameters
    ----------
    walk_results:
        List of ``(oid_string, value)`` tuples from :meth:`CiscoSNMPClient.walk`.
    base_oid:
        The base OID that was walked, used to strip the prefix.

    Returns
    -------
    dict[str, Any]
        Mapping of interface index to SNMP value.
    """
    indexed: dict[str, Any] = {}
    for oid, value in walk_results:
        idx = _extract_index(oid, base_oid)
        indexed[idx] = value
    return indexed


def _to_int(value: Any) -> int:
    """Coerce an SNMP value to a Python int.

    pysnmp returns Counter32, Integer32, Gauge32, etc. which all support
    ``int()`` conversion.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_str(value: Any) -> str:
    """Coerce an SNMP value to a Python str.

    OctetString values use ``prettyPrint()`` when available; otherwise
    falls back to ``str()``.
    """
    if hasattr(value, "prettyPrint"):
        return str(value.prettyPrint())
    return str(value)


# ---------------------------------------------------------------------------
# Interface counters
# ---------------------------------------------------------------------------


def map_interface_counters(
    walk_results: dict[str, list[tuple[str, Any]]],
) -> list[InterfaceCounters]:
    """Map SNMP IF-MIB walks into :class:`~cisco.models.InterfaceCounters`.

    Parameters
    ----------
    walk_results:
        A dict keyed by column name with the corresponding walk output.
        Expected keys: ``"ifDescr"``, ``"ifInOctets"``, ``"ifOutOctets"``,
        ``"ifInErrors"``, ``"ifOutErrors"``, ``"ifInDiscards"``,
        ``"ifOutDiscards"``, ``"ifInUcastPkts"``, ``"ifOutUcastPkts"``.

        The walk list values are ``(oid_string, value)`` tuples as returned
        by :meth:`CiscoSNMPClient.walk`.

    Returns
    -------
    list[InterfaceCounters]
        One entry per interface index found in the ``ifDescr`` walk.
    """
    from cisco.snmp.oids import IF_MIB

    descr_idx = _index_walk(walk_results.get("ifDescr", []), IF_MIB.ifDescr)
    in_octets_idx = _index_walk(walk_results.get("ifInOctets", []), IF_MIB.ifInOctets)
    out_octets_idx = _index_walk(walk_results.get("ifOutOctets", []), IF_MIB.ifOutOctets)
    in_errors_idx = _index_walk(walk_results.get("ifInErrors", []), IF_MIB.ifInErrors)
    out_errors_idx = _index_walk(walk_results.get("ifOutErrors", []), IF_MIB.ifOutErrors)
    in_discards_idx = _index_walk(walk_results.get("ifInDiscards", []), IF_MIB.ifInDiscards)
    out_discards_idx = _index_walk(walk_results.get("ifOutDiscards", []), IF_MIB.ifOutDiscards)
    in_pkts_idx = _index_walk(walk_results.get("ifInUcastPkts", []), IF_MIB.ifInUcastPkts)
    out_pkts_idx = _index_walk(walk_results.get("ifOutUcastPkts", []), IF_MIB.ifOutUcastPkts)

    counters: list[InterfaceCounters] = []
    for idx, descr_val in sorted(descr_idx.items()):
        counters.append(
            InterfaceCounters(
                port=_to_str(descr_val),
                rx_bytes=_to_int(in_octets_idx.get(idx, 0)),
                tx_bytes=_to_int(out_octets_idx.get(idx, 0)),
                rx_errors=_to_int(in_errors_idx.get(idx, 0)),
                tx_errors=_to_int(out_errors_idx.get(idx, 0)),
                rx_discards=_to_int(in_discards_idx.get(idx, 0)),
                tx_discards=_to_int(out_discards_idx.get(idx, 0)),
                rx_packets=_to_int(in_pkts_idx.get(idx, 0)),
                tx_packets=_to_int(out_pkts_idx.get(idx, 0)),
            )
        )

    logger.debug("Mapped %d interface counter entries from SNMP", len(counters))
    return counters


# ---------------------------------------------------------------------------
# MAC address table
# ---------------------------------------------------------------------------


def map_mac_table(
    walk_results: list[tuple[str, Any]],
) -> list[MACEntry]:
    """Map a Q-BRIDGE-MIB dot1qTpFdbPort walk into :class:`~cisco.models.MACEntry`.

    The dot1qTpFdbPort OID encodes both the VLAN ID and the MAC address
    in its index:

        ``<base_oid>.<vlan_id>.<mac_byte1>.<mac_byte2>...<mac_byte6>``

    The value is the bridge port index.

    Parameters
    ----------
    walk_results:
        Raw ``(oid_string, value)`` tuples from walking
        :data:`~cisco.snmp.oids.Q_BRIDGE_MIB.dot1qTpFdbPort`.

    Returns
    -------
    list[MACEntry]
        One entry per MAC address found in the forwarding database.
    """
    from cisco.snmp.oids import Q_BRIDGE_MIB

    base = Q_BRIDGE_MIB.dot1qTpFdbPort
    entries: list[MACEntry] = []

    for oid, value in walk_results:
        suffix = _extract_index(oid, base)
        parts = suffix.split(".")

        # Expect: <vlan_id>.<6 MAC bytes> = 7 parts
        if len(parts) != 7:
            logger.warning("Unexpected dot1qTpFdbPort index format: %s", suffix)
            continue

        try:
            vlan_id = int(parts[0])
            mac_bytes = [int(p) for p in parts[1:7]]
        except ValueError:
            logger.warning("Cannot parse dot1qTpFdbPort index: %s", suffix)
            continue

        mac_hex = ":".join(f"{b:02x}" for b in mac_bytes)
        port_index = _to_int(value)

        entries.append(
            MACEntry(
                mac=normalize_mac(mac_hex),
                vlan_id=vlan_id,
                interface=str(port_index),
                entry_type="dynamic",
            )
        )

    logger.debug("Mapped %d MAC table entries from SNMP", len(entries))
    return entries


# ---------------------------------------------------------------------------
# LLDP neighbors
# ---------------------------------------------------------------------------


def map_lldp_neighbors(
    walk_results: dict[str, list[tuple[str, Any]]],
) -> list[LLDPNeighbor]:
    """Map LLDP-MIB walks into :class:`~cisco.models.LLDPNeighbor`.

    LLDP remote table OIDs are indexed by a three-part key:

        ``<base_oid>.<time_mark>.<local_port_num>.<remote_index>``

    This function correlates ``lldpRemSysName`` and ``lldpRemPortId``
    walks by their shared ``(time_mark, local_port, index)`` key.

    Parameters
    ----------
    walk_results:
        A dict keyed by column name with the corresponding walk output.
        Expected keys: ``"lldpRemSysName"``, ``"lldpRemPortId"``.

    Returns
    -------
    list[LLDPNeighbor]
        One entry per discovered LLDP neighbor.
    """
    from cisco.snmp.oids import LLDP_MIB

    sys_name_idx = _index_walk(
        walk_results.get("lldpRemSysName", []),
        LLDP_MIB.lldpRemSysName,
    )
    port_id_idx = _index_walk(
        walk_results.get("lldpRemPortId", []),
        LLDP_MIB.lldpRemPortId,
    )

    neighbors: list[LLDPNeighbor] = []
    for compound_key in sorted(sys_name_idx.keys()):
        # compound_key is "<time_mark>.<local_port>.<remote_index>"
        key_parts = compound_key.split(".")
        if len(key_parts) < 3:
            logger.warning("Unexpected LLDP index format: %s", compound_key)
            continue

        # The local_port is the second component
        local_port = key_parts[1]

        remote_device = _to_str(sys_name_idx.get(compound_key, ""))
        remote_port = _to_str(port_id_idx.get(compound_key, ""))

        if not remote_device:
            continue

        neighbors.append(
            LLDPNeighbor(
                local_port=local_port,
                remote_device=remote_device,
                remote_port=remote_port,
                capabilities="",
            )
        )

    logger.debug("Mapped %d LLDP neighbor entries from SNMP", len(neighbors))
    return neighbors
