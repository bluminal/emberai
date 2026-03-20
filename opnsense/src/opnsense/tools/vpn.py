# SPDX-License-Identifier: MIT
"""VPN skill tools for OPNsense IPSec, OpenVPN, and WireGuard.

Provides read-only tools for querying VPN tunnel status across all three
VPN technologies supported by OPNsense. No write operations -- VPN
tunnels are configured via the OPNsense web UI.

Tools
-----
- ``opnsense__vpn__list_ipsec_sessions`` -- IPSec tunnel sessions
- ``opnsense__vpn__list_openvpn_instances`` -- OpenVPN server/client instances
- ``opnsense__vpn__list_wireguard_peers`` -- WireGuard peer connections
- ``opnsense__vpn__get_vpn_status`` -- Aggregate status across all VPN types
"""

from __future__ import annotations

import logging
from typing import Any

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.models.vpn import IPSecSession, OpenVPNInstance, WireGuardPeer

logger = logging.getLogger(__name__)


async def opnsense__vpn__list_ipsec_sessions(
    client: OPNsenseClient,
) -> list[dict[str, Any]]:
    """List all IPSec tunnel sessions.

    Queries ``GET /api/ipsec/sessions/search`` and returns normalized
    session data including tunnel status, traffic selectors, and byte
    counters.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    list[dict]
        List of IPSec session dictionaries with normalized field names.
    """
    raw = await client.get("ipsec", "sessions", "search")
    rows = raw.get("rows", [])

    sessions: list[dict[str, Any]] = []
    for row in rows:
        try:
            session = IPSecSession.model_validate(row)
            sessions.append(session.model_dump())
        except Exception:
            logger.warning("Failed to parse IPSec session: %s", row.get("id", "unknown"))
            sessions.append(row)

    logger.info("Listed %d IPSec sessions", len(sessions))
    return sessions


async def opnsense__vpn__list_openvpn_instances(
    client: OPNsenseClient,
) -> list[dict[str, Any]]:
    """List all OpenVPN instances (servers and clients).

    Queries ``GET /api/openvpn/instances/search`` and returns normalized
    instance data including role, protocol, port, and connected client count.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    list[dict]
        List of OpenVPN instance dictionaries with normalized field names.
    """
    raw = await client.get("openvpn", "instances", "search")
    rows = raw.get("rows", [])

    instances: list[dict[str, Any]] = []
    for row in rows:
        try:
            instance = OpenVPNInstance.model_validate(row)
            instances.append(instance.model_dump())
        except Exception:
            logger.warning(
                "Failed to parse OpenVPN instance: %s", row.get("uuid", "unknown")
            )
            instances.append(row)

    logger.info("Listed %d OpenVPN instances", len(instances))
    return instances


async def opnsense__vpn__list_wireguard_peers(
    client: OPNsenseClient,
) -> list[dict[str, Any]]:
    """List all WireGuard peers.

    Queries ``GET /api/wireguard/client/search`` and returns normalized
    peer data including public keys, endpoints, allowed IPs, and handshake
    timestamps.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    list[dict]
        List of WireGuard peer dictionaries with normalized field names.
    """
    raw = await client.get("wireguard", "client", "search")
    rows = raw.get("rows", [])

    peers: list[dict[str, Any]] = []
    for row in rows:
        try:
            peer = WireGuardPeer.model_validate(row)
            peers.append(peer.model_dump())
        except Exception:
            logger.warning(
                "Failed to parse WireGuard peer: %s", row.get("uuid", "unknown")
            )
            peers.append(row)

    logger.info("Listed %d WireGuard peers", len(peers))
    return peers


async def opnsense__vpn__get_vpn_status(
    client: OPNsenseClient,
) -> dict[str, Any]:
    """Get aggregate VPN status across all VPN types.

    Queries IPSec, OpenVPN, and WireGuard endpoints and returns a
    consolidated status summary with counts, health indicators, and
    per-technology breakdowns.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    dict
        Aggregate VPN status with keys:
        - ``ipsec``: dict with ``sessions`` list and ``summary``
        - ``openvpn``: dict with ``instances`` list and ``summary``
        - ``wireguard``: dict with ``peers`` list and ``summary``
        - ``totals``: dict with aggregate counts
    """
    # Fetch all VPN data concurrently via sequential calls
    # (OPNsense API does not support concurrent requests well)
    ipsec_sessions = await opnsense__vpn__list_ipsec_sessions(client)
    openvpn_instances = await opnsense__vpn__list_openvpn_instances(client)
    wireguard_peers = await opnsense__vpn__list_wireguard_peers(client)

    # IPSec summary
    ipsec_connected = sum(
        1 for s in ipsec_sessions if s.get("status") == "connected"
    )
    ipsec_disconnected = len(ipsec_sessions) - ipsec_connected

    # OpenVPN summary
    openvpn_servers = sum(
        1 for i in openvpn_instances if i.get("role") == "server"
    )
    openvpn_clients = sum(
        1 for i in openvpn_instances if i.get("role") == "client"
    )
    openvpn_enabled = sum(
        1 for i in openvpn_instances if i.get("enabled") is True
    )

    # WireGuard summary
    wg_active = sum(
        1 for p in wireguard_peers if p.get("last_handshake") is not None
    )
    wg_inactive = len(wireguard_peers) - wg_active

    total_tunnels = len(ipsec_sessions) + len(openvpn_instances) + len(wireguard_peers)
    total_active = ipsec_connected + openvpn_enabled + wg_active

    result: dict[str, Any] = {
        "ipsec": {
            "sessions": ipsec_sessions,
            "summary": {
                "total": len(ipsec_sessions),
                "connected": ipsec_connected,
                "disconnected": ipsec_disconnected,
            },
        },
        "openvpn": {
            "instances": openvpn_instances,
            "summary": {
                "total": len(openvpn_instances),
                "servers": openvpn_servers,
                "clients": openvpn_clients,
                "enabled": openvpn_enabled,
            },
        },
        "wireguard": {
            "peers": wireguard_peers,
            "summary": {
                "total": len(wireguard_peers),
                "active": wg_active,
                "inactive": wg_inactive,
            },
        },
        "totals": {
            "total_tunnels": total_tunnels,
            "total_active": total_active,
        },
    }

    logger.info(
        "VPN status: %d total tunnels, %d active",
        total_tunnels,
        total_active,
    )
    return result
