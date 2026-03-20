# SPDX-License-Identifier: MIT
"""Diagnostics skill MCP tools -- LLDP neighbor discovery.

Provides MCP tools for retrieving LLDP (Link Layer Discovery Protocol)
neighbor information from the OPNsense firewall. LLDP provides physical
layer adjacency data useful for network topology mapping.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.server import mcp_server

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def _get_client() -> OPNsenseClient:
    """Get a configured OPNsenseClient from environment variables."""
    host = os.environ.get("OPNSENSE_HOST", "")
    api_key = os.environ.get("OPNSENSE_API_KEY", "")
    api_secret = os.environ.get("OPNSENSE_API_SECRET", "")
    verify_ssl = os.environ.get("OPNSENSE_VERIFY_SSL", "true").lower() != "false"
    return OPNsenseClient(
        host=host,
        api_key=api_key,
        api_secret=api_secret,
        verify_ssl=verify_ssl,
    )


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def opnsense__diagnostics__get_lldp_neighbors(
    interface: str | None = None,
) -> list[dict[str, Any]]:
    """List LLDP neighbors discovered on the OPNsense firewall.

    Returns neighbor information including local interface, remote chassis,
    remote port, remote system name, and remote capabilities.

    LLDP (Link Layer Discovery Protocol) reveals the physical network
    topology by advertising device identity over Ethernet.

    Args:
        interface: Optional interface name to filter neighbors
            (e.g. 'igb0', 'igb1'). If not provided, returns
            all LLDP neighbors.

    API endpoint: GET /api/diagnostics/interface/getLldpNeighbors
    """
    client = _get_client()
    try:
        raw = await client.get("diagnostics", "interface", "getLldpNeighbors")
    finally:
        await client.close()

    # The LLDP endpoint returns neighbors in various formats depending
    # on the OPNsense version. Handle both flat and nested structures.
    neighbors: list[dict[str, Any]] = []

    # Try "lldp.interface" nested structure first
    lldp_data = raw.get("lldp", raw)
    interface_data = lldp_data.get("interface", [])

    if isinstance(interface_data, list):
        for iface_entry in interface_data:
            local_if = iface_entry.get("name", "")

            # Apply interface filter if specified
            if interface and local_if != interface:
                continue

            chassis_entries = iface_entry.get("chassis", [])
            if isinstance(chassis_entries, dict):
                chassis_entries = [chassis_entries]

            for chassis in chassis_entries:
                neighbor: dict[str, Any] = {
                    "local_interface": local_if,
                    "chassis_name": chassis.get("name", [{}])[0].get("value", "")
                    if isinstance(chassis.get("name"), list)
                    else chassis.get("name", ""),
                    "chassis_id": chassis.get("id", [{}])[0].get("value", "")
                    if isinstance(chassis.get("id"), list)
                    else chassis.get("id", ""),
                    "chassis_descr": chassis.get("descr", [{}])[0].get("value", "")
                    if isinstance(chassis.get("descr"), list)
                    else chassis.get("descr", ""),
                }

                # Extract port info
                port_entries = iface_entry.get("port", [])
                if isinstance(port_entries, dict):
                    port_entries = [port_entries]
                if port_entries:
                    port = port_entries[0]
                    neighbor["remote_port"] = port.get("id", [{}])[0].get("value", "") \
                        if isinstance(port.get("id"), list) \
                        else port.get("id", "")
                    neighbor["remote_port_descr"] = port.get("descr", [{}])[0].get("value", "") \
                        if isinstance(port.get("descr"), list) \
                        else port.get("descr", "")

                neighbors.append(neighbor)
    elif isinstance(interface_data, dict):
        # Alternative format: dict keyed by interface name
        for if_name, if_data in interface_data.items():
            if interface and if_name != interface:
                continue

            if isinstance(if_data, dict):
                neighbors.append({
                    "local_interface": if_name,
                    "chassis_name": if_data.get("chassis_name", ""),
                    "chassis_id": if_data.get("chassis_id", ""),
                    "chassis_descr": if_data.get("chassis_descr", ""),
                    "remote_port": if_data.get("remote_port", ""),
                    "remote_port_descr": if_data.get("remote_port_descr", ""),
                })

    logger.info(
        "Listed %d LLDP neighbors%s",
        len(neighbors),
        f" for interface {interface}" if interface else "",
        extra={"component": "diagnostics"},
    )

    return neighbors
