# SPDX-License-Identifier: MIT
"""Traffic skill MCP tools -- bandwidth, DPI, port stats, and WAN usage.

Provides MCP tools for inspecting UniFi network traffic patterns,
application-level DPI breakdowns, per-port switch statistics, and
historical WAN usage via the Local Gateway API.
"""

from __future__ import annotations

import logging
from typing import Any

from unifi.server import mcp_server
from unifi.tools._client_factory import get_local_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


_get_client = get_local_client  # Shared factory with credential validation


# ---------------------------------------------------------------------------
# Tool 1: Get Bandwidth
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__traffic__get_bandwidth(
    site_id: str = "default",
    hours: int = 24,
) -> dict[str, Any]:
    """Get WAN and LAN throughput history for a UniFi site.

    Returns current bandwidth rates and historical throughput data
    for both WAN and LAN interfaces over the specified time window.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
        hours: Number of hours of history to retrieve. Defaults to 24.
    """
    client = _get_client()
    try:
        # Get health data for current rates
        health_normalized = await client.get_normalized(
            f"/api/s/{site_id}/stat/health",
        )

        # Get hourly site stats for history
        stat_normalized = await client.get_normalized(
            f"/api/s/{site_id}/stat/report/hourly.site",
        )
    finally:
        await client.close()

    # Extract current WAN/LAN rates from health subsystems
    wan_rx_mbps: float = 0.0
    wan_tx_mbps: float = 0.0
    lan_rx_mbps: float = 0.0
    lan_tx_mbps: float = 0.0

    for sub in health_normalized.data:
        subsystem = sub.get("subsystem", "")
        if subsystem == "wan":
            # Bytes/sec to Mbps
            wan_rx_mbps = _bytes_to_mbps(sub.get("rx_bytes-r", 0))
            wan_tx_mbps = _bytes_to_mbps(sub.get("tx_bytes-r", 0))
        elif subsystem == "lan":
            lan_rx_mbps = _bytes_to_mbps(sub.get("rx_bytes-r", 0))
            lan_tx_mbps = _bytes_to_mbps(sub.get("tx_bytes-r", 0))

    # Build history from hourly stats (limit to requested hours)
    history: list[dict[str, Any]] = []
    for entry in stat_normalized.data[-hours:]:
        history.append(
            {
                "timestamp": entry.get("time", entry.get("datetime")),
                "wan_rx_bytes": entry.get("wan-rx_bytes", 0),
                "wan_tx_bytes": entry.get("wan-tx_bytes", 0),
                "lan_rx_bytes": entry.get("lan-rx_bytes", 0),
                "lan_tx_bytes": entry.get("lan-tx_bytes", 0),
            }
        )

    result: dict[str, Any] = {
        "wan": {
            "rx_mbps": round(wan_rx_mbps, 2),
            "tx_mbps": round(wan_tx_mbps, 2),
            "history": history,
        },
        "lan": {
            "rx_mbps": round(lan_rx_mbps, 2),
            "tx_mbps": round(lan_tx_mbps, 2),
        },
    }

    logger.info(
        "Retrieved bandwidth data for site '%s': WAN rx=%.1f Mbps, tx=%.1f Mbps",
        site_id,
        wan_rx_mbps,
        wan_tx_mbps,
        extra={"component": "traffic"},
    )

    return result


def _bytes_to_mbps(bytes_per_sec: int | float) -> float:
    """Convert bytes/sec to megabits/sec."""
    return (bytes_per_sec * 8) / 1_000_000


# ---------------------------------------------------------------------------
# Tool 2: Get DPI Stats
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__traffic__get_dpi_stats(
    site_id: str = "default",
) -> list[dict[str, Any]]:
    """Get application-level DPI (Deep Packet Inspection) breakdown.

    Returns traffic statistics grouped by application and category,
    including bytes transferred and session counts.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(
            f"/api/s/{site_id}/stat/sitedpi",
        )
    finally:
        await client.close()

    # The DPI endpoint returns nested structures; flatten into a list
    dpi_entries: list[dict[str, Any]] = []

    for raw in normalized.data:
        # Handle both flat and nested DPI response formats
        by_app = raw.get("by_app", [])
        by_cat = raw.get("by_cat", [])

        if by_app:
            for app_entry in by_app:
                dpi_entries.append(
                    {
                        "application": app_entry.get("app", app_entry.get("name", "")),
                        "category": app_entry.get("cat", ""),
                        "tx_bytes": app_entry.get("tx_bytes", 0),
                        "rx_bytes": app_entry.get("rx_bytes", 0),
                        "session_count": app_entry.get("clients", app_entry.get("sessions", 0)),
                    }
                )
        elif by_cat:
            for cat_entry in by_cat:
                dpi_entries.append(
                    {
                        "application": "",
                        "category": cat_entry.get("cat", cat_entry.get("name", "")),
                        "tx_bytes": cat_entry.get("tx_bytes", 0),
                        "rx_bytes": cat_entry.get("rx_bytes", 0),
                        "session_count": cat_entry.get("clients", cat_entry.get("sessions", 0)),
                    }
                )
        elif not by_app and not by_cat:
            # Flat entry format
            dpi_entries.append(
                {
                    "application": raw.get("app", raw.get("name", "")),
                    "category": raw.get("cat", raw.get("category", "")),
                    "tx_bytes": raw.get("tx_bytes", 0),
                    "rx_bytes": raw.get("rx_bytes", 0),
                    "session_count": raw.get("clients", raw.get("sessions", 0)),
                }
            )

    logger.info(
        "Retrieved %d DPI entries for site '%s'",
        len(dpi_entries),
        site_id,
        extra={"component": "traffic"},
    )

    return dpi_entries


# ---------------------------------------------------------------------------
# Tool 3: Get Port Stats
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__traffic__get_port_stats(
    device_id: str,
    site_id: str = "default",
) -> list[dict[str, Any]]:
    """Get per-port traffic statistics for a switch or gateway.

    Returns tx/rx bytes, error counts, uplink status, and PoE power
    consumption for each physical port on the device.

    Args:
        device_id: The device MAC address or ID.
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        raw_device = await client.get_single(
            f"/api/s/{site_id}/stat/device/{device_id}",
        )
    finally:
        await client.close()

    port_table = raw_device.get("port_table", [])

    ports: list[dict[str, Any]] = []
    for port in port_table:
        port_entry: dict[str, Any] = {
            "port_idx": port.get("port_idx"),
            "name": port.get("name", f"Port {port.get('port_idx', '?')}"),
            "tx_bytes": port.get("tx_bytes", 0),
            "rx_bytes": port.get("rx_bytes", 0),
            "tx_errors": port.get("tx_errors", 0),
            "rx_errors": port.get("rx_errors", 0),
            "is_uplink": port.get("is_uplink", False),
            "poe_power_w": port.get("poe_power"),
        }
        ports.append(port_entry)

    logger.info(
        "Retrieved %d port stats for device '%s'",
        len(ports),
        device_id,
        extra={"component": "traffic"},
    )

    return ports


# ---------------------------------------------------------------------------
# Tool 4: Get WAN Usage
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__traffic__get_wan_usage(
    site_id: str = "default",
    days: int = 30,
) -> list[dict[str, Any]]:
    """Get daily WAN usage history for a UniFi site.

    Returns daily download and upload totals in gigabytes over
    the specified number of days.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
        days: Number of days of history to retrieve. Defaults to 30.
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(
            f"/api/s/{site_id}/stat/report/daily.site",
        )
    finally:
        await client.close()

    # Take the last N days of data
    daily_data = normalized.data[-days:]

    usage: list[dict[str, Any]] = []
    for entry in daily_data:
        download_bytes = entry.get("wan-rx_bytes", 0)
        upload_bytes = entry.get("wan-tx_bytes", 0)

        usage.append(
            {
                "date": entry.get("time", entry.get("datetime", "")),
                "download_gb": round(download_bytes / 1_073_741_824, 2),
                "upload_gb": round(upload_bytes / 1_073_741_824, 2),
            }
        )

    logger.info(
        "Retrieved %d days of WAN usage for site '%s'",
        len(usage),
        site_id,
        extra={"component": "traffic"},
    )

    return usage
