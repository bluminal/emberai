# SPDX-License-Identifier: MIT
"""Topology agent -- orchestrates topology tools into a complete site scan.

Calls the four topology MCP tools (list_devices, get_vlans, get_uplinks)
and formats the results into a unified report using OX formatters.

This is the backend for the ``unifi scan`` command.
"""

from __future__ import annotations

import logging

from unifi.output import format_summary, format_table
from unifi.tools.topology import (
    unifi__topology__get_uplinks,
    unifi__topology__get_vlans,
    unifi__topology__list_devices,
)

logger = logging.getLogger(__name__)


def _format_uptime(seconds: int) -> str:
    """Convert uptime in seconds to a human-readable string.

    Examples:
        >>> _format_uptime(90061)
        '1d 1h 1m'
        >>> _format_uptime(3600)
        '1h 0m'
        >>> _format_uptime(45)
        '0m'
    """
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _format_speed(speed: int | None) -> str:
    """Convert link speed in Mbps to a human-readable string.

    Examples:
        >>> _format_speed(10000)
        '10 Gbps'
        >>> _format_speed(1000)
        '1 Gbps'
        >>> _format_speed(100)
        '100 Mbps'
    """
    if speed is None:
        return ""
    if speed >= 1000:
        return f"{speed // 1000} Gbps"
    return f"{speed} Mbps"


async def scan_site(site_id: str = "default") -> str:
    """Build a complete topology scan of a UniFi site.

    Calls list_devices, get_vlans, and get_uplinks to build a full
    site map. Returns a formatted report using OX formatters.

    This is the backend for the ``unifi scan`` command.

    Args:
        site_id: The UniFi site ID. Defaults to ``"default"``.

    Returns:
        A formatted markdown report containing device inventory,
        VLAN configuration, and uplink topology.
    """
    devices = await unifi__topology__list_devices(site_id)
    vlans = await unifi__topology__get_vlans(site_id)
    uplinks = await unifi__topology__get_uplinks(site_id)

    logger.info(
        "Site scan complete: %d devices, %d VLANs, %d uplinks",
        len(devices),
        len(vlans),
        len(uplinks),
        extra={"component": "topology"},
    )

    sections: list[str] = []

    # --- Summary ---
    sections.append(
        format_summary(
            "Site Scan Complete",
            {
                "Devices": len(devices),
                "VLANs": len(vlans),
                "Uplinks": len(uplinks),
            },
        )
    )

    # --- Device table ---
    if devices:
        device_rows = [
            [
                d.get("name", ""),
                d.get("model", ""),
                d.get("ip", ""),
                d.get("status", ""),
                d.get("firmware", ""),
                _format_uptime(d.get("uptime", 0)),
            ]
            for d in devices
        ]
        sections.append(
            format_table(
                headers=["Name", "Model", "IP", "Status", "Firmware", "Uptime"],
                rows=device_rows,
                title="Devices",
            )
        )

    # --- VLAN table ---
    if vlans:
        vlan_rows = [
            [
                v.get("name", ""),
                str(v.get("vlan_id", "")),
                v.get("subnet", ""),
                "Yes" if v.get("dhcp_enabled") else "No",
                v.get("purpose", ""),
            ]
            for v in vlans
        ]
        sections.append(
            format_table(
                headers=["Name", "VLAN ID", "Subnet", "DHCP", "Purpose"],
                rows=vlan_rows,
                title="VLANs",
            )
        )

    # --- Uplink table ---
    if uplinks:
        uplink_rows = [
            [
                f"{u.get('device_name', '')} -> {u.get('uplink_device_name', '')}",
                str(u.get("uplink_port", "")),
                _format_speed(u.get("speed")),
                u.get("uplink_type", ""),
            ]
            for u in uplinks
        ]
        sections.append(
            format_table(
                headers=["Device -> Parent", "Port", "Speed", "Type"],
                rows=uplink_rows,
                title="Uplinks",
            )
        )

    return "\n".join(sections)
