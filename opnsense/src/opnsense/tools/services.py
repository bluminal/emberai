# SPDX-License-Identifier: MIT
"""Services skill tools for OPNsense DNS (Unbound), DHCP (Kea), and traffic shaping.

Provides read tools for DNS overrides, forwarders, hostname resolution,
DHCP leases, and traffic shaper settings. Includes one write tool for
adding DNS host overrides with full safety gate enforcement.

OPNsense 26.x Compatibility
----------------------------
OPNsense 26.x moved Unbound DNS host override endpoints from the
``/api/unbound/host/`` controller to ``/api/unbound/settings/``:

- ``searchHost``     -> ``searchHostOverride``     (settings controller)
- ``addHost``        -> ``addHostOverride``        (settings controller)
- ``searchForward``  -> ``searchDomainOverride``   (settings controller)

The ``/api/unbound/service/reconfigure`` endpoint is unchanged.

If the 26.x endpoints return 404 (Unbound not installed), functions
degrade gracefully and return empty results with metadata.

Tools
-----
- ``opnsense__services__get_dns_overrides`` -- List DNS host overrides
- ``opnsense__services__get_dns_forwarders`` -- List DNS domain forwarders
- ``opnsense__services__resolve_hostname`` -- Resolve a hostname via Unbound
- ``opnsense__services__add_dns_override`` -- Add a DNS host override (WRITE)
- ``opnsense__services__get_dhcp_leases4`` -- List DHCPv4 leases
- ``opnsense__services__get_traffic_shaper`` -- Get traffic shaper settings
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from opnsense.errors import APIError
from opnsense.models.services import DHCPLease, DNSOverride
from opnsense.safety import reconfigure_gate, write_gate

if TYPE_CHECKING:
    from opnsense.api.opnsense_client import OPNsenseClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DNS endpoint constants -- OPNsense 26.x settings controller
# ---------------------------------------------------------------------------

# Read endpoints
_DNS_HOST_MODULE = "unbound"
_DNS_HOST_CONTROLLER = "settings"
_DNS_HOST_SEARCH_CMD = "searchHostOverride"

_DNS_FORWARD_MODULE = "unbound"
_DNS_FORWARD_CONTROLLER = "settings"
_DNS_FORWARD_SEARCH_CMD = "searchDomainOverride"

# Write endpoints
_DNS_HOST_ADD_CMD = "addHostOverride"

# Pagination params -- fetch all rows in a single request
_ALL_ROWS_PARAMS: dict[str, int] = {"rowCount": -1, "current": 1}


async def opnsense__services__get_dns_overrides(
    client: OPNsenseClient,
) -> list[dict[str, Any]]:
    """List all DNS host overrides from Unbound.

    Queries ``GET /api/unbound/settings/searchHostOverride`` (OPNsense 26.x)
    and returns all configured DNS host overrides (local DNS records).

    Handles 404 gracefully: if Unbound is not installed or the endpoint
    does not exist, returns an empty list and logs a warning.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    list[dict]
        List of DNS override dictionaries with normalized field names.
        Returns an empty list if Unbound is not installed.
    """
    try:
        raw = await client.get(
            _DNS_HOST_MODULE,
            _DNS_HOST_CONTROLLER,
            _DNS_HOST_SEARCH_CMD,
            params=_ALL_ROWS_PARAMS,
        )
    except APIError as exc:
        if exc.status_code == 404:
            logger.warning(
                "Unbound DNS host override endpoint returned 404. "
                "Unbound may not be installed or the plugin is missing. "
                "Endpoint: /api/%s/%s/%s",
                _DNS_HOST_MODULE,
                _DNS_HOST_CONTROLLER,
                _DNS_HOST_SEARCH_CMD,
            )
            return []
        raise

    rows = raw.get("rows", [])

    overrides: list[dict[str, Any]] = []
    for row in rows:
        try:
            override = DNSOverride.model_validate(row)
            overrides.append(override.model_dump())
        except Exception:
            logger.warning("Failed to parse DNS override: %s", row.get("hostname", "unknown"))
            overrides.append(row)

    logger.info("Listed %d DNS overrides", len(overrides))
    return overrides


async def opnsense__services__get_dns_forwarders(
    client: OPNsenseClient,
) -> list[dict[str, Any]]:
    """List DNS domain overrides (forwarding entries) configured in Unbound.

    Queries ``GET /api/unbound/settings/searchDomainOverride`` (OPNsense 26.x)
    and returns all configured DNS domain forwarding entries.

    Handles 404 gracefully: if Unbound is not installed or the endpoint
    does not exist, returns an empty list and logs a warning.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    list[dict]
        List of DNS forwarder/domain override dictionaries.
        Returns an empty list if Unbound is not installed.
    """
    try:
        raw = await client.get(
            _DNS_FORWARD_MODULE,
            _DNS_FORWARD_CONTROLLER,
            _DNS_FORWARD_SEARCH_CMD,
            params=_ALL_ROWS_PARAMS,
        )
    except APIError as exc:
        if exc.status_code == 404:
            logger.warning(
                "Unbound DNS domain override endpoint returned 404. "
                "Unbound may not be installed or the plugin is missing. "
                "Endpoint: /api/%s/%s/%s",
                _DNS_FORWARD_MODULE,
                _DNS_FORWARD_CONTROLLER,
                _DNS_FORWARD_SEARCH_CMD,
            )
            return []
        raise

    rows: list[dict[str, Any]] = raw.get("rows", [])

    logger.info("Listed %d DNS domain overrides (forwarders)", len(rows))
    return rows


async def opnsense__services__resolve_hostname(
    client: OPNsenseClient,
    hostname: str,
) -> dict[str, Any]:
    """Resolve a hostname using the OPNsense Unbound DNS resolver.

    Queries ``GET /api/unbound/diagnostics/lookup/{hostname}`` to
    perform a DNS lookup through the firewall's local resolver.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    hostname:
        The hostname to resolve (e.g. ``"nas.home.local"``).

    Returns
    -------
    dict
        DNS lookup result from Unbound diagnostics.
    """
    raw = await client.get("unbound", "diagnostics", f"lookup/{hostname}")
    logger.info("Resolved hostname: %s", hostname)
    return raw


@write_gate("OPNSENSE")
async def _add_dns_override_write(
    client: OPNsenseClient,
    hostname: str,
    domain: str,
    ip: str,
    description: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Internal write operation for adding a DNS override.

    Protected by the write gate. Saves the host override to config
    via ``POST /api/unbound/settings/addHostOverride`` (OPNsense 26.x).

    The payload key is ``host_override`` (26.x convention) with the
    ``server`` field containing the target IP address.
    """
    data = {
        "host_override": {
            "hostname": hostname,
            "domain": domain,
            "server": ip,
            "description": description,
            "enabled": "1",
        }
    }
    result = await client.write(
        _DNS_HOST_MODULE,
        _DNS_HOST_CONTROLLER,
        _DNS_HOST_ADD_CMD,
        data=data,
    )
    logger.info(
        "Added DNS override: %s.%s -> %s",
        hostname,
        domain,
        ip,
    )
    return result


@reconfigure_gate("OPNSENSE")
async def _reconfigure_unbound(
    client: OPNsenseClient,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Internal reconfigure operation for Unbound DNS.

    Protected by the reconfigure gate. Applies saved DNS config
    to the live Unbound resolver.
    """
    result = await client.reconfigure("unbound", "service")
    logger.info("Unbound reconfigure completed")
    return result


async def opnsense__services__add_dns_override(
    client: OPNsenseClient,
    hostname: str,
    domain: str,
    ip: str,
    description: str = "",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Add a DNS host override to Unbound and optionally apply.

    This is a WRITE operation protected by the safety gate. It follows
    the OPNsense two-step pattern:

    1. Save the host override to config (write gate).
    2. Reconfigure Unbound to apply the change (reconfigure gate).

    Both steps require ``OPNSENSE_WRITE_ENABLED=true`` and ``apply=True``.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    hostname:
        Hostname portion (e.g. ``"nas"`` for ``nas.home.local``).
    domain:
        Domain portion (e.g. ``"home.local"``).
    ip:
        IP address the hostname should resolve to.
    description:
        Optional human-readable description.
    apply:
        Must be ``True`` to execute. Without it, the safety gate blocks.

    Returns
    -------
    dict
        Result with ``write_result`` and ``reconfigure_result`` keys.

    Raises
    ------
    WriteGateError
        If ``OPNSENSE_WRITE_ENABLED`` is not ``true`` or ``apply`` is ``False``.
    """
    write_result = await _add_dns_override_write(
        client,
        hostname,
        domain,
        ip,
        description,
        apply=apply,
    )
    reconfigure_result = await _reconfigure_unbound(client, apply=apply)

    return {
        "write_result": write_result,
        "reconfigure_result": reconfigure_result,
        "hostname": hostname,
        "domain": domain,
        "ip": ip,
        "fqdn": f"{hostname}.{domain}",
    }


async def opnsense__services__get_dhcp_leases4(
    client: OPNsenseClient,
    *,
    interface: str | None = None,
) -> list[dict[str, Any]]:
    """List DHCPv4 leases from the Kea DHCP server.

    Queries ``GET /api/kea/leases4/search`` and returns all DHCP leases,
    optionally filtered by interface.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    interface:
        If provided, filter leases to this interface (e.g. ``"igb1"``).

    Returns
    -------
    list[dict]
        List of DHCP lease dictionaries with normalized field names.
    """
    raw = await client.get("kea", "leases4", "search")
    rows = raw.get("rows", [])

    leases: list[dict[str, Any]] = []
    for row in rows:
        try:
            lease = DHCPLease.model_validate(row)
            lease_dict = lease.model_dump()

            # Post-filter by interface if requested
            if interface is not None and lease_dict.get("interface") != interface:
                continue

            leases.append(lease_dict)
        except Exception:
            logger.warning("Failed to parse DHCP lease: %s", row.get("address", "unknown"))
            if interface is None or row.get("interface") == interface:
                leases.append(row)

    logger.info("Listed %d DHCP leases (interface=%s)", len(leases), interface)
    return leases


async def opnsense__services__get_traffic_shaper(
    client: OPNsenseClient,
) -> dict[str, Any]:
    """Get traffic shaper settings.

    Queries ``GET /api/trafficshaper/settings/getSettings`` and returns
    the full traffic shaping configuration including pipes, queues,
    and rules.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    dict
        Traffic shaper settings dictionary.
    """
    raw = await client.get("trafficshaper", "settings", "getSettings")
    logger.info("Retrieved traffic shaper settings")
    return raw
