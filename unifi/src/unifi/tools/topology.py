# SPDX-License-Identifier: MIT
"""Topology skill MCP tools -- device, VLAN, uplink, site, and host discovery.

Provides MCP tools for listing and inspecting UniFi network devices
(switches, access points, gateways, consoles), VLANs, sites, and hosts
via the Local Gateway API and Cloud V1 API.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from unifi.api.cloud_v1_client import CloudV1Client
from unifi.api.local_gateway_client import LocalGatewayClient
from unifi.errors import APIError, AuthenticationError
from unifi.models.device import Device
from unifi.models.site import Site
from unifi.models.vlan import VLAN
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


def _get_cloud_client() -> CloudV1Client:
    """Get a configured CloudV1Client from the ``UNIFI_API_KEY`` env var.

    Raises
    ------
    AuthenticationError
        If ``UNIFI_API_KEY`` is not set or empty.
    """
    api_key = os.environ.get("UNIFI_API_KEY", "").strip()
    if not api_key:
        raise AuthenticationError(
            "UNIFI_API_KEY is not configured. "
            "Set this environment variable to use Cloud V1 API features.",
            env_var="UNIFI_API_KEY",
        )
    return CloudV1Client(api_key=api_key)


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


@mcp_server.tool()
async def unifi__topology__get_device(
    device_id: str,
    site_id: str = "default",
) -> dict[str, Any]:
    """Get detailed information for a single device.

    Returns full device details including port table, uplink info,
    VLAN assignments, radio table (for APs), and config.

    Args:
        device_id: The device MAC address or ID.
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()

    try:
        raw_device = await client.get_single(
            f"/api/s/{site_id}/stat/device/{device_id}",
        )
    except APIError:
        raise
    except Exception as exc:
        raise APIError(
            f"Failed to fetch device {device_id}: {exc}",
            status_code=500,
            endpoint=f"/api/s/{site_id}/stat/device/{device_id}",
        ) from exc
    finally:
        await client.close()

    if "state" in raw_device:
        raw_device["state"] = _state_to_str(raw_device["state"])

    device = Device.model_validate(raw_device)

    return device.model_dump(by_alias=False, exclude_none=True)


# ---------------------------------------------------------------------------
# VLAN filtering
# ---------------------------------------------------------------------------

_WAN_PURPOSES = frozenset({"wan", "wan2"})


def _is_vlan_network(network: dict[str, Any]) -> bool:
    """Return True if the network entry represents a LAN/VLAN (not a WAN)."""
    purpose = network.get("purpose", "")
    if purpose in _WAN_PURPOSES:
        return False

    has_vlan_tag = network.get("vlan_enabled", False) and "vlan" in network
    is_default_lan = not network.get("vlan_enabled", False) and purpose not in _WAN_PURPOSES

    return has_vlan_tag or is_default_lan


@mcp_server.tool()
async def unifi__topology__get_vlans(site_id: str = "default") -> list[dict[str, Any]]:
    """List all VLANs/networks configured for a UniFi site.

    Returns VLAN inventory with ID, name, subnet, DHCP status,
    purpose, and domain name.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()

    async with client:
        endpoint = f"/api/s/{site_id}/rest/networkconf"
        normalized = await client.get_normalized(endpoint)

    vlan_networks = [n for n in normalized.data if _is_vlan_network(n)]

    vlans: list[dict[str, Any]] = []
    for network in vlan_networks:
        try:
            vlan = VLAN.model_validate(network)
            vlans.append(vlan.model_dump())
        except Exception:
            logger.warning(
                "Skipping unparseable network entry: %s",
                network.get("name", network.get("_id", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Found %d VLANs for site %s (from %d total networks)",
        len(vlans),
        site_id,
        len(normalized.data),
    )

    return vlans


# ---------------------------------------------------------------------------
# Uplink graph
# ---------------------------------------------------------------------------


def _build_uplink_graph(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build an uplink graph from a list of raw device dicts.

    For each device that has an ``uplink`` field with an ``uplink_mac``,
    resolve the parent device from the device list and emit a relationship
    record.  Devices without an uplink (root gateways) or with
    self-referencing uplinks are silently skipped.

    Returns:
        A list of uplink-relationship dicts, one per non-root device.
    """
    # Index devices by MAC for O(1) parent lookup
    mac_to_device: dict[str, dict[str, Any]] = {
        d["mac"]: d for d in devices if "mac" in d
    }

    graph: list[dict[str, Any]] = []

    for device in devices:
        uplink = device.get("uplink")
        if not uplink:
            continue

        uplink_mac = uplink.get("uplink_mac")
        if not uplink_mac:
            continue

        device_mac = device.get("mac", "")
        # Skip self-referencing uplinks
        if uplink_mac == device_mac:
            continue

        parent = mac_to_device.get(uplink_mac)

        graph.append({
            "device_id": device.get("_id", ""),
            "device_name": device.get("name", ""),
            "device_mac": device_mac,
            "uplink_device_id": parent.get("_id", "") if parent else "",
            "uplink_device_name": parent.get("name", "") if parent else "",
            "uplink_device_mac": uplink_mac,
            "uplink_port": uplink.get("uplink_remote_port"),
            "uplink_type": uplink.get("type", ""),
            "speed": uplink.get("speed"),
        })

    return graph


@mcp_server.tool()
async def unifi__topology__get_uplinks(site_id: str = "default") -> list[dict[str, Any]]:
    """Derive the uplink graph showing device-to-device connections.

    Returns uplink relationships: which device connects to which,
    through which port, at what speed, and via what connection type.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/stat/device")
    finally:
        await client.close()

    graph = _build_uplink_graph(normalized.data)

    logger.info(
        "Built uplink graph with %d links for site '%s'",
        len(graph),
        site_id,
        extra={"component": "topology"},
    )

    return graph


# ---------------------------------------------------------------------------
# Cloud V1 tools: Sites and Hosts
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__topology__list_sites() -> list[dict[str, Any]]:
    """List all UniFi sites accessible via Cloud V1 API.

    Requires UNIFI_API_KEY to be configured. Returns site inventory
    with ID, name, description, device count, and client count.
    """
    client = _get_cloud_client()
    try:
        normalized = await client.get_normalized("sites")
    finally:
        await client.close()

    sites: list[dict[str, Any]] = []
    for raw_site in normalized.data:
        try:
            site = Site.model_validate(raw_site)
            sites.append(site.model_dump(by_alias=False))
        except Exception:
            logger.warning(
                "Skipping unparseable site entry: %s",
                raw_site.get("name", raw_site.get("_id", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Listed %d sites via Cloud V1 API",
        len(sites),
        extra={"component": "topology"},
    )

    return sites


@mcp_server.tool()
async def unifi__topology__list_hosts() -> list[dict[str, Any]]:
    """List all UniFi hosts (controllers/consoles) via Cloud V1 API.

    Requires UNIFI_API_KEY to be configured. Returns host inventory
    with host ID, name, IP address, hardware type, and firmware version.
    """
    client = _get_cloud_client()
    try:
        normalized = await client.get_normalized("hosts")
    finally:
        await client.close()

    hosts: list[dict[str, Any]] = []
    for raw_host in normalized.data:
        hosts.append({
            "host_id": raw_host.get("_id", raw_host.get("id", "")),
            "name": raw_host.get("hostname", raw_host.get("name", "")),
            "ip": raw_host.get("ip", raw_host.get("wan_ip", "")),
            "type": raw_host.get("type", raw_host.get("hardware_type", "")),
            "firmware_version": raw_host.get(
                "firmware_version",
                raw_host.get("version", ""),
            ),
        })

    logger.info(
        "Listed %d hosts via Cloud V1 API",
        len(hosts),
        extra={"component": "topology"},
    )

    return hosts
