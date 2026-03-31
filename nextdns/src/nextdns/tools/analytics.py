# SPDX-License-Identifier: MIT
"""Analytics tools -- DNS query statistics and usage breakdowns.

Provides MCP tools for reading NextDNS analytics data including query
status counts, top domains, block reasons, devices, protocols, encryption
stats, destinations, IPs, query types, IP versions, and DNSSEC stats.

All tools are read-only and follow the common analytics API pattern:
``GET /profiles/{id}/analytics/{endpoint}`` with optional date-range,
device, and limit parameters.
"""

from __future__ import annotations

import logging
from typing import Any

from nextdns.models.analytics import (
    AnalyticsDestination,
    AnalyticsDevice,
    AnalyticsDomain,
    AnalyticsEncryption,
    AnalyticsIP,
    AnalyticsProtocol,
    AnalyticsReason,
)
from nextdns.server import mcp_server
from nextdns.tools._client_factory import get_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_analytics_params(
    from_time: str | None = None,
    to_time: str | None = None,
    device: str | None = None,
    limit: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build query params for analytics endpoints.

    Args:
        from_time: Start of the date range (ISO 8601 or relative like ``-7d``).
        to_time: End of the date range.
        device: Filter by device ID.
        limit: Maximum number of results (1-500).
        **extra: Additional endpoint-specific parameters.

    Returns:
        A dict of non-None query parameters ready for the API call.
    """
    params: dict[str, Any] = {}
    if from_time:
        params["from"] = from_time
    if to_time:
        params["to"] = to_time
    if device:
        params["device"] = device
    if limit:
        params["limit"] = limit
    params.update({k: v for k, v in extra.items() if v is not None})
    return params


def _analytics_endpoint(profile_id: str, sub: str) -> str:
    """Build the analytics endpoint path.

    Args:
        profile_id: NextDNS profile identifier.
        sub: Analytics sub-endpoint (e.g. ``"status"``, ``"domains"``).

    Returns:
        The full endpoint path.
    """
    return f"/profiles/{profile_id}/analytics/{sub}"


# ---------------------------------------------------------------------------
# MCP Tools -- Tasks 222-229
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def nextdns__analytics__get_status(
    profile_id: str,
    from_time: str | None = None,
    to_time: str | None = None,
    device: str | None = None,
) -> list[dict[str, Any]]:
    """Get query status breakdown for a NextDNS profile.

    Returns counts of queries by resolution status: default (resolved
    normally), blocked, and allowed (explicitly on allowlist).

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        from_time: Start of the date range (ISO 8601 or relative like "-7d").
        to_time: End of the date range.
        device: Filter by device ID.
    """
    client = get_client()
    params = _build_analytics_params(from_time=from_time, to_time=to_time, device=device)
    endpoint = _analytics_endpoint(profile_id, "status")
    raw = await client.get(endpoint, params=params or None)
    data = raw.get("data", [])

    logger.info(
        "Fetched analytics status for profile %s (%d entries)",
        profile_id,
        len(data),
        extra={"component": "analytics"},
    )
    return data  # type: ignore[return-value]


@mcp_server.tool()
async def nextdns__analytics__get_top_domains(
    profile_id: str,
    status: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
    device: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Get top queried domains for a NextDNS profile.

    Uses cursor-based pagination to fetch all results up to the limit.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        status: Filter by status ("default", "blocked", or "allowed").
        from_time: Start of the date range (ISO 8601 or relative like "-7d").
        to_time: End of the date range.
        device: Filter by device ID.
        limit: Maximum number of domains to return (1-500).
    """
    client = get_client()
    params = _build_analytics_params(
        from_time=from_time,
        to_time=to_time,
        device=device,
        status=status,
    )
    endpoint = _analytics_endpoint(profile_id, "domains")
    items = await client.get_paginated(endpoint, params=params or None, limit=limit)

    results = [AnalyticsDomain.model_validate(item).model_dump() for item in items]

    logger.info(
        "Fetched %d top domains for profile %s",
        len(results),
        profile_id,
        extra={"component": "analytics"},
    )
    return results


@mcp_server.tool()
async def nextdns__analytics__get_block_reasons(
    profile_id: str,
    from_time: str | None = None,
    to_time: str | None = None,
    device: str | None = None,
) -> list[dict[str, Any]]:
    """Get block reasons for a NextDNS profile.

    Returns the reasons why queries were blocked, with query counts.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        from_time: Start of the date range (ISO 8601 or relative like "-7d").
        to_time: End of the date range.
        device: Filter by device ID.
    """
    client = get_client()
    params = _build_analytics_params(from_time=from_time, to_time=to_time, device=device)
    endpoint = _analytics_endpoint(profile_id, "reasons")
    raw = await client.get(endpoint, params=params or None)
    data = raw.get("data", [])

    results = [AnalyticsReason.model_validate(item).model_dump() for item in data]

    logger.info(
        "Fetched %d block reasons for profile %s",
        len(results),
        profile_id,
        extra={"component": "analytics"},
    )
    return results


@mcp_server.tool()
async def nextdns__analytics__get_devices(
    profile_id: str,
    from_time: str | None = None,
    to_time: str | None = None,
) -> list[dict[str, Any]]:
    """Get device activity for a NextDNS profile.

    Returns devices that have made DNS queries, with query counts.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        from_time: Start of the date range (ISO 8601 or relative like "-7d").
        to_time: End of the date range.
    """
    client = get_client()
    params = _build_analytics_params(from_time=from_time, to_time=to_time)
    endpoint = _analytics_endpoint(profile_id, "devices")
    raw = await client.get(endpoint, params=params or None)
    data = raw.get("data", [])

    results = [AnalyticsDevice.model_validate(item).model_dump(by_alias=True) for item in data]

    logger.info(
        "Fetched %d devices for profile %s",
        len(results),
        profile_id,
        extra={"component": "analytics"},
    )
    return results


@mcp_server.tool()
async def nextdns__analytics__get_protocols(
    profile_id: str,
    from_time: str | None = None,
    to_time: str | None = None,
) -> dict[str, Any]:
    """Get DNS protocol breakdown for a NextDNS profile.

    Returns protocol usage (DoH, DoT, UDP, TCP, etc.) with query counts.
    Includes an ``unencrypted_warning`` flag set to true if any
    unencrypted protocol (UDP, TCP) has queries.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        from_time: Start of the date range (ISO 8601 or relative like "-7d").
        to_time: End of the date range.
    """
    client = get_client()
    params = _build_analytics_params(from_time=from_time, to_time=to_time)
    endpoint = _analytics_endpoint(profile_id, "protocols")
    raw = await client.get(endpoint, params=params or None)
    data = raw.get("data", [])

    protocols = [AnalyticsProtocol.model_validate(item).model_dump() for item in data]

    # Unencrypted protocols are those NOT using DNS-over-HTTPS or DNS-over-TLS.
    encrypted_prefixes = ("DNS-over-HTTPS", "DNS-over-TLS", "DNS-over-QUIC", "DoH", "DoT", "DoQ")
    unencrypted_warning = any(
        p["queries"] > 0 and not p["name"].startswith(encrypted_prefixes) for p in protocols
    )

    logger.info(
        "Fetched %d protocols for profile %s (unencrypted_warning=%s)",
        len(protocols),
        profile_id,
        unencrypted_warning,
        extra={"component": "analytics"},
    )
    return {
        "protocols": protocols,
        "unencrypted_warning": unencrypted_warning,
    }


@mcp_server.tool()
async def nextdns__analytics__get_encryption(
    profile_id: str,
    from_time: str | None = None,
    to_time: str | None = None,
) -> dict[str, Any]:
    """Get encryption breakdown for a NextDNS profile.

    Returns counts of encrypted vs unencrypted DNS queries, with
    computed totals, percentage, and a warning flag if unencrypted
    traffic exceeds 10%.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        from_time: Start of the date range (ISO 8601 or relative like "-7d").
        to_time: End of the date range.
    """
    client = get_client()
    params = _build_analytics_params(from_time=from_time, to_time=to_time)
    endpoint = _analytics_endpoint(profile_id, "encryption")
    raw = await client.get(endpoint, params=params or None)
    data = raw.get("data", [])

    # The API returns a single-item list with {encrypted, unencrypted}.
    enc = AnalyticsEncryption.model_validate(data[0]) if data else AnalyticsEncryption()

    total = enc.encrypted + enc.unencrypted
    unencrypted_pct = (enc.unencrypted / total * 100.0) if total > 0 else 0.0
    warning = unencrypted_pct > 10.0

    result = {
        "encrypted": enc.encrypted,
        "unencrypted": enc.unencrypted,
        "total": total,
        "unencrypted_percentage": round(unencrypted_pct, 2),
        "warning": warning,
    }

    logger.info(
        "Fetched encryption stats for profile %s: %d/%d encrypted (warning=%s)",
        profile_id,
        enc.encrypted,
        total,
        warning,
        extra={"component": "analytics"},
    )
    return result


@mcp_server.tool()
async def nextdns__analytics__get_destinations(
    profile_id: str,
    destination_type: str,
    from_time: str | None = None,
    to_time: str | None = None,
) -> list[dict[str, Any]]:
    """Get destination breakdown for a NextDNS profile.

    Returns query counts by destination, grouped by country or
    GAFAM provider (Google, Apple, Facebook, Amazon, Microsoft).

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        destination_type: Either "countries" or "gafam".
        from_time: Start of the date range (ISO 8601 or relative like "-7d").
        to_time: End of the date range.
    """
    client = get_client()
    params = _build_analytics_params(
        from_time=from_time,
        to_time=to_time,
        type=destination_type,
    )
    endpoint = _analytics_endpoint(profile_id, "destinations")
    raw = await client.get(endpoint, params=params or None)
    data = raw.get("data", [])

    results = [AnalyticsDestination.model_validate(item).model_dump() for item in data]

    logger.info(
        "Fetched %d destinations (%s) for profile %s",
        len(results),
        destination_type,
        profile_id,
        extra={"component": "analytics"},
    )
    return results


# ---------------------------------------------------------------------------
# MCP Tools -- Task 229 (remaining analytics)
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def nextdns__analytics__get_ips(
    profile_id: str,
    from_time: str | None = None,
    to_time: str | None = None,
    device: str | None = None,
) -> list[dict[str, Any]]:
    """Get source IP addresses for a NextDNS profile.

    Returns IPs that have made DNS queries, with geo/ISP metadata
    and query counts.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        from_time: Start of the date range (ISO 8601 or relative like "-7d").
        to_time: End of the date range.
        device: Filter by device ID.
    """
    client = get_client()
    params = _build_analytics_params(from_time=from_time, to_time=to_time, device=device)
    endpoint = _analytics_endpoint(profile_id, "ips")
    raw = await client.get(endpoint, params=params or None)
    data = raw.get("data", [])

    results = [AnalyticsIP.model_validate(item).model_dump(by_alias=True) for item in data]

    logger.info(
        "Fetched %d IPs for profile %s",
        len(results),
        profile_id,
        extra={"component": "analytics"},
    )
    return results


@mcp_server.tool()
async def nextdns__analytics__get_query_types(
    profile_id: str,
    from_time: str | None = None,
    to_time: str | None = None,
) -> list[dict[str, Any]]:
    """Get DNS query type breakdown for a NextDNS profile.

    Returns query counts by DNS record type (A, AAAA, CNAME, MX, etc.).

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        from_time: Start of the date range (ISO 8601 or relative like "-7d").
        to_time: End of the date range.
    """
    client = get_client()
    params = _build_analytics_params(from_time=from_time, to_time=to_time)
    endpoint = _analytics_endpoint(profile_id, "queryTypes")
    raw = await client.get(endpoint, params=params or None)
    data = raw.get("data", [])

    logger.info(
        "Fetched %d query types for profile %s",
        len(data),
        profile_id,
        extra={"component": "analytics"},
    )
    return data  # type: ignore[return-value]


@mcp_server.tool()
async def nextdns__analytics__get_ip_versions(
    profile_id: str,
    from_time: str | None = None,
    to_time: str | None = None,
) -> list[dict[str, Any]]:
    """Get IP version breakdown for a NextDNS profile.

    Returns query counts by IP version (IPv4, IPv6).

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        from_time: Start of the date range (ISO 8601 or relative like "-7d").
        to_time: End of the date range.
    """
    client = get_client()
    params = _build_analytics_params(from_time=from_time, to_time=to_time)
    endpoint = _analytics_endpoint(profile_id, "ipVersions")
    raw = await client.get(endpoint, params=params or None)
    data = raw.get("data", [])

    logger.info(
        "Fetched %d IP versions for profile %s",
        len(data),
        profile_id,
        extra={"component": "analytics"},
    )
    return data  # type: ignore[return-value]


@mcp_server.tool()
async def nextdns__analytics__get_dnssec(
    profile_id: str,
    from_time: str | None = None,
    to_time: str | None = None,
) -> list[dict[str, Any]]:
    """Get DNSSEC validation breakdown for a NextDNS profile.

    Returns query counts by DNSSEC validation status.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        from_time: Start of the date range (ISO 8601 or relative like "-7d").
        to_time: End of the date range.
    """
    client = get_client()
    params = _build_analytics_params(from_time=from_time, to_time=to_time)
    endpoint = _analytics_endpoint(profile_id, "dnssec")
    raw = await client.get(endpoint, params=params or None)
    data = raw.get("data", [])

    logger.info(
        "Fetched %d DNSSEC entries for profile %s",
        len(data),
        profile_id,
        extra={"component": "analytics"},
    )
    return data  # type: ignore[return-value]
