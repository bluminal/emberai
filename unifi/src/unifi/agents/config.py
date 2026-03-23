# SPDX-License-Identifier: MIT
"""Config agent -- orchestrates config tools into a configuration state report.

Calls the config MCP tools (get_config_snapshot, diff_baseline,
get_backup_state) and produces a formatted configuration review using
OX formatters.

This is the backend for the ``unifi config`` command.
"""

from __future__ import annotations

import logging
from typing import Any

from unifi.output import Finding, Severity, format_severity_report, format_summary
from unifi.tools.config import (
    unifi__config__diff_baseline,
    unifi__config__get_backup_state,
    unifi__config__get_config_snapshot,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Snapshot classification
# ---------------------------------------------------------------------------


def _classify_snapshot(snapshot: dict[str, Any]) -> list[Finding]:
    """Classify config snapshot into severity-tiered findings.

    - WARNING: Zero networks or WLANs configured (unusual)
    - WARNING: Zero firewall rules (no protection)
    - INFORMATIONAL: Configuration summary
    """
    findings: list[Finding] = []

    network_count = snapshot.get("network_count", 0)
    wlan_count = snapshot.get("wlan_count", 0)
    rule_count = snapshot.get("rule_count", 0)

    if network_count == 0:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title="No networks configured",
                detail=(
                    "No network configurations found. This is unusual and may indicate a problem."
                ),
                recommendation="Verify site configuration and network setup.",
            )
        )

    if wlan_count == 0:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title="No WLANs configured",
                detail=(
                    "No wireless networks configured. Wireless clients will not be able to connect."
                ),
                recommendation="Configure at least one WLAN if wireless access is needed.",
            )
        )

    if rule_count == 0:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title="No firewall rules configured",
                detail="No custom firewall rules found. The site relies entirely on default rules.",
                recommendation="Review firewall configuration and add rules as needed.",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Backup state classification
# ---------------------------------------------------------------------------


def _classify_backup(backup: dict[str, Any]) -> list[Finding]:
    """Classify backup state into severity-tiered findings.

    - WARNING: No recent backup or cloud backup disabled
    - INFORMATIONAL: Backup status summary
    """
    findings: list[Finding] = []

    last_backup = backup.get("last_backup_time", "")
    cloud_enabled = backup.get("cloud_enabled", False)

    if not last_backup:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title="No backup timestamp found",
                detail="Could not determine when the last backup was taken.",
                recommendation="Verify backup configuration and schedule regular backups.",
            )
        )

    if not cloud_enabled:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title="Cloud backup not enabled",
                detail="Cloud backup is not enabled. Backups are stored locally only.",
                recommendation="Consider enabling cloud backup for off-site disaster recovery.",
            )
        )

    if last_backup:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title="Backup status",
                detail=(
                    f"Last backup: {last_backup}, "
                    f"Type: {backup.get('backup_type', 'unknown')}, "
                    f"Cloud: {'enabled' if cloud_enabled else 'disabled'}."
                ),
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Diff classification
# ---------------------------------------------------------------------------


def _classify_diff(diff: dict[str, Any]) -> list[Finding]:
    """Classify config diff into severity-tiered findings.

    - WARNING: Items added, removed, or modified since baseline
    - INFORMATIONAL: No drift detected
    """
    findings: list[Finding] = []

    if diff.get("error"):
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title="No baseline available",
                detail=diff.get("error", "No baseline found."),
                recommendation=diff.get("hint", "Save a baseline first."),
            )
        )
        return findings

    added = diff.get("added", [])
    removed = diff.get("removed", [])
    modified = diff.get("modified", [])

    total_changes = len(added) + len(removed) + len(modified)

    if total_changes == 0:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title="No configuration drift",
                detail="Current configuration matches the stored baseline.",
            )
        )
    else:
        parts: list[str] = []
        if added:
            names = ", ".join(i.get("name", i.get("id", "?")) for i in added)
            parts.append(f"{len(added)} added ({names})")
        if removed:
            names = ", ".join(i.get("name", i.get("id", "?")) for i in removed)
            parts.append(f"{len(removed)} removed ({names})")
        if modified:
            names = ", ".join(i.get("name", i.get("id", "?")) for i in modified)
            parts.append(f"{len(modified)} modified ({names})")

        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"Configuration drift detected: {total_changes} change(s)",
                detail="; ".join(parts) + ".",
                recommendation="Review changes and update baseline if intentional.",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Public agent function
# ---------------------------------------------------------------------------


async def config_review(site_id: str = "default", drift: bool = False) -> str:
    """Run a configuration review and produce a formatted report.

    Calls config tools and classifies findings by severity:
    - WARNING: Missing configs, no backup, configuration drift
    - INFORMATIONAL: Config summaries, backup status

    When ``drift`` is ``True``, diffs the current configuration against
    a stored baseline and includes any added, removed, or modified items
    in the findings.  When ``False``, the baseline diff is skipped.

    Returns a formatted report using OX formatters.
    This is the backend for the ``unifi config`` command.

    Args:
        site_id: The UniFi site ID. Defaults to ``"default"``.
        drift: If ``True``, diff against stored baseline. Defaults to ``False``.

    Returns:
        A formatted markdown report containing configuration findings
        organized by severity.
    """
    # Gather data from config tools.
    snapshot = await unifi__config__get_config_snapshot(site_id)
    backup = await unifi__config__get_backup_state(site_id)
    diff = await unifi__config__diff_baseline(site_id) if drift else None

    logger.info(
        "Config review data gathered for site '%s': networks=%d, wlans=%d, rules=%d",
        site_id,
        snapshot.get("network_count", 0),
        snapshot.get("wlan_count", 0),
        snapshot.get("rule_count", 0),
        extra={"component": "config"},
    )

    # Classify findings from each data source.
    findings: list[Finding] = []
    findings.extend(_classify_snapshot(snapshot))
    findings.extend(_classify_backup(backup))
    if diff is not None:
        findings.extend(_classify_diff(diff))

    # Build report sections.
    sections: list[str] = []

    # Summary header.
    summary_stats: dict[str, int | str] = {
        "Networks": snapshot.get("network_count", 0),
        "WLANs": snapshot.get("wlan_count", 0),
        "Firewall Rules": snapshot.get("rule_count", 0),
    }

    if backup.get("last_backup_time"):
        summary_stats["Last Backup"] = backup["last_backup_time"]

    # Count findings by severity for the summary.
    warning_count = sum(1 for f in findings if f.severity == Severity.WARNING)
    if warning_count > 0:
        summary_stats["Warnings"] = warning_count

    detail: str | None = None
    if warning_count == 0:
        detail = "Configuration review complete -- no issues detected."

    sections.append(format_summary("Config Review", summary_stats, detail=detail))

    # Severity report (only if there are findings).
    if findings:
        sections.append(format_severity_report("Config Findings", findings))

    logger.info(
        "Config review complete for site '%s': %d warning(s), %d total findings",
        site_id,
        warning_count,
        len(findings),
        extra={"component": "config"},
    )

    return "\n".join(sections)
