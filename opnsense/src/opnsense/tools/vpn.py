# SPDX-License-Identifier: MIT
"""VPN skill tools for OPNsense IPSec, OpenVPN, and WireGuard.

Provides read-only tools for querying VPN tunnel status across all three
VPN technologies supported by OPNsense. No write operations -- VPN
tunnels are configured via the OPNsense web UI.

Graceful degradation
--------------------
VPN plugins (IPSec, OpenVPN, WireGuard) are optional on OPNsense. When a
plugin is not installed, the corresponding API endpoints return 404. These
tools handle 404 responses gracefully by returning an empty result set with
metadata indicating the service is unavailable, rather than raising an error.

Additionally, OPNsense 26.x restructured some MVC API paths. Each tool
tries the primary endpoint first, then falls back to known 26.x
alternative endpoints before concluding the service is unavailable.

Tools
-----
- ``opnsense__vpn__list_ipsec_sessions`` -- IPSec tunnel sessions
- ``opnsense__vpn__list_openvpn_instances`` -- OpenVPN server/client instances
- ``opnsense__vpn__list_wireguard_peers`` -- WireGuard peer connections
- ``opnsense__vpn__get_vpn_status`` -- Aggregate status across all VPN types
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from opnsense.errors import APIError
from opnsense.models.vpn import IPSecSession, OpenVPNInstance, WireGuardPeer

if TYPE_CHECKING:
    from opnsense.api.opnsense_client import OPNsenseClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VPN result type
# ---------------------------------------------------------------------------

class VPNResult:
    """Container for VPN query results with availability metadata.

    Attributes
    ----------
    items:
        List of parsed VPN entries (sessions, instances, or peers).
    available:
        Whether the VPN service is installed and reachable.
    endpoint_used:
        The API endpoint that successfully returned data, or None
        if the service is unavailable.
    note:
        Human-readable note about service availability.
    """

    __slots__ = ("available", "endpoint_used", "items", "note")

    def __init__(
        self,
        items: list[dict[str, Any]],
        *,
        available: bool = True,
        endpoint_used: str | None = None,
        note: str = "",
    ) -> None:
        self.items = items
        self.available = available
        self.endpoint_used = endpoint_used
        self.note = note

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary suitable for API responses."""
        result: dict[str, Any] = {
            "items": self.items,
            "_meta": {
                "available": self.available,
                "endpoint_used": self.endpoint_used,
                "note": self.note,
            },
        }
        return result


# ---------------------------------------------------------------------------
# Endpoint definitions with fallback chains
# ---------------------------------------------------------------------------

# Each entry is (module, controller, command, rows_key) where rows_key
# is the key containing the result list in the API response.
_IPSEC_ENDPOINTS: list[tuple[str, str, str, str]] = [
    ("ipsec", "sessions", "search", "rows"),
    ("ipsec", "tunnel", "searchPhase1", "rows"),
    ("ipsec", "sad", "search", "rows"),
]

_OPENVPN_ENDPOINTS: list[tuple[str, str, str, str]] = [
    ("openvpn", "instances", "search", "rows"),
    ("openvpn", "service", "searchServer", "rows"),
]

_WIREGUARD_ENDPOINTS: list[tuple[str, str, str, str]] = [
    ("wireguard", "client", "search", "rows"),
    ("wireguard", "server", "searchServer", "rows"),
    ("wireguard", "general", "get", "rows"),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _try_vpn_endpoints(
    client: OPNsenseClient,
    endpoints: list[tuple[str, str, str, str]],
    service_name: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Try a chain of API endpoints, returning rows from the first that succeeds.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    endpoints:
        Ordered list of ``(module, controller, command, rows_key)`` to try.
    service_name:
        Human-readable name for logging (e.g. ``"IPSec"``).

    Returns
    -------
    tuple[list[dict], str | None]
        ``(rows, endpoint_path)`` -- the raw rows from the first successful
        endpoint and the path used, or ``([], None)`` if all returned 404.

    Raises
    ------
    APIError
        Re-raised for non-404 errors (e.g. 500, 403).
    """
    for module, controller, command, rows_key in endpoints:
        endpoint_path = f"/api/{module}/{controller}/{command}"
        try:
            raw = await client.get(module, controller, command)
            rows = raw.get(rows_key, [])
            if endpoint_path != f"/api/{endpoints[0][0]}/{endpoints[0][1]}/{endpoints[0][2]}":
                logger.info(
                    "%s: primary endpoint unavailable, using fallback %s",
                    service_name,
                    endpoint_path,
                )
            return rows, endpoint_path
        except APIError as exc:
            if exc.status_code == 404:
                logger.debug(
                    "%s endpoint %s returned 404, trying next fallback",
                    service_name,
                    endpoint_path,
                )
                continue
            # Non-404 errors are real failures -- propagate them.
            raise

    # All endpoints returned 404 -- service is not installed.
    logger.info(
        "%s: all endpoints returned 404 -- plugin is likely not installed",
        service_name,
    )
    return [], None


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------


async def opnsense__vpn__list_ipsec_sessions(
    client: OPNsenseClient,
) -> dict[str, Any]:
    """List all IPSec tunnel sessions.

    Tries ``GET /api/ipsec/sessions/search`` first, then falls back to
    alternative 26.x endpoints. If all return 404, the IPSec plugin is
    likely not installed and an empty result with availability metadata
    is returned.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    dict
        Result dict with keys:
        - ``items``: list of IPSec session dicts with normalized field names
        - ``_meta``: availability metadata (``available``, ``endpoint_used``, ``note``)
    """
    rows, endpoint_used = await _try_vpn_endpoints(client, _IPSEC_ENDPOINTS, "IPSec")

    if endpoint_used is None:
        return VPNResult(
            [],
            available=False,
            note="IPSec plugin is not installed or API endpoint is unavailable",
        ).to_dict()

    sessions: list[dict[str, Any]] = []
    for row in rows:
        try:
            session = IPSecSession.model_validate(row)
            sessions.append(session.model_dump())
        except Exception:
            logger.warning("Failed to parse IPSec session: %s", row.get("id", "unknown"))
            sessions.append(row)

    logger.info("Listed %d IPSec sessions via %s", len(sessions), endpoint_used)
    return VPNResult(
        sessions,
        available=True,
        endpoint_used=endpoint_used,
    ).to_dict()


async def opnsense__vpn__list_openvpn_instances(
    client: OPNsenseClient,
) -> dict[str, Any]:
    """List all OpenVPN instances (servers and clients).

    Tries ``GET /api/openvpn/instances/search`` first, then falls back to
    alternative 26.x endpoints. If all return 404, the OpenVPN plugin is
    likely not installed and an empty result with availability metadata
    is returned.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    dict
        Result dict with keys:
        - ``items``: list of OpenVPN instance dicts with normalized field names
        - ``_meta``: availability metadata (``available``, ``endpoint_used``, ``note``)
    """
    rows, endpoint_used = await _try_vpn_endpoints(client, _OPENVPN_ENDPOINTS, "OpenVPN")

    if endpoint_used is None:
        return VPNResult(
            [],
            available=False,
            note="OpenVPN plugin is not installed or API endpoint is unavailable",
        ).to_dict()

    instances: list[dict[str, Any]] = []
    for row in rows:
        try:
            instance = OpenVPNInstance.model_validate(row)
            instances.append(instance.model_dump())
        except Exception:
            logger.warning("Failed to parse OpenVPN instance: %s", row.get("uuid", "unknown"))
            instances.append(row)

    logger.info("Listed %d OpenVPN instances via %s", len(instances), endpoint_used)
    return VPNResult(
        instances,
        available=True,
        endpoint_used=endpoint_used,
    ).to_dict()


async def opnsense__vpn__list_wireguard_peers(
    client: OPNsenseClient,
) -> dict[str, Any]:
    """List all WireGuard peers.

    Tries ``GET /api/wireguard/client/search`` first, then falls back to
    alternative 26.x endpoints. If all return 404, the WireGuard plugin is
    likely not installed and an empty result with availability metadata
    is returned.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    dict
        Result dict with keys:
        - ``items``: list of WireGuard peer dicts with normalized field names
        - ``_meta``: availability metadata (``available``, ``endpoint_used``, ``note``)
    """
    rows, endpoint_used = await _try_vpn_endpoints(client, _WIREGUARD_ENDPOINTS, "WireGuard")

    if endpoint_used is None:
        return VPNResult(
            [],
            available=False,
            note="WireGuard plugin is not installed or API endpoint is unavailable",
        ).to_dict()

    peers: list[dict[str, Any]] = []
    for row in rows:
        try:
            peer = WireGuardPeer.model_validate(row)
            peers.append(peer.model_dump())
        except Exception:
            logger.warning("Failed to parse WireGuard peer: %s", row.get("uuid", "unknown"))
            peers.append(row)

    logger.info("Listed %d WireGuard peers via %s", len(peers), endpoint_used)
    return VPNResult(
        peers,
        available=True,
        endpoint_used=endpoint_used,
    ).to_dict()


async def opnsense__vpn__get_vpn_status(
    client: OPNsenseClient,
) -> dict[str, Any]:
    """Get aggregate VPN status across all VPN types.

    Queries IPSec, OpenVPN, and WireGuard endpoints and returns a
    consolidated status summary. Handles partial failures gracefully --
    if some VPN services are not installed, those sections show as
    unavailable while available services are reported normally.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    dict
        Aggregate VPN status with keys:
        - ``ipsec``: dict with ``sessions`` list, ``summary``, and ``_meta``
        - ``openvpn``: dict with ``instances`` list, ``summary``, and ``_meta``
        - ``wireguard``: dict with ``peers`` list, ``summary``, and ``_meta``
        - ``totals``: dict with aggregate counts
        - ``_meta``: dict with overall availability info
    """
    # Fetch all VPN data sequentially
    # (OPNsense API does not support concurrent requests well)
    ipsec_result = await opnsense__vpn__list_ipsec_sessions(client)
    openvpn_result = await opnsense__vpn__list_openvpn_instances(client)
    wireguard_result = await opnsense__vpn__list_wireguard_peers(client)

    # Extract items from results
    ipsec_sessions = ipsec_result["items"]
    openvpn_instances = openvpn_result["items"]
    wireguard_peers = wireguard_result["items"]

    # IPSec summary
    ipsec_connected = sum(1 for s in ipsec_sessions if s.get("status") == "connected")
    ipsec_disconnected = len(ipsec_sessions) - ipsec_connected

    # OpenVPN summary
    openvpn_servers = sum(1 for i in openvpn_instances if i.get("role") == "server")
    openvpn_clients = sum(1 for i in openvpn_instances if i.get("role") == "client")
    openvpn_enabled = sum(1 for i in openvpn_instances if i.get("enabled") is True)

    # WireGuard summary
    wg_active = sum(1 for p in wireguard_peers if p.get("last_handshake") is not None)
    wg_inactive = len(wireguard_peers) - wg_active

    total_tunnels = len(ipsec_sessions) + len(openvpn_instances) + len(wireguard_peers)
    total_active = ipsec_connected + openvpn_enabled + wg_active

    # Track which services are available
    services_available = {
        "ipsec": ipsec_result["_meta"]["available"],
        "openvpn": openvpn_result["_meta"]["available"],
        "wireguard": wireguard_result["_meta"]["available"],
    }
    unavailable_services = [k for k, v in services_available.items() if not v]

    result: dict[str, Any] = {
        "ipsec": {
            "sessions": ipsec_sessions,
            "summary": {
                "total": len(ipsec_sessions),
                "connected": ipsec_connected,
                "disconnected": ipsec_disconnected,
            },
            "_meta": ipsec_result["_meta"],
        },
        "openvpn": {
            "instances": openvpn_instances,
            "summary": {
                "total": len(openvpn_instances),
                "servers": openvpn_servers,
                "clients": openvpn_clients,
                "enabled": openvpn_enabled,
            },
            "_meta": openvpn_result["_meta"],
        },
        "wireguard": {
            "peers": wireguard_peers,
            "summary": {
                "total": len(wireguard_peers),
                "active": wg_active,
                "inactive": wg_inactive,
            },
            "_meta": wireguard_result["_meta"],
        },
        "totals": {
            "total_tunnels": total_tunnels,
            "total_active": total_active,
        },
        "_meta": {
            "services_available": services_available,
            "unavailable_services": unavailable_services,
        },
    }

    logger.info(
        "VPN status: %d total tunnels, %d active (%d services unavailable: %s)",
        total_tunnels,
        total_active,
        len(unavailable_services),
        ", ".join(unavailable_services) if unavailable_services else "none",
    )
    return result
