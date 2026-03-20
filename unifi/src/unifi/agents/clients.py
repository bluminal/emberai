# SPDX-License-Identifier: MIT
"""Clients agent -- orchestrates client tools into a client inventory report.

Calls the client MCP tools (list_clients) with optional filters and
formats the results into a readable report using OX formatters.

This is the backend for the ``unifi clients`` command.
"""

from __future__ import annotations

import logging
from typing import Any

from unifi.output import format_summary, format_table
from unifi.tools.clients import unifi__clients__list_clients

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_bytes(byte_count: int | None) -> str:
    """Convert a byte count to a human-readable string.

    Examples:
        >>> _format_bytes(0)
        '0 B'
        >>> _format_bytes(1024)
        '1.0 KB'
        >>> _format_bytes(1048576)
        '1.0 MB'
        >>> _format_bytes(1073741824)
        '1.0 GB'
    """
    if byte_count is None or byte_count == 0:
        return "0 B"

    units = [("TB", 1 << 40), ("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)]
    for label, threshold in units:
        if byte_count >= threshold:
            return f"{byte_count / threshold:.1f} {label}"
    return f"{byte_count} B"


def _format_signal(rssi: int | None) -> str:
    """Convert RSSI value to a human-readable signal quality string.

    Uses standard dBm ranges:
      - >= 50: Excellent
      - >= 35: Good
      - >= 20: Fair
      - < 20: Poor
      - None: N/A (wired client)

    Args:
        rssi: The RSSI value (higher is better, typically 0-100 range).

    Returns:
        Human-readable signal quality string.
    """
    if rssi is None:
        return ""
    if rssi >= 50:
        return f"{rssi} (Excellent)"
    if rssi >= 35:
        return f"{rssi} (Good)"
    if rssi >= 20:
        return f"{rssi} (Fair)"
    return f"{rssi} (Poor)"


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


def _client_display_name(client: dict[str, Any]) -> str:
    """Return the best available display name for a client."""
    return client.get("hostname") or client.get("client_mac", "unknown")


def _connection_info(client: dict[str, Any]) -> str:
    """Build a connection description string for a client.

    For wireless clients: shows AP MAC and SSID.
    For wired clients: shows switch port.
    """
    if client.get("is_wired"):
        port = client.get("port_id")
        if port is not None:
            return f"Port {port}"
        return "Wired"

    ap = client.get("ap_id", "")
    ssid = client.get("ssid", "")
    if ap and ssid:
        return f"{ap} ({ssid})"
    if ap:
        return ap
    return "Wireless"


def _traffic_summary(client: dict[str, Any]) -> str:
    """Build a compact traffic summary string."""
    tx = client.get("tx_bytes")
    rx = client.get("rx_bytes")
    parts: list[str] = []
    if tx is not None:
        parts.append(f"TX: {_format_bytes(tx)}")
    if rx is not None:
        parts.append(f"RX: {_format_bytes(rx)}")
    return " / ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Client filtering (AP-level filter applied post-fetch)
# ---------------------------------------------------------------------------


def _filter_by_ap(
    clients: list[dict[str, Any]],
    ap_id: str | None,
) -> list[dict[str, Any]]:
    """Filter clients by access point ID (MAC).

    Returns all clients if ap_id is None.
    """
    if ap_id is None:
        return clients
    return [c for c in clients if c.get("ap_id") == ap_id]


# ---------------------------------------------------------------------------
# Public agent function
# ---------------------------------------------------------------------------


async def list_clients_report(
    site_id: str = "default",
    vlan_id: str | None = None,
    ap_id: str | None = None,
) -> str:
    """Produce a client inventory report with signal quality and traffic summary.

    Calls list_clients with optional VLAN filter, then applies AP filter
    client-side. Formats using OX tables.

    Shows: hostname/MAC, IP, VLAN, AP/port, connection type, signal (wireless),
    traffic summary.

    Args:
        site_id: The UniFi site ID. Defaults to ``"default"``.
        vlan_id: Optional VLAN/network ID to filter by.
        ap_id: Optional access point MAC to filter by.

    Returns:
        A formatted markdown report containing client inventory.
    """
    clients = await unifi__clients__list_clients(site_id, vlan_id=vlan_id)

    # Apply AP filter (not supported by the list_clients tool natively).
    clients = _filter_by_ap(clients, ap_id)

    logger.info(
        "Client report: %d clients for site '%s' (vlan=%s, ap=%s)",
        len(clients),
        site_id,
        vlan_id,
        ap_id,
        extra={"component": "clients"},
    )

    sections: list[str] = []

    # --- Summary ---
    wireless_count = sum(1 for c in clients if not c.get("is_wired", False))
    wired_count = sum(1 for c in clients if c.get("is_wired", False))
    guest_count = sum(1 for c in clients if c.get("is_guest", False))

    stats: dict[str, int | str] = {
        "Total": len(clients),
        "Wireless": wireless_count,
        "Wired": wired_count,
    }
    if guest_count > 0:
        stats["Guests"] = guest_count

    filters_applied: list[str] = []
    if vlan_id:
        filters_applied.append(f"VLAN: {vlan_id}")
    if ap_id:
        filters_applied.append(f"AP: {ap_id}")

    detail = f"Filters: {', '.join(filters_applied)}" if filters_applied else None

    sections.append(format_summary("Client Inventory", stats, detail=detail))

    # --- Client table ---
    if clients:
        rows: list[list[str]] = []
        for c in clients:
            conn_type = "Wired" if c.get("is_wired") else "Wireless"
            if c.get("is_guest"):
                conn_type += " (Guest)"

            rows.append([
                _client_display_name(c),
                c.get("ip", ""),
                c.get("vlan_id", ""),
                _connection_info(c),
                conn_type,
                _format_signal(c.get("rssi")) if not c.get("is_wired") else "",
                _traffic_summary(c),
            ])

        sections.append(
            format_table(
                headers=[
                    "Name/MAC",
                    "IP",
                    "VLAN",
                    "AP/Port",
                    "Type",
                    "Signal",
                    "Traffic",
                ],
                rows=rows,
                title="Connected Clients",
            )
        )
    else:
        sections.append("\nNo clients found matching the specified filters.\n")

    return "\n".join(sections)
