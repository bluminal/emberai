# SPDX-License-Identifier: MIT
"""Interfaces agent -- interface and VLAN inventory report.

Produces a severity-tiered OX report covering all interfaces, VLAN
definitions, and DHCP leases on the OPNsense firewall. Identifies
issues such as unconfigured interfaces, VLANs without IPs, and
expired DHCP leases.
"""

from __future__ import annotations

import logging

from opnsense.output import Finding, Severity, format_severity_report, format_table
from opnsense.tools.interfaces import (
    opnsense__interfaces__get_dhcp_leases,
    opnsense__interfaces__list_interfaces,
    opnsense__interfaces__list_vlan_interfaces,
)

logger = logging.getLogger(__name__)


async def run_interface_report() -> str:
    """Generate an interface and VLAN inventory report.

    Fetches all interfaces, VLAN definitions, and DHCP leases, then
    produces a formatted report with:
    - Interface inventory table
    - VLAN definitions table
    - DHCP lease summary
    - Findings (issues detected)

    Returns:
        A markdown-formatted report string.
    """
    # Fetch data from tools (gracefully handle missing endpoints)
    interfaces = await opnsense__interfaces__list_interfaces()
    try:
        vlans = await opnsense__interfaces__list_vlan_interfaces()
    except Exception:
        logger.warning("VLAN interfaces endpoint not available, skipping")
        vlans = []
    try:
        leases = await opnsense__interfaces__get_dhcp_leases()
    except Exception:
        logger.warning("DHCP leases endpoint not available, skipping")
        leases = []

    findings: list[Finding] = []
    sections: list[str] = []

    # --- Interface inventory table ---
    if interfaces:
        iface_headers = ["Name", "Description", "IP", "Subnet", "Type", "Status"]
        iface_rows: list[list[str]] = []
        for iface in interfaces:
            status = "up" if iface.get("enabled", True) else "down"
            iface_rows.append(
                [
                    iface.get("name", ""),
                    iface.get("description", ""),
                    iface.get("ip", ""),
                    iface.get("subnet", ""),
                    iface.get("if_type", ""),
                    status,
                ]
            )

            # Check for interfaces without IP addresses
            if (
                not iface.get("ip")
                and iface.get("enabled", True)
                and iface.get("if_type") != "bridge"
            ):
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        title=f"Interface '{iface.get('name', '')}' has no IP address",
                        detail=(
                            f"Interface {iface.get('name', '')} "
                            f"({iface.get('description', 'no description')}) "
                            "is enabled but has no IPv4 address assigned."
                        ),
                        recommendation="Assign an IP address or disable the interface.",
                    )
                )

        sections.append(format_table(iface_headers, iface_rows, title="Interface Inventory"))
    else:
        findings.append(
            Finding(
                severity=Severity.HIGH,
                title="No interfaces found",
                detail=(
                    "The API returned no interface data. This may indicate a connectivity issue."
                ),
                recommendation="Verify API connectivity and permissions.",
            )
        )

    # --- VLAN definitions table ---
    if vlans:
        vlan_headers = ["Tag", "Interface", "Parent", "Description"]
        vlan_rows: list[list[str]] = []
        for vlan in vlans:
            vlan_rows.append(
                [
                    str(vlan.get("tag", "")),
                    vlan.get("if_", ""),
                    vlan.get("parent_if", ""),
                    vlan.get("description", ""),
                ]
            )

        sections.append(format_table(vlan_headers, vlan_rows, title="VLAN Definitions"))

        # Check for VLANs that lack a corresponding interface with an IP
        vlan_if_names = {v.get("if_", "") for v in vlans}
        iface_with_ip = {i.get("name", "") for i in interfaces if i.get("ip")}
        orphan_vlans = vlan_if_names - iface_with_ip
        for orphan in orphan_vlans:
            if orphan:
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        title=f"VLAN interface '{orphan}' has no IP address",
                        detail=(
                            f"VLAN interface {orphan} is defined but has no IP "
                            "assigned in the interface configuration."
                        ),
                        recommendation="Assign an IP address to make this VLAN functional.",
                    )
                )

    # --- DHCP lease summary ---
    if leases:
        active_leases = [le for le in leases if le.get("state") == "active"]
        expired_leases = [le for le in leases if le.get("state") == "expired"]

        lease_headers = ["MAC", "IP", "Hostname", "Interface", "State"]
        lease_rows: list[list[str]] = []
        for lease in leases[:20]:  # Limit display to first 20
            lease_rows.append(
                [
                    lease.get("mac", ""),
                    lease.get("ip", ""),
                    lease.get("hostname", "") or "(unknown)",
                    lease.get("interface", ""),
                    lease.get("state", ""),
                ]
            )

        title = f"DHCP Leases ({len(active_leases)} active, {len(expired_leases)} expired)"
        sections.append(format_table(lease_headers, lease_rows, title=title))

        if expired_leases:
            findings.append(
                Finding(
                    severity=Severity.INFORMATIONAL,
                    title=f"{len(expired_leases)} expired DHCP lease(s)",
                    detail=(
                        "These leases have expired and the IP addresses"
                        " are available for reassignment."
                    ),
                )
            )

    # --- Build report ---
    report_body = "\n".join(sections)

    # Add summary stats
    stats_line = (
        f"**{len(interfaces)} interfaces** | **{len(vlans)} VLANs** | **{len(leases)} DHCP leases**"
    )

    # Add findings report
    findings_report = format_severity_report("Interface Findings", findings)

    full_report = (
        f"## Interface & VLAN Inventory Report\n\n{stats_line}\n\n{report_body}\n{findings_report}"
    )

    logger.info(
        "Generated interface report: %d interfaces, %d VLANs, %d leases, %d findings",
        len(interfaces),
        len(vlans),
        len(leases),
        len(findings),
        extra={"component": "agents.interfaces"},
    )

    return full_report
