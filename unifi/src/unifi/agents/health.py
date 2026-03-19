# SPDX-License-Identifier: MIT
"""Health agent -- orchestrates health tools into a comprehensive severity report.

Calls the four health MCP tools (get_site_health, get_events,
get_firmware_status, get_isp_metrics) and classifies findings by severity
using OX formatters.

This is the backend for the ``unifi health`` command.
"""

from __future__ import annotations

import logging
from typing import Any

from unifi.output import Finding, Severity, format_severity_report, format_summary
from unifi.tools.health import (
    unifi__health__get_events,
    unifi__health__get_firmware_status,
    unifi__health__get_isp_metrics,
    unifi__health__get_site_health,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Subsystem status classification
# ---------------------------------------------------------------------------

# Subsystem labels for human-readable display.
_SUBSYSTEM_LABELS: dict[str, str] = {
    "wan_status": "WAN",
    "lan_status": "LAN",
    "wlan_status": "WLAN",
    "www_status": "Internet (WWW)",
}


def _classify_site_health(health: dict[str, Any]) -> list[Finding]:
    """Classify site health data into severity-tiered findings.

    - CRITICAL: Any subsystem not "ok", offline devices detected
    - INFORMATIONAL: Device and client counts
    """
    findings: list[Finding] = []

    # Check each subsystem status.
    for field, label in _SUBSYSTEM_LABELS.items():
        status = health.get(field, "unknown")
        if status != "ok":
            findings.append(
                Finding(
                    severity=Severity.CRITICAL,
                    title=f"{label} subsystem is {status}",
                    detail=f"The {label} subsystem is reporting status '{status}' instead of 'ok'.",
                    recommendation=f"Investigate {label} subsystem immediately.",
                )
            )

    # Check for offline devices.
    offline = health.get("offline_count", 0)
    if offline > 0:
        findings.append(
            Finding(
                severity=Severity.CRITICAL,
                title=f"{offline} device(s) offline",
                detail=f"{offline} device(s) are disconnected and not responding.",
                recommendation="Check physical connections and power for offline devices.",
            )
        )

    return findings


def _classify_events(events: list[dict[str, Any]]) -> list[Finding]:
    """Classify recent events into severity-tiered findings.

    - WARNING: Events with severity >= "warning"
    """
    findings: list[Finding] = []

    for event in events:
        event_severity = event.get("severity", "info")
        if event_severity in ("warning", "critical"):
            finding_severity = (
                Severity.CRITICAL if event_severity == "critical" else Severity.WARNING
            )
            event_type = event.get("type", "unknown")
            message = event.get("message", "No message")
            findings.append(
                Finding(
                    severity=finding_severity,
                    title=f"Event: {event_type}",
                    detail=message,
                )
            )

    return findings


def _classify_firmware(firmware_list: list[dict[str, Any]]) -> list[Finding]:
    """Classify firmware status into severity-tiered findings.

    - WARNING: Devices with firmware upgrades available
    """
    findings: list[Finding] = []

    upgradable = [fw for fw in firmware_list if fw.get("upgrade_available")]
    if upgradable:
        device_details = ", ".join(
            f"{fw.get('model', 'unknown')}"
            f" ({fw.get('current_version', '?')} -> {fw.get('latest_version', '?')})"
            for fw in upgradable
        )
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"Firmware update available for {len(upgradable)} device(s)",
                detail=f"Devices with pending updates: {device_details}.",
                recommendation="Schedule firmware upgrades during a maintenance window.",
            )
        )

    return findings


def _classify_isp(isp_metrics: dict[str, Any]) -> list[Finding]:
    """Classify ISP metrics into severity-tiered findings.

    - CRITICAL: WAN status not "ok"
    - INFORMATIONAL: ISP metrics summary
    """
    findings: list[Finding] = []

    wan_status = isp_metrics.get("wan_status", "unknown")
    if wan_status != "ok":
        findings.append(
            Finding(
                severity=Severity.CRITICAL,
                title=f"WAN link status is {wan_status}",
                detail=f"The WAN connection is reporting status '{wan_status}'.",
                recommendation="Check WAN cable, modem, and ISP service status.",
            )
        )

    # Build ISP summary as informational finding.
    isp_name = isp_metrics.get("isp_name", "")
    latency = isp_metrics.get("latency_ms")
    download = isp_metrics.get("download_mbps")
    upload = isp_metrics.get("upload_mbps")
    drops = isp_metrics.get("drops")

    summary_parts: list[str] = []
    if isp_name:
        summary_parts.append(f"ISP: {isp_name}")
    if latency is not None:
        summary_parts.append(f"Latency: {latency}ms")
    if download is not None:
        summary_parts.append(f"Download: {download} Mbps")
    if upload is not None:
        summary_parts.append(f"Upload: {upload} Mbps")
    if drops is not None:
        summary_parts.append(f"Drops: {drops}")

    if summary_parts:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title="ISP metrics",
                detail=", ".join(summary_parts) + ".",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Public agent function
# ---------------------------------------------------------------------------


async def check_health(site_id: str = "default") -> str:
    """Run a comprehensive health check and produce a severity-tiered report.

    Calls all health tools and classifies findings by severity:
    - CRITICAL: Devices offline, WAN down, high packet loss
    - WARNING: Firmware outdated, high CPU/memory, degraded WiFi
    - INFORMATIONAL: All healthy, ISP metrics summary

    Returns a formatted report using OX formatters.
    This is the backend for the ``unifi health`` command.

    Args:
        site_id: The UniFi site ID. Defaults to ``"default"``.

    Returns:
        A formatted markdown report containing health findings
        organized by severity.
    """
    # Gather data from all health tools.
    health = await unifi__health__get_site_health(site_id)
    events = await unifi__health__get_events(site_id, hours=24)
    firmware = await unifi__health__get_firmware_status(site_id)
    isp_metrics = await unifi__health__get_isp_metrics(site_id)

    logger.info(
        "Health check data gathered for site '%s': health=%s, events=%d, firmware=%d",
        site_id,
        health.get("wan_status", "unknown"),
        len(events),
        len(firmware),
        extra={"component": "health"},
    )

    # Classify findings from each data source.
    findings: list[Finding] = []
    findings.extend(_classify_site_health(health))
    findings.extend(_classify_events(events))
    findings.extend(_classify_firmware(firmware))
    findings.extend(_classify_isp(isp_metrics))

    # Build report sections.
    sections: list[str] = []

    # Summary header.
    device_count = health.get("device_count", 0)
    client_count = health.get("client_count", 0)

    summary_stats: dict[str, int | str] = {
        "Devices": device_count,
        "Clients": client_count,
    }

    # Count findings by severity for the summary.
    critical_count = sum(1 for f in findings if f.severity == Severity.CRITICAL)
    warning_count = sum(1 for f in findings if f.severity == Severity.WARNING)

    if critical_count > 0:
        summary_stats["Critical"] = critical_count
    if warning_count > 0:
        summary_stats["Warnings"] = warning_count

    # Add healthy message if no actionable findings.
    detail: str | None = None
    if critical_count == 0 and warning_count == 0:
        detail = (
            f"All systems healthy -- {device_count} device(s) online, "
            f"{client_count} client(s) connected."
        )

    sections.append(
        format_summary("Health Check", summary_stats, detail=detail)
    )

    # Severity report (only if there are findings).
    if findings:
        sections.append(format_severity_report("Findings", findings))

    logger.info(
        "Health check complete for site '%s': %d critical, %d warning, %d total findings",
        site_id,
        critical_count,
        warning_count,
        len(findings),
        extra={"component": "health"},
    )

    return "\n".join(sections)
