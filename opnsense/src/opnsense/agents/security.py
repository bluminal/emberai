# SPDX-License-Identifier: MIT
"""Security audit report agent for OPNsense.

Produces a security posture report covering IDS/IPS alerts and TLS
certificate status. Highlights critical alerts, expiring certificates,
and IDS policy gaps using the OX severity-tiered report pattern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opnsense.output import Finding, Severity, format_severity_report, format_table
from opnsense.tools.security import (
    opnsense__security__get_certificates,
    opnsense__security__get_ids_alerts,
)

if TYPE_CHECKING:
    from opnsense.api.opnsense_client import OPNsenseClient

# Map IDS severity integers to our severity levels
_IDS_SEVERITY_MAP: dict[int, Severity] = {
    1: Severity.HIGH,
    2: Severity.WARNING,
    3: Severity.INFORMATIONAL,
}


async def security_audit_report(
    client: OPNsenseClient,
    *,
    alert_hours: int = 24,
) -> str:
    """Generate an IDS/certificate security audit report.

    Fetches recent IDS alerts and the full certificate inventory, then
    produces a severity-tiered report with actionable findings.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    alert_hours:
        Number of hours of alert history to include (default: 24).

    Returns
    -------
    str
        Markdown-formatted security audit report.
    """
    alerts = await opnsense__security__get_ids_alerts(client, hours=alert_hours)
    certificates = await opnsense__security__get_certificates(client)

    findings: list[Finding] = []
    sections: list[str] = []

    # --- IDS Alert Analysis ---
    if alerts:
        # Count by severity
        sev_counts: dict[int, int] = {}
        drop_count = 0
        for a in alerts:
            sev = a.get("severity", 3)
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
            if a.get("action") == "drop":
                drop_count += 1

        # Alert table
        rows: list[list[str]] = []
        for a in alerts:
            rows.append(
                [
                    a.get("timestamp", "")[:19],
                    str(a.get("severity", "")),
                    a.get("signature", a.get("alert", "")),
                    a.get("src_ip", ""),
                    a.get("dst_ip", a.get("dest_ip", "")),
                    a.get("action", ""),
                ]
            )

        sections.append(
            format_table(
                headers=["Time", "Sev", "Signature", "Source", "Destination", "Action"],
                rows=rows,
                title=f"IDS Alerts (last {alert_hours}h)",
            )
        )

        # Findings based on alert severity distribution
        high_count = sev_counts.get(1, 0)
        medium_count = sev_counts.get(2, 0)

        if high_count > 0:
            findings.append(
                Finding(
                    severity=Severity.HIGH,
                    title=f"{high_count} high-severity IDS alert(s) in last {alert_hours}h",
                    detail=(
                        f"Detected {high_count} severity-1 alert(s). These typically "
                        "indicate active attack attempts or known-malicious traffic."
                    ),
                    recommendation=(
                        "Review source IPs for patterns. Consider blocking persistent "
                        "offenders via firewall aliases."
                    ),
                )
            )

        if medium_count > 0:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title=f"{medium_count} medium-severity IDS alert(s)",
                    detail=(
                        f"Detected {medium_count} severity-2 alert(s) which may "
                        "indicate reconnaissance or suspicious activity."
                    ),
                )
            )

        if drop_count > 0:
            findings.append(
                Finding(
                    severity=Severity.INFORMATIONAL,
                    title=f"{drop_count} alert(s) resulted in traffic being dropped",
                    detail=(
                        f"IPS mode actively blocked {drop_count} connection(s) matching "
                        "IDS rules configured for drop action."
                    ),
                )
            )
    else:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title=f"No IDS alerts in the last {alert_hours}h",
                detail="No Suricata alerts were recorded in the specified time window.",
            )
        )

    # --- Certificate Analysis ---
    if certificates:
        rows = []
        for c in certificates:
            days_left = c.get("days_until_expiry")
            days_str = str(days_left) if days_left is not None else "N/A"
            in_use = ", ".join(c.get("in_use_for", [])) or "None"
            rows.append(
                [
                    c.get("cn", ""),
                    c.get("issuer", ""),
                    c.get("not_after", c.get("valid_to", "")),
                    days_str,
                    in_use,
                ]
            )

        sections.append(
            format_table(
                headers=["CN", "Issuer", "Expires", "Days Left", "In Use By"],
                rows=rows,
                title="TLS Certificates",
            )
        )

        # Check for expiring/expired certificates
        for c in certificates:
            days_left = c.get("days_until_expiry")
            cn = c.get("cn", "unknown")
            in_use = c.get("in_use_for", [])

            if days_left is not None:
                if days_left < 0:
                    sev = Severity.CRITICAL if in_use else Severity.HIGH
                    findings.append(
                        Finding(
                            severity=sev,
                            title=f"Certificate expired: {cn}",
                            detail=(
                                f"Certificate '{cn}' expired {abs(days_left)} day(s) ago. "
                                f"In use by: {', '.join(in_use) or 'nothing'}."
                            ),
                            recommendation="Renew or replace the certificate immediately.",
                        )
                    )
                elif days_left <= 30:
                    sev = Severity.HIGH if in_use else Severity.WARNING
                    findings.append(
                        Finding(
                            severity=sev,
                            title=f"Certificate expiring soon: {cn}",
                            detail=(
                                f"Certificate '{cn}' expires in {days_left} day(s). "
                                f"In use by: {', '.join(in_use) or 'nothing'}."
                            ),
                            recommendation="Plan certificate renewal before expiry.",
                        )
                    )
                elif days_left <= 90:
                    findings.append(
                        Finding(
                            severity=Severity.INFORMATIONAL,
                            title=f"Certificate expires in {days_left} days: {cn}",
                            detail=f"Certificate '{cn}' has {days_left} days remaining.",
                        )
                    )
    else:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title="No certificates found in trust store",
                detail="The trust store is empty or inaccessible.",
            )
        )

    # Build final report
    report_parts: list[str] = []

    if findings:
        report_parts.append(format_severity_report("Security Audit Report", findings))

    for section in sections:
        report_parts.append(section)

    return "\n".join(report_parts)
