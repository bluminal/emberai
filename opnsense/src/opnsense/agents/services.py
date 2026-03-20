# SPDX-License-Identifier: MIT
"""Services report agent for OPNsense DNS, DHCP, and traffic shaping.

Produces a comprehensive services report covering Unbound DNS overrides,
Kea DHCP leases, and traffic shaper configuration. Uses the OX output
pattern for consistent formatting.
"""

from __future__ import annotations

from typing import Any

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.output import Finding, Severity, format_severity_report, format_table
from opnsense.tools.services import (
    opnsense__services__get_dhcp_leases4,
    opnsense__services__get_dns_overrides,
)


async def services_report(client: OPNsenseClient) -> str:
    """Generate a DNS/DHCP/traffic services report.

    Fetches DNS overrides and DHCP leases, then produces a report
    with tables and findings highlighting potential issues.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    str
        Markdown-formatted services report.
    """
    dns_overrides = await opnsense__services__get_dns_overrides(client)
    dhcp_leases = await opnsense__services__get_dhcp_leases4(client)

    findings: list[Finding] = []
    sections: list[str] = []

    # --- DNS Overrides ---
    if dns_overrides:
        rows: list[list[str]] = []
        for o in dns_overrides:
            fqdn = f"{o.get('hostname', '')}.{o.get('domain', '')}"
            rows.append([
                fqdn,
                o.get("ip", ""),
                o.get("description", ""),
            ])

        sections.append(format_table(
            headers=["FQDN", "IP", "Description"],
            rows=rows,
            title="DNS Host Overrides",
        ))

        findings.append(Finding(
            severity=Severity.INFORMATIONAL,
            title=f"{len(dns_overrides)} DNS host override(s) configured",
            detail="Local DNS records managed by Unbound.",
        ))
    else:
        findings.append(Finding(
            severity=Severity.INFORMATIONAL,
            title="No DNS host overrides configured",
            detail=(
                "No local DNS overrides found in Unbound. All DNS queries "
                "are resolved via upstream forwarders."
            ),
        ))

    # --- DHCP Leases ---
    if dhcp_leases:
        # Separate active and expired
        active_leases = [l for l in dhcp_leases if l.get("state") == "active"]
        expired_leases = [l for l in dhcp_leases if l.get("state") == "expired"]
        other_leases = [
            l for l in dhcp_leases
            if l.get("state") not in ("active", "expired")
        ]

        rows = []
        for l in dhcp_leases:
            hostname = l.get("hostname") or "(unknown)"
            rows.append([
                hostname,
                l.get("ip", ""),
                l.get("mac", ""),
                l.get("state", ""),
                l.get("interface", ""),
                l.get("expiry", l.get("expire", "")),
            ])

        sections.append(format_table(
            headers=["Hostname", "IP", "MAC", "State", "Interface", "Expires"],
            rows=rows,
            title="DHCP Leases",
        ))

        # Count by interface
        interface_counts: dict[str, int] = {}
        for l in active_leases:
            iface = l.get("interface", "unknown")
            interface_counts[iface] = interface_counts.get(iface, 0) + 1

        iface_summary = ", ".join(
            f"{iface}: {count}" for iface, count in sorted(interface_counts.items())
        )

        findings.append(Finding(
            severity=Severity.INFORMATIONAL,
            title=f"{len(active_leases)} active DHCP lease(s)",
            detail=f"Active leases by interface: {iface_summary}",
        ))

        if expired_leases:
            findings.append(Finding(
                severity=Severity.INFORMATIONAL,
                title=f"{len(expired_leases)} expired DHCP lease(s)",
                detail=(
                    "Expired leases are retained by Kea for a grace period. "
                    "These IPs will be returned to the pool."
                ),
            ))

        # Check for clients with no hostname
        no_hostname = [l for l in active_leases if not l.get("hostname")]
        if no_hostname:
            findings.append(Finding(
                severity=Severity.WARNING,
                title=f"{len(no_hostname)} active lease(s) with no hostname",
                detail=(
                    "Devices without hostnames are harder to identify. "
                    "These may be IoT devices, guest devices, or devices "
                    "with DHCP hostname reporting disabled."
                ),
                recommendation=(
                    "Consider using static DHCP mappings with descriptive "
                    "names for known devices."
                ),
            ))
    else:
        findings.append(Finding(
            severity=Severity.INFORMATIONAL,
            title="No DHCP leases found",
            detail="No active or expired DHCP leases in the Kea database.",
        ))

    # Build final report
    report_parts: list[str] = []

    if findings:
        report_parts.append(format_severity_report("Services Report", findings))

    for section in sections:
        report_parts.append(section)

    return "\n".join(report_parts)
