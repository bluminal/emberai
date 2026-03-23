# SPDX-License-Identifier: MIT
"""Diagnose agent -- root-cause analysis for a device or client.

Correlates health events, client data, and topology information to produce
a diagnostic report with findings and recommendations.

Phase 1 scope: correlates health events + client data + topology.
Security correlation will be added in Phase 2.

This is the backend for the ``unifi diagnose`` command.
"""

from __future__ import annotations

import logging
from typing import Any

from unifi.ask import Assumption, format_assumption_resolution
from unifi.output import (
    Finding,
    Severity,
    format_key_value,
    format_severity_report,
    format_summary,
)
from unifi.tools.clients import (
    unifi__clients__get_client,
    unifi__clients__search_clients,
)
from unifi.tools.health import (
    unifi__health__get_device_health,
    unifi__health__get_events,
)
from unifi.tools.topology import unifi__topology__list_devices

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


def _device_matches_query(device: dict[str, Any], query_lower: str) -> bool:
    """Check if a device dict matches a search query.

    Performs case-insensitive partial matching against mac, name, and ip fields.
    """
    searchable_fields = [
        device.get("mac", ""),
        device.get("name", ""),
        device.get("ip", ""),
    ]
    return any(query_lower in (field or "").lower() for field in searchable_fields)


async def _resolve_target(
    target: str,
    site_id: str,
) -> dict[str, Any]:
    """Resolve a target string to either a device or client.

    Returns a dict with:
        - "type": "device" | "client" | "ambiguous" | "not_found"
        - "matches": list of matched items (for ambiguous)
        - "item": the resolved device or client dict (for device/client)

    Args:
        target: Device MAC/name/IP or client MAC/hostname/IP to search for.
        site_id: The UniFi site ID.

    Returns:
        Resolution result dict.
    """
    target_lower = target.lower()

    # Search for clients matching the target.
    client_matches = await unifi__clients__search_clients(target, site_id=site_id)

    # Search for devices matching the target.
    all_devices = await unifi__topology__list_devices(site_id)
    device_matches = [d for d in all_devices if _device_matches_query(d, target_lower)]

    total_matches = len(client_matches) + len(device_matches)

    if total_matches == 0:
        return {"type": "not_found", "matches": [], "item": None}

    # Exact MAC match takes priority.
    for d in device_matches:
        if d.get("mac", "").lower() == target_lower:
            return {"type": "device", "matches": [], "item": d}
    for c in client_matches:
        if c.get("client_mac", "").lower() == target_lower:
            return {"type": "client", "matches": [], "item": c}

    # Single match: return it directly.
    if total_matches == 1:
        if device_matches:
            return {"type": "device", "matches": [], "item": device_matches[0]}
        return {"type": "client", "matches": [], "item": client_matches[0]}

    # Multiple matches: ambiguous.
    all_matches: list[dict[str, Any]] = []
    for d in device_matches:
        all_matches.append(
            {
                "kind": "device",
                "name": d.get("name", ""),
                "mac": d.get("mac", ""),
                "ip": d.get("ip", ""),
            }
        )
    for c in client_matches:
        all_matches.append(
            {
                "kind": "client",
                "name": c.get("hostname", ""),
                "mac": c.get("client_mac", ""),
                "ip": c.get("ip", ""),
            }
        )

    return {"type": "ambiguous", "matches": all_matches, "item": None}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_uptime(seconds: int) -> str:
    """Convert uptime in seconds to a human-readable string."""
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _format_bytes(byte_count: int | None) -> str:
    """Convert a byte count to a human-readable string."""
    if byte_count is None or byte_count == 0:
        return "0 B"

    units = [("TB", 1 << 40), ("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)]
    for label, threshold in units:
        if byte_count >= threshold:
            return f"{byte_count / threshold:.1f} {label}"
    return f"{byte_count} B"


# ---------------------------------------------------------------------------
# Diagnostic analysis
# ---------------------------------------------------------------------------


def _analyze_client(
    client: dict[str, Any],
    ap_health: dict[str, Any] | None,
    events: list[dict[str, Any]],
) -> list[Finding]:
    """Analyze a client and produce diagnostic findings.

    Checks:
      - Signal quality (wireless only)
      - AP health status (if AP health data available)
      - Related events
    """
    findings: list[Finding] = []
    client_mac = client.get("client_mac", "")

    # --- Signal quality check (wireless only) ---
    if not client.get("is_wired", False):
        rssi = client.get("rssi")
        if rssi is not None:
            if rssi < 20:
                findings.append(
                    Finding(
                        severity=Severity.CRITICAL,
                        title="Very poor signal quality",
                        detail=(
                            f"RSSI is {rssi}, indicating extremely weak signal. "
                            "The client may experience frequent disconnections "
                            "and very slow speeds."
                        ),
                        recommendation=(
                            "Move the client closer to the AP, reduce obstructions, "
                            "or add an AP closer to the client's location."
                        ),
                    )
                )
            elif rssi < 35:
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        title="Fair signal quality",
                        detail=(
                            f"RSSI is {rssi}, indicating marginal signal. "
                            "The client may experience intermittent issues."
                        ),
                        recommendation=(
                            "Consider repositioning the AP or client, "
                            "or adding an additional AP for better coverage."
                        ),
                    )
                )

    # --- AP health check ---
    if ap_health:
        ap_status = ap_health.get("status", "")
        if ap_status != "connected":
            findings.append(
                Finding(
                    severity=Severity.CRITICAL,
                    title=f"Associated AP is {ap_status}",
                    detail=(
                        f"The access point '{ap_health.get('name', 'unknown')}' "
                        f"is reporting status '{ap_status}' instead of 'connected'."
                    ),
                    recommendation="Investigate the AP status immediately.",
                )
            )

        cpu = ap_health.get("cpu_usage_pct")
        if cpu is not None and cpu > 80:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title="AP CPU usage is high",
                    detail=(
                        f"The associated AP has CPU usage at {cpu:.1f}%. "
                        "This may impact wireless performance."
                    ),
                    recommendation="Check for excessive client count or firmware issues on the AP.",
                )
            )

        mem = ap_health.get("mem_usage_pct")
        if mem is not None and mem > 85:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title="AP memory usage is high",
                    detail=(
                        f"The associated AP has memory usage at {mem:.1f}%. "
                        "This may cause instability."
                    ),
                    recommendation="Consider rebooting the AP during a maintenance window.",
                )
            )

    # --- Related events ---
    client_events = [e for e in events if e.get("client_mac") == client_mac]
    disconnect_count = sum(1 for e in client_events if "disconnect" in e.get("type", "").lower())
    if disconnect_count > 0:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"{disconnect_count} disconnect event(s) in the last 24 hours",
                detail=(
                    f"The client has disconnected {disconnect_count} time(s) recently. "
                    "This may indicate signal issues, roaming problems, or AP instability."
                ),
                recommendation="Check signal strength at the client's location and AP logs.",
            )
        )

    # If no issues found, add an informational finding.
    if not findings:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title="No issues detected",
                detail="The client appears to be operating normally with no recent problems.",
            )
        )

    return findings


def _analyze_device(
    device_health: dict[str, Any],
    events: list[dict[str, Any]],
) -> list[Finding]:
    """Analyze a device and produce diagnostic findings.

    Checks:
      - Device status
      - CPU and memory usage
      - Temperature
      - Firmware status
      - Related events
    """
    findings: list[Finding] = []
    device_mac = device_health.get("mac", "")

    # --- Device status ---
    status = device_health.get("status", "")
    if status != "connected":
        findings.append(
            Finding(
                severity=Severity.CRITICAL,
                title=f"Device is {status}",
                detail=(
                    f"Device '{device_health.get('name', 'unknown')}' "
                    f"is reporting status '{status}' instead of 'connected'."
                ),
                recommendation="Check power and physical connections to the device.",
            )
        )

    # --- CPU usage ---
    cpu = device_health.get("cpu_usage_pct")
    if cpu is not None and cpu > 80:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"High CPU usage ({cpu:.1f}%)",
                detail=(
                    "CPU usage exceeds 80%. This may impact device performance "
                    "and cause packet processing delays."
                ),
                recommendation="Check for excessive traffic or firmware issues.",
            )
        )

    # --- Memory usage ---
    mem = device_health.get("mem_usage_pct")
    if mem is not None and mem > 85:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"High memory usage ({mem:.1f}%)",
                detail=(
                    "Memory usage exceeds 85%. This may cause instability or crashes under load."
                ),
                recommendation="Consider rebooting during a maintenance window.",
            )
        )

    # --- Temperature ---
    temp = device_health.get("temperature_c")
    if temp is not None and temp > 75:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"High temperature ({temp:.0f}C)",
                detail=(
                    "Device temperature exceeds 75C. Sustained high temperatures "
                    "can reduce hardware lifespan."
                ),
                recommendation="Ensure adequate ventilation and check fan status.",
            )
        )

    # --- Firmware upgrade available ---
    if device_health.get("upgrade_available"):
        current = device_health.get("current_firmware", "")
        upgrade = device_health.get("upgrade_firmware", "")
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title="Firmware upgrade available",
                detail=f"Current: {current}, Available: {upgrade}.",
                recommendation="Schedule firmware upgrade during a maintenance window.",
            )
        )

    # --- Related events ---
    device_events = [e for e in events if e.get("device_id") == device_mac]
    warning_events = [e for e in device_events if e.get("severity") in ("warning", "critical")]
    if warning_events:
        event_summaries = "; ".join(
            f"{e.get('type', 'unknown')}: {e.get('message', '')}" for e in warning_events[:3]
        )
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"{len(warning_events)} warning/critical event(s) in the last 24 hours",
                detail=f"Recent events: {event_summaries}",
                recommendation="Investigate the events for potential issues.",
            )
        )

    # If no issues found, add an informational finding.
    if not findings:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title="No issues detected",
                detail="The device appears to be operating normally with no recent problems.",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Public agent function
# ---------------------------------------------------------------------------


async def diagnose_target(target: str, site_id: str = "default") -> str:
    """Run root-cause analysis for a device or client.

    Phase 1 scope: correlates health events + client data + topology.
    Security correlation added in Phase 2.

    1. Searches for the target using search_clients and list_devices.
    2. If ambiguous (matches multiple), returns an AskUserQuestion prompt.
    3. If it's a client: gets client details, AP health, recent events.
    4. If it's a device: gets device health, recent events.
    5. Returns a diagnostic report with findings and recommendations.

    Args:
        target: Device MAC/name/IP or client MAC/hostname/IP to diagnose.
        site_id: The UniFi site ID. Defaults to ``"default"``.

    Returns:
        A formatted diagnostic report or an AskUserQuestion prompt.
    """
    resolution = await _resolve_target(target, site_id)

    # --- Not found ---
    if resolution["type"] == "not_found":
        return (
            f"## Diagnosis: Not Found\n\n"
            f"No device or client matching '{target}' was found at site '{site_id}'.\n\n"
            f"Verify the MAC address, hostname, or IP and try again.\n"
        )

    # --- Ambiguous match: use AskUserQuestion pattern ---
    if resolution["type"] == "ambiguous":
        matches = resolution["matches"]
        assumptions = [
            Assumption(
                question="Which target did you mean?",
                implication=(
                    "Multiple matches found. Please specify the exact MAC address "
                    "or provide a more specific identifier:\n"
                    + "\n".join(
                        f"  - {m['kind'].title()}: {m['name'] or m['mac']} "
                        f"(MAC: {m['mac']}, IP: {m['ip']})"
                        for m in matches
                    )
                ),
            )
        ]
        return format_assumption_resolution(
            assumptions,
            resolved_facts=[f"Search term: '{target}'"],
        )

    # --- Client diagnosis ---
    if resolution["type"] == "client":
        return await _diagnose_client(resolution["item"], site_id)

    # --- Device diagnosis ---
    return await _diagnose_device(resolution["item"], site_id)


async def _diagnose_client(client: dict[str, Any], site_id: str) -> str:
    """Run diagnosis for a client target."""
    client_mac = client.get("client_mac", "")
    display_name = client.get("hostname") or client_mac

    # Fetch full client details.
    try:
        client_detail = await unifi__clients__get_client(client_mac, site_id=site_id)
    except Exception:
        logger.warning(
            "Could not fetch full client details for %s, using search result",
            client_mac,
            exc_info=True,
        )
        client_detail = client

    # Fetch AP health if wireless.
    ap_health: dict[str, Any] | None = None
    ap_id = client_detail.get("ap_id")
    if ap_id and not client_detail.get("is_wired", False):
        try:
            ap_health = await unifi__health__get_device_health(ap_id, site_id=site_id)
        except Exception:
            logger.warning(
                "Could not fetch AP health for %s",
                ap_id,
                exc_info=True,
            )

    # Fetch recent events.
    events = await unifi__health__get_events(site_id, hours=24)

    # Analyze.
    findings = _analyze_client(client_detail, ap_health, events)

    # Build report.
    sections: list[str] = []

    # Summary.
    conn_type = "Wired" if client_detail.get("is_wired") else "Wireless"
    sections.append(
        format_summary(
            f"Diagnosis: {display_name}",
            {
                "Type": "Client",
                "Connection": conn_type,
                "IP": client_detail.get("ip", "N/A"),
            },
        )
    )

    # Client details.
    detail_data: dict[str, str] = {
        "MAC": client_mac,
        "Hostname": client_detail.get("hostname") or "N/A",
        "IP": client_detail.get("ip", "N/A"),
        "VLAN": client_detail.get("vlan_id", "N/A"),
        "Connection": conn_type,
        "Uptime": _format_uptime(client_detail.get("uptime", 0)),
    }

    if not client_detail.get("is_wired", False):
        detail_data["AP"] = client_detail.get("ap_id", "N/A")
        detail_data["SSID"] = client_detail.get("ssid") or "N/A"
        rssi = client_detail.get("rssi")
        detail_data["RSSI"] = str(rssi) if rssi is not None else "N/A"

    tx = client_detail.get("tx_bytes")
    rx = client_detail.get("rx_bytes")
    if tx is not None:
        detail_data["TX"] = _format_bytes(tx)
    if rx is not None:
        detail_data["RX"] = _format_bytes(rx)

    sections.append(format_key_value(detail_data, title="Client Details"))

    # AP health (if available).
    if ap_health:
        ap_data: dict[str, str] = {
            "Name": ap_health.get("name", "N/A"),
            "Status": ap_health.get("status", "N/A"),
            "Uptime": _format_uptime(ap_health.get("uptime", 0)),
        }
        cpu = ap_health.get("cpu_usage_pct")
        if cpu is not None:
            ap_data["CPU"] = f"{cpu:.1f}%"
        mem = ap_health.get("mem_usage_pct")
        if mem is not None:
            ap_data["Memory"] = f"{mem:.1f}%"
        sections.append(format_key_value(ap_data, title="Associated AP Health"))

    # Findings.
    sections.append(format_severity_report("Diagnostic Findings", findings))

    logger.info(
        "Client diagnosis complete for '%s': %d findings",
        display_name,
        len(findings),
        extra={"component": "diagnose"},
    )

    return "\n".join(sections)


async def _diagnose_device(device: dict[str, Any], site_id: str) -> str:
    """Run diagnosis for a device target."""
    device_mac = device.get("mac", "")
    display_name = device.get("name") or device_mac

    # Fetch device health.
    try:
        device_health = await unifi__health__get_device_health(device_mac, site_id=site_id)
    except Exception:
        logger.warning(
            "Could not fetch device health for %s, using search result",
            device_mac,
            exc_info=True,
        )
        # Build a minimal health dict from the device data.
        device_health = {
            "device_id": device.get("device_id", ""),
            "name": display_name,
            "mac": device_mac,
            "model": device.get("model", ""),
            "status": device.get("status", "unknown"),
            "uptime": device.get("uptime", 0),
        }

    # Fetch recent events.
    events = await unifi__health__get_events(site_id, hours=24)

    # Analyze.
    findings = _analyze_device(device_health, events)

    # Build report.
    sections: list[str] = []

    # Summary.
    sections.append(
        format_summary(
            f"Diagnosis: {display_name}",
            {
                "Type": "Device",
                "Model": device_health.get("model", "N/A"),
                "Status": device_health.get("status", "N/A"),
            },
        )
    )

    # Device details.
    detail_data: dict[str, str] = {
        "MAC": device_mac,
        "Name": display_name,
        "Model": device_health.get("model", "N/A"),
        "Status": device_health.get("status", "N/A"),
        "Firmware": device_health.get("current_firmware", "N/A"),
        "Uptime": _format_uptime(device_health.get("uptime", 0)),
    }

    cpu = device_health.get("cpu_usage_pct")
    if cpu is not None:
        detail_data["CPU"] = f"{cpu:.1f}%"
    mem = device_health.get("mem_usage_pct")
    if mem is not None:
        detail_data["Memory"] = f"{mem:.1f}%"
    temp = device_health.get("temperature_c")
    if temp is not None:
        detail_data["Temperature"] = f"{temp:.0f}C"
    satisfaction = device_health.get("satisfaction")
    if satisfaction is not None:
        detail_data["Satisfaction"] = str(satisfaction)

    sections.append(format_key_value(detail_data, title="Device Details"))

    # Findings.
    sections.append(format_severity_report("Diagnostic Findings", findings))

    logger.info(
        "Device diagnosis complete for '%s': %d findings",
        display_name,
        len(findings),
        extra={"component": "diagnose"},
    )

    return "\n".join(sections)
