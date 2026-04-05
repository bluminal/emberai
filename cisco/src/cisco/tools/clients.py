# SPDX-License-Identifier: MIT
"""MAC address table tools for Cisco SG-300.

Provides MAC address table listing, lookup by MAC, VLAN, and port
via SSH CLI commands.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from cisco.cache import CacheTTL, TTLCache
from cisco.errors import AuthenticationError, NetworkError, SSHCommandError, ValidationError
from cisco.models.validators import normalize_mac
from cisco.parsers import parse_show_mac_address_table
from cisco.server import mcp_server
from cisco.ssh.client import get_client

logger = logging.getLogger(__name__)

_cache = TTLCache(max_size=100, default_ttl=30.0)

# Valid port format: gi1-gi24, fa1-fa24, Po1-Po8, te1-te4
_PORT_RE = re.compile(r"^(gi|fa|Po|te)\d+$", re.IGNORECASE)


def _validate_port(port: str) -> str:
    """Validate a port identifier format."""
    if not _PORT_RE.match(port):
        raise ValidationError(
            f"Invalid port format: {port!r}. "
            f"Expected formats: gi1-gi24, fa1-fa24, Po1-Po8, te1-te4",
            details={"port": port},
        )
    return port


@mcp_server.tool()
async def cisco__clients__list_mac_table() -> list[dict[str, Any]]:
    """List all MAC address table entries.

    Returns a list of dicts, each with keys: mac, vlan_id, interface, entry_type.
    """
    try:
        client = get_client()
    except AuthenticationError as exc:
        return [{"error": str(exc), "hint": exc.retry_hint}]

    async def _fetch() -> list[dict[str, Any]]:
        await client.connect()
        raw = await client.send_command("show mac address-table")
        entries = parse_show_mac_address_table(raw)
        return [dict(e.model_dump()) for e in entries]

    try:
        result: list[dict[str, Any]] = await _cache.get_or_fetch(
            "clients:mac_table",
            fetcher=_fetch,
            ttl=CacheTTL.MAC_TABLE,
        )
        return result
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to list MAC table: %s", exc)
        return [{"error": str(exc), "hint": getattr(exc, "retry_hint", None)}]


@mcp_server.tool()
async def cisco__clients__find_mac(mac: str) -> list[dict[str, Any]]:
    """Find a specific MAC address in the table.

    Performs a case-insensitive search, normalizing the input MAC to
    colon-separated lowercase format before matching.

    Parameters
    ----------
    mac:
        MAC address in any common format (aa:bb:cc:dd:ee:ff,
        aa-bb-cc-dd-ee-ff, aabb.ccdd.eeff).

    Returns a list of matching dicts with keys: mac, vlan_id, interface, entry_type.
    """
    try:
        normalized = normalize_mac(mac)
    except ValueError:
        return [{"error": f"Invalid MAC address format: {mac!r}"}]

    # Fetch the full table (uses cache from list_mac_table)
    all_entries: list[dict[str, Any]] = await cisco__clients__list_mac_table()

    # Check for error responses
    if all_entries and "error" in all_entries[0]:
        return all_entries

    # Filter by normalized MAC
    return [entry for entry in all_entries if entry.get("mac") == normalized]


@mcp_server.tool()
async def cisco__clients__list_mac_by_vlan(vlan_id: int) -> list[dict[str, Any]]:
    """List MAC addresses on a specific VLAN.

    Parameters
    ----------
    vlan_id:
        VLAN ID to filter by (1-4094).

    Returns a list of dicts with keys: mac, vlan_id, interface, entry_type.
    """
    if not 1 <= vlan_id <= 4094:
        return [{"error": f"Invalid VLAN ID: {vlan_id}. Must be between 1 and 4094."}]

    try:
        client = get_client()
    except AuthenticationError as exc:
        return [{"error": str(exc), "hint": exc.retry_hint}]

    try:
        await client.connect()
        raw = await client.send_command(f"show mac address-table vlan {vlan_id}")
        entries = parse_show_mac_address_table(raw)
        return [dict(e.model_dump()) for e in entries]
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to list MAC table for VLAN %d: %s", vlan_id, exc)
        return [{"error": str(exc), "hint": getattr(exc, "retry_hint", None)}]


@mcp_server.tool()
async def cisco__clients__list_mac_by_port(port: str) -> list[dict[str, Any]]:
    """List MAC addresses on a specific port.

    Parameters
    ----------
    port:
        Port identifier (e.g. gi1, Po1, fa2, te1).

    Returns a list of dicts with keys: mac, vlan_id, interface, entry_type.
    """
    try:
        validated_port = _validate_port(port)
    except ValidationError as exc:
        return [{"error": str(exc)}]

    try:
        client = get_client()
    except AuthenticationError as exc:
        return [{"error": str(exc), "hint": exc.retry_hint}]

    try:
        await client.connect()
        raw = await client.send_command(
            f"show mac address-table interface {validated_port}"
        )
        entries = parse_show_mac_address_table(raw)
        return [dict(e.model_dump()) for e in entries]
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to list MAC table for port %s: %s", port, exc)
        return [{"error": str(exc), "hint": getattr(exc, "retry_hint", None)}]
