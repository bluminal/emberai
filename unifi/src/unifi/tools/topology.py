# SPDX-License-Identifier: MIT
"""Topology tools for UniFi network device discovery.

Provides MCP tools for listing and inspecting UniFi network devices
(switches, access points, gateways, consoles) via the Local Gateway API.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from unifi.api.local_gateway_client import LocalGatewayClient
from unifi.models.device import Device
from unifi.server import mcp_server

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State mapping: UniFi API returns numeric state codes
# ---------------------------------------------------------------------------

_STATE_MAP: dict[int, str] = {
    0: "disconnected",
    1: "connected",
    2: "pending_adoption",
    4: "upgrading",
    5: "provisioning",
    6: "heartbeat_missed",
    7: "adopting",
    9: "adoption_failed",
    10: "isolated",
    11: "rf_scanning",
}


def _state_to_str(state: int | str) -> str:
    """Convert a numeric device state to a human-readable string.

    If *state* is already a string, return it as-is.  Unknown integer
    codes are returned as ``"unknown(<code>)"``.
    """
    if isinstance(state, str):
        return state
    return _STATE_MAP.get(state, f"unknown({state})")


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def _get_client() -> LocalGatewayClient:
    """Get a configured LocalGatewayClient from environment variables."""
    host = os.environ.get("UNIFI_LOCAL_HOST", "")
    key = os.environ.get("UNIFI_LOCAL_KEY", "")
    return LocalGatewayClient(host=host, api_key=key)


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__topology__list_devices(site_id: str = "default") -> list[dict[str, Any]]:
    """List all devices (switches, APs, gateways) for a UniFi site.

    Returns device inventory with name, model, MAC, IP, status,
    uptime, firmware version, and product line.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/stat/device")
    finally:
        await client.close()

    devices: list[dict[str, Any]] = []
    for raw_device in normalized.data:
        # Convert numeric state to string before Pydantic strict validation
        if "state" in raw_device:
            raw_device["state"] = _state_to_str(raw_device["state"])

        device = Device.model_validate(raw_device)
        devices.append(device.model_dump(by_alias=False))

    logger.info(
        "Listed %d devices for site '%s'",
        len(devices),
        site_id,
        extra={"component": "topology"},
    )

    return devices
