# SPDX-License-Identifier: MIT
"""Command-level MCP tools -- thin wrappers that delegate to agent orchestrators.

These tools represent the user-facing ``unifi scan`` and ``unifi health``
commands.  Each is a minimal shim that forwards to the corresponding
agent function, keeping the tool surface lean and the business logic
testable independently.
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
