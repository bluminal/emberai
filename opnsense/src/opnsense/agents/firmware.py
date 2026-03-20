# SPDX-License-Identifier: MIT
"""Firmware report agent for OPNsense.

Produces a firmware status report covering the installed version,
available updates, and package inventory. Uses the OX severity-tiered
report pattern to highlight update availability and version drift.
"""

from __future__ import annotations

from typing import Any

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.output import (
    Finding,
    Severity,
    format_key_value,
    format_severity_report,
    format_table,
)
from opnsense.tools.firmware import (
    opnsense__firmware__get_status,
    opnsense__firmware__list_packages,
)


async def firmware_report(client: OPNsenseClient) -> str:
    """Generate a firmware status report.

    Fetches firmware version info and package list, then produces a
    report highlighting update availability and system version.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    str
        Markdown-formatted firmware report.
    """
    status = await opnsense__firmware__get_status(client)
    packages = await opnsense__firmware__list_packages(client)

    findings: list[Finding] = []
    sections: list[str] = []

    # --- Firmware Status ---
    current_version = status.get("current_version", "unknown")
    latest_version = status.get("latest_version", "")
    upgrade_available = status.get("upgrade_available", False)
    last_check = status.get("last_check", "never")

    kv_data: dict[str, str] = {
        "Current Version": current_version,
        "Latest Version": latest_version or current_version,
        "Upgrade Available": "Yes" if upgrade_available else "No",
        "Last Update Check": last_check or "never",
    }

    changelog_url = status.get("changelog_url")
    if changelog_url:
        kv_data["Changelog"] = changelog_url

    sections.append(format_key_value(kv_data, title="Firmware Status"))

    # --- Findings ---
    if upgrade_available:
        findings.append(Finding(
            severity=Severity.WARNING,
            title=f"Firmware update available: {latest_version}",
            detail=(
                f"Current version {current_version} can be upgraded to "
                f"{latest_version}. Review the changelog before upgrading."
            ),
            recommendation=(
                "Schedule a maintenance window and upgrade via the OPNsense "
                "web UI (System > Firmware > Updates). Ensure you have a "
                "configuration backup before upgrading."
            ),
        ))
    else:
        findings.append(Finding(
            severity=Severity.INFORMATIONAL,
            title=f"Firmware is up to date ({current_version})",
            detail="No firmware updates available at this time.",
        ))

    # --- Package inventory ---
    if packages and isinstance(packages[0], dict):
        # Filter to meaningful package entries
        pkg_rows: list[list[str]] = []
        for pkg in packages:
            name = pkg.get("name", pkg.get("n", ""))
            version = pkg.get("version", pkg.get("v", ""))
            if name:
                pkg_rows.append([
                    name,
                    version,
                    pkg.get("comment", pkg.get("description", "")),
                ])

        if pkg_rows:
            sections.append(format_table(
                headers=["Package", "Version", "Description"],
                rows=pkg_rows[:20],  # Limit to first 20 for readability
                title=f"Installed Packages ({len(pkg_rows)} total)",
            ))

            findings.append(Finding(
                severity=Severity.INFORMATIONAL,
                title=f"{len(pkg_rows)} package(s) installed",
                detail="Package inventory retrieved successfully.",
            ))

    # Build final report
    report_parts: list[str] = []

    if findings:
        report_parts.append(format_severity_report("Firmware Report", findings))

    for section in sections:
        report_parts.append(section)

    return "\n".join(report_parts)
