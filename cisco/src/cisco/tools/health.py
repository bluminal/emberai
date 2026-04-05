# SPDX-License-Identifier: MIT
"""Composite health monitoring tool for Cisco SG-300.

Aggregates data from multiple SSH commands to produce a single
health overview of the switch.
"""

from __future__ import annotations

import logging
from typing import Any

from cisco.errors import AuthenticationError, NetworkError, SSHCommandError
from cisco.parsers import (
    parse_show_interfaces_status,
    parse_show_lldp_neighbors,
    parse_show_version,
)
from cisco.parsers.system import parse_hostname_from_config
from cisco.server import mcp_server
from cisco.ssh.client import get_client

logger = logging.getLogger(__name__)


@mcp_server.tool()
async def cisco__health__get_status() -> dict[str, Any]:
    """Composite health overview of the switch.

    Aggregates system info, port status counts, and LLDP neighbor count
    into a single health report.

    Returns a dict with keys:
    - device_info: {hostname, model, firmware_version, serial_number,
                    uptime_seconds, mac_address}
    - ports: {total, up, down}
    - lldp_neighbor_count: int
    - uptime_seconds: int
    - summary: str (human-readable markdown summary)
    """
    try:
        client = get_client()
    except AuthenticationError as exc:
        return {"error": str(exc), "hint": exc.retry_hint}

    try:
        await client.connect()

        # Gather data from multiple commands
        version_output = await client.send_command("show version")
        config_output = await client.send_command("show running-config")
        interfaces_output = await client.send_command("show interfaces status")
        lldp_output = await client.send_command("show lldp neighbors")

        # Parse all outputs
        hostname = parse_hostname_from_config(config_output)
        device_info = parse_show_version(version_output, hostname=hostname)
        ports = parse_show_interfaces_status(interfaces_output)
        neighbors = parse_show_lldp_neighbors(lldp_output)

        # Compute port status counts
        ports_up = sum(1 for p in ports if p.status.lower() == "up")
        ports_down = sum(1 for p in ports if p.status.lower() == "down")
        ports_total = len(ports)

        # Build summary
        summary_lines = [
            f"## {device_info.hostname} Health Report",
            "",
            f"**Model:** {device_info.model}",
            f"**Firmware:** {device_info.firmware_version}",
            f"**MAC:** {device_info.mac_address}",
            f"**Uptime:** {_format_uptime(device_info.uptime_seconds)}",
            "",
            f"**Ports:** {ports_up}/{ports_total} up, {ports_down} down",
            f"**LLDP Neighbors:** {len(neighbors)}",
        ]

        # Flag potential issues
        if ports_down > 0:
            down_ports = [p.id for p in ports if p.status.lower() == "down"]
            summary_lines.append("")
            summary_lines.append(
                f"**Down ports:** {', '.join(down_ports[:10])}"
                + (
                    f" (+{len(down_ports) - 10} more)"
                    if len(down_ports) > 10
                    else ""
                )
            )

        return {
            "device_info": dict(device_info.model_dump()),
            "ports": {
                "total": ports_total,
                "up": ports_up,
                "down": ports_down,
            },
            "lldp_neighbor_count": len(neighbors),
            "uptime_seconds": device_info.uptime_seconds,
            "summary": "\n".join(summary_lines),
        }

    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to get health status: %s", exc)
        return {"error": str(exc), "hint": getattr(exc, "retry_hint", None)}


def _format_uptime(seconds: int) -> str:
    """Format uptime seconds into a human-readable string.

    Parameters
    ----------
    seconds:
        Uptime in seconds.

    Returns
    -------
    str
        Formatted string like "5d 3h 22m" or "unknown" if 0.
    """
    if seconds <= 0:
        return "unknown (use SNMP sysUpTime for accurate uptime)"

    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")

    return " ".join(parts) if parts else "<1m"
