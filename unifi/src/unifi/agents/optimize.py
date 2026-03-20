# SPDX-License-Identifier: MIT
"""Optimize agent -- aggregates data from multiple agents to produce recommendations.

Orchestrates WiFi, traffic, security, and config agents to generate a
prioritized list of optimization recommendations.  Supports two modes:

1. **Read-only** (``generate_recommendations``) -- produces recommendations
   without applying any changes.
2. **Apply** (``apply_optimizations``) -- write-gated: requires
   ``UNIFI_WRITE_ENABLED=true`` + ``apply=True`` + operator confirmation.
   Presents a full change plan via AskUserQuestion before executing.

This is the backend for the ``unifi optimize`` command.
"""

from __future__ import annotations

import logging
from typing import Any

from unifi.ask import PlanStep, format_plan_confirmation
from unifi.output import (
    Finding,
    Severity,
    format_severity_report,
    format_summary,
)
from unifi.safety import describe_write_status, write_gate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recommendation data structure
# ---------------------------------------------------------------------------


PRIORITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def _priority_sort_key(rec: dict[str, Any]) -> int:
    """Sort key for recommendations by priority."""
    return PRIORITY_ORDER.get(rec.get("priority", "low"), 99)


# ---------------------------------------------------------------------------
# Data gathering helpers
# ---------------------------------------------------------------------------


async def _gather_wifi_data(site_id: str) -> list[Finding]:
    """Gather WiFi findings for optimization analysis."""
    try:
        # Gather raw data directly for structured analysis.
        from unifi.tools.wifi import (
            unifi__wifi__get_aps,
            unifi__wifi__get_channel_utilization,
        )

        aps = await unifi__wifi__get_aps(site_id)
        findings: list[Finding] = []

        for ap in aps:
            ap_mac = ap.get("mac", "")
            ap_name = ap.get("name", ap_mac)

            try:
                util = await unifi__wifi__get_channel_utilization(ap_mac, site_id)
                for band_key, band_label in [
                    ("radio_2g", "2.4 GHz"),
                    ("radio_5g", "5 GHz"),
                    ("radio_6g", "6 GHz"),
                ]:
                    radio = util.get(band_key)
                    if radio is None:
                        continue
                    util_pct = radio.get("utilization_pct")
                    if util_pct is not None and util_pct > 50:
                        sev = Severity.CRITICAL if util_pct > 80 else Severity.WARNING
                        findings.append(
                            Finding(
                                severity=sev,
                                title=f"{ap_name} {band_label} at {util_pct}%",
                                detail=(
                                    f"Channel {radio.get('channel', '?')} on {ap_name} "
                                    f"has {util_pct}% utilization."
                                ),
                                recommendation="Consider changing to a less congested channel.",
                            )
                        )
            except Exception:
                logger.debug("Skipping WiFi util for %s during optimize", ap_name)

        return findings
    except Exception:
        logger.warning("Failed to gather WiFi data for optimization", exc_info=True)
        return []


async def _gather_security_data(site_id: str) -> list[Finding]:
    """Gather security findings for optimization analysis."""
    try:
        from unifi.tools.security import (
            unifi__security__get_firewall_rules,
            unifi__security__get_port_forwards,
        )

        rules = await unifi__security__get_firewall_rules(site_id)
        forwards = await unifi__security__get_port_forwards(site_id)

        findings: list[Finding] = []

        disabled_rules = [r for r in rules if not r.get("enabled", True)]
        if disabled_rules:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title=f"{len(disabled_rules)} disabled firewall rule(s)",
                    detail="Disabled rules may indicate security gaps.",
                    recommendation="Review and remove or re-enable disabled rules.",
                )
            )

        sensitive_ports = {"22", "23", "3389", "445", "3306", "5432", "1433"}
        for fwd in forwards:
            if fwd.get("enabled", True) and str(fwd.get("wan_port", "")) in sensitive_ports:
                findings.append(
                    Finding(
                        severity=Severity.HIGH,
                        title=f"Sensitive port {fwd.get('wan_port')} exposed",
                        detail=(
                            f"Port forward '{fwd.get('name', 'unnamed')}' "
                            f"exposes a sensitive port."
                        ),
                        recommendation="Consider VPN instead of direct port forwarding.",
                    )
                )

        return findings
    except Exception:
        logger.warning("Failed to gather security data for optimization", exc_info=True)
        return []


async def _gather_config_data(site_id: str) -> list[Finding]:
    """Gather config findings for optimization analysis."""
    try:
        from unifi.tools.config import (
            unifi__config__get_backup_state,
            unifi__config__get_config_snapshot,
        )

        snapshot = await unifi__config__get_config_snapshot(site_id)
        backup = await unifi__config__get_backup_state(site_id)

        findings: list[Finding] = []

        if snapshot.get("rule_count", 0) == 0:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title="No custom firewall rules",
                    detail="The site relies entirely on default firewall rules.",
                    recommendation="Add custom rules to restrict inter-VLAN traffic.",
                )
            )

        if not backup.get("last_backup_time"):
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title="No recent backup",
                    detail="No backup timestamp found.",
                    recommendation="Configure and verify automatic backups.",
                )
            )

        if not backup.get("cloud_enabled", False):
            findings.append(
                Finding(
                    severity=Severity.INFORMATIONAL,
                    title="Cloud backup disabled",
                    detail="Backups are local-only.",
                    recommendation="Enable cloud backup for off-site disaster recovery.",
                )
            )

        return findings
    except Exception:
        logger.warning("Failed to gather config data for optimization", exc_info=True)
        return []


async def _gather_traffic_data(site_id: str) -> list[Finding]:
    """Gather traffic findings for optimization analysis."""
    try:
        from unifi.tools.traffic import (
            unifi__traffic__get_bandwidth,
            unifi__traffic__get_wan_usage,
        )

        bandwidth = await unifi__traffic__get_bandwidth(site_id)
        wan_usage = await unifi__traffic__get_wan_usage(site_id)

        findings: list[Finding] = []

        wan = bandwidth.get("wan", {})
        if wan.get("rx_mbps", 0) > 900 or wan.get("tx_mbps", 0) > 900:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title="High WAN bandwidth utilization",
                    detail=(
                        f"WAN throughput: {wan.get('rx_mbps', 0):.1f} Mbps down, "
                        f"{wan.get('tx_mbps', 0):.1f} Mbps up."
                    ),
                    recommendation="Review top applications consuming bandwidth.",
                )
            )

        if wan_usage:
            total = sum(
                d.get("download_gb", 0) + d.get("upload_gb", 0) for d in wan_usage
            )
            avg_daily = total / len(wan_usage)
            if avg_daily > 100:
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        title=f"High average daily WAN usage: {avg_daily:.1f} GB/day",
                        detail=(
                            f"Average daily usage is {avg_daily:.1f} GB "
                            f"over {len(wan_usage)} days."
                        ),
                        recommendation="Review DPI data to identify bandwidth-heavy applications.",
                    )
                )

        return findings
    except Exception:
        logger.warning("Failed to gather traffic data for optimization", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Recommendation generation
# ---------------------------------------------------------------------------


def _findings_to_recommendations(findings: list[Finding]) -> list[dict[str, Any]]:
    """Convert severity-tiered findings into prioritized recommendations."""
    severity_to_priority: dict[Severity, str] = {
        Severity.CRITICAL: "critical",
        Severity.HIGH: "high",
        Severity.WARNING: "medium",
        Severity.INFORMATIONAL: "low",
    }

    recommendations: list[dict[str, Any]] = []
    for finding in findings:
        if finding.recommendation:
            recommendations.append({
                "priority": severity_to_priority.get(finding.severity, "low"),
                "category": _categorize_finding(finding),
                "title": finding.title,
                "detail": finding.detail,
                "action": finding.recommendation,
            })

    # Sort by priority
    recommendations.sort(key=_priority_sort_key)
    return recommendations


def _categorize_finding(finding: Finding) -> str:
    """Determine the category of a finding based on its content."""
    title_lower = finding.title.lower()
    if any(kw in title_lower for kw in ("channel", "wifi", "ssid", "ap ", "ghz")):
        return "wifi"
    if any(kw in title_lower for kw in ("firewall", "port", "security", "rule")):
        return "security"
    if any(kw in title_lower for kw in ("bandwidth", "wan", "traffic", "usage")):
        return "traffic"
    if any(kw in title_lower for kw in ("backup", "config", "drift")):
        return "config"
    return "general"


# ---------------------------------------------------------------------------
# Public agent functions
# ---------------------------------------------------------------------------


async def generate_recommendations(site_id: str = "default") -> str:
    """Generate optimization recommendations from wifi, traffic, security, config data.

    Read-only -- produces recommendations without applying changes.

    Aggregates findings from all four subsystem agents, converts them
    into prioritized recommendations, and formats a report.

    Args:
        site_id: The UniFi site ID. Defaults to ``"default"``.

    Returns:
        A formatted markdown report of optimization recommendations.
    """
    logger.info(
        "Generating optimization recommendations for site '%s'",
        site_id,
        extra={"component": "optimize"},
    )

    # Gather findings from all subsystem agents
    all_findings: list[Finding] = []
    all_findings.extend(await _gather_wifi_data(site_id))
    all_findings.extend(await _gather_security_data(site_id))
    all_findings.extend(await _gather_config_data(site_id))
    all_findings.extend(await _gather_traffic_data(site_id))

    # Convert to recommendations
    recommendations = _findings_to_recommendations(all_findings)

    # Build report
    sections: list[str] = []

    # Summary
    category_counts: dict[str, int] = {}
    for rec in recommendations:
        cat = rec.get("category", "general")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    summary_stats: dict[str, int | str] = {
        "Total Recommendations": len(recommendations),
    }
    for cat, count in sorted(category_counts.items()):
        summary_stats[cat.title()] = count

    # Include write status
    write_status = describe_write_status("UNIFI")

    sections.append(
        format_summary(
            "Optimization Recommendations",
            summary_stats,
            detail=f"Mode: read-only (plan only). {write_status}",
        )
    )

    # Findings report (all findings grouped by severity)
    if all_findings:
        sections.append(format_severity_report("Analysis Findings", all_findings))

    # Recommendations list
    if recommendations:
        rec_lines: list[str] = ["## Prioritized Recommendations", ""]
        for i, rec in enumerate(recommendations, start=1):
            priority = rec["priority"].upper()
            rec_lines.append(
                f"{i}. **[{priority}] [{rec['category'].upper()}]** {rec['title']}"
            )
            rec_lines.append(f"   {rec['detail']}")
            rec_lines.append(f"   *Action:* {rec['action']}")
            rec_lines.append("")
        sections.append("\n".join(rec_lines))
    else:
        sections.append(
            "\n## Prioritized Recommendations\n\n"
            "No recommendations -- all subsystems look healthy.\n"
        )

    logger.info(
        "Optimization analysis complete for site '%s': %d recommendations",
        site_id,
        len(recommendations),
        extra={"component": "optimize"},
    )

    return "\n".join(sections)


@write_gate("UNIFI")
async def apply_optimizations(site_id: str = "default", *, apply: bool = False) -> str:
    """Apply approved optimization recommendations.

    Write-gated: requires ``UNIFI_WRITE_ENABLED=true`` + ``apply=True``
    + operator confirmation.

    First generates recommendations (same as ``generate_recommendations``),
    then builds a change plan from actionable recommendations and presents
    it to the operator for confirmation via ``AskUserQuestion``.

    Args:
        site_id: The UniFi site ID. Defaults to ``"default"``.
        apply: Must be ``True`` for the write gate to pass.

    Returns:
        A formatted change plan for operator confirmation, or an error
        message if the write gate is not satisfied.
    """
    logger.info(
        "Building optimization change plan for site '%s'",
        site_id,
        extra={"component": "optimize"},
    )

    # Gather findings from all subsystem agents
    all_findings: list[Finding] = []
    all_findings.extend(await _gather_wifi_data(site_id))
    all_findings.extend(await _gather_security_data(site_id))
    all_findings.extend(await _gather_config_data(site_id))
    all_findings.extend(await _gather_traffic_data(site_id))

    # Convert to recommendations
    recommendations = _findings_to_recommendations(all_findings)

    if not recommendations:
        return (
            "## Optimization Change Plan\n\n"
            "No actionable recommendations found -- all subsystems look healthy.\n"
            "No changes to apply."
        )

    # Build plan steps from recommendations
    steps: list[PlanStep] = []
    for i, rec in enumerate(recommendations, start=1):
        steps.append(
            PlanStep(
                number=i,
                system="unifi",
                action=f"[{rec['priority'].upper()}] {rec['title']}",
                detail=rec["action"],
                expected_outcome=f"Resolves: {rec['detail'][:100]}",
            )
        )

    # Present change plan for operator confirmation
    plan = format_plan_confirmation(
        steps=steps,
        outage_risk="LOW -- These are optimization recommendations. "
        "Individual changes should be reviewed for outage risk.",
    )

    logger.info(
        "Optimization change plan generated for site '%s': %d steps",
        site_id,
        len(steps),
        extra={"component": "optimize"},
    )

    return plan
