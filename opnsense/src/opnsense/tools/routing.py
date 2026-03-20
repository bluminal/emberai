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

import logging
import os
from typing import Any

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.api.response import is_action_success, normalize_response
from opnsense.cache import CacheTTL
from opnsense.errors import APIError, ValidationError
from opnsense.models.routing import Gateway, Route
from opnsense.safety import write_gate
from opnsense.server import mcp_server

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OPNsense API coercion helpers
# ---------------------------------------------------------------------------

_STR_BOOL_TRUE = frozenset({"1", "true", "yes"})


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
            "routes", "routes", "searchRoute",
            cache_key="routing:routes",
            ttl=CacheTTL.ROUTES,
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
    status, priority, and round-trip time.

    API endpoint: GET /api/routes/gateway/status
    """
    client = _get_client()
    try:
        raw = await client.get_cached(
            "routes", "gateway", "status",
            cache_key="routing:gateways",
            ttl=CacheTTL.GATEWAYS,
        )
    finally:
        await client.close()

    # Gateway status returns an "items" array (action-style response)
    items = raw.get("items", [])
    if not items and "rows" in raw:
        # Fall back to search-style if the API returns rows instead
        items = raw["rows"]

    gateways: list[dict[str, Any]] = []
    for item in items:
        try:
            gw = Gateway.model_validate(item)
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


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------


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
            "routes", "routes", "addRoute",
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
        network, gateway, description,
        extra={"component": "routing"},
    )

    return {
        "status": "created",
        "network": network.strip(),
        "gateway": gateway.strip(),
        "description": description,
        "uuid": write_result.get("uuid", ""),
    }
