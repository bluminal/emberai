# SPDX-License-Identifier: MIT
"""Client skill MCP tools -- list, get, search, and traffic analysis.

Provides MCP tools for listing connected clients, inspecting individual
client details, retrieving traffic statistics, and searching clients
by MAC, hostname, IP, or alias via the Local Gateway API.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from unifi.api.local_gateway_client import LocalGatewayClient
from unifi.errors import APIError, NetexError
from unifi.models.client import Client
from unifi.server import mcp_server

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def _get_client() -> LocalGatewayClient:
    """Get a configured LocalGatewayClient from environment variables."""
    host = os.environ.get("UNIFI_LOCAL_HOST", "")
    key = os.environ.get("UNIFI_LOCAL_KEY", "")
    return LocalGatewayClient(host=host, api_key=key)


# ---------------------------------------------------------------------------
# Tool 1: List Clients
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__clients__list_clients(
    site_id: str = "default",
    vlan_id: str | None = None,
) -> list[dict[str, Any]]:
    """List all connected clients (wired and wireless) for a UniFi site.

    Returns client inventory with MAC, hostname, IP, VLAN, connection type,
    uptime, and traffic counters. Optionally filter by VLAN/network ID.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
        vlan_id: Optional VLAN/network ID to filter clients by.
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/stat/sta")
    finally:
        await client.close()

    clients: list[dict[str, Any]] = []
    for raw_client in normalized.data:
        # Apply VLAN filter if specified
        if vlan_id is not None and raw_client.get("network_id") != vlan_id:
            continue

        try:
            parsed = Client.model_validate(raw_client)
            clients.append(parsed.model_dump(by_alias=False, exclude_none=True))
        except Exception:
            logger.warning(
                "Skipping unparseable client: %s",
                raw_client.get("mac", raw_client.get("_id", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Listed %d clients for site '%s'%s",
        len(clients),
        site_id,
        f" (vlan_id={vlan_id})" if vlan_id else "",
        extra={"component": "clients"},
    )

    return clients


# ---------------------------------------------------------------------------
# Tool 2: Get Client
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__clients__get_client(
    client_mac: str,
    site_id: str = "default",
) -> dict[str, Any]:
    """Get detailed information for a single client by MAC address.

    Returns full client details including AP association, SSID, signal
    strength, traffic counters, OS detection, and vendor information.

    Args:
        client_mac: The client's MAC address.
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()

    try:
        raw_client = await client.get_single(
            f"/api/s/{site_id}/stat/sta/{client_mac}",
        )
    except NetexError:
        raise
    except Exception as exc:
        raise APIError(
            f"Failed to fetch client {client_mac}: {exc}",
            status_code=500,
            endpoint=f"/api/s/{site_id}/stat/sta/{client_mac}",
        ) from exc
    finally:
        await client.close()

    parsed = Client.model_validate(raw_client)

    logger.info(
        "Retrieved client details for '%s' (mac=%s)",
        parsed.hostname or parsed.client_mac,
        client_mac,
        extra={"component": "clients"},
    )

    return parsed.model_dump(by_alias=False, exclude_none=True)


# ---------------------------------------------------------------------------
# Tool 3: Get Client Traffic
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__clients__get_client_traffic(
    client_mac: str,
    site_id: str = "default",
) -> dict[str, Any]:
    """Get traffic statistics for a single client by MAC address.

    Returns transmit/receive byte and packet counters, and DPI
    (Deep Packet Inspection) data if available.

    Args:
        client_mac: The client's MAC address.
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()

    try:
        raw_client = await client.get_single(
            f"/api/s/{site_id}/stat/user/{client_mac}",
        )
    except NetexError:
        raise
    except Exception as exc:
        raise APIError(
            f"Failed to fetch traffic for client {client_mac}: {exc}",
            status_code=500,
            endpoint=f"/api/s/{site_id}/stat/user/{client_mac}",
        ) from exc
    finally:
        await client.close()

    traffic: dict[str, Any] = {
        "client_mac": raw_client.get("mac", client_mac),
        "hostname": raw_client.get("hostname"),
        "ip": raw_client.get("ip"),
        "tx_bytes": raw_client.get("tx_bytes", 0),
        "rx_bytes": raw_client.get("rx_bytes", 0),
        "tx_packets": raw_client.get("tx_packets", 0),
        "rx_packets": raw_client.get("rx_packets", 0),
    }

    # Include DPI data if available
    dpi_stats = raw_client.get("dpi_stats")
    if dpi_stats is not None:
        traffic["dpi_stats"] = dpi_stats

    logger.info(
        "Retrieved traffic for client '%s' (mac=%s): tx=%d rx=%d bytes",
        traffic["hostname"] or traffic["client_mac"],
        client_mac,
        traffic["tx_bytes"],
        traffic["rx_bytes"],
        extra={"component": "clients"},
    )

    return traffic


# ---------------------------------------------------------------------------
# Tool 4: Search Clients
# ---------------------------------------------------------------------------


def _client_matches_query(raw_client: dict[str, Any], query_lower: str) -> bool:
    """Check if a raw client dict matches a search query.

    Performs case-insensitive partial matching against mac, hostname,
    ip, and name (alias) fields.
    """
    searchable_fields = [
        raw_client.get("mac", ""),
        raw_client.get("hostname", ""),
        raw_client.get("ip", ""),
        raw_client.get("name", ""),
    ]

    return any(
        query_lower in (field or "").lower()
        for field in searchable_fields
    )


@mcp_server.tool()
async def unifi__clients__search_clients(
    query: str,
    site_id: str = "default",
) -> list[dict[str, Any]]:
    """Search connected clients by partial match on MAC, hostname, IP, or name.

    Performs case-insensitive substring matching across multiple client
    fields. Fetches all clients for the site and filters client-side.

    Args:
        query: Search string to match against client fields.
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/stat/sta")
    finally:
        await client.close()

    query_lower = query.lower()
    matches: list[dict[str, Any]] = []

    for raw_client in normalized.data:
        if not _client_matches_query(raw_client, query_lower):
            continue

        try:
            parsed = Client.model_validate(raw_client)
            matches.append(parsed.model_dump(by_alias=False, exclude_none=True))
        except Exception:
            logger.warning(
                "Skipping unparseable client during search: %s",
                raw_client.get("mac", raw_client.get("_id", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Search for '%s' matched %d clients at site '%s'",
        query,
        len(matches),
        site_id,
        extra={"component": "clients"},
    )

    return matches
