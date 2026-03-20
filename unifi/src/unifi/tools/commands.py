# SPDX-License-Identifier: MIT
"""Command-level MCP tools -- thin wrappers that delegate to agent orchestrators.

These tools represent the user-facing ``unifi scan``, ``unifi health``,
``unifi clients``, and ``unifi diagnose`` commands.  Each is a minimal
shim that forwards to the corresponding agent function, keeping the tool
surface lean and the business logic testable independently.
"""

from __future__ import annotations

from unifi.server import mcp_server


@mcp_server.tool()
async def unifi_scan(site_id: str = "default") -> str:
    """Discover and map the full network topology for a UniFi site.

    Shows all devices (switches, APs, gateways), VLANs, and uplink
    connections in a formatted report.

    Phase 1 scope: single-site only. Multi-site selection added in Phase 2.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    from unifi.agents.topology import scan_site

    return await scan_site(site_id)


@mcp_server.tool()
async def unifi_health(site_id: str = "default") -> str:
    """Run a comprehensive health check with severity-tiered findings.

    Checks subsystem status, recent events, firmware updates, and ISP
    metrics. Returns findings grouped by severity (Critical > Warning >
    Informational).

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    from unifi.agents.health import check_health

    return await check_health(site_id)


@mcp_server.tool()
async def unifi_clients(
    site_id: str = "default",
    vlan_id: str | None = None,
    ap_id: str | None = None,
) -> str:
    """Inventory all connected clients, optionally filtered.

    Shows hostname/MAC, IP, VLAN, AP/port, connection type, signal quality,
    and traffic summary for each connected client.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
        vlan_id: Filter by VLAN/network ID.
        ap_id: Filter by access point MAC address.
    """
    from unifi.agents.clients import list_clients_report

    return await list_clients_report(site_id, vlan_id=vlan_id, ap_id=ap_id)


@mcp_server.tool()
async def unifi_diagnose(target: str, site_id: str = "default") -> str:
    """Root-cause analysis for a device or client.

    Searches for the target by MAC, hostname, IP, or name. If the target
    is ambiguous (matches multiple devices or clients), prompts for
    clarification. Correlates health data, events, and topology to
    produce a diagnostic report with findings and recommendations.

    Phase 1 scope: correlates health events + client data + topology.
    Security correlation added in Phase 2.

    Args:
        target: Device MAC/name/IP or client MAC/hostname/IP to diagnose.
        site_id: The UniFi site ID. Defaults to "default".
    """
    from unifi.agents.diagnose import diagnose_target

    return await diagnose_target(target, site_id=site_id)
