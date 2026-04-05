# SPDX-License-Identifier: MIT
"""Topology discovery tools for Cisco SG-300.

Provides device information, VLAN listing, and LLDP neighbor discovery
via SSH CLI commands.
"""

from __future__ import annotations

import logging
from typing import Any

from cisco.cache import CacheTTL, TTLCache
from cisco.errors import AuthenticationError, NetworkError, SSHCommandError
from cisco.parsers import (
    parse_show_lldp_neighbors,
    parse_show_version,
    parse_show_vlan,
)
from cisco.parsers.system import parse_hostname_from_config
from cisco.server import mcp_server
from cisco.ssh.client import get_client

logger = logging.getLogger(__name__)

_cache = TTLCache(max_size=100, default_ttl=300.0)


@mcp_server.tool()
async def cisco__topology__get_device_info() -> dict[str, Any]:
    """Get switch system info (model, firmware, hostname, MAC).

    Returns a dict with keys: hostname, model, firmware_version,
    serial_number, uptime_seconds, mac_address.
    """
    try:
        client = get_client()
    except AuthenticationError as exc:
        return {"error": str(exc), "hint": exc.retry_hint}

    async def _fetch() -> dict[str, Any]:
        await client.connect()
        version_output = await client.send_command("show version")
        config_output = await client.send_command("show running-config")
        hostname = parse_hostname_from_config(config_output)
        info = parse_show_version(version_output, hostname=hostname)
        return dict(info.model_dump())

    try:
        result: dict[str, Any] = await _cache.get_or_fetch(
            "topology:device_info",
            fetcher=_fetch,
            ttl=CacheTTL.SYSTEM_INFO,
        )
        return result
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to get device info: %s", exc)
        return {"error": str(exc), "hint": getattr(exc, "retry_hint", None)}


@mcp_server.tool()
async def cisco__topology__list_vlans() -> list[dict[str, Any]]:
    """List all VLANs configured on the switch.

    Returns a list of dicts, each with keys: id, name, ports, tagged_ports.
    """
    try:
        client = get_client()
    except AuthenticationError as exc:
        return [{"error": str(exc), "hint": exc.retry_hint}]

    async def _fetch() -> list[dict[str, Any]]:
        await client.connect()
        raw = await client.send_command("show vlan")
        vlans = parse_show_vlan(raw)
        return [dict(v.model_dump()) for v in vlans]

    try:
        result: list[dict[str, Any]] = await _cache.get_or_fetch(
            "topology:vlans",
            fetcher=_fetch,
            ttl=CacheTTL.VLANS,
        )
        return result
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to list VLANs: %s", exc)
        return [{"error": str(exc), "hint": getattr(exc, "retry_hint", None)}]


@mcp_server.tool()
async def cisco__topology__get_lldp_neighbors() -> list[dict[str, Any]]:
    """List LLDP neighbors (connected devices).

    Returns a list of dicts, each with keys: local_port, remote_device,
    remote_port, capabilities, remote_ip.
    """
    try:
        client = get_client()
    except AuthenticationError as exc:
        return [{"error": str(exc), "hint": exc.retry_hint}]

    async def _fetch() -> list[dict[str, Any]]:
        await client.connect()
        raw = await client.send_command("show lldp neighbors")
        neighbors = parse_show_lldp_neighbors(raw)
        return [dict(n.model_dump()) for n in neighbors]

    try:
        result: list[dict[str, Any]] = await _cache.get_or_fetch(
            "topology:lldp_neighbors",
            fetcher=_fetch,
            ttl=CacheTTL.LLDP_NEIGHBORS,
        )
        return result
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to get LLDP neighbors: %s", exc)
        return [{"error": str(exc), "hint": getattr(exc, "retry_hint", None)}]
