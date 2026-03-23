# SPDX-License-Identifier: MIT
"""Security agent -- orchestrates security tools into a risk-ranked posture report.

Calls the five security MCP tools (get_firewall_rules, get_zbf_policies,
get_acls, get_port_forwards, get_ids_alerts) and classifies findings by
severity using OX formatters.

This is the backend for the ``unifi secure`` command.
"""

from __future__ import annotations

import logging
from typing import Any

from unifi.output import Finding, Severity, format_severity_report, format_summary
from unifi.tools.security import (
    unifi__security__get_acls,
    unifi__security__get_firewall_rules,
    unifi__security__get_ids_alerts,
    unifi__security__get_port_forwards,
    unifi__security__get_zbf_policies,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Firewall rule classification
# ---------------------------------------------------------------------------


def _classify_firewall_rules(rules: list[dict[str, Any]]) -> list[Finding]:
    """Classify firewall rules into severity-tiered findings.

    - WARNING: Disabled rules (potential security gap)
    - WARNING: Over-broad rules (action=accept with no src/dst restrictions)
    - INFORMATIONAL: Rule count summary
    """
    findings: list[Finding] = []

    disabled_rules = [r for r in rules if not r.get("enabled", True)]
    if disabled_rules:
        names = ", ".join(r.get("name", r.get("rule_id", "unnamed")) for r in disabled_rules)
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"{len(disabled_rules)} firewall rule(s) disabled",
                detail=f"Disabled rules may indicate security gaps: {names}.",
                recommendation="Review disabled rules and either re-enable or remove them.",
            )
        )

    # Check for over-broad accept rules (no source or destination restriction)
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        action = rule.get("action", "")
        src = rule.get("src", "")
        dst = rule.get("dst", "")

        if action == "accept" and not src and not dst:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title=f"Over-broad firewall rule: {rule.get('name', 'unnamed')}",
                    detail=(
                        f"Rule '{rule.get('name', '')}' accepts all traffic with "
                        "no source or destination restriction "
                        f"(protocol={rule.get('protocol', 'all')})."
                    ),
                    recommendation="Add source/destination restrictions to limit attack surface.",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# ZBF policy classification
# ---------------------------------------------------------------------------


def _classify_zbf_policies(policies: list[dict[str, Any]]) -> list[Finding]:
    """Classify ZBF policies into severity-tiered findings.

    - WARNING: Policies that allow all traffic between zones
    - INFORMATIONAL: Policy count
    """
    findings: list[Finding] = []

    for policy in policies:
        if policy.get("action") == "accept" and policy.get("match_all"):
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title=(
                        f"Unrestricted zone policy: "
                        f"{policy.get('from_zone', '?')} -> {policy.get('to_zone', '?')}"
                    ),
                    detail=(
                        f"Traffic from '{policy.get('from_zone', '')}' to "
                        f"'{policy.get('to_zone', '')}' is accepted without restriction."
                    ),
                    recommendation=(
                        "Consider adding specific match criteria to limit inter-zone traffic."
                    ),
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Port forward classification
# ---------------------------------------------------------------------------


def _classify_port_forwards(forwards: list[dict[str, Any]]) -> list[Finding]:
    """Classify port forwarding rules into severity-tiered findings.

    - HIGH: Exposed sensitive ports (22, 23, 3389, 445, 3306, 5432)
    - WARNING: Any enabled port forward (exposes LAN to WAN)
    - INFORMATIONAL: Port forward count
    """
    findings: list[Finding] = []

    sensitive_ports = {"22", "23", "3389", "445", "3306", "5432", "1433"}

    enabled_forwards = [f for f in forwards if f.get("enabled", True)]

    for fwd in enabled_forwards:
        wan_port = str(fwd.get("wan_port", ""))
        if wan_port in sensitive_ports:
            findings.append(
                Finding(
                    severity=Severity.HIGH,
                    title=f"Sensitive port exposed: {fwd.get('name', 'unnamed')} (port {wan_port})",
                    detail=(
                        f"Port {wan_port} is forwarded to {fwd.get('lan_host', '?')}:"
                        f"{fwd.get('lan_port', '?')}. "
                        f"This port is commonly targeted by attackers."
                    ),
                    recommendation=(
                        f"Consider using VPN instead of exposing port {wan_port} directly. "
                        f"If required, restrict source IPs."
                    ),
                )
            )

    if enabled_forwards:
        non_sensitive = [
            f for f in enabled_forwards if str(f.get("wan_port", "")) not in sensitive_ports
        ]
        if non_sensitive:
            names = ", ".join(
                f"{f.get('name', 'unnamed')} (:{f.get('wan_port', '?')})" for f in non_sensitive
            )
            findings.append(
                Finding(
                    severity=Severity.INFORMATIONAL,
                    title=f"{len(non_sensitive)} port forward(s) active",
                    detail=f"Active port forwards: {names}.",
                    recommendation=(
                        "Periodically review port forwards to ensure they are still needed."
                    ),
                )
            )

    return findings


# ---------------------------------------------------------------------------
# IDS alert classification
# ---------------------------------------------------------------------------


def _classify_ids_alerts(alerts: list[dict[str, Any]]) -> list[Finding]:
    """Classify IDS/IPS alerts into severity-tiered findings.

    - CRITICAL: High-severity alerts (severity 1-2)
    - WARNING: Medium-severity alerts (severity 3)
    - INFORMATIONAL: Low-severity alerts and summary
    """
    findings: list[Finding] = []

    if not alerts:
        return findings

    # Group by severity level
    critical_alerts = []
    warning_alerts = []
    info_alerts = []

    for alert in alerts:
        sev = alert.get("severity", "unknown")
        # UniFi IDS severity can be numeric (1=high, 2=medium, 3=low) or string
        if isinstance(sev, (int, float)):
            if sev <= 1:
                critical_alerts.append(alert)
            elif sev <= 2:
                warning_alerts.append(alert)
            else:
                info_alerts.append(alert)
        elif isinstance(sev, str):
            sev_lower = sev.lower()
            if sev_lower in ("high", "critical"):
                critical_alerts.append(alert)
            elif sev_lower in ("medium", "warning"):
                warning_alerts.append(alert)
            else:
                info_alerts.append(alert)
        else:
            info_alerts.append(alert)

    if critical_alerts:
        sigs = ", ".join(a.get("signature", "unknown")[:50] for a in critical_alerts[:5])
        findings.append(
            Finding(
                severity=Severity.CRITICAL,
                title=f"{len(critical_alerts)} high-severity IDS alert(s)",
                detail=f"Recent critical IDS alerts: {sigs}.",
                recommendation="Investigate critical IDS alerts immediately for active threats.",
            )
        )

    if warning_alerts:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"{len(warning_alerts)} medium-severity IDS alert(s)",
                detail=(
                    f"{len(warning_alerts)} medium-severity intrusion "
                    "detection alerts in the time window."
                ),
                recommendation="Review medium-severity alerts for potential threats.",
            )
        )

    if info_alerts:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title=f"{len(info_alerts)} low-severity IDS alert(s)",
                detail=f"{len(info_alerts)} low-severity alerts recorded (likely benign).",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Public agent function
# ---------------------------------------------------------------------------


async def security_audit(site_id: str = "default") -> str:
    """Run a comprehensive security posture audit and produce a risk-ranked report.

    Calls all security tools and classifies findings by severity:
    - CRITICAL: Active high-severity IDS alerts
    - HIGH: Sensitive ports exposed via port forwarding
    - WARNING: Disabled firewall rules, over-broad rules, unrestricted zone policies
    - INFORMATIONAL: Summaries and low-severity items

    Returns a formatted report using OX formatters.
    This is the backend for the ``unifi secure`` command.

    Args:
        site_id: The UniFi site ID. Defaults to ``"default"``.

    Returns:
        A formatted markdown report containing security findings
        organized by severity.
    """
    # Gather data from all security tools.
    firewall_rules = await unifi__security__get_firewall_rules(site_id)
    zbf_policies = await unifi__security__get_zbf_policies(site_id)
    acls = await unifi__security__get_acls(site_id)
    port_forwards = await unifi__security__get_port_forwards(site_id)
    ids_alerts = await unifi__security__get_ids_alerts(site_id, hours=24)

    logger.info(
        "Security audit data gathered for site '%s': "
        "rules=%d, zbf=%d, acls=%d, forwards=%d, ids=%d",
        site_id,
        len(firewall_rules),
        len(zbf_policies),
        len(acls),
        len(port_forwards),
        len(ids_alerts),
        extra={"component": "security"},
    )

    # Classify findings from each data source.
    findings: list[Finding] = []
    findings.extend(_classify_firewall_rules(firewall_rules))
    findings.extend(_classify_zbf_policies(zbf_policies))
    findings.extend(_classify_port_forwards(port_forwards))
    findings.extend(_classify_ids_alerts(ids_alerts))

    # Build report sections.
    sections: list[str] = []

    # Summary header.
    summary_stats: dict[str, int | str] = {
        "Firewall Rules": len(firewall_rules),
        "ZBF Policies": len(zbf_policies),
        "ACLs": len(acls),
        "Port Forwards": len(port_forwards),
        "IDS Alerts (24h)": len(ids_alerts),
    }

    # Count findings by severity for the summary.
    critical_count = sum(1 for f in findings if f.severity == Severity.CRITICAL)
    high_count = sum(1 for f in findings if f.severity == Severity.HIGH)
    warning_count = sum(1 for f in findings if f.severity == Severity.WARNING)

    if critical_count > 0:
        summary_stats["Critical"] = critical_count
    if high_count > 0:
        summary_stats["High"] = high_count
    if warning_count > 0:
        summary_stats["Warnings"] = warning_count

    # Add healthy message if no actionable findings.
    detail: str | None = None
    if critical_count == 0 and high_count == 0 and warning_count == 0:
        detail = (
            f"No security concerns detected -- {len(firewall_rules)} firewall rule(s), "
            f"{len(port_forwards)} port forward(s) reviewed."
        )

    sections.append(format_summary("Security Audit", summary_stats, detail=detail))

    # Severity report (only if there are findings).
    if findings:
        sections.append(format_severity_report("Security Findings", findings))

    logger.info(
        "Security audit complete for site '%s': %d critical, %d high, %d warning, %d total",
        site_id,
        critical_count,
        high_count,
        warning_count,
        len(findings),
        extra={"component": "security"},
    )

    return "\n".join(sections)
