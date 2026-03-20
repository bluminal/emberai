# SPDX-License-Identifier: MIT
"""Traffic agent -- orchestrates traffic tools into a bandwidth and usage report.

Calls the traffic MCP tools (get_bandwidth, get_dpi_stats, get_wan_usage)
and formats the results into a unified traffic report using OX formatters.

This is the backend for the ``unifi traffic`` command.
"""

from __future__ import annotations

import logging
from typing import Any

from unifi.output import (
    Finding,
    Severity,
    format_severity_report,
    format_summary,
    format_table,
)
from unifi.tools.traffic import (
    unifi__traffic__get_bandwidth,
    unifi__traffic__get_dpi_stats,
    unifi__traffic__get_wan_usage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def _classify_bandwidth(bandwidth: dict[str, Any]) -> list[Finding]:
    """Classify bandwidth data into severity findings."""
    findings: list[Finding] = []

    wan = bandwidth.get("wan", {})
    wan_rx = wan.get("rx_mbps", 0)
    wan_tx = wan.get("tx_mbps", 0)

    # Flag very high WAN utilization
    if wan_rx > 900 or wan_tx > 900:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title="High WAN bandwidth utilization",
                detail=(
                    f"WAN throughput is elevated: "
                    f"download {wan_rx:.1f} Mbps, upload {wan_tx:.1f} Mbps."
                ),
                recommendation="Review top applications consuming bandwidth.",
            )
        )

    return findings


def _classify_wan_usage(usage: list[dict[str, Any]]) -> list[Finding]:
    """Classify WAN usage trends into severity findings."""
    findings: list[Finding] = []

    if not usage:
        return findings

    # Calculate total and average daily usage
    total_download = sum(d.get("download_gb", 0) for d in usage)
    total_upload = sum(d.get("upload_gb", 0) for d in usage)
    avg_daily = (total_download + total_upload) / len(usage) if usage else 0

    if avg_daily > 100:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"High average daily WAN usage: {avg_daily:.1f} GB/day",
                detail=(
                    f"Average daily WAN usage is {avg_daily:.1f} GB over "
                    f"{len(usage)} days (total: {total_download + total_upload:.1f} GB)."
                ),
                recommendation="Review DPI data to identify bandwidth-heavy applications.",
            )
        )

    return findings


def _format_bytes(byte_count: int) -> str:
    """Format a byte count into a human-readable string."""
    if byte_count >= 1_073_741_824:
        return f"{byte_count / 1_073_741_824:.1f} GB"
    if byte_count >= 1_048_576:
        return f"{byte_count / 1_048_576:.1f} MB"
    if byte_count >= 1024:
        return f"{byte_count / 1024:.1f} KB"
    return f"{byte_count} B"


# ---------------------------------------------------------------------------
# Public agent function
# ---------------------------------------------------------------------------


async def traffic_report(site_id: str = "default") -> str:
    """Generate a comprehensive traffic report for a UniFi site.

    Produces a bandwidth summary, top applications by traffic,
    and WAN usage trends with severity-tiered findings.

    This is the backend for the ``unifi traffic`` command.

    Args:
        site_id: The UniFi site ID. Defaults to ``"default"``.

    Returns:
        A formatted markdown report of traffic analysis.
    """
    # Gather data from traffic tools
    bandwidth = await unifi__traffic__get_bandwidth(site_id)
    dpi_stats = await unifi__traffic__get_dpi_stats(site_id)
    wan_usage = await unifi__traffic__get_wan_usage(site_id)

    logger.info(
        "Traffic report data gathered for site '%s': %d DPI entries, %d usage days",
        site_id,
        len(dpi_stats),
        len(wan_usage),
        extra={"component": "traffic"},
    )

    # Classify findings
    findings: list[Finding] = []
    findings.extend(_classify_bandwidth(bandwidth))
    findings.extend(_classify_wan_usage(wan_usage))

    # Build report sections
    sections: list[str] = []

    # --- Summary ---
    wan = bandwidth.get("wan", {})
    lan = bandwidth.get("lan", {})

    total_wan_download = sum(d.get("download_gb", 0) for d in wan_usage)
    total_wan_upload = sum(d.get("upload_gb", 0) for d in wan_usage)

    sections.append(
        format_summary(
            "Traffic Report",
            {
                "WAN Download": f"{wan.get('rx_mbps', 0):.1f} Mbps",
                "WAN Upload": f"{wan.get('tx_mbps', 0):.1f} Mbps",
                "LAN Download": f"{lan.get('rx_mbps', 0):.1f} Mbps",
                "LAN Upload": f"{lan.get('tx_mbps', 0):.1f} Mbps",
                "Total WAN Usage": f"{total_wan_download + total_wan_upload:.1f} GB",
            },
        )
    )

    # --- Top Applications (DPI) ---
    if dpi_stats:
        # Sort by total bytes (rx + tx) descending, show top 15
        sorted_dpi = sorted(
            dpi_stats,
            key=lambda d: d.get("tx_bytes", 0) + d.get("rx_bytes", 0),
            reverse=True,
        )[:15]

        dpi_rows = [
            [
                str(d.get("application", "")),
                str(d.get("category", "")),
                _format_bytes(d.get("rx_bytes", 0)),
                _format_bytes(d.get("tx_bytes", 0)),
                str(d.get("session_count", 0)),
            ]
            for d in sorted_dpi
        ]
        sections.append(
            format_table(
                headers=["Application", "Category", "Download", "Upload", "Sessions"],
                rows=dpi_rows,
                title="Top Applications (DPI)",
            )
        )

    # --- WAN Usage Trend ---
    if wan_usage:
        # Show last 7 days in detail, summarize the rest
        recent_usage = wan_usage[-7:] if len(wan_usage) > 7 else wan_usage
        usage_rows = [
            [
                str(d.get("date", "")),
                f"{d.get('download_gb', 0):.2f} GB",
                f"{d.get('upload_gb', 0):.2f} GB",
            ]
            for d in recent_usage
        ]
        sections.append(
            format_table(
                headers=["Date", "Download", "Upload"],
                rows=usage_rows,
                title=f"WAN Usage (last {len(recent_usage)} days of {len(wan_usage)})",
            )
        )

    # --- Findings ---
    if findings:
        sections.append(format_severity_report("Traffic Findings", findings))

    logger.info(
        "Traffic report complete for site '%s': %d findings",
        site_id,
        len(findings),
        extra={"component": "traffic"},
    )

    return "\n".join(sections)
