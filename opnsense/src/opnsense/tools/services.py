# SPDX-License-Identifier: MIT
"""Services skill tools for OPNsense DNS (Unbound), DHCP (Kea), and traffic shaping.

Provides read tools for DNS overrides, forwarders, hostname resolution,
DHCP leases, and traffic shaper settings. Includes one write tool for
adding DNS host overrides with full safety gate enforcement.

Tools
-----
- ``opnsense__services__get_dns_overrides`` -- List DNS host overrides
- ``opnsense__services__get_dns_forwarders`` -- List DNS forwarders
- ``opnsense__services__resolve_hostname`` -- Resolve a hostname via Unbound
- ``opnsense__services__add_dns_override`` -- Add a DNS host override (WRITE)
- ``opnsense__services__get_dhcp_leases4`` -- List DHCPv4 leases
- ``opnsense__services__get_traffic_shaper`` -- Get traffic shaper settings
"""

from __future__ import annotations

import logging
from typing import Any

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.models.services import DHCPLease, DNSOverride
from opnsense.safety import reconfigure_gate, write_gate

logger = logging.getLogger(__name__)


async def opnsense__services__get_dns_overrides(
    client: OPNsenseClient,
) -> list[dict[str, Any]]:
    """List all DNS host overrides from Unbound.

    Queries ``GET /api/unbound/host/searchHost`` and returns all
    configured DNS host overrides (local DNS records).

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    list[dict]
        List of DNS override dictionaries with normalized field names.
    """
    raw = await client.get("unbound", "host", "searchHost")
    rows = raw.get("rows", [])

    overrides: list[dict[str, Any]] = []
    for row in rows:
        try:
            override = DNSOverride.model_validate(row)
            overrides.append(override.model_dump())
        except Exception:
            logger.warning(
                "Failed to parse DNS override: %s", row.get("hostname", "unknown")
            )
            overrides.append(row)

    logger.info("Listed %d DNS overrides", len(overrides))
    return overrides


async def opnsense__services__get_dns_forwarders(
    client: OPNsenseClient,
) -> list[dict[str, Any]]:
    """List DNS query forwarders configured in Unbound.

    Queries ``GET /api/unbound/forward/searchForward`` and returns
    all configured DNS forwarding entries.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    list[dict]
        List of DNS forwarder dictionaries.
    """
    raw = await client.get("unbound", "forward", "searchForward")
    rows = raw.get("rows", [])

    logger.info("Listed %d DNS forwarders", len(rows))
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
    via ``POST /api/unbound/host/addHost``.
    """
    data = {
        "host": {
            "hostname": hostname,
            "domain": domain,
            "server": ip,
            "description": description,
        }
    }
    result = await client.write("unbound", "host", "addHost", data=data)
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
        client, hostname, domain, ip, description, apply=apply,
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
            logger.warning(
                "Failed to parse DHCP lease: %s", row.get("address", "unknown")
            )
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
