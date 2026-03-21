# SPDX-License-Identifier: MIT
"""Health skill MCP tools -- site health, device health, ISP metrics, events, firmware.

Provides MCP tools for monitoring UniFi network health, device status,
ISP connectivity metrics, event retrieval, and firmware upgrade status
via the Local Gateway API and Cloud V1 API.

When ``UNIFI_API_KEY`` is configured, the firmware status tool uses the
Cloud V1 ``/v1/devices`` endpoint for more accurate cloud-reported
firmware state.  Otherwise it falls back to local device data.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from unifi.api.cloud_v1_client import CloudV1Client
from unifi.api.local_gateway_client import LocalGatewayClient
from unifi.api.response import NormalizedResponse
from unifi.models.event import Event
from unifi.models.health import FirmwareStatus, HealthStatus
from unifi.server import mcp_server
from unifi.tools._client_factory import get_local_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State mapping (shared with topology, but re-used here for device health)
# ---------------------------------------------------------------------------

_STATE_MAP: dict[int, str] = {
    0: "disconnected",
    1: "connected",
    2: "pending_adoption",
    4: "upgrading",
    5: "provisioning",
    6: "heartbeat_missed",
    7: "adopting",
    9: "adoption_failed",
    10: "isolated",
    11: "rf_scanning",
}


def _state_to_str(state: int | str) -> str:
    """Convert a numeric device state to a human-readable string."""
    if isinstance(state, str):
        return state
    return _STATE_MAP.get(state, f"unknown({state})")


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


_get_client = get_local_client  # Shared factory with credential validation


def _has_cloud_api_key() -> bool:
    """Return True if ``UNIFI_API_KEY`` is set and non-empty."""
    return bool(os.environ.get("UNIFI_API_KEY", "").strip())


def _get_cloud_client() -> CloudV1Client:
    """Get a configured CloudV1Client from the ``UNIFI_API_KEY`` env var."""
    api_key = os.environ.get("UNIFI_API_KEY", "").strip()
    return CloudV1Client(api_key=api_key)


# ---------------------------------------------------------------------------
# Tool 1: Site Health
# ---------------------------------------------------------------------------


def _aggregate_health(subsystems: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate an array of subsystem objects into a single HealthStatus dict.

    The ``/stat/health`` endpoint returns an array where each element
    represents a subsystem (wan, lan, wlan, vpn, www).  This function
    merges them into the flat shape expected by ``HealthStatus``.
    """
    merged: dict[str, Any] = {}
    total_adopted = 0
    total_disconnected = 0
    total_sta = 0
    total_devices = 0

    for sub in subsystems:
        subsystem_name = sub.get("subsystem", "")
        status = sub.get("status", "unknown")

        if subsystem_name == "wan":
            merged["wan_status"] = status
        elif subsystem_name == "lan":
            merged["lan_status"] = status
        elif subsystem_name == "wlan":
            merged["wlan_status"] = status
        elif subsystem_name == "www":
            merged["www_status"] = status

        # Accumulate device and client counts across subsystems
        total_adopted += sub.get("num_adopted", 0)
        total_disconnected += sub.get("num_disconnected", 0)
        total_sta += sub.get("num_sta", sub.get("num_user", 0))

        # Count device slots (gateways, switches, APs)
        total_devices += sub.get("num_gw", 0)
        total_devices += sub.get("num_sw", 0)
        total_devices += sub.get("num_ap", 0)

    merged["num_d"] = total_devices
    merged["num_adopted"] = total_adopted
    merged["num_disconnected"] = total_disconnected
    merged["num_sta"] = total_sta

    return merged


@mcp_server.tool()
async def unifi__health__get_site_health(
    site_id: str = "default",
) -> dict[str, Any]:
    """Get aggregate health status for all subsystems (WAN, LAN, WLAN, WWW) at a site.

    Returns status for each subsystem, total device count, adopted count,
    offline count, and connected client count.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/stat/health")
    finally:
        await client.close()

    merged = _aggregate_health(normalized.data)
    health = HealthStatus.model_validate(merged)

    logger.info(
        "Retrieved site health for '%s': wan=%s, lan=%s, wlan=%s, www=%s",
        site_id,
        health.wan_status,
        health.lan_status,
        health.wlan_status,
        health.www_status,
        extra={"component": "health"},
    )

    return health.model_dump(by_alias=False)


# ---------------------------------------------------------------------------
# Tool 2: Device Health
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__health__get_device_health(
    device_id: str,
    site_id: str = "default",
) -> dict[str, Any]:
    """Get health metrics for a single device (uptime, CPU, memory, temperature, satisfaction).

    Extracts health-relevant fields from the device stat endpoint.

    Args:
        device_id: The device MAC address or ID.
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        raw_device = await client.get_single(
            f"/api/s/{site_id}/stat/device/{device_id}",
        )
    finally:
        await client.close()

    # Extract system stats
    system_stats = raw_device.get("system-stats", {})

    # Extract health metrics
    health_metrics: dict[str, Any] = {
        "device_id": raw_device.get("_id", ""),
        "name": raw_device.get("name", ""),
        "mac": raw_device.get("mac", ""),
        "model": raw_device.get("model", ""),
        "status": _state_to_str(raw_device.get("state", 0)),
        "uptime": raw_device.get("uptime", 0),
        "cpu_usage_pct": _safe_float(system_stats.get("cpu")),
        "mem_usage_pct": _safe_float(system_stats.get("mem")),
        "temperature_c": _safe_float(raw_device.get("general_temperature")),
        "satisfaction": raw_device.get("satisfaction"),
        "upgrade_available": raw_device.get("upgradable", False),
        "current_firmware": raw_device.get("version", ""),
        "upgrade_firmware": raw_device.get("upgrade_to_firmware", ""),
    }

    logger.info(
        "Retrieved device health for '%s' (device=%s)",
        health_metrics["name"],
        device_id,
        extra={"component": "health"},
    )

    return health_metrics


def _safe_float(value: Any) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Tool 3: ISP Metrics
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__health__get_isp_metrics(
    site_id: str = "default",
) -> dict[str, Any]:
    """Get ISP connectivity metrics from the WAN subsystem health data.

    Returns WAN IP, latency, speed test results, ISP name, and uptime.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/stat/health")
    finally:
        await client.close()

    # Find the WAN subsystem
    wan_data: dict[str, Any] = {}
    for sub in normalized.data:
        if sub.get("subsystem") == "wan":
            wan_data = sub
            break

    isp_metrics: dict[str, Any] = {
        "wan_ip": wan_data.get("wan_ip", ""),
        "isp_name": wan_data.get("isp_name", ""),
        "isp_organization": wan_data.get("isp_organization", ""),
        "latency_ms": wan_data.get("latency"),
        "speedtest_ping_ms": wan_data.get("speedtest_ping"),
        "download_mbps": wan_data.get("xput_down"),
        "upload_mbps": wan_data.get("xput_up"),
        "speedtest_lastrun": wan_data.get("speedtest_lastrun"),
        "uptime_seconds": wan_data.get("uptime"),
        "drops": wan_data.get("drops"),
        "tx_bytes_rate": wan_data.get("tx_bytes-r"),
        "rx_bytes_rate": wan_data.get("rx_bytes-r"),
        "wan_status": wan_data.get("status", "unknown"),
    }

    logger.info(
        "Retrieved ISP metrics for site '%s': isp=%s, latency=%sms",
        site_id,
        isp_metrics["isp_name"],
        isp_metrics["latency_ms"],
        extra={"component": "health"},
    )

    return isp_metrics


# ---------------------------------------------------------------------------
# Tool 4: Events
# ---------------------------------------------------------------------------


def _filter_events_by_time(
    events: list[dict[str, Any]],
    hours: int,
) -> list[dict[str, Any]]:
    """Filter events to only those within the last *hours* hours."""
    cutoff = datetime.now(tz=UTC) - timedelta(hours=hours)
    filtered: list[dict[str, Any]] = []

    for event in events:
        dt_raw = event.get("datetime")
        if dt_raw is None:
            continue

        # Parse the datetime value (could be ISO string or epoch int)
        if isinstance(dt_raw, str):
            try:
                event_dt = datetime.fromisoformat(dt_raw)
                # Ensure timezone-aware
                if event_dt.tzinfo is None:
                    event_dt = event_dt.replace(tzinfo=UTC)
            except ValueError:
                continue
        elif isinstance(dt_raw, (int, float)):
            event_dt = datetime.fromtimestamp(dt_raw, tz=UTC)
        else:
            continue

        if event_dt >= cutoff:
            filtered.append(event)

    return filtered


def _filter_events_by_severity(
    events: list[dict[str, Any]],
    severity: str,
) -> list[dict[str, Any]]:
    """Filter events by severity level.

    If *severity* is ``"all"``, all events are returned unfiltered.
    """
    if severity == "all":
        return events
    return [e for e in events if e.get("severity", "info") == severity]


@mcp_server.tool()
async def unifi__health__get_events(
    site_id: str = "default",
    hours: int = 24,
    severity: str = "all",
) -> list[dict[str, Any]]:
    """Get recent network events, optionally filtered by time window and severity.

    Returns a list of events (alarms, state changes, notifications) from
    the site's event log.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
        hours: Number of hours to look back. Defaults to 24.
        severity: Filter by severity: "critical", "warning", "info", or "all". Defaults to "all".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/stat/event")
    finally:
        await client.close()

    events_raw = normalized.data

    # Apply time window filter
    events_raw = _filter_events_by_time(events_raw, hours)

    # Apply severity filter
    events_raw = _filter_events_by_severity(events_raw, severity)

    # Parse into Event models
    events: list[dict[str, Any]] = []
    for raw_event in events_raw:
        try:
            event = Event.model_validate(raw_event)
            events.append(event.model_dump(by_alias=False))
        except Exception:
            logger.warning(
                "Skipping unparseable event: %s",
                raw_event.get("key", raw_event.get("_id", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Retrieved %d events for site '%s' (hours=%d, severity=%s)",
        len(events),
        site_id,
        hours,
        severity,
        extra={"component": "health"},
    )

    return events


# ---------------------------------------------------------------------------
# Tool 5: Firmware Status
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__health__get_firmware_status(
    site_id: str = "default",
) -> list[dict[str, Any]]:
    """Get firmware upgrade status for all devices at a site.

    Returns each device's current firmware version, latest available
    version, and whether an upgrade is available.

    When ``UNIFI_API_KEY`` is configured, uses the Cloud V1
    ``/v1/devices`` endpoint for more accurate cloud-reported firmware
    state.  Falls back to local device data when the key is not set.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    if _has_cloud_api_key():
        return await _firmware_status_cloud()
    return await _firmware_status_local(site_id)


async def _firmware_status_cloud() -> list[dict[str, Any]]:
    """Fetch firmware status via Cloud V1 ``/v1/devices``."""
    cloud_client = _get_cloud_client()
    try:
        normalized = await cloud_client.get_normalized("devices")
    finally:
        await cloud_client.close()

    firmware_list: list[dict[str, Any]] = []
    for raw_device in normalized.data:
        # Cloud V1 may return state as int or string
        if "state" in raw_device:
            raw_device["state"] = _state_to_str(raw_device["state"])

        try:
            fw = FirmwareStatus.model_validate(raw_device)
            firmware_list.append(fw.model_dump(by_alias=False))
        except Exception:
            logger.warning(
                "Skipping device for firmware status (cloud): %s",
                raw_device.get("name", raw_device.get("_id", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Retrieved firmware status for %d devices via Cloud V1 API",
        len(firmware_list),
        extra={"component": "health"},
    )

    return firmware_list


async def _firmware_status_local(site_id: str) -> list[dict[str, Any]]:
    """Fetch firmware status via the local gateway API."""
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/stat/device")
    finally:
        await client.close()

    firmware_list: list[dict[str, Any]] = []
    for raw_device in normalized.data:
        # Convert state for consistency
        if "state" in raw_device:
            raw_device["state"] = _state_to_str(raw_device["state"])

        try:
            fw = FirmwareStatus.model_validate(raw_device)
            firmware_list.append(fw.model_dump(by_alias=False))
        except Exception:
            logger.warning(
                "Skipping device for firmware status: %s",
                raw_device.get("name", raw_device.get("_id", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Retrieved firmware status for %d devices at site '%s'",
        len(firmware_list),
        site_id,
        extra={"component": "health"},
    )

    return firmware_list
