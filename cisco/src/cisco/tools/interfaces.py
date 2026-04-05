# SPDX-License-Identifier: MIT
"""Interface and port tools for Cisco SG-300.

Provides port listing, detailed port configuration, and interface
traffic counters via SSH CLI and SNMP.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from cisco.cache import CacheTTL, TTLCache
from cisco.errors import AuthenticationError, NetworkError, SSHCommandError, ValidationError
from cisco.parsers import parse_show_interfaces_status, parse_show_switchport
from cisco.server import mcp_server
from cisco.ssh.client import get_client

logger = logging.getLogger(__name__)

_cache = TTLCache(max_size=100, default_ttl=120.0)

# Valid port format: gi1-gi24, fa1-fa24, Po1-Po8, te1-te4
_PORT_RE = re.compile(r"^(gi|fa|Po|te)\d+$", re.IGNORECASE)


def _validate_port(port: str) -> str:
    """Validate and normalize a port identifier.

    Accepts formats like gi1, Gi1, fa2, Po1, te1.

    Parameters
    ----------
    port:
        The port identifier to validate.

    Returns
    -------
    str
        The validated port string (as-is, case preserved for CLI).

    Raises
    ------
    ValidationError
        If the port format is invalid.
    """
    if not _PORT_RE.match(port):
        raise ValidationError(
            f"Invalid port format: {port!r}. "
            f"Expected formats: gi1-gi24, fa1-fa24, Po1-Po8, te1-te4",
            details={"port": port},
        )
    return port


@mcp_server.tool()
async def cisco__interfaces__list_ports() -> list[dict[str, Any]]:
    """List all switch ports with status.

    Returns a list of dicts, each with keys: id, name, status, speed,
    duplex, vlan_id, mode, description.
    """
    try:
        client = get_client()
    except AuthenticationError as exc:
        return [{"error": str(exc), "hint": exc.retry_hint}]

    async def _fetch() -> list[dict[str, Any]]:
        await client.connect()
        raw = await client.send_command("show interfaces status")
        ports = parse_show_interfaces_status(raw)
        return [dict(p.model_dump()) for p in ports]

    try:
        result: list[dict[str, Any]] = await _cache.get_or_fetch(
            "interfaces:list_ports",
            fetcher=_fetch,
            ttl=CacheTTL.INTERFACES,
        )
        return result
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to list ports: %s", exc)
        return [{"error": str(exc), "hint": getattr(exc, "retry_hint", None)}]


@mcp_server.tool()
async def cisco__interfaces__get_port_detail(port: str) -> dict[str, Any]:
    """Get detailed port config (VLAN, mode, trunk VLANs).

    Parameters
    ----------
    port:
        Port identifier (e.g. gi1, Po1, fa2, te1).

    Returns a dict with keys: id, name, status, speed, duplex, vlan_id,
    mode, description, trunk_allowed_vlans, native_vlan.
    """
    try:
        validated_port = _validate_port(port)
    except ValidationError as exc:
        return {"error": str(exc)}

    try:
        client = get_client()
    except AuthenticationError as exc:
        return {"error": str(exc), "hint": exc.retry_hint}

    try:
        await client.connect()
        raw = await client.send_command(f"show interfaces switchport {validated_port}")
        detail = parse_show_switchport(raw)
        return dict(detail.model_dump())
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to get port detail for %s: %s", port, exc)
        return {"error": str(exc), "hint": getattr(exc, "retry_hint", None)}
    except ValueError as exc:
        return {"error": f"Failed to parse switchport output for {port}: {exc}"}


@mcp_server.tool()
async def cisco__interfaces__get_counters() -> list[dict[str, Any]]:
    """Get interface traffic counters via SNMP.

    Returns a list of dicts, each with keys: port, rx_bytes, tx_bytes,
    rx_packets, tx_packets, rx_errors, tx_errors, rx_discards, tx_discards.

    Requires CISCO_SNMP_COMMUNITY to be configured. Returns an error
    message if SNMP is not available.
    """
    community = os.environ.get("CISCO_SNMP_COMMUNITY", "").strip()
    host = os.environ.get("CISCO_HOST", "").strip()

    if not community:
        return [
            {
                "error": "SNMP not configured",
                "hint": (
                    "Set the CISCO_SNMP_COMMUNITY environment variable "
                    "to enable SNMP polling"
                ),
            }
        ]

    if not host:
        return [
            {
                "error": "CISCO_HOST not configured",
                "hint": "Set the CISCO_HOST environment variable",
            }
        ]

    async def _fetch() -> list[dict[str, Any]]:
        # Lazy import to avoid hard dependency on pysnmp when SNMP is not used
        try:
            from pysnmp.hlapi.v3arch.asyncio import (  # type: ignore[import-untyped]
                CommunityData,
                ObjectIdentity,
                ObjectType,
                SnmpEngine,
                UdpTransportTarget,
                bulkWalkCmd,
            )
        except ImportError:
            return [
                {
                    "error": "pysnmp is not installed",
                    "hint": (
                        "Install pysnmp to enable SNMP counter collection: "
                        "pip install pysnmp"
                    ),
                }
            ]

        from cisco.snmp.oids import IF_MIB

        engine = SnmpEngine()
        transport = await UdpTransportTarget.create((host, 161))
        auth = CommunityData(community, mpModel=1)  # SNMPv2c

        # Walk IF-MIB tables for interface counters
        oid_map: dict[str, str] = {
            IF_MIB.ifDescr: "descr",
            IF_MIB.ifInOctets: "rx_bytes",
            IF_MIB.ifOutOctets: "tx_bytes",
            IF_MIB.ifInUcastPkts: "rx_packets",
            IF_MIB.ifOutUcastPkts: "tx_packets",
            IF_MIB.ifInErrors: "rx_errors",
            IF_MIB.ifOutErrors: "tx_errors",
            IF_MIB.ifInDiscards: "rx_discards",
            IF_MIB.ifOutDiscards: "tx_discards",
        }

        # Collect data per interface index
        if_data: dict[str, dict[str, Any]] = {}

        for oid_base, field_name in oid_map.items():
            try:
                async for (
                    error_indication,
                    error_status,
                    _error_index,
                    var_binds,
                ) in bulkWalkCmd(
                    engine,
                    auth,
                    transport,
                    0,
                    25,
                    ObjectType(ObjectIdentity(oid_base)),
                ):
                    if error_indication or error_status:
                        break
                    for var_bind in var_binds:
                        oid_str = str(var_bind[0])
                        value = var_bind[1]
                        # Extract ifIndex from the OID suffix
                        if_index = oid_str.rsplit(".", 1)[-1]
                        if if_index not in if_data:
                            if_data[if_index] = {}
                        if field_name == "descr":
                            if_data[if_index][field_name] = str(value)
                        else:
                            if_data[if_index][field_name] = int(value)
            except Exception as exc:
                logger.warning("SNMP walk failed for OID %s: %s", oid_base, exc)
                continue

        # Build result list from collected data
        results: list[dict[str, Any]] = []
        for _if_index, data in sorted(if_data.items(), key=lambda x: int(x[0])):
            port_name = data.get("descr", f"if{_if_index}")
            results.append(
                {
                    "port": port_name,
                    "rx_bytes": data.get("rx_bytes", 0),
                    "tx_bytes": data.get("tx_bytes", 0),
                    "rx_packets": data.get("rx_packets", 0),
                    "tx_packets": data.get("tx_packets", 0),
                    "rx_errors": data.get("rx_errors", 0),
                    "tx_errors": data.get("tx_errors", 0),
                    "rx_discards": data.get("rx_discards", 0),
                    "tx_discards": data.get("tx_discards", 0),
                }
            )

        return results

    try:
        result: list[dict[str, Any]] = await _cache.get_or_fetch(
            "interfaces:counters",
            fetcher=_fetch,
            ttl=CacheTTL.INTERFACE_COUNTERS,
        )
        return result
    except Exception as exc:
        logger.error("Failed to get interface counters via SNMP: %s", exc)
        return [
            {
                "error": f"SNMP counter collection failed: {exc}",
                "hint": (
                    "Verify SNMP community string and network access "
                    "to the switch on UDP/161"
                ),
            }
        ]
