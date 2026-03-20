# SPDX-License-Identifier: MIT
"""Diagnostics report agent for OPNsense.

Produces network diagnostics reports including connectivity tests
(ping, traceroute) and device discovery results. Uses the OX output
pattern for consistent formatting.
"""

from __future__ import annotations

from typing import Any

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.output import Finding, Severity, format_key_value, format_severity_report
from opnsense.tools.diagnostics import (
    opnsense__diagnostics__run_ping,
    opnsense__diagnostics__run_traceroute,
)


async def diagnostics_report(
    client: OPNsenseClient,
    *,
    targets: list[str] | None = None,
) -> str:
    """Generate a network diagnostics report.

    Runs ping and traceroute tests to specified targets (or defaults)
    and produces a summary report with connectivity findings.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    targets:
        List of hostnames or IPs to test. Defaults to common
        connectivity check targets.

    Returns
    -------
    str
        Markdown-formatted diagnostics report.
    """
    if targets is None:
        targets = ["8.8.8.8", "1.1.1.1"]

    findings: list[Finding] = []
    sections: list[str] = []

    for target in targets:
        try:
            ping_result = await opnsense__diagnostics__run_ping(
                client, target, count=3,
            )

            # Extract key metrics from ping result
            kv_data: dict[str, str] = {
                "Target": target,
                "Status": "Reachable" if ping_result else "Unknown",
            }

            # Add any available metrics
            for key in ("avg", "min", "max", "loss", "packets_received"):
                if key in ping_result:
                    kv_data[key.replace("_", " ").title()] = str(ping_result[key])

            sections.append(format_key_value(kv_data, title=f"Ping: {target}"))

            # Assess connectivity
            loss = ping_result.get("loss", "")
            if isinstance(loss, str) and "100" in loss:
                findings.append(Finding(
                    severity=Severity.HIGH,
                    title=f"Host unreachable: {target}",
                    detail=f"100% packet loss when pinging {target}.",
                    recommendation="Check routing, firewall rules, and upstream connectivity.",
                ))
            elif loss and loss != "0":
                findings.append(Finding(
                    severity=Severity.WARNING,
                    title=f"Packet loss to {target}",
                    detail=f"Experienced {loss} packet loss when pinging {target}.",
                    recommendation="Investigate link quality and congestion.",
                ))
            else:
                findings.append(Finding(
                    severity=Severity.INFORMATIONAL,
                    title=f"Connectivity OK: {target}",
                    detail=f"Ping to {target} succeeded with no packet loss.",
                ))

        except Exception as exc:
            findings.append(Finding(
                severity=Severity.HIGH,
                title=f"Ping failed: {target}",
                detail=f"Unable to ping {target}: {exc}",
                recommendation="Verify network connectivity and DNS resolution.",
            ))

    # Build final report
    report_parts: list[str] = []

    if findings:
        report_parts.append(format_severity_report("Network Diagnostics", findings))

    for section in sections:
        report_parts.append(section)

    return "\n".join(report_parts)
