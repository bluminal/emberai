# SPDX-License-Identifier: MIT
"""WiFi agent -- orchestrates wifi tools into a channel utilization and RF report.

Calls the wifi MCP tools (get_wlans, get_aps, get_channel_utilization,
get_rf_scan, get_roaming_events) and formats the results into a unified
wireless environment report using OX formatters.

This is the backend for the ``unifi wifi`` command.
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
from unifi.tools.wifi import (
    unifi__wifi__get_aps,
    unifi__wifi__get_channel_utilization,
    unifi__wifi__get_rf_scan,
    unifi__wifi__get_roaming_events,
    unifi__wifi__get_wlans,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def _classify_channel_utilization(
    ap_name: str,
    utilization: dict[str, Any],
) -> list[Finding]:
    """Classify channel utilization metrics into severity findings."""
    findings: list[Finding] = []

    for band_key, band_label in [
        ("radio_2g", "2.4 GHz"),
        ("radio_5g", "5 GHz"),
        ("radio_6g", "6 GHz"),
    ]:
        radio = utilization.get(band_key)
        if radio is None:
            continue

        util_pct = radio.get("utilization_pct")
        if util_pct is None:
            continue

        if util_pct > 80:
            findings.append(
                Finding(
                    severity=Severity.CRITICAL,
                    title=f"{ap_name} {band_label} channel utilization at {util_pct}%",
                    detail=(
                        f"Channel {radio.get('channel', '?')} on {ap_name} "
                        f"has {util_pct}% utilization, causing performance degradation."
                    ),
                    recommendation="Consider changing to a less congested channel.",
                )
            )
        elif util_pct > 50:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title=f"{ap_name} {band_label} channel utilization at {util_pct}%",
                    detail=(
                        f"Channel {radio.get('channel', '?')} on {ap_name} "
                        f"has {util_pct}% utilization."
                    ),
                    recommendation="Monitor for further degradation.",
                )
            )

    return findings


def _classify_rf_neighbors(
    ap_name: str,
    neighbors: list[dict[str, Any]],
) -> list[Finding]:
    """Classify RF scan results into severity findings."""
    findings: list[Finding] = []

    # Count non-own SSIDs with strong signal
    strong_neighbors = [
        n for n in neighbors
        if not n.get("is_own", False) and (n.get("rssi") or 0) > -60
    ]

    if len(strong_neighbors) > 5:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"{ap_name}: {len(strong_neighbors)} strong neighboring SSIDs",
                detail=(
                    f"Detected {len(strong_neighbors)} non-own SSIDs with RSSI > -60 dBm "
                    f"near {ap_name}, indicating a dense RF environment."
                ),
                recommendation=(
                    "Review channel assignments to minimize co-channel interference."
                ),
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Public agent function
# ---------------------------------------------------------------------------


async def analyze_wifi(site_id: str = "default") -> str:
    """Run a comprehensive WiFi environment analysis.

    Calls all wifi tools and produces a report with:
    - WLAN inventory
    - AP inventory with channel assignments
    - Per-AP channel utilization analysis
    - RF environment scan results
    - Roaming event summary
    - Severity-tiered findings for issues detected

    This is the backend for the ``unifi wifi`` command.

    Args:
        site_id: The UniFi site ID. Defaults to ``"default"``.

    Returns:
        A formatted markdown report of the wireless environment.
    """
    # Gather data from all wifi tools
    wlans = await unifi__wifi__get_wlans(site_id)
    aps = await unifi__wifi__get_aps(site_id)
    roaming_events = await unifi__wifi__get_roaming_events(site_id)

    logger.info(
        "WiFi analysis data gathered for site '%s': %d WLANs, %d APs, %d roaming events",
        site_id,
        len(wlans),
        len(aps),
        len(roaming_events),
        extra={"component": "wifi"},
    )

    # Collect per-AP utilization and RF scan data
    findings: list[Finding] = []
    utilizations: list[dict[str, Any]] = []
    all_neighbors: list[dict[str, Any]] = []

    for ap in aps:
        ap_mac = ap.get("mac", "")
        ap_name = ap.get("name", ap_mac)

        try:
            util = await unifi__wifi__get_channel_utilization(ap_mac, site_id)
            utilizations.append({"ap_name": ap_name, **util})
            findings.extend(_classify_channel_utilization(ap_name, util))
        except Exception:
            logger.warning(
                "Failed to get channel utilization for AP '%s'",
                ap_name,
                exc_info=True,
            )

        try:
            neighbors = await unifi__wifi__get_rf_scan(ap_mac, site_id)
            all_neighbors.extend(neighbors)
            findings.extend(_classify_rf_neighbors(ap_name, neighbors))
        except Exception:
            logger.warning(
                "Failed to get RF scan for AP '%s'",
                ap_name,
                exc_info=True,
            )

    # Build report sections
    sections: list[str] = []

    # --- Summary ---
    sections.append(
        format_summary(
            "WiFi Environment Analysis",
            {
                "WLANs": len(wlans),
                "APs": len(aps),
                "Roaming Events (24h)": len(roaming_events),
                "Neighboring SSIDs": len(all_neighbors),
            },
        )
    )

    # --- WLAN table ---
    if wlans:
        wlan_rows = [
            [
                w.get("name", ""),
                w.get("security", ""),
                w.get("band", ""),
                str(w.get("client_count", 0)),
                "Yes" if w.get("enabled") else "No",
            ]
            for w in wlans
        ]
        sections.append(
            format_table(
                headers=["SSID", "Security", "Band", "Clients", "Enabled"],
                rows=wlan_rows,
                title="WLANs",
            )
        )

    # --- AP table ---
    if aps:
        ap_rows = [
            [
                a.get("name", ""),
                a.get("model", ""),
                str(a.get("channel_2g", "")),
                str(a.get("channel_5g", "")),
                str(a.get("client_count", 0)),
                str(a.get("satisfaction", "")),
            ]
            for a in aps
        ]
        sections.append(
            format_table(
                headers=["Name", "Model", "Ch 2.4G", "Ch 5G", "Clients", "Satisfaction"],
                rows=ap_rows,
                title="Access Points",
            )
        )

    # --- Roaming events table ---
    if roaming_events:
        roam_rows = [
            [
                str(e.get("timestamp", "")),
                e.get("client_mac", ""),
                e.get("from_ap_id", ""),
                e.get("to_ap_id", ""),
                e.get("roam_reason", ""),
            ]
            for e in roaming_events[:20]  # Limit to most recent 20
        ]
        sections.append(
            format_table(
                headers=["Time", "Client", "From AP", "To AP", "Reason"],
                rows=roam_rows,
                title=f"Roaming Events ({len(roaming_events)} total)",
            )
        )

    # --- Findings report ---
    if findings:
        sections.append(format_severity_report("WiFi Findings", findings))

    logger.info(
        "WiFi analysis complete for site '%s': %d findings",
        site_id,
        len(findings),
        extra={"component": "wifi"},
    )

    return "\n".join(sections)
