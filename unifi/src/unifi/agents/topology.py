# SPDX-License-Identifier: MIT
"""Topology agent -- orchestrates topology tools into a complete site scan.

Calls the topology MCP tools (list_devices, get_vlans, get_uplinks)
and formats the results into a unified report using OX formatters.

When ``UNIFI_API_KEY`` is configured, the agent first queries the Cloud V1
API to discover available sites.  If only one site exists, it proceeds
with the scan automatically.  If multiple sites are found, it returns a
site list and asks the operator to specify which site to scan.

This is the backend for the ``unifi scan`` command.
"""

from __future__ import annotations

import logging
import os

from unifi.errors import AuthenticationError
from unifi.output import format_summary, format_table
from unifi.tools.topology import (
    unifi__topology__get_uplinks,
    unifi__topology__get_vlans,
    unifi__topology__list_devices,
    unifi__topology__list_sites,
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


def _has_cloud_api_key() -> bool:
    """Return True if ``UNIFI_API_KEY`` is set and non-empty."""
    return bool(os.environ.get("UNIFI_API_KEY", "").strip())


def _format_site_list(sites: list[dict[str, object]]) -> str:
    """Format a list of sites as a table for the operator to choose from.

    Returns a markdown report with a site table and a prompt to specify
    which site to scan.
    """
    sections: list[str] = []

    sections.append(
        format_summary(
            "Multiple Sites Found",
            {"Sites": len(sites)},
            detail=(
                "Multiple UniFi sites are available. "
                "Please specify which site to scan by providing the site name "
                "or ID.\n\n"
                'Example: ``unifi scan`` with ``site_id="<site name>"``'
            ),
        )
    )

    if sites:
        site_rows = [
            [
                str(s.get("name", "")),
                str(s.get("site_id", "")),
                str(s.get("description", "")),
                str(s.get("device_count", 0)),
                str(s.get("client_count", 0)),
            ]
            for s in sites
        ]
        sections.append(
            format_table(
                headers=["Name", "Site ID", "Description", "Devices", "Clients"],
                rows=site_rows,
                title="Available Sites",
            )
        )

    return "\n".join(sections)


async def scan_site(site_id: str = "default") -> str:
    """Build a complete topology scan of a UniFi site.

    When ``UNIFI_API_KEY`` is configured and the caller uses the default
    site_id (``"default"``):

    - Calls ``list_sites()`` to discover available sites.
    - If exactly one site exists, scans that site automatically.
    - If multiple sites exist, returns a formatted site list asking
      the operator to specify which site to scan.

    When ``UNIFI_API_KEY`` is not configured, or when the caller provides
    an explicit site_id, falls back to single-site mode (Phase 1 behavior).

    Args:
        site_id: The UniFi site ID. Defaults to ``"default"``.

    Returns:
        A formatted markdown report containing device inventory,
        VLAN configuration, and uplink topology -- or a site list
        when multiple sites are discovered and no specific site
        was requested.
    """
    # --- Multi-site discovery (Cloud V1) ---
    if _has_cloud_api_key() and site_id == "default":
        try:
            sites = await unifi__topology__list_sites()
        except AuthenticationError:
            logger.warning(
                "Cloud V1 API key is set but authentication failed. "
                "Falling back to single-site mode.",
                extra={"component": "topology"},
            )
            sites = []

        if len(sites) > 1:
            logger.info(
                "Multiple sites found (%d). Returning site list.",
                len(sites),
                extra={"component": "topology"},
            )
            return _format_site_list(sites)

        if len(sites) == 1:
            # Use the discovered site's name as the site_id for the scan.
            site_id = sites[0].get("name", "default")
            logger.info(
                "Single site discovered: '%s'. Proceeding with scan.",
                site_id,
                extra={"component": "topology"},
            )

    # --- Single-site scan ---
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
