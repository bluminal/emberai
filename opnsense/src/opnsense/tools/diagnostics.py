# SPDX-License-Identifier: MIT
"""Diagnostics skill tools for OPNsense network troubleshooting.

Provides tools for ping, traceroute, DNS lookup, LLDP neighbor discovery,
and ARP-based host discovery. The host discovery tool uses an async polling
pattern since the OPNsense API runs discovery as a background job.

Tools
-----
- ``opnsense__diagnostics__run_ping`` -- ICMP ping a host
- ``opnsense__diagnostics__run_traceroute`` -- Trace route to a host
- ``opnsense__diagnostics__dns_lookup`` -- DNS lookup via diagnostics API
- ``opnsense__diagnostics__get_lldp_neighbors`` -- LLDP neighbor table
- ``opnsense__diagnostics__run_host_discovery`` -- ARP host discovery (async polling)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from opnsense.api.opnsense_client import OPNsenseClient

logger = logging.getLogger(__name__)

# Host discovery polling configuration
_POLL_INTERVAL_SECONDS = 2.0
_POLL_TIMEOUT_SECONDS = 120.0


async def opnsense__diagnostics__run_ping(
    client: OPNsenseClient,
    host: str,
    *,
    count: int | None = None,
    source_ip: str | None = None,
) -> dict[str, Any]:
    """Ping a host from the OPNsense firewall.

    Sends an ICMP ping via ``POST /api/diagnostics/interface/getPing``
    and returns the results including round-trip times and packet loss.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    host:
        Target hostname or IP address to ping.
    count:
        Number of ping packets to send (default: API default, usually 3).
    source_ip:
        Source IP address for the ping (useful for multi-WAN setups).

    Returns
    -------
    dict
        Ping result including RTT statistics and packet loss.
    """
    data: dict[str, Any] = {"address": host}
    if count is not None:
        data["count"] = str(count)
    if source_ip is not None:
        data["source_address"] = source_ip

    result = await client.post("diagnostics", "interface", "getPing", data=data)
    logger.info("Ping %s completed", host)
    return result


async def opnsense__diagnostics__run_traceroute(
    client: OPNsenseClient,
    host: str,
    *,
    max_hops: int | None = None,
) -> dict[str, Any]:
    """Trace the route to a host from the OPNsense firewall.

    Runs a traceroute via ``POST /api/diagnostics/interface/getTrace``
    and returns the hop-by-hop path including RTT for each hop.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    host:
        Target hostname or IP address.
    max_hops:
        Maximum number of hops (TTL). Default: API default (usually 30).

    Returns
    -------
    dict
        Traceroute result with per-hop data.
    """
    data: dict[str, Any] = {"address": host}
    if max_hops is not None:
        data["maxttl"] = str(max_hops)

    result = await client.post("diagnostics", "interface", "getTrace", data=data)
    logger.info("Traceroute to %s completed", host)
    return result


async def opnsense__diagnostics__dns_lookup(
    client: OPNsenseClient,
    hostname: str,
    *,
    record_type: str | None = None,
) -> dict[str, Any]:
    """Perform a DNS lookup via the OPNsense diagnostics API.

    Uses ``GET /api/diagnostics/dns/reverseResolve`` for reverse
    lookups and general DNS resolution diagnostics.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    hostname:
        The hostname or IP address to look up.
    record_type:
        Optional DNS record type (e.g. ``"A"``, ``"AAAA"``, ``"MX"``).

    Returns
    -------
    dict
        DNS lookup result.
    """
    params: dict[str, Any] = {"address": hostname}
    if record_type is not None:
        params["type"] = record_type

    result = await client.get(
        "diagnostics", "dns", "reverseResolve", params=params,
    )
    logger.info("DNS lookup for %s completed", hostname)
    return result


async def opnsense__diagnostics__get_lldp_neighbors(
    client: OPNsenseClient,
    *,
    interface: str | None = None,
) -> list[dict[str, Any]]:
    """Get LLDP neighbor table from the OPNsense firewall.

    Queries LLDP (Link Layer Discovery Protocol) neighbor information
    to identify directly connected network devices.

    .. note::
        This tool may already exist in M3.2 parallel work. If so,
        the duplication will be resolved at merge time.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    interface:
        If provided, filter neighbors to this interface.

    Returns
    -------
    list[dict]
        List of LLDP neighbor dictionaries.
    """
    raw = await client.get("diagnostics", "lldp", "getNeighbors")

    # Response may be in "rows" or "neighbors" format depending on version
    neighbors: list[dict[str, Any]]
    if "rows" in raw and isinstance(raw["rows"], list):
        neighbors = raw["rows"]
    elif "neighbors" in raw and isinstance(raw["neighbors"], list):
        neighbors = raw["neighbors"]
    else:
        # Flat response, wrap as single entry
        neighbors = [raw] if raw else []

    # Post-filter by interface if requested
    if interface is not None:
        neighbors = [
            n for n in neighbors
            if n.get("interface") == interface or n.get("local_port") == interface
        ]

    logger.info("Listed %d LLDP neighbors (interface=%s)", len(neighbors), interface)
    return neighbors


async def opnsense__diagnostics__run_host_discovery(
    client: OPNsenseClient,
    interface: str,
) -> dict[str, Any]:
    """Run ARP-based host discovery on an interface.

    This is an asynchronous operation that uses the OPNsense polling
    pattern:

    1. ``POST /api/diagnostics/interface/startScan`` -- start the scan
    2. Poll ``GET /api/diagnostics/interface/getScanResult`` every 2s
    3. Return results when scan completes or timeout (120s) is reached

    If the scan times out, partial results are returned with a
    ``timed_out: true`` flag.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    interface:
        The interface to scan (e.g. ``"igb1"``, ``"igb1_vlan10"``).

    Returns
    -------
    dict
        Discovery results with keys:
        - ``hosts``: list of discovered hosts
        - ``interface``: the scanned interface
        - ``completed``: whether the scan finished before timeout
        - ``elapsed_seconds``: time taken
    """
    # Step 1: Start the scan
    start_data = {"interface": interface}
    start_result = await client.post(
        "diagnostics", "interface", "startScan", data=start_data,
    )
    logger.info("Started host discovery on %s", interface)

    # Step 2: Poll for results
    elapsed = 0.0
    hosts: list[dict[str, Any]] = []
    completed = False

    while elapsed < _POLL_TIMEOUT_SECONDS:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        elapsed += _POLL_INTERVAL_SECONDS

        try:
            poll_result = await client.get(
                "diagnostics", "interface", "getScanResult",
            )
        except Exception:
            logger.warning(
                "Poll error during host discovery at %.1fs, continuing...",
                elapsed,
            )
            continue

        # Check if scan is complete
        status = poll_result.get("status", "")
        if isinstance(status, str) and status.lower() in ("done", "completed"):
            completed = True
            # Extract hosts from result
            if "rows" in poll_result:
                hosts = poll_result["rows"]
            elif "hosts" in poll_result:
                hosts = poll_result["hosts"]
            else:
                hosts = [poll_result]
            break

        # Collect partial results if available
        if "rows" in poll_result:
            hosts = poll_result["rows"]
        elif "hosts" in poll_result:
            hosts = poll_result["hosts"]

    if not completed:
        logger.warning(
            "Host discovery on %s timed out after %.1fs with %d partial results",
            interface,
            elapsed,
            len(hosts),
        )
    else:
        logger.info(
            "Host discovery on %s completed in %.1fs, found %d hosts",
            interface,
            elapsed,
            len(hosts),
        )

    return {
        "hosts": hosts,
        "interface": interface,
        "completed": completed,
        "elapsed_seconds": round(elapsed, 1),
        "start_result": start_result,
    }
