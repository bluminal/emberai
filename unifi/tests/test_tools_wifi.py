"""Tests for the WiFi MCP tools (WLANs, APs, channel util, RF scan, roaming, client RF)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, NetworkError
from unifi.server import mcp_server
from unifi.tools.wifi import (
    _compute_snr,
    _extract_radio_field,
    _extract_radio_utilization,
    _get_client,
    _is_ap,
    _is_roam_event,
    unifi__wifi__get_aps,
    unifi__wifi__get_channel_utilization,
    unifi__wifi__get_client_rf,
    unifi__wifi__get_rf_scan,
    unifi__wifi__get_roaming_events,
    unifi__wifi__get_wlans,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalized(data: list[dict[str, Any]]) -> NormalizedResponse:
    return NormalizedResponse(
        data=data,
        count=len(data),
        total_count=None,
        meta={"rc": "ok"},
    )


def _mock_client_normalized(data: list[dict[str, Any]]) -> AsyncMock:
    """Create a mock client returning a NormalizedResponse."""
    mock = AsyncMock()
    mock.get_normalized = AsyncMock(return_value=_normalized(data))
    mock.close = AsyncMock()
    return mock


def _mock_client_single(data: dict[str, Any]) -> AsyncMock:
    """Create a mock client returning a single dict."""
    mock = AsyncMock()
    mock.get_single = AsyncMock(return_value=data)
    mock.close = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------


class TestGetClient:
    """Verify the helper builds a client from env vars."""

    def test_creates_client_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "10.0.0.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "wifi-key-123")

        client = _get_client()

        assert client._host == "10.0.0.1"
        assert client._api_key == "wifi-key-123"

    def test_defaults_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNIFI_LOCAL_HOST", raising=False)
        monkeypatch.delenv("UNIFI_LOCAL_KEY", raising=False)

        client = _get_client()

        assert client._host == ""
        assert client._api_key == ""


# ---------------------------------------------------------------------------
# _is_ap
# ---------------------------------------------------------------------------


class TestIsAp:
    """Verify AP detection logic."""

    def test_uap_type(self) -> None:
        assert _is_ap({"type": "uap", "model": "U6-Pro"}) is True

    def test_udm_type(self) -> None:
        assert _is_ap({"type": "udm", "model": "UDM-Pro"}) is True

    def test_usw_type_excluded(self) -> None:
        assert _is_ap({"type": "usw", "model": "USW-24"}) is False

    def test_ugw_type_excluded(self) -> None:
        assert _is_ap({"type": "ugw", "model": "UXG-Max"}) is False

    def test_u6_model_prefix(self) -> None:
        assert _is_ap({"type": "", "model": "U6-LR"}) is True

    def test_u7_model_prefix(self) -> None:
        assert _is_ap({"type": "", "model": "U7-Pro"}) is True

    def test_uap_model_prefix(self) -> None:
        assert _is_ap({"type": "", "model": "UAP-AC-Pro"}) is True

    def test_usw_model_not_ap(self) -> None:
        assert _is_ap({"type": "", "model": "USW-Lite-8"}) is False

    def test_empty_device(self) -> None:
        assert _is_ap({}) is False


# ---------------------------------------------------------------------------
# _extract_radio_field
# ---------------------------------------------------------------------------


class TestExtractRadioField:
    """Verify radio field extraction."""

    def test_extracts_channel_from_ng(self) -> None:
        radios = [{"radio": "ng", "channel": 6}, {"radio": "na", "channel": 36}]
        assert _extract_radio_field(radios, "ng", "channel") == 6

    def test_extracts_channel_from_na(self) -> None:
        radios = [{"radio": "ng", "channel": 6}, {"radio": "na", "channel": 36}]
        assert _extract_radio_field(radios, "na", "channel") == 36

    def test_missing_band_returns_none(self) -> None:
        radios = [{"radio": "ng", "channel": 6}]
        assert _extract_radio_field(radios, "na", "channel") is None

    def test_empty_radio_table(self) -> None:
        assert _extract_radio_field([], "ng", "channel") is None


# ---------------------------------------------------------------------------
# _extract_radio_utilization
# ---------------------------------------------------------------------------


class TestExtractRadioUtilization:
    """Verify radio utilization extraction."""

    def test_extracts_utilization(self) -> None:
        radio_table = [{"radio": "ng", "channel": 6, "name": "radio0"}]
        stats = [{"radio": "ng", "cu_total": 45, "cu_self_rx": 12}]

        result = _extract_radio_utilization(radio_table, stats, "ng")

        assert result is not None
        assert result["channel"] == 6
        assert result["utilization_pct"] == 45
        assert result["interference_pct"] == 12

    def test_missing_band_returns_none(self) -> None:
        radio_table = [{"radio": "ng", "channel": 6}]
        stats = [{"radio": "ng", "cu_total": 45}]

        result = _extract_radio_utilization(radio_table, stats, "na")

        assert result is None

    def test_empty_tables(self) -> None:
        assert _extract_radio_utilization([], [], "ng") is None

    def test_fallback_channel_utilization_field(self) -> None:
        radio_table = [{"radio": "na", "channel": 36, "name": "radio1"}]
        stats = [{"radio": "na", "channel_utilization": 30}]

        result = _extract_radio_utilization(radio_table, stats, "na")

        assert result is not None
        assert result["utilization_pct"] == 30


# ---------------------------------------------------------------------------
# _compute_snr
# ---------------------------------------------------------------------------


class TestComputeSnr:
    """Verify SNR computation."""

    def test_normal_values(self) -> None:
        assert _compute_snr(-50, -90) == 40

    def test_none_rssi(self) -> None:
        assert _compute_snr(None, -90) is None

    def test_none_noise(self) -> None:
        assert _compute_snr(-50, None) is None

    def test_both_none(self) -> None:
        assert _compute_snr(None, None) is None

    def test_invalid_type(self) -> None:
        assert _compute_snr("bad", -90) is None


# ---------------------------------------------------------------------------
# _is_roam_event
# ---------------------------------------------------------------------------


class TestIsRoamEvent:
    """Verify roaming event detection."""

    def test_roam_event(self) -> None:
        assert _is_roam_event({"key": "EVT_WU_Roam"}) is True

    def test_roam_radio_event(self) -> None:
        assert _is_roam_event({"key": "EVT_WU_RoamRadio"}) is True

    def test_wc_roam_event(self) -> None:
        assert _is_roam_event({"key": "EVT_WC_Roam"}) is True

    def test_non_roam_event(self) -> None:
        assert _is_roam_event({"key": "EVT_WU_Connected"}) is False

    def test_key_with_roam_substring(self) -> None:
        assert _is_roam_event({"key": "EVT_CUSTOM_roam_event"}) is True

    def test_empty_key(self) -> None:
        assert _is_roam_event({"key": ""}) is False

    def test_missing_key(self) -> None:
        assert _is_roam_event({}) is False


# ---------------------------------------------------------------------------
# Tool 1: unifi__wifi__get_wlans
# ---------------------------------------------------------------------------


class TestGetWlans:
    """Tests for the get_wlans MCP tool."""

    async def test_returns_wlan_list(self) -> None:
        wlan_data = [
            {
                "_id": "wlan001",
                "name": "HomeNetwork",
                "security": "wpapsk",
                "wlan_band": "both",
                "networkconf_id": "net001",
                "enabled": True,
                "num_sta": 12,
                "satisfaction": 95,
            },
            {
                "_id": "wlan002",
                "name": "GuestWiFi",
                "security": "wpapsk",
                "wlan_band": "both",
                "networkconf_id": "net002",
                "enabled": True,
                "num_sta": 3,
            },
        ]
        mock = _mock_client_normalized(wlan_data)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_wlans()

        assert len(result) == 2
        assert result[0]["wlan_id"] == "wlan001"
        assert result[0]["ssid"] == "HomeNetwork"
        assert result[0]["security"] == "wpapsk"
        assert result[0]["client_count"] == 12
        assert result[0]["satisfaction"] == 95
        assert result[1]["client_count"] == 3
        mock.get_normalized.assert_called_once_with("/api/s/default/rest/wlanconf")
        mock.close.assert_called_once()

    async def test_custom_site_id(self) -> None:
        mock = _mock_client_normalized([])

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            await unifi__wifi__get_wlans(site_id="remote")

        mock.get_normalized.assert_called_once_with("/api/s/remote/rest/wlanconf")

    async def test_empty_wlan_list(self) -> None:
        mock = _mock_client_normalized([])

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_wlans()

        assert result == []

    async def test_defaults_for_missing_fields(self) -> None:
        wlan_data = [{"_id": "wlan003"}]
        mock = _mock_client_normalized(wlan_data)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_wlans()

        assert result[0]["security"] == "open"
        assert result[0]["band"] == "both"
        assert result[0]["enabled"] is True
        assert result[0]["client_count"] == 0

    async def test_api_error_propagates(self) -> None:
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(
            side_effect=APIError("Server error", status_code=500)
        )
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.wifi._get_client", return_value=mock),
            pytest.raises(APIError, match="Server error"),
        ):
            await unifi__wifi__get_wlans()

        mock.close.assert_called_once()

    async def test_client_closed_on_error(self) -> None:
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(side_effect=NetworkError("Timeout"))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.wifi._get_client", return_value=mock),
            pytest.raises(NetworkError),
        ):
            await unifi__wifi__get_wlans()

        mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool 2: unifi__wifi__get_aps
# ---------------------------------------------------------------------------


class TestGetAps:
    """Tests for the get_aps MCP tool."""

    def _make_ap(
        self,
        device_id: str = "ap001",
        name: str = "Office-AP",
        mac: str = "aa:bb:cc:dd:ee:01",
    ) -> dict[str, Any]:
        return {
            "_id": device_id,
            "type": "uap",
            "name": name,
            "mac": mac,
            "model": "U6-Pro",
            "radio_table": [
                {"radio": "ng", "channel": 6, "tx_power": 20},
                {"radio": "na", "channel": 36, "tx_power": 23},
            ],
            "num_sta": 8,
            "satisfaction": 92,
        }

    async def test_returns_ap_list(self) -> None:
        devices = [
            self._make_ap(),
            {"_id": "sw001", "type": "usw", "model": "USW-24", "name": "Switch"},
        ]
        mock = _mock_client_normalized(devices)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_aps()

        assert len(result) == 1
        assert result[0]["ap_id"] == "ap001"
        assert result[0]["name"] == "Office-AP"
        assert result[0]["channel_2g"] == 6
        assert result[0]["channel_5g"] == 36
        assert result[0]["tx_power_2g"] == 20
        assert result[0]["tx_power_5g"] == 23
        assert result[0]["client_count"] == 8
        assert result[0]["satisfaction"] == 92

    async def test_filters_non_aps(self) -> None:
        devices = [
            {"_id": "gw001", "type": "ugw", "model": "UXG-Max", "name": "Gateway"},
            {"_id": "sw001", "type": "usw", "model": "USW-24", "name": "Switch"},
        ]
        mock = _mock_client_normalized(devices)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_aps()

        assert result == []

    async def test_custom_site_id(self) -> None:
        mock = _mock_client_normalized([])

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            await unifi__wifi__get_aps(site_id="branch")

        mock.get_normalized.assert_called_once_with("/api/s/branch/stat/device")

    async def test_ap_without_radio_table(self) -> None:
        devices = [{"_id": "ap002", "type": "uap", "model": "U6-LR", "name": "Bare-AP", "mac": "11:22:33:44:55:66"}]
        mock = _mock_client_normalized(devices)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_aps()

        assert len(result) == 1
        assert result[0]["channel_2g"] is None
        assert result[0]["channel_5g"] is None

    async def test_empty_device_list(self) -> None:
        mock = _mock_client_normalized([])

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_aps()

        assert result == []

    async def test_api_error_propagates(self) -> None:
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(side_effect=APIError("Fail", status_code=500))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.wifi._get_client", return_value=mock),
            pytest.raises(APIError),
        ):
            await unifi__wifi__get_aps()

        mock.close.assert_called_once()

    async def test_multiple_aps(self) -> None:
        devices = [
            self._make_ap("ap001", "AP-1", "aa:bb:cc:dd:ee:01"),
            self._make_ap("ap002", "AP-2", "aa:bb:cc:dd:ee:02"),
            self._make_ap("ap003", "AP-3", "aa:bb:cc:dd:ee:03"),
        ]
        mock = _mock_client_normalized(devices)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_aps()

        assert len(result) == 3
        assert [r["name"] for r in result] == ["AP-1", "AP-2", "AP-3"]


# ---------------------------------------------------------------------------
# Tool 3: unifi__wifi__get_channel_utilization
# ---------------------------------------------------------------------------


class TestGetChannelUtilization:
    """Tests for the get_channel_utilization MCP tool."""

    async def test_returns_utilization(self) -> None:
        raw = {
            "_id": "ap001",
            "radio_table": [
                {"radio": "ng", "channel": 6, "name": "radio0"},
                {"radio": "na", "channel": 36, "name": "radio1"},
            ],
            "radio_table_stats": [
                {"radio": "ng", "cu_total": 35, "cu_self_rx": 10},
                {"radio": "na", "cu_total": 15, "cu_self_rx": 3},
            ],
        }
        mock = _mock_client_single(raw)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_channel_utilization(ap_id="aa:bb:cc:dd:ee:01")

        assert result["ap_id"] == "ap001"
        assert result["radio_2g"]["channel"] == 6
        assert result["radio_2g"]["utilization_pct"] == 35
        assert result["radio_2g"]["interference_pct"] == 10
        assert result["radio_5g"]["channel"] == 36
        assert result["radio_5g"]["utilization_pct"] == 15

    async def test_custom_site_id(self) -> None:
        raw = {"_id": "ap001", "radio_table": [], "radio_table_stats": []}
        mock = _mock_client_single(raw)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            await unifi__wifi__get_channel_utilization(ap_id="mac1", site_id="site2")

        mock.get_single.assert_called_once_with("/api/s/site2/stat/device/mac1")

    async def test_no_radio_tables(self) -> None:
        raw = {"_id": "ap002"}
        mock = _mock_client_single(raw)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_channel_utilization(ap_id="mac2")

        assert result["radio_2g"] is None
        assert result["radio_5g"] is None
        assert result["radio_6g"] is None

    async def test_api_error_propagates(self) -> None:
        mock = AsyncMock()
        mock.get_single = AsyncMock(side_effect=APIError("Not found", status_code=404))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.wifi._get_client", return_value=mock),
            pytest.raises(APIError, match="Not found"),
        ):
            await unifi__wifi__get_channel_utilization(ap_id="bad-mac")

        mock.close.assert_called_once()

    async def test_client_closed_on_success(self) -> None:
        raw = {"_id": "ap003", "radio_table": [], "radio_table_stats": []}
        mock = _mock_client_single(raw)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            await unifi__wifi__get_channel_utilization(ap_id="mac3")

        mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool 4: unifi__wifi__get_rf_scan
# ---------------------------------------------------------------------------


class TestGetRfScan:
    """Tests for the get_rf_scan MCP tool."""

    async def test_returns_neighbors(self) -> None:
        rogue_data = [
            {
                "ap_mac": "aa:bb:cc:dd:ee:01",
                "essid": "Neighbor-WiFi",
                "bssid": "ff:ee:dd:cc:bb:aa",
                "channel": 6,
                "band": "2.4 GHz",
                "rssi": -65,
                "security": "wpapsk",
                "is_ubnt": False,
            },
            {
                "ap_mac": "aa:bb:cc:dd:ee:01",
                "essid": "OwnNetwork",
                "bssid": "11:22:33:44:55:66",
                "channel": 36,
                "band": "5 GHz",
                "rssi": -30,
                "security": "wpapsk",
                "is_ubnt": True,
            },
        ]
        mock = _mock_client_normalized(rogue_data)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_rf_scan(ap_id="aa:bb:cc:dd:ee:01")

        assert len(result) == 2
        assert result[0]["ssid"] == "Neighbor-WiFi"
        assert result[0]["is_own"] is False
        assert result[1]["ssid"] == "OwnNetwork"
        assert result[1]["is_own"] is True

    async def test_filters_by_ap_mac(self) -> None:
        rogue_data = [
            {"ap_mac": "aa:bb:cc:dd:ee:01", "essid": "Mine", "bssid": "1"},
            {"ap_mac": "aa:bb:cc:dd:ee:02", "essid": "Other", "bssid": "2"},
        ]
        mock = _mock_client_normalized(rogue_data)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_rf_scan(ap_id="aa:bb:cc:dd:ee:01")

        assert len(result) == 1
        assert result[0]["ssid"] == "Mine"

    async def test_includes_entries_without_ap_mac(self) -> None:
        rogue_data = [
            {"essid": "NoApMac", "bssid": "11:22:33:44:55:66"},
        ]
        mock = _mock_client_normalized(rogue_data)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_rf_scan(ap_id="any-mac")

        assert len(result) == 1

    async def test_empty_rogue_list(self) -> None:
        mock = _mock_client_normalized([])

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_rf_scan(ap_id="mac1")

        assert result == []

    async def test_custom_site_id(self) -> None:
        mock = _mock_client_normalized([])

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            await unifi__wifi__get_rf_scan(ap_id="mac1", site_id="branch")

        mock.get_normalized.assert_called_once_with("/api/s/branch/stat/rogueap")

    async def test_api_error_propagates(self) -> None:
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(side_effect=APIError("Fail", status_code=500))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.wifi._get_client", return_value=mock),
            pytest.raises(APIError),
        ):
            await unifi__wifi__get_rf_scan(ap_id="mac1")

        mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool 5: unifi__wifi__get_roaming_events
# ---------------------------------------------------------------------------


class TestGetRoamingEvents:
    """Tests for the get_roaming_events MCP tool."""

    def _make_roam_event(self, hours_ago: float = 0.5) -> dict[str, Any]:
        ts = (datetime.now(tz=UTC) - timedelta(hours=hours_ago)).isoformat()
        return {
            "key": "EVT_WU_Roam",
            "datetime": ts,
            "user": "aa:bb:cc:dd:ee:ff",
            "ap_from": "ap001",
            "ap_to": "ap002",
            "rssi_from": -65,
            "rssi_to": -50,
            "msg": "station roamed",
        }

    async def test_returns_roaming_events(self) -> None:
        events = [self._make_roam_event()]
        mock = _mock_client_normalized(events)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_roaming_events()

        assert len(result) == 1
        assert result[0]["client_mac"] == "aa:bb:cc:dd:ee:ff"
        assert result[0]["from_ap_id"] == "ap001"
        assert result[0]["to_ap_id"] == "ap002"
        assert result[0]["rssi_before"] == -65
        assert result[0]["rssi_after"] == -50

    async def test_filters_non_roam_events(self) -> None:
        events = [
            self._make_roam_event(),
            {
                "key": "EVT_WU_Connected",
                "datetime": datetime.now(tz=UTC).isoformat(),
                "user": "11:22:33:44:55:66",
                "msg": "connected",
            },
        ]
        mock = _mock_client_normalized(events)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_roaming_events()

        assert len(result) == 1

    async def test_time_filtering(self) -> None:
        recent = self._make_roam_event(hours_ago=1)
        old = {
            "key": "EVT_WU_Roam",
            "datetime": (datetime.now(tz=UTC) - timedelta(hours=48)).isoformat(),
            "user": "aa:bb:cc:dd:ee:ff",
            "msg": "old roam",
        }
        mock = _mock_client_normalized([recent, old])

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_roaming_events(hours=24)

        assert len(result) == 1

    async def test_custom_hours(self) -> None:
        event_2h_ago = {
            "key": "EVT_WU_Roam",
            "datetime": (datetime.now(tz=UTC) - timedelta(hours=2)).isoformat(),
            "user": "aa:bb:cc:dd:ee:ff",
            "msg": "roam",
        }
        mock = _mock_client_normalized([event_2h_ago])

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result_4h = await unifi__wifi__get_roaming_events(hours=4)

        assert len(result_4h) == 1

        mock2 = _mock_client_normalized([event_2h_ago])
        with patch("unifi.tools.wifi._get_client", return_value=mock2):
            result_1h = await unifi__wifi__get_roaming_events(hours=1)

        assert len(result_1h) == 0

    async def test_empty_events(self) -> None:
        mock = _mock_client_normalized([])

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_roaming_events()

        assert result == []

    async def test_custom_site_id(self) -> None:
        mock = _mock_client_normalized([])

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            await unifi__wifi__get_roaming_events(site_id="campus")

        mock.get_normalized.assert_called_once_with("/api/s/campus/stat/event")

    async def test_epoch_timestamp_supported(self) -> None:
        event = {
            "key": "EVT_WU_Roam",
            "datetime": datetime.now(tz=UTC).timestamp(),
            "user": "aa:bb:cc:dd:ee:ff",
            "msg": "roam",
        }
        mock = _mock_client_normalized([event])

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_roaming_events()

        assert len(result) == 1

    async def test_invalid_datetime_skipped(self) -> None:
        event = {
            "key": "EVT_WU_Roam",
            "datetime": "not-a-date",
            "user": "aa:bb:cc:dd:ee:ff",
            "msg": "roam",
        }
        mock = _mock_client_normalized([event])

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_roaming_events()

        assert len(result) == 0

    async def test_api_error_propagates(self) -> None:
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(side_effect=APIError("Fail", status_code=500))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.wifi._get_client", return_value=mock),
            pytest.raises(APIError),
        ):
            await unifi__wifi__get_roaming_events()

        mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool 6: unifi__wifi__get_client_rf
# ---------------------------------------------------------------------------


class TestGetClientRf:
    """Tests for the get_client_rf MCP tool."""

    async def test_returns_rf_metrics(self) -> None:
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "ap_mac": "11:22:33:44:55:66",
            "essid": "HomeNetwork",
            "rssi": -55,
            "noise": -90,
            "tx_rate": 866,
            "rx_rate": 866,
            "tx_retries": 2,
            "channel": 36,
            "radio": "na",
        }
        mock = _mock_client_single(raw)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_client_rf(client_mac="aa:bb:cc:dd:ee:ff")

        assert result["client_mac"] == "aa:bb:cc:dd:ee:ff"
        assert result["ap_id"] == "11:22:33:44:55:66"
        assert result["ssid"] == "HomeNetwork"
        assert result["rssi"] == -55
        assert result["noise"] == -90
        assert result["snr"] == 35
        assert result["tx_rate_mbps"] == 866
        assert result["rx_rate_mbps"] == 866
        assert result["tx_retries_pct"] == 2
        assert result["channel"] == 36
        assert result["band"] == "na"

    async def test_custom_site_id(self) -> None:
        raw = {"mac": "aa:bb:cc:dd:ee:ff"}
        mock = _mock_client_single(raw)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            await unifi__wifi__get_client_rf(client_mac="aa:bb:cc:dd:ee:ff", site_id="remote")

        mock.get_single.assert_called_once_with(
            "/api/s/remote/stat/sta/aa:bb:cc:dd:ee:ff"
        )

    async def test_missing_noise_snr_is_none(self) -> None:
        raw = {"mac": "aa:bb:cc:dd:ee:ff", "rssi": -55}
        mock = _mock_client_single(raw)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            result = await unifi__wifi__get_client_rf(client_mac="aa:bb:cc:dd:ee:ff")

        assert result["rssi"] == -55
        assert result["noise"] is None
        assert result["snr"] is None

    async def test_api_error_propagates(self) -> None:
        mock = AsyncMock()
        mock.get_single = AsyncMock(side_effect=APIError("Not found", status_code=404))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.wifi._get_client", return_value=mock),
            pytest.raises(APIError, match="Not found"),
        ):
            await unifi__wifi__get_client_rf(client_mac="bad-mac")

        mock.close.assert_called_once()

    async def test_client_closed_on_success(self) -> None:
        raw = {"mac": "aa:bb:cc:dd:ee:ff"}
        mock = _mock_client_single(raw)

        with patch("unifi.tools.wifi._get_client", return_value=mock):
            await unifi__wifi__get_client_rf(client_mac="aa:bb:cc:dd:ee:ff")

        mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify all wifi tools are registered on the MCP server."""

    def test_get_wlans_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__wifi__get_wlans" in tool_names

    def test_get_aps_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__wifi__get_aps" in tool_names

    def test_get_channel_utilization_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__wifi__get_channel_utilization" in tool_names

    def test_get_rf_scan_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__wifi__get_rf_scan" in tool_names

    def test_get_roaming_events_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__wifi__get_roaming_events" in tool_names

    def test_get_client_rf_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__wifi__get_client_rf" in tool_names
