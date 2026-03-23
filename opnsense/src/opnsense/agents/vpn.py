# SPDX-License-Identifier: MIT
"""VPN status report agent for OPNsense.

Produces a comprehensive VPN status report covering IPSec tunnels,
OpenVPN instances, and WireGuard peers. Reports are formatted using
the OX severity-tiered report pattern for consistent operator
experience.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opnsense.output import Finding, Severity, format_severity_report, format_table
from opnsense.tools.vpn import opnsense__vpn__get_vpn_status

if TYPE_CHECKING:
    from opnsense.api.opnsense_client import OPNsenseClient


def _bytes_human(n: int | None) -> str:
    """Convert bytes to human-readable string."""
    if n is None or n == 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n = int(n / 1024)
    return f"{n:.1f} PB"


async def vpn_status_report(client: OPNsenseClient) -> str:
    """Generate a VPN status report across all VPN technologies.

    Aggregates status from IPSec, OpenVPN, and WireGuard and produces
    a severity-tiered report highlighting disconnected tunnels, inactive
    peers, and overall health.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    str
        Markdown-formatted VPN status report.
    """
    status = await opnsense__vpn__get_vpn_status(client)
    findings: list[Finding] = []
    sections: list[str] = []

    # --- IPSec section ---
    ipsec = status["ipsec"]
    ipsec_sessions = ipsec["sessions"]
    ipsec_summary = ipsec["summary"]

    if ipsec_sessions:
        rows: list[list[str]] = []
        for s in ipsec_sessions:
            rows.append(
                [
                    s.get("description", ""),
                    s.get("status", "unknown"),
                    s.get("local_ts", ""),
                    s.get("remote_ts", ""),
                    _bytes_human(s.get("rx_bytes", 0)),
                    _bytes_human(s.get("tx_bytes", 0)),
                ]
            )

        sections.append(
            format_table(
                headers=["Description", "Status", "Local TS", "Remote TS", "RX", "TX"],
                rows=rows,
                title="IPSec Tunnels",
            )
        )

        # Generate findings for disconnected tunnels
        if ipsec_summary["disconnected"] > 0:
            findings.append(
                Finding(
                    severity=Severity.HIGH,
                    title=f"{ipsec_summary['disconnected']} IPSec tunnel(s) disconnected",
                    detail=(
                        f"Out of {ipsec_summary['total']} configured IPSec tunnels, "
                        f"{ipsec_summary['disconnected']} are currently disconnected."
                    ),
                    recommendation=(
                        "Check the remote peer status and verify IPSec phase 1/2 "
                        "settings match on both ends."
                    ),
                )
            )

    # --- OpenVPN section ---
    openvpn = status["openvpn"]
    openvpn_instances = openvpn["instances"]

    if openvpn_instances:
        rows = []
        for i in openvpn_instances:
            clients_str = str(i.get("connected_clients", "N/A"))
            rows.append(
                [
                    i.get("description", ""),
                    i.get("role", ""),
                    i.get("protocol", ""),
                    str(i.get("port", "")),
                    "Yes" if i.get("enabled") else "No",
                    clients_str,
                ]
            )

        sections.append(
            format_table(
                headers=["Description", "Role", "Protocol", "Port", "Enabled", "Clients"],
                rows=rows,
                title="OpenVPN Instances",
            )
        )

        disabled_count = sum(1 for i in openvpn_instances if not i.get("enabled"))
        if disabled_count > 0:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title=f"{disabled_count} OpenVPN instance(s) disabled",
                    detail=(
                        f"{disabled_count} OpenVPN instance(s) are administratively "
                        "disabled and not serving connections."
                    ),
                )
            )

    # --- WireGuard section ---
    wireguard = status["wireguard"]
    wg_peers = wireguard["peers"]
    wg_summary = wireguard["summary"]

    if wg_peers:
        rows = []
        for p in wg_peers:
            handshake = p.get("last_handshake") or "Never"
            rows.append(
                [
                    p.get("name", ""),
                    p.get("allowed_ips", ""),
                    p.get("endpoint") or "Roaming",
                    handshake,
                    _bytes_human(p.get("rx_bytes")),
                    _bytes_human(p.get("tx_bytes")),
                ]
            )

        sections.append(
            format_table(
                headers=["Name", "Allowed IPs", "Endpoint", "Last Handshake", "RX", "TX"],
                rows=rows,
                title="WireGuard Peers",
            )
        )

        if wg_summary["inactive"] > 0:
            findings.append(
                Finding(
                    severity=Severity.INFORMATIONAL,
                    title=f"{wg_summary['inactive']} WireGuard peer(s) inactive",
                    detail=(
                        f"{wg_summary['inactive']} peer(s) have never completed "
                        "a handshake or have no recent handshake."
                    ),
                )
            )

    # --- Summary ---
    totals = status["totals"]
    if totals["total_tunnels"] == 0:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title="No VPN tunnels configured",
                detail="No IPSec, OpenVPN, or WireGuard configurations found.",
            )
        )
    elif totals["total_active"] == totals["total_tunnels"]:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title="All VPN tunnels healthy",
                detail=(f"All {totals['total_tunnels']} VPN tunnel(s) are active/connected."),
            )
        )

    # Build final report
    report_parts: list[str] = []

    if findings:
        report_parts.append(format_severity_report("VPN Status Report", findings))

    for section in sections:
        report_parts.append(section)

    return "\n".join(report_parts)
