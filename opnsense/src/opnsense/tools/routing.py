# SPDX-License-Identifier: MIT
"""Routing skill MCP tools -- routes, gateways, and Quagga/FRR status.

Provides MCP tools for listing static routes, gateway status, and
adding new routes on an OPNsense firewall.

Includes graceful degradation for Quagga/FRR: if the os-quagga plugin
is not installed, a warning is logged and Quagga-related queries return
an informative message rather than raising an error.

Write tools follow the OPNsense two-step pattern: write (save config)
then reconfigure (apply to live system). All write tools are protected
by the ``@write_gate("OPNSENSE")`` decorator.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.api.response import is_action_success, normalize_response
from opnsense.cache import CacheTTL
from opnsense.errors import APIError, ValidationError
from opnsense.models.routing import Gateway, GatewayGroup, GatewayGroupMember, Route
from opnsense.safety import write_gate
from opnsense.server import mcp_server

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OPNsense API coercion helpers
# ---------------------------------------------------------------------------

_STR_BOOL_TRUE = frozenset({"1", "true", "yes"})

# OPNsense 26.x uses "~" as a sentinel for "no data available"
_TILDE_SENTINEL = "~"

# dpinger raw status -> normalized human-readable status
_DPINGER_STATUS_MAP: dict[str, str] = {
    "none": "online",
    "down": "offline",
    "delay": "degraded",
    "loss": "degraded",
    "delay+loss": "degraded",
    "force_down": "offline",
}


def _parse_dpinger_metric(value: Any) -> float | None:
    """Parse a dpinger metric value to a float.

    OPNsense 26.x returns dpinger metrics in several formats:
    - ``"~"``       -> None (no data)
    - ``"4.2 ms"``  -> 4.2
    - ``"0.0 %"``   -> 0.0
    - ``4.2``       -> 4.2 (already numeric)
    - ``""``        -> None

    Returns None if the value cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value or value == _TILDE_SENTINEL:
        return None

    # Strip common unit suffixes: "ms", "%", "s"
    cleaned = re.sub(r"\s*(ms|%|s)\s*$", "", value, flags=re.IGNORECASE).strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _coerce_gateway_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Coerce OPNsense 26.x gateway status fields to model-compatible types.

    OPNsense 26.x ``/api/routes/gateway/status`` returns gateway entries with:
    - ``"~"`` sentinels for missing data (address, monitor, metrics)
    - String-formatted metrics: ``"4.2 ms"``, ``"0.0 %"``
    - Raw dpinger status codes: ``"none"`` (online), ``"down"`` (offline)
    - No ``interface`` or ``priority`` fields

    This function normalizes all of these into the types expected by the
    :class:`Gateway` model.
    """
    coerced = dict(item)

    # Normalize "~" sentinels in string fields to empty string
    for str_field in ("address", "monitor", "name"):
        val = coerced.get(str_field)
        if isinstance(val, str) and val.strip() == _TILDE_SENTINEL:
            coerced[str_field] = ""

    # Parse delay -> rtt_ms (float)
    coerced["delay"] = _parse_dpinger_metric(coerced.get("delay"))

    # Parse loss -> loss_pct (float)
    coerced["loss_pct"] = _parse_dpinger_metric(coerced.pop("loss", None))

    # Parse stddev -> stddev_ms (float)
    coerced["stddev_ms"] = _parse_dpinger_metric(coerced.pop("stddev", None))

    # Normalize status from dpinger codes to human-readable
    raw_status = coerced.get("status", "")
    if isinstance(raw_status, str):
        normalized = _DPINGER_STATUS_MAP.get(raw_status.lower().strip(), "")
        if normalized:
            coerced["status"] = normalized
        # If not in the map, keep the original value (it might already
        # be human-readable, e.g. "online", "offline" from older versions)

    # Ensure priority is an int (may be missing in 26.x)
    priority = coerced.get("priority")
    if priority is not None:
        try:
            coerced["priority"] = int(priority)
        except (ValueError, TypeError):
            coerced["priority"] = 255

    return coerced


def _coerce_route_booleans(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce OPNsense string booleans to Python bools for Pydantic strict mode.

    The OPNsense API returns ``"0"``/``"1"`` for the ``disabled`` field
    in route search responses.
    """
    coerced = dict(row)
    if "disabled" in coerced and isinstance(coerced["disabled"], str):
        coerced["disabled"] = coerced["disabled"].lower() in _STR_BOOL_TRUE
    return coerced


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
# Quagga/FRR graceful degradation
# ---------------------------------------------------------------------------


async def _probe_quagga(client: OPNsenseClient) -> bool:
    """Probe the Quagga/FRR API to check if the plugin is installed.

    Returns True if the Quagga plugin is installed and responding,
    False otherwise. A 404 response (plugin not installed) is expected
    and handled gracefully.
    """
    try:
        await client.get("quagga", "general", "get")
        return True
    except APIError as exc:
        if exc.status_code == 404:
            logger.warning(
                "Quagga/FRR plugin not installed (404). "
                "Dynamic routing features are not available.",
                extra={"component": "routing"},
            )
            return False
        # Re-raise unexpected errors
        raise
    except Exception:
        logger.warning(
            "Quagga/FRR probe failed. Dynamic routing features may not be available.",
            exc_info=True,
            extra={"component": "routing"},
        )
        return False


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def opnsense__routing__list_routes() -> list[dict[str, Any]]:
    """List all static routes on the OPNsense firewall.

    Returns route inventory with UUID, destination network, gateway,
    description, and disabled status.

    Also probes for Quagga/FRR dynamic routing plugin and includes
    its availability status in the response metadata.

    API endpoint: GET /api/routes/routes/searchRoute
    """
    client = _get_client()
    try:
        raw = await client.get_cached(
            "routes",
            "routes",
            "searchRoute",
            cache_key="routing:routes",
            ttl=CacheTTL.ROUTES,
            params={"rowCount": -1, "current": 1},
        )

        # Probe Quagga availability (non-blocking, does not fail the request)
        quagga_available = await _probe_quagga(client)
    finally:
        await client.close()

    normalized = normalize_response(raw)

    routes: list[dict[str, Any]] = []
    for row in normalized.data:
        try:
            coerced = _coerce_route_booleans(row)
            route = Route.model_validate(coerced)
            routes.append(route.model_dump(by_alias=False))
        except Exception:
            logger.warning(
                "Skipping unparseable route entry: %s",
                row.get("uuid", row.get("network", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Listed %d static routes (quagga=%s)",
        len(routes),
        "available" if quagga_available else "not installed",
        extra={"component": "routing"},
    )

    return routes


@mcp_server.tool()
async def opnsense__routing__list_gateways() -> list[dict[str, Any]]:
    """List all gateways and their status on the OPNsense firewall.

    Returns gateway inventory with name, address, interface, monitor IP,
    status, priority, round-trip time, packet loss, and RTT stddev.

    Handles OPNsense 26.x response format where dpinger metrics are
    returned as strings with unit suffixes (e.g. "4.2 ms", "0.0 %")
    and missing values use the "~" sentinel.

    API endpoint: GET /api/routes/gateway/status
    """
    client = _get_client()
    try:
        raw = await client.get_cached(
            "routes",
            "gateway",
            "status",
            cache_key="routing:gateways",
            ttl=CacheTTL.GATEWAYS,
        )
    finally:
        await client.close()

    # Gateway status returns an "items" array (action-style response).
    # OPNsense 26.x: {"items": [...], "status": "ok"}
    items = raw.get("items", [])
    if not items and "rows" in raw:
        # Fall back to search-style if the API returns rows instead
        items = raw["rows"]

    gateways: list[dict[str, Any]] = []
    for item in items:
        try:
            coerced = _coerce_gateway_fields(item)
            gw = Gateway.model_validate(coerced)
            gateways.append(gw.model_dump(by_alias=False))
        except Exception:
            logger.warning(
                "Skipping unparseable gateway entry: %s",
                item.get("name", "unknown"),
                exc_info=True,
            )

    logger.info(
        "Listed %d gateways",
        len(gateways),
        extra={"component": "routing"},
    )

    return gateways


@mcp_server.tool()
async def opnsense__routing__list_gateway_groups() -> list[dict[str, Any]]:
    """List all gateway groups on the OPNsense firewall.

    Returns gateway group inventory with UUID, name, failover trigger,
    and member gateways with their tier and weight.

    API endpoint: GET /api/routes/gateway/searchgroup
    """
    client = _get_client()
    try:
        raw = await client.get_cached(
            "routes",
            "gateway",
            "searchgroup",
            cache_key="routing:gateway_groups",
            ttl=CacheTTL.GATEWAY_GROUPS,
            params={"rowCount": -1, "current": 1},
        )
    finally:
        await client.close()

    normalized = normalize_response(raw)

    groups: list[dict[str, Any]] = []
    for row in normalized.data:
        try:
            group = _parse_gateway_group(row)
            groups.append(group.model_dump(by_alias=False))
        except Exception:
            logger.warning(
                "Skipping unparseable gateway group: %s",
                row.get("name", row.get("uuid", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Listed %d gateway groups",
        len(groups),
        extra={"component": "routing"},
    )

    return groups


def _parse_gateway_group(row: dict[str, Any]) -> GatewayGroup:
    """Parse a raw gateway group API response into a GatewayGroup model.

    OPNsense may return members in different formats depending on version:
    - As a list of dicts with gateway/tier/weight keys
    - As a semicolon-delimited string: "GW1|1|1;GW2|2|1"
    - As named keys on the group object itself (gateway name -> priority/weight)

    This parser handles all known formats.
    """
    members: list[GatewayGroupMember] = []

    raw_members = row.get("members", "")
    if isinstance(raw_members, list):
        # List of dicts format
        for m in raw_members:
            if isinstance(m, dict):
                members.append(
                    GatewayGroupMember(
                        gateway=str(m.get("gateway", m.get("name", ""))),
                        tier=int(m.get("tier") or m.get("priority") or 1),
                        weight=int(m.get("weight", 1)),
                    )
                )
    elif isinstance(raw_members, str) and raw_members:
        # Semicolon-delimited format: "GW1|1|1;GW2|2|1"
        for entry in raw_members.split(";"):
            parts = entry.strip().split("|")
            if len(parts) >= 2:
                members.append(
                    GatewayGroupMember(
                        gateway=parts[0].strip(),
                        tier=int(parts[1]) if len(parts) > 1 else 1,
                        weight=int(parts[2]) if len(parts) > 2 else 1,
                    )
                )

    return GatewayGroup(
        uuid=row.get("uuid", ""),
        name=row.get("name", ""),
        trigger=row.get("trigger", "down"),
        members=members,
    )


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__routing__add_gateway_group(
    name: str,
    members: str,
    trigger: str = "down",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Add a new gateway group for failover or load balancing.

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        name: Gateway group name (e.g. 'WAN1_Failover').
        members: JSON string -- list of objects with 'gateway', 'tier',
            and 'weight' keys. Example:
            '[{"gateway": "WAN_DHCP", "tier": 1, "weight": 1},
              {"gateway": "WAN2_DHCP", "tier": 2, "weight": 1}]'
        trigger: Failover trigger. One of: 'down', 'packet_loss',
            'high_latency', 'packet_loss_high_latency'. Default: 'down'.
        apply: Must be True to execute (write gate).

    API endpoint: POST /api/routes/gateway/addgroup
    """
    if not name or not name.strip():
        raise ValidationError(
            "Gateway group name must not be empty.",
            details={"field": "name"},
        )

    valid_triggers = {"down", "packet_loss", "high_latency", "packet_loss_high_latency"}
    if trigger not in valid_triggers:
        raise ValidationError(
            f"Trigger must be one of {valid_triggers}, got '{trigger}'",
            details={"field": "trigger", "value": trigger},
        )

    try:
        member_list = json.loads(members)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValidationError(
            f"Members must be valid JSON: {exc}",
            details={"field": "members"},
        ) from exc

    if not isinstance(member_list, list) or not member_list:
        raise ValidationError(
            "Members must be a non-empty JSON array.",
            details={"field": "members"},
        )

    # Build the group payload in OPNsense format.
    # OPNsense expects members as gateway-keyed entries with priority/weight.
    group_data: dict[str, Any] = {
        "group": {
            "name": name.strip(),
            "trigger": trigger,
        },
    }

    # Add each member gateway with its tier/weight
    for i, m in enumerate(member_list):
        gw_name = m.get("gateway", "")
        tier = m.get("tier", 1)
        weight = m.get("weight", 1)
        if not gw_name:
            raise ValidationError(
                f"Member at index {i} is missing 'gateway' field.",
                details={"field": "members", "index": i},
            )
        group_data["group"][gw_name] = f"{tier}|{weight}"

    client = _get_client()
    try:
        write_result = await client.write(
            "routes",
            "gateway",
            "addgroup",
            data=group_data,
        )

        if not is_action_success(write_result):
            validations = write_result.get("validations", {})
            detail = f"validations={validations}" if validations else f"response={write_result}"
            raise APIError(
                f"Failed to add gateway group '{name}': "
                f"{write_result.get('result', 'unknown error')} -- {detail}",
                status_code=400,
                endpoint="/api/routes/gateway/addgroup",
                response_body=str(write_result),
            )

        await client.reconfigure("routes", "gateway")

    finally:
        await client.close()

    logger.info(
        "Added gateway group: name='%s', trigger='%s', members=%d",
        name,
        trigger,
        len(member_list),
        extra={"component": "routing"},
    )

    return {
        "status": "created",
        "name": name.strip(),
        "trigger": trigger,
        "members": member_list,
        "uuid": write_result.get("uuid", ""),
    }


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__routing__add_route(
    network: str,
    gateway: str,
    description: str = "",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Add a new static route.

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        network: Destination network in CIDR notation (e.g. '10.0.0.0/8').
        gateway: Gateway name (e.g. 'WAN_GW') or IP address.
        description: Human-readable route description.
        apply: Must be True to execute (write gate).

    API endpoint: POST /api/routes/routes/addRoute
    """
    if not network or not network.strip():
        raise ValidationError(
            "Network must not be empty.",
            details={"field": "network"},
        )
    if not gateway or not gateway.strip():
        raise ValidationError(
            "Gateway must not be empty.",
            details={"field": "gateway"},
        )

    client = _get_client()
    try:
        write_result = await client.write(
            "routes",
            "routes",
            "addRoute",
            data={
                "route": {
                    "network": network.strip(),
                    "gateway": gateway.strip(),
                    "descr": description,
                    "disabled": "0",
                },
            },
        )

        if not is_action_success(write_result):
            raise APIError(
                f"Failed to add route {network} via {gateway}: "
                f"{write_result.get('result', 'unknown error')}",
                status_code=400,
                endpoint="/api/routes/routes/addRoute",
                response_body=str(write_result),
            )

        await client.reconfigure("routes", "routes")

    finally:
        await client.close()

    logger.info(
        "Added static route: %s via %s (%s)",
        network,
        gateway,
        description,
        extra={"component": "routing"},
    )

    return {
        "status": "created",
        "network": network.strip(),
        "gateway": gateway.strip(),
        "description": description,
        "uuid": write_result.get("uuid", ""),
    }
