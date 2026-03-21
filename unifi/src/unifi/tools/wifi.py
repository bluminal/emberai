# SPDX-License-Identifier: MIT
"""WiFi skill MCP tools -- WLAN, AP, RF environment, and roaming analysis.

Provides MCP tools for inspecting UniFi wireless networks, access points,
channel utilization, RF scans, roaming events, and per-client RF metrics
via the Local Gateway API.

All tools are read-only. No active RF scans are triggered -- passive data only.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from unifi.api.local_gateway_client import LocalGatewayClient
from unifi.server import mcp_server
from unifi.tools._client_factory import get_local_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


_get_client = get_local_client  # Shared factory with credential validation


# ---------------------------------------------------------------------------
# Tool 1: Get WLANs
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__wifi__get_wlans(site_id: str = "default") -> list[dict[str, Any]]:
    """List all configured WLANs (SSIDs) for a UniFi site.

    Returns SSID list with security mode, band, VLAN assignment,
    enabled status, client count, and satisfaction score.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(
            f"/api/s/{site_id}/rest/wlanconf",
        )
    finally:
        await client.close()

    wlans: list[dict[str, Any]] = []
    for raw in normalized.data:
        wlan: dict[str, Any] = {
            "wlan_id": raw.get("_id", ""),
            "name": raw.get("name", ""),
            "ssid": raw.get("name", ""),
            "security": raw.get("security", "open"),
            "band": raw.get("wlan_band", "both"),
            "vlan_id": raw.get("networkconf_id", ""),
            "enabled": raw.get("enabled", True),
            "client_count": raw.get("num_sta", 0),
            "satisfaction": raw.get("satisfaction"),
        }
        wlans.append(wlan)

    logger.info(
        "Listed %d WLANs for site '%s'",
        len(wlans),
        site_id,
        extra={"component": "wifi"},
    )

    return wlans


# ---------------------------------------------------------------------------
# Tool 2: Get APs
# ---------------------------------------------------------------------------


_AP_TYPES = frozenset({"uap", "udm"})


def _is_ap(device: dict[str, Any]) -> bool:
    """Return True if the device is an access point."""
    device_type = device.get("type", "")
    if device_type in _AP_TYPES:
        return True
    # Fallback: check model prefix for AP models
    model = device.get("model", "")
    return model.startswith("U6") or model.startswith("U7") or model.startswith("UAP")


def _extract_radio_field(
    radio_table: list[dict[str, Any]],
    band: str,
    field: str,
) -> Any | None:
    """Extract a field value from a specific radio band entry."""
    for radio in radio_table:
        radio_band = radio.get("radio", "")
        if radio_band == band:
            return radio.get(field)
    return None


@mcp_server.tool()
async def unifi__wifi__get_aps(site_id: str = "default") -> list[dict[str, Any]]:
    """List all access points for a UniFi site with radio details.

    Returns AP inventory with channels, transmit power, client count,
    and satisfaction score per radio band.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(
            f"/api/s/{site_id}/stat/device",
        )
    finally:
        await client.close()

    aps: list[dict[str, Any]] = []
    for raw in normalized.data:
        if not _is_ap(raw):
            continue

        radio_table = raw.get("radio_table", [])

        ap: dict[str, Any] = {
            "ap_id": raw.get("_id", ""),
            "name": raw.get("name", ""),
            "mac": raw.get("mac", ""),
            "model": raw.get("model", ""),
            "channel_2g": _extract_radio_field(radio_table, "ng", "channel"),
            "channel_5g": _extract_radio_field(radio_table, "na", "channel"),
            "channel_6g": _extract_radio_field(radio_table, "6e", "channel"),
            "tx_power_2g": _extract_radio_field(radio_table, "ng", "tx_power"),
            "tx_power_5g": _extract_radio_field(radio_table, "na", "tx_power"),
            "client_count": raw.get("num_sta", 0),
            "satisfaction": raw.get("satisfaction"),
        }
        aps.append(ap)

    logger.info(
        "Listed %d APs for site '%s'",
        len(aps),
        site_id,
        extra={"component": "wifi"},
    )

    return aps


# ---------------------------------------------------------------------------
# Tool 3: Get Channel Utilization
# ---------------------------------------------------------------------------


def _extract_radio_utilization(
    radio_table: list[dict[str, Any]],
    radio_table_stats: list[dict[str, Any]],
    band: str,
) -> dict[str, Any] | None:
    """Build a utilization dict for a specific radio band."""
    radio_entry: dict[str, Any] | None = None
    for radio in radio_table:
        if radio.get("radio") == band:
            radio_entry = radio
            break

    if radio_entry is None:
        return None

    # Find matching stats entry
    stats_entry: dict[str, Any] = {}
    for stats in radio_table_stats:
        if stats.get("radio") == band or stats.get("name") == radio_entry.get("name"):
            stats_entry = stats
            break

    return {
        "channel": radio_entry.get("channel"),
        "utilization_pct": stats_entry.get("cu_total", stats_entry.get("channel_utilization")),
        "interference_pct": stats_entry.get("cu_self_rx"),
    }


@mcp_server.tool()
async def unifi__wifi__get_channel_utilization(
    ap_id: str,
    site_id: str = "default",
) -> dict[str, Any]:
    """Get radio channel utilization and interference metrics for an AP.

    Returns per-band utilization and interference percentages from
    the AP's radio table statistics.

    Args:
        ap_id: The AP MAC address or device ID.
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        raw_device = await client.get_single(
            f"/api/s/{site_id}/stat/device/{ap_id}",
        )
    finally:
        await client.close()

    radio_table = raw_device.get("radio_table", [])
    radio_table_stats = raw_device.get("radio_table_stats", [])

    result: dict[str, Any] = {
        "ap_id": raw_device.get("_id", ap_id),
        "radio_2g": _extract_radio_utilization(radio_table, radio_table_stats, "ng"),
        "radio_5g": _extract_radio_utilization(radio_table, radio_table_stats, "na"),
        "radio_6g": _extract_radio_utilization(radio_table, radio_table_stats, "6e"),
    }

    logger.info(
        "Retrieved channel utilization for AP '%s'",
        ap_id,
        extra={"component": "wifi"},
    )

    return result


# ---------------------------------------------------------------------------
# Tool 4: Get RF Scan (cached/passive)
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__wifi__get_rf_scan(
    ap_id: str,
    site_id: str = "default",
) -> list[dict[str, Any]]:
    """Get cached RF scan data showing neighboring SSIDs detected by an AP.

    Returns a list of detected neighboring networks with SSID, BSSID,
    channel, band, signal strength, security mode, and whether it
    belongs to our network.

    Note: Returns cached scan data. Does NOT trigger a new active scan.

    Args:
        ap_id: The AP MAC address or device ID.
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(
            f"/api/s/{site_id}/stat/rogueap",
        )
    finally:
        await client.close()

    # Filter to entries detected by the specified AP
    neighbors: list[dict[str, Any]] = []
    for raw in normalized.data:
        # rogueap entries may have an ap_mac field indicating which AP saw them
        detected_by = raw.get("ap_mac", "")
        if detected_by and detected_by != ap_id:
            continue

        neighbor: dict[str, Any] = {
            "ssid": raw.get("essid", raw.get("ssid", "")),
            "bssid": raw.get("bssid", ""),
            "channel": raw.get("channel"),
            "band": raw.get("band", raw.get("radio", "")),
            "rssi": raw.get("rssi", raw.get("signal")),
            "security": raw.get("security", ""),
            "is_own": raw.get("is_ubnt", raw.get("is_unifi", False)),
        }
        neighbors.append(neighbor)

    logger.info(
        "Retrieved %d RF scan entries for AP '%s'",
        len(neighbors),
        ap_id,
        extra={"component": "wifi"},
    )

    return neighbors


# ---------------------------------------------------------------------------
# Tool 5: Get Roaming Events
# ---------------------------------------------------------------------------

_ROAM_EVENT_KEYS = frozenset({
    "EVT_WU_Roam",
    "EVT_WU_RoamRadio",
    "EVT_WC_Roam",
})


def _is_roam_event(event: dict[str, Any]) -> bool:
    """Return True if the event is a roaming event."""
    key = event.get("key", "")
    return key in _ROAM_EVENT_KEYS or "roam" in key.lower()


@mcp_server.tool()
async def unifi__wifi__get_roaming_events(
    site_id: str = "default",
    hours: int = 24,
) -> list[dict[str, Any]]:
    """Get recent client roaming events for a UniFi site.

    Returns roaming events showing client transitions between APs,
    including signal strength before/after and roam reason.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
        hours: Number of hours to look back. Defaults to 24.
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(
            f"/api/s/{site_id}/stat/event",
        )
    finally:
        await client.close()

    cutoff = datetime.now(tz=UTC) - timedelta(hours=hours)

    events: list[dict[str, Any]] = []
    for raw in normalized.data:
        if not _is_roam_event(raw):
            continue

        # Apply time window filter
        dt_raw = raw.get("datetime", raw.get("time"))
        if dt_raw is not None:
            if isinstance(dt_raw, str):
                try:
                    event_dt = datetime.fromisoformat(dt_raw)
                    if event_dt.tzinfo is None:
                        event_dt = event_dt.replace(tzinfo=UTC)
                except ValueError:
                    continue
            elif isinstance(dt_raw, (int, float)):
                event_dt = datetime.fromtimestamp(dt_raw, tz=UTC)
            else:
                continue

            if event_dt < cutoff:
                continue

        event: dict[str, Any] = {
            "timestamp": dt_raw,
            "client_mac": raw.get("user", raw.get("client", "")),
            "from_ap_id": raw.get("ap_from", raw.get("ap", "")),
            "to_ap_id": raw.get("ap_to", raw.get("ap", "")),
            "rssi_before": raw.get("rssi_from"),
            "rssi_after": raw.get("rssi_to", raw.get("rssi")),
            "roam_reason": raw.get("reason", raw.get("msg", "")),
        }
        events.append(event)

    logger.info(
        "Retrieved %d roaming events for site '%s' (hours=%d)",
        len(events),
        site_id,
        hours,
        extra={"component": "wifi"},
    )

    return events


# ---------------------------------------------------------------------------
# Tool 6: Get Client RF
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__wifi__get_client_rf(
    client_mac: str,
    site_id: str = "default",
) -> dict[str, Any]:
    """Get RF signal quality metrics for a specific wireless client.

    Returns signal strength, noise floor, SNR, data rates, retry
    percentage, channel, and band for the client's current connection.

    Args:
        client_mac: The client's MAC address.
        site_id: The UniFi site ID. Defaults to "default".
    """
    api_client = _get_client()
    try:
        raw = await api_client.get_single(
            f"/api/s/{site_id}/stat/sta/{client_mac}",
        )
    finally:
        await api_client.close()

    rf_metrics: dict[str, Any] = {
        "client_mac": raw.get("mac", client_mac),
        "ap_id": raw.get("ap_mac", ""),
        "ssid": raw.get("essid", raw.get("bssid", "")),
        "rssi": raw.get("rssi", raw.get("signal")),
        "noise": raw.get("noise"),
        "snr": _compute_snr(raw.get("rssi"), raw.get("noise")),
        "tx_rate_mbps": raw.get("tx_rate", raw.get("tx_bytes_r")),
        "rx_rate_mbps": raw.get("rx_rate", raw.get("rx_bytes_r")),
        "tx_retries_pct": raw.get("tx_retries"),
        "channel": raw.get("channel"),
        "band": raw.get("radio", raw.get("radio_proto", "")),
    }

    logger.info(
        "Retrieved RF metrics for client '%s'",
        client_mac,
        extra={"component": "wifi"},
    )

    return rf_metrics


def _compute_snr(rssi: Any, noise: Any) -> int | None:
    """Compute SNR from RSSI and noise floor values."""
    if rssi is None or noise is None:
        return None
    try:
        return int(rssi) - int(noise)
    except (ValueError, TypeError):
        return None
