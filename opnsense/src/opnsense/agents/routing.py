# SPDX-License-Identifier: MIT
"""Routing agent -- routing table report.

Produces a severity-tiered OX report covering static routes and gateway
status on the OPNsense firewall. Identifies issues such as offline
gateways, disabled routes, and high-latency gateways.
"""

from __future__ import annotations

import logging
from typing import Any

from opnsense.output import Finding, Severity, format_severity_report, format_table
from opnsense.tools.routing import (
    opnsense__routing__list_gateways,
    opnsense__routing__list_routes,
)

logger = logging.getLogger(__name__)

# Gateway RTT thresholds in milliseconds
_RTT_WARNING_THRESHOLD = 50.0
_RTT_HIGH_THRESHOLD = 200.0


async def run_routing_report() -> str:
    """Generate a routing table report.

    Fetches all static routes and gateway statuses, then produces
    a formatted report with:
    - Gateway status table
    - Static route table
    - Findings (offline gateways, disabled routes, high latency)

    Returns:
        A markdown-formatted routing report string.
    """
    # Fetch data from tools
    routes = await opnsense__routing__list_routes()
    gateways = await opnsense__routing__list_gateways()

    findings: list[Finding] = []
    sections: list[str] = []

    # --- Gateway status table ---
    if gateways:
        gw_headers = ["Name", "Address", "Interface", "Status", "RTT (ms)", "Monitor"]
        gw_rows: list[list[str]] = []
        for gw in gateways:
            rtt = gw.get("rtt_ms")
            rtt_str = f"{rtt:.1f}" if rtt is not None else "n/a"
            status = gw.get("status", "unknown")
            gw_rows.append([
                gw.get("name", ""),
                gw.get("gateway", ""),
                gw.get("interface", ""),
                status,
                rtt_str,
                gw.get("monitor", ""),
            ])

            # Check for offline gateways
            if status.lower() in ("offline", "down"):
                findings.append(Finding(
                    severity=Severity.CRITICAL,
                    title=f"Gateway '{gw.get('name', '')}' is offline",
                    detail=(
                        f"Gateway {gw.get('name', '')} at {gw.get('gateway', '')} "
                        f"on interface {gw.get('interface', '')} is reporting "
                        f"status '{status}'. Routes using this gateway are not functional."
                    ),
                    recommendation=(
                        "Check physical connectivity and upstream provider status. "
                        "Verify the monitor IP is reachable."
                    ),
                ))

            # Check for high-latency gateways
            if rtt is not None and rtt >= _RTT_HIGH_THRESHOLD:
                findings.append(Finding(
                    severity=Severity.HIGH,
                    title=f"Gateway '{gw.get('name', '')}' has very high latency",
                    detail=(
                        f"Gateway {gw.get('name', '')} has an RTT of {rtt:.1f} ms "
                        f"(threshold: {_RTT_HIGH_THRESHOLD} ms). This may indicate "
                        "severe congestion or a routing issue."
                    ),
                    recommendation="Investigate upstream link quality and routing path.",
                ))
            elif rtt is not None and rtt >= _RTT_WARNING_THRESHOLD:
                findings.append(Finding(
                    severity=Severity.WARNING,
                    title=f"Gateway '{gw.get('name', '')}' has elevated latency",
                    detail=(
                        f"Gateway {gw.get('name', '')} has an RTT of {rtt:.1f} ms "
                        f"(warning threshold: {_RTT_WARNING_THRESHOLD} ms)."
                    ),
                    recommendation="Monitor for further degradation.",
                ))

        sections.append(format_table(gw_headers, gw_rows, title="Gateway Status"))
    else:
        findings.append(Finding(
            severity=Severity.HIGH,
            title="No gateways found",
            detail="The API returned no gateway data. This may indicate a connectivity issue.",
            recommendation="Verify API connectivity and permissions.",
        ))

    # --- Static route table ---
    if routes:
        route_headers = ["Network", "Gateway", "Status", "Description"]
        route_rows: list[list[str]] = []
        for route in routes:
            disabled = route.get("disabled", False)
            status = "disabled" if disabled else "active"
            route_rows.append([
                route.get("network", ""),
                route.get("gateway", ""),
                status,
                route.get("description", ""),
            ])

            # Check for disabled routes
            if disabled:
                findings.append(Finding(
                    severity=Severity.INFORMATIONAL,
                    title=f"Disabled route: {route.get('network', '')}",
                    detail=(
                        f"Route to {route.get('network', '')} via "
                        f"{route.get('gateway', '')} is disabled. "
                        f"Description: {route.get('description', 'none')}"
                    ),
                    recommendation="Review and either re-enable or delete the route.",
                ))

            # Check for routes pointing to offline gateways
            route_gw = route.get("gateway", "")
            gw_status_map = {g.get("name", ""): g.get("status", "") for g in gateways}
            if route_gw in gw_status_map and gw_status_map[route_gw].lower() in ("offline", "down"):
                if not disabled:
                    findings.append(Finding(
                        severity=Severity.HIGH,
                        title=f"Route via offline gateway: {route.get('network', '')}",
                        detail=(
                            f"Active route to {route.get('network', '')} uses gateway "
                            f"'{route_gw}' which is currently offline. Traffic to this "
                            "network will be blackholed."
                        ),
                        recommendation=(
                            "Disable the route or resolve the gateway connectivity issue."
                        ),
                    ))

        sections.append(format_table(route_headers, route_rows, title="Static Routes"))

    # --- Build report ---
    report_body = "\n".join(sections)

    active_routes = [r for r in routes if not r.get("disabled", False)]
    disabled_routes = [r for r in routes if r.get("disabled", False)]
    online_gw = [g for g in gateways if g.get("status", "").lower() in ("online", "up")]
    offline_gw = [g for g in gateways if g.get("status", "").lower() in ("offline", "down")]

    stats_line = (
        f"**{len(online_gw)}/{len(gateways)} gateways online** | "
        f"**{len(active_routes)} active routes** | "
        f"**{len(disabled_routes)} disabled**"
    )

    findings_report = format_severity_report("Routing Findings", findings)

    full_report = f"## Routing Table Report\n\n{stats_line}\n\n{report_body}\n{findings_report}"

    logger.info(
        "Generated routing report: %d gateways, %d routes, %d findings",
        len(gateways), len(routes), len(findings),
        extra={"component": "agents.routing"},
    )

    return full_report
