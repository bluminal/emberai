# SPDX-License-Identifier: MIT
"""Diagnostics skill tools for OPNsense network troubleshooting.

Provides tools for ping, traceroute, DNS lookup, LLDP neighbor discovery,
and ARP-based host discovery.  Ping, traceroute, and host discovery use the
OPNsense 26.x async POST-then-poll pattern:

1. ``POST`` to start the operation (returns immediately).
2. ``GET`` a status endpoint repeatedly until the operation completes.
3. Return aggregated output once done, or partial output on timeout.

Tools
-----
- ``opnsense__diagnostics__run_ping`` -- ICMP ping a host (async polling)
- ``opnsense__diagnostics__run_traceroute`` -- Trace route to a host (async polling)
- ``opnsense__diagnostics__dns_lookup`` -- DNS lookup via Unbound diagnostics API
- ``opnsense__diagnostics__get_lldp_neighbors`` -- LLDP neighbor table
- ``opnsense__diagnostics__run_host_discovery`` -- ARP host discovery (async polling)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from opnsense.api.opnsense_client import OPNsenseClient

logger = logging.getLogger(__name__)

# Polling configuration -- shared by ping, traceroute, and host discovery.
_POLL_INTERVAL_SECONDS = 2.0
_POLL_TIMEOUT_SECONDS = 120.0


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
# Shared polling helper
# ---------------------------------------------------------------------------


async def _poll_for_result(
    client: OPNsenseClient,
    module: str,
    controller: str,
    status_command: str,
    *,
    label: str,
) -> dict[str, Any]:
    """Poll an OPNsense status endpoint until the operation completes.

    OPNsense 26.x diagnostics (ping, traceroute, host discovery) follow a
    pattern where the status endpoint returns ``{"status": "running", ...}``
    while the operation is in progress and ``{"status": "done", ...}`` (or
    ``"completed"``) when finished.  Some endpoints (ping, traceroute) do
    not include a ``status`` field but instead return progressively longer
    output text -- completion is detected by observing that the output has
    stopped growing between two consecutive polls.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    module:
        API module (e.g. ``"diagnostics"``).
    controller:
        API controller (e.g. ``"interface"``).
    status_command:
        The status/poll command (e.g. ``"pingStatus"``).
    label:
        Human-readable label for log messages (e.g. ``"ping 8.8.8.8"``).

    Returns
    -------
    dict
        ``{"result": <raw poll response>, "completed": bool,
        "elapsed_seconds": float}``
    """
    elapsed = 0.0
    last_result: dict[str, Any] = {}
    completed = False
    prev_output_len = -1

    while elapsed < _POLL_TIMEOUT_SECONDS:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        elapsed += _POLL_INTERVAL_SECONDS

        try:
            poll_result = await client.get(module, controller, status_command)
        except Exception:
            logger.warning(
                "Poll error during %s at %.1fs, continuing...",
                label,
                elapsed,
            )
            continue

        last_result = poll_result

        # Method 1: Explicit status field (used by host discovery, some
        # traceroute implementations).
        status = poll_result.get("status", "")
        if isinstance(status, str) and status.lower() in ("done", "completed"):
            completed = True
            break

        # Method 2: For ping/traceroute the response is typically
        # ``{"result": "<output text>", "status": "running"}``.
        # When status goes to "done" or the output stabilises, we're done.
        # Detect stabilisation: if output length unchanged between two polls
        # AND we have at least some output, treat as completed.
        output = poll_result.get("result", poll_result.get("output", ""))
        if isinstance(output, str):
            cur_len = len(output)
            if cur_len > 0 and cur_len == prev_output_len:
                # Output has stabilised -- operation is finished.
                completed = True
                break
            prev_output_len = cur_len

    if completed:
        logger.info("%s completed in %.1fs", label, elapsed)
    else:
        logger.warning("%s timed out after %.1fs", label, elapsed)

    return {
        "result": last_result,
        "completed": completed,
        "elapsed_seconds": round(elapsed, 1),
    }


# ---------------------------------------------------------------------------
# Ping (26.x POST-then-poll)
# ---------------------------------------------------------------------------


async def opnsense__diagnostics__run_ping(
    client: OPNsenseClient,
    host: str,
    *,
    count: int | None = None,
    source_ip: str | None = None,
) -> dict[str, Any]:
    """Ping a host from the OPNsense firewall.

    Uses the OPNsense 26.x async polling pattern:

    1. ``POST /api/diagnostics/interface/ping`` -- start the ping job.
    2. ``GET  /api/diagnostics/interface/pingStatus`` -- poll for results.

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
        Ping result dict with keys:
        - ``host``: the target that was pinged
        - ``output``: raw ping output text
        - ``completed``: whether the operation finished before timeout
        - ``elapsed_seconds``: wall-clock time taken
    """
    data: dict[str, Any] = {"address": host}
    if count is not None:
        data["count"] = str(count)
    if source_ip is not None:
        data["source_address"] = source_ip

    # Step 1: Start the ping
    await client.post("diagnostics", "interface", "ping", data=data)
    logger.info("Started ping to %s", host)

    # Step 2: Poll for results
    poll = await _poll_for_result(
        client,
        "diagnostics",
        "interface",
        "pingStatus",
        label=f"ping {host}",
    )

    raw = poll["result"]
    return {
        "host": host,
        "output": raw.get("result", raw.get("output", raw)),
        "completed": poll["completed"],
        "elapsed_seconds": poll["elapsed_seconds"],
    }


# ---------------------------------------------------------------------------
# Traceroute (26.x POST-then-poll)
# ---------------------------------------------------------------------------


async def opnsense__diagnostics__run_traceroute(
    client: OPNsenseClient,
    host: str,
    *,
    max_hops: int | None = None,
) -> dict[str, Any]:
    """Trace the route to a host from the OPNsense firewall.

    Uses the OPNsense 26.x async polling pattern:

    1. ``POST /api/diagnostics/interface/trace`` -- start the traceroute.
    2. ``GET  /api/diagnostics/interface/traceStatus`` -- poll for results.

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
        Traceroute result dict with keys:
        - ``host``: the target traced
        - ``output``: raw traceroute output text
        - ``completed``: whether the operation finished before timeout
        - ``elapsed_seconds``: wall-clock time taken
    """
    data: dict[str, Any] = {"address": host}
    if max_hops is not None:
        data["maxttl"] = str(max_hops)

    # Step 1: Start the traceroute
    await client.post("diagnostics", "interface", "trace", data=data)
    logger.info("Started traceroute to %s", host)

    # Step 2: Poll for results
    poll = await _poll_for_result(
        client,
        "diagnostics",
        "interface",
        "traceStatus",
        label=f"traceroute {host}",
    )

    raw = poll["result"]
    return {
        "host": host,
        "output": raw.get("result", raw.get("output", raw)),
        "completed": poll["completed"],
        "elapsed_seconds": poll["elapsed_seconds"],
    }


# ---------------------------------------------------------------------------
# DNS Lookup (26.x Unbound diagnostics)
# ---------------------------------------------------------------------------


async def opnsense__diagnostics__dns_lookup(
    client: OPNsenseClient,
    hostname: str,
    *,
    record_type: str | None = None,
) -> dict[str, Any]:
    """Perform a DNS lookup via the OPNsense Unbound diagnostics API.

    Uses ``GET /api/unbound/diagnostics/lookup`` which is the correct
    endpoint on OPNsense 26.x.  The previous ``/api/diagnostics/dns/
    reverseResolve`` endpoint returns 404 on 26.x.

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
    params: dict[str, Any] = {"hostname": hostname}
    if record_type is not None:
        params["type"] = record_type

    result = await client.get(
        "unbound",
        "diagnostics",
        "lookup",
        params=params,
    )
    logger.info("DNS lookup for %s completed", hostname)
    return result


async def opnsense__diagnostics__get_lldp_neighbors(
    *,
    interface: str | None = None,
) -> list[dict[str, Any]]:
    """Get LLDP neighbor table from the OPNsense firewall.

    Queries LLDP (Link Layer Discovery Protocol) neighbor information
    to identify directly connected network devices.

    Parameters
    ----------
    interface:
        If provided, filter neighbors to this interface.

    Returns
    -------
    list[dict]
        List of LLDP neighbor dictionaries with keys:
        ``local_interface``, ``chassis_name``, ``chassis_id``,
        ``chassis_descr``, ``port_id``, ``port_descr``.
    """
    client = _get_client()
    try:
        raw = await client.get("diagnostics", "lldp", "getNeighbors")
    finally:
        await client.close()

    neighbors: list[dict[str, Any]] = []

    # OPNsense LLDP response format: {lldp: {interface: [...]}}
    lldp_data = raw.get("lldp", {})
    iface_list = lldp_data.get("interface", [])
    if isinstance(iface_list, list):
        for iface_entry in iface_list:
            chassis_list = iface_entry.get("chassis", [])
            port_list = iface_entry.get("port", [])
            chassis = chassis_list[0] if chassis_list else {}
            port = port_list[0] if port_list else {}

            neighbor: dict[str, Any] = {
                "local_interface": iface_entry.get("name", ""),
                "chassis_name": _extract_lldp_value(chassis, "name"),
                "chassis_id": _extract_lldp_value(chassis, "id"),
                "chassis_descr": _extract_lldp_value(chassis, "descr"),
                "port_id": _extract_lldp_value(port, "id"),
                "port_descr": _extract_lldp_value(port, "descr"),
            }
            neighbors.append(neighbor)

    # Fallback: rows or neighbors format (non-LLDP-XML responses)
    if not neighbors:
        if "rows" in raw and isinstance(raw["rows"], list):
            neighbors = raw["rows"]
        elif "neighbors" in raw and isinstance(raw["neighbors"], list):
            neighbors = raw["neighbors"]

    # Post-filter by interface if requested
    if interface is not None:
        neighbors = [
            n
            for n in neighbors
            if n.get("local_interface") == interface
            or n.get("interface") == interface
            or n.get("local_port") == interface
        ]

    logger.info(
        "Listed %d LLDP neighbors (interface=%s)",
        len(neighbors),
        interface,
    )
    return neighbors


def _extract_lldp_value(data: dict[str, Any], key: str) -> str:
    """Extract a value from LLDP nested format.

    LLDP values come as ``{"name": [{"value": "..."}]}`` or
    plain ``{"name": "..."}``.
    """
    val = data.get(key, "")
    if isinstance(val, list) and val:
        return str(val[0].get("value", ""))
    return str(val)


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
    ``completed: false`` flag.

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
        "diagnostics",
        "interface",
        "startScan",
        data=start_data,
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
                "diagnostics",
                "interface",
                "getScanResult",
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
