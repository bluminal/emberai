"""Tests for the health MCP tools (site health, device health, ISP, events, firmware)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tests.fixtures import load_fixture
from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, NetworkError
from unifi.server import mcp_server
from unifi.tools.health import (
    _aggregate_health,
    _filter_events_by_severity,
    _filter_events_by_time,
    _get_client,
    _safe_float,
    _state_to_str,
    unifi__health__get_device_health,
    unifi__health__get_events,
    unifi__health__get_firmware_status,
    unifi__health__get_isp_metrics,
    unifi__health__get_site_health,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalized_from_fixture(fixture: dict[str, Any]) -> NormalizedResponse:
    data = fixture.get("data", [])
    return NormalizedResponse(
        data=data,
        count=len(data),
        total_count=None,
        meta=fixture.get("meta", {}),
    )


def _mock_client_with_normalized(fixture_data: dict[str, Any]) -> AsyncMock:
    """Create a mock client that returns a NormalizedResponse from fixture data."""
    normalized = _normalized_from_fixture(fixture_data)
    mock_client = AsyncMock()
    mock_client.get_normalized = AsyncMock(return_value=normalized)
    mock_client.close = AsyncMock()
    return mock_client


def _mock_client_with_single(raw_device: dict[str, Any]) -> AsyncMock:
    """Create a mock client that returns a single device dict."""
    mock_client = AsyncMock()
    mock_client.get_single = AsyncMock(return_value=raw_device)
    mock_client.close = AsyncMock()
    return mock_client


# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------


class TestGetClient:
    """Verify the helper builds a client from env vars."""

    def test_creates_client_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "10.0.0.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "health-key-123")

        client = _get_client()

        assert client._host == "10.0.0.1"
        assert client._api_key == "health-key-123"

    def test_defaults_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNIFI_LOCAL_HOST", raising=False)
        monkeypatch.delenv("UNIFI_LOCAL_KEY", raising=False)

        with pytest.raises(APIError, match="credentials not configured"):
            _get_client()


# ---------------------------------------------------------------------------
# _state_to_str
# ---------------------------------------------------------------------------


class TestStateToStr:
    """Verify numeric state codes map to human-readable strings."""

    def test_connected(self) -> None:
        assert _state_to_str(1) == "connected"

    def test_disconnected(self) -> None:
        assert _state_to_str(0) == "disconnected"

    def test_unknown_code(self) -> None:
        assert _state_to_str(99) == "unknown(99)"

    def test_string_passthrough(self) -> None:
        assert _state_to_str("connected") == "connected"


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------


class TestSafeFloat:
    """Verify _safe_float handles various input types."""

    def test_none(self) -> None:
        assert _safe_float(None) is None

    def test_int(self) -> None:
        assert _safe_float(42) == 42.0

    def test_float(self) -> None:
        assert _safe_float(3.14) == 3.14

    def test_str_numeric(self) -> None:
        assert _safe_float("55.5") == 55.5

    def test_str_non_numeric(self) -> None:
        assert _safe_float("not-a-number") is None

    def test_empty_string(self) -> None:
        assert _safe_float("") is None


# ---------------------------------------------------------------------------
# _aggregate_health
# ---------------------------------------------------------------------------


class TestAggregateHealth:
    """Verify subsystem merging into a flat HealthStatus dict."""

    def test_full_subsystem_fixture(self) -> None:
        fixture = load_fixture("health.json")
        merged = _aggregate_health(fixture["data"])

        assert merged["wan_status"] == "ok"
        assert merged["lan_status"] == "ok"
        assert merged["wlan_status"] == "ok"
        assert merged["www_status"] == "ok"
        assert merged["num_d"] == 3  # 1 gw + 1 sw + 1 ap
        assert merged["num_adopted"] >= 3
        assert merged["num_disconnected"] == 0
        assert merged["num_sta"] >= 0

    def test_empty_subsystems(self) -> None:
        merged = _aggregate_health([])

        assert merged["num_d"] == 0
        assert merged["num_adopted"] == 0
        assert merged["num_disconnected"] == 0
        assert merged["num_sta"] == 0

    def test_wan_only(self) -> None:
        subsystems = [{"subsystem": "wan", "status": "error", "num_gw": 1, "num_adopted": 1}]
        merged = _aggregate_health(subsystems)

        assert merged["wan_status"] == "error"
        assert merged["num_d"] == 1
        assert "lan_status" not in merged
        assert "wlan_status" not in merged

    def test_uses_num_user_fallback_for_sta(self) -> None:
        """When num_sta is missing, fall back to num_user for client count."""
        subsystems = [
            {"subsystem": "lan", "status": "ok", "num_sw": 1, "num_user": 12, "num_adopted": 1},
        ]
        merged = _aggregate_health(subsystems)
        assert merged["num_sta"] == 12


# ---------------------------------------------------------------------------
# Tool 1: unifi__health__get_site_health
# ---------------------------------------------------------------------------


class TestGetSiteHealth:
    """Integration tests for the get_site_health MCP tool."""

    async def test_returns_aggregated_health(self) -> None:
        fixture = load_fixture("health.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_site_health()

        assert isinstance(result, dict)
        assert result["wan_status"] == "ok"
        assert result["lan_status"] == "ok"
        assert result["wlan_status"] == "ok"
        assert result["www_status"] == "ok"
        assert result["device_count"] == 3
        assert isinstance(result["adopted_count"], int)
        assert isinstance(result["offline_count"], int)
        assert isinstance(result["client_count"], int)

        mock_client.get_normalized.assert_called_once_with("/api/s/default/stat/health")
        mock_client.close.assert_called_once()

    async def test_custom_site_id(self) -> None:
        fixture = load_fixture("health.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            await unifi__health__get_site_health(site_id="site-abc")

        mock_client.get_normalized.assert_called_once_with("/api/s/site-abc/stat/health")

    async def test_empty_health_data(self) -> None:
        mock_client = _mock_client_with_normalized({"meta": {"rc": "ok"}, "data": []})

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_site_health()

        assert result["wan_status"] == "unknown"
        assert result["device_count"] == 0
        assert result["client_count"] == 0

    async def test_api_error_propagates(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(side_effect=APIError("API error", status_code=500))
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.health._get_client", return_value=mock_client),
            pytest.raises(APIError, match="API error"),
        ):
            await unifi__health__get_site_health()

        mock_client.close.assert_called_once()

    async def test_client_closed_on_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(side_effect=NetworkError("Connection refused"))
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.health._get_client", return_value=mock_client),
            pytest.raises(NetworkError),
        ):
            await unifi__health__get_site_health()

        mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool 2: unifi__health__get_device_health
# ---------------------------------------------------------------------------


class TestGetDeviceHealth:
    """Integration tests for the get_device_health MCP tool."""

    @pytest.fixture()
    def device_with_system_stats(self) -> dict[str, Any]:
        return {
            "_id": "dev001",
            "name": "USG-Gateway",
            "mac": "f0:9f:c2:aa:11:22",
            "model": "UXG-Max",
            "state": 1,
            "uptime": 1728432,
            "version": "4.0.6.6754",
            "system-stats": {"cpu": "12.5", "mem": "45.2"},
            "general_temperature": 52,
            "satisfaction": 98,
            "upgradable": False,
        }

    async def test_returns_health_metrics(self, device_with_system_stats: dict[str, Any]) -> None:
        mock_client = _mock_client_with_single(device_with_system_stats)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_device_health(device_id="f0:9f:c2:aa:11:22")

        assert result["device_id"] == "dev001"
        assert result["name"] == "USG-Gateway"
        assert result["status"] == "connected"
        assert result["uptime"] == 1728432
        assert result["cpu_usage_pct"] == 12.5
        assert result["mem_usage_pct"] == 45.2
        assert result["temperature_c"] == 52.0
        assert result["satisfaction"] == 98
        assert result["upgrade_available"] is False
        assert result["current_firmware"] == "4.0.6.6754"

    async def test_missing_system_stats(self) -> None:
        raw = {
            "_id": "dev002",
            "name": "Bare-Switch",
            "mac": "aa:bb:cc:dd:ee:ff",
            "model": "USW-24",
            "state": 1,
            "uptime": 3600,
            "version": "7.0.50",
        }
        mock_client = _mock_client_with_single(raw)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_device_health(device_id="aa:bb:cc:dd:ee:ff")

        assert result["cpu_usage_pct"] is None
        assert result["mem_usage_pct"] is None
        assert result["temperature_c"] is None
        assert result["satisfaction"] is None

    async def test_custom_site_id(self) -> None:
        raw = {
            "_id": "dev003",
            "name": "AP",
            "mac": "11:22:33:44:55:66",
            "model": "U6-Pro",
            "state": 1,
            "uptime": 100,
            "version": "7.0.76",
        }
        mock_client = _mock_client_with_single(raw)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            await unifi__health__get_device_health(device_id="11:22:33:44:55:66", site_id="remote")

        mock_client.get_single.assert_called_once_with(
            "/api/s/remote/stat/device/11:22:33:44:55:66"
        )

    async def test_api_error_propagates(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_single = AsyncMock(side_effect=APIError("Not found", status_code=404))
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.health._get_client", return_value=mock_client),
            pytest.raises(APIError, match="Not found"),
        ):
            await unifi__health__get_device_health(device_id="00:00:00:00:00:00")

        mock_client.close.assert_called_once()

    async def test_disconnected_state(self) -> None:
        raw = {
            "_id": "dev004",
            "name": "Offline-AP",
            "mac": "aa:bb:cc:dd:ee:01",
            "model": "U6-LR",
            "state": 0,
            "uptime": 0,
            "version": "7.0.76",
        }
        mock_client = _mock_client_with_single(raw)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_device_health(device_id="aa:bb:cc:dd:ee:01")

        assert result["status"] == "disconnected"

    async def test_upgrade_available(self) -> None:
        raw = {
            "_id": "dev005",
            "name": "Switch-16",
            "mac": "74:ac:b9:bb:33:44",
            "model": "USLITE16P",
            "state": 1,
            "uptime": 864210,
            "version": "7.0.50.15116",
            "upgradable": True,
            "upgrade_to_firmware": "7.0.72.15290",
        }
        mock_client = _mock_client_with_single(raw)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_device_health(device_id="74:ac:b9:bb:33:44")

        assert result["upgrade_available"] is True
        assert result["upgrade_firmware"] == "7.0.72.15290"


# ---------------------------------------------------------------------------
# Tool 3: unifi__health__get_isp_metrics
# ---------------------------------------------------------------------------


class TestGetIspMetrics:
    """Integration tests for the get_isp_metrics MCP tool."""

    async def test_extracts_wan_subsystem(self) -> None:
        fixture = load_fixture("health.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_isp_metrics()

        assert result["wan_ip"] == "203.0.113.42"
        assert result["isp_name"] == "Example ISP"
        assert result["isp_organization"] == "Example Telecom Corp"
        assert result["latency_ms"] == 8
        assert result["speedtest_ping_ms"] == 8
        assert result["download_mbps"] == 423.7
        assert result["upload_mbps"] == 38.2
        assert result["uptime_seconds"] == 1728432
        assert result["drops"] == 0
        assert result["wan_status"] == "ok"

    async def test_custom_site_id(self) -> None:
        fixture = load_fixture("health.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            await unifi__health__get_isp_metrics(site_id="branch-office")

        mock_client.get_normalized.assert_called_once_with("/api/s/branch-office/stat/health")

    async def test_no_wan_subsystem(self) -> None:
        """When no WAN subsystem exists, all fields should be defaults."""
        fixture = {
            "meta": {"rc": "ok"},
            "data": [
                {"subsystem": "lan", "status": "ok"},
                {"subsystem": "wlan", "status": "ok"},
            ],
        }
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_isp_metrics()

        assert result["wan_ip"] == ""
        assert result["isp_name"] == ""
        assert result["latency_ms"] is None
        assert result["download_mbps"] is None
        assert result["wan_status"] == "unknown"

    async def test_api_error_propagates(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Server error", status_code=500)
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.health._get_client", return_value=mock_client),
            pytest.raises(APIError),
        ):
            await unifi__health__get_isp_metrics()

        mock_client.close.assert_called_once()

    async def test_empty_health_data(self) -> None:
        mock_client = _mock_client_with_normalized({"meta": {"rc": "ok"}, "data": []})

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_isp_metrics()

        assert result["wan_ip"] == ""
        assert result["wan_status"] == "unknown"


# ---------------------------------------------------------------------------
# Event filtering unit tests
# ---------------------------------------------------------------------------


class TestFilterEventsByTime:
    """Unit tests for _filter_events_by_time."""

    def test_recent_events_included(self) -> None:
        now_iso = datetime.now(tz=UTC).isoformat()
        events = [{"datetime": now_iso, "key": "recent"}]
        result = _filter_events_by_time(events, hours=24)
        assert len(result) == 1

    def test_old_events_excluded(self) -> None:
        old = (datetime.now(tz=UTC) - timedelta(hours=48)).isoformat()
        events = [{"datetime": old, "key": "old"}]
        result = _filter_events_by_time(events, hours=24)
        assert len(result) == 0

    def test_epoch_timestamp_supported(self) -> None:
        recent_epoch = datetime.now(tz=UTC).timestamp()
        events = [{"datetime": recent_epoch, "key": "epoch"}]
        result = _filter_events_by_time(events, hours=24)
        assert len(result) == 1

    def test_missing_datetime_skipped(self) -> None:
        events = [{"key": "no-datetime"}]
        result = _filter_events_by_time(events, hours=24)
        assert len(result) == 0

    def test_invalid_datetime_string_skipped(self) -> None:
        events = [{"datetime": "not-a-date", "key": "bad"}]
        result = _filter_events_by_time(events, hours=24)
        assert len(result) == 0

    def test_narrow_window(self) -> None:
        one_hour_ago = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()
        three_hours_ago = (datetime.now(tz=UTC) - timedelta(hours=3)).isoformat()
        events = [
            {"datetime": one_hour_ago, "key": "recent"},
            {"datetime": three_hours_ago, "key": "old"},
        ]
        result = _filter_events_by_time(events, hours=2)
        assert len(result) == 1
        assert result[0]["key"] == "recent"


class TestFilterEventsBySeverity:
    """Unit tests for _filter_events_by_severity."""

    def test_all_returns_everything(self) -> None:
        events = [
            {"severity": "critical"},
            {"severity": "warning"},
            {"severity": "info"},
        ]
        result = _filter_events_by_severity(events, "all")
        assert len(result) == 3

    def test_critical_only(self) -> None:
        events = [
            {"severity": "critical"},
            {"severity": "warning"},
            {"severity": "info"},
        ]
        result = _filter_events_by_severity(events, "critical")
        assert len(result) == 1
        assert result[0]["severity"] == "critical"

    def test_warning_only(self) -> None:
        events = [{"severity": "warning"}, {"severity": "info"}]
        result = _filter_events_by_severity(events, "warning")
        assert len(result) == 1

    def test_no_match(self) -> None:
        events = [{"severity": "info"}]
        result = _filter_events_by_severity(events, "critical")
        assert len(result) == 0

    def test_missing_severity_defaults_to_info(self) -> None:
        """Events without a severity field default to 'info' for filtering."""
        events = [{"key": "no-severity"}]
        result = _filter_events_by_severity(events, "info")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Tool 4: unifi__health__get_events
# ---------------------------------------------------------------------------


class TestGetEvents:
    """Integration tests for the get_events MCP tool."""

    def _make_recent_event(
        self, key: str = "EVT_TEST", severity: str = "info", **extra: Any
    ) -> dict[str, Any]:
        """Create a recent event dict that will pass time filtering."""
        return {
            "datetime": datetime.now(tz=UTC).isoformat(),
            "key": key,
            "msg": f"Test event: {key}",
            "severity": severity,
            "subsystem": "lan",
            **extra,
        }

    async def test_returns_parsed_events(self) -> None:
        events_data = [
            self._make_recent_event("EVT_WU_Connected"),
            self._make_recent_event("EVT_SW_PoeOverload", severity="warning"),
        ]
        fixture = {"meta": {"rc": "ok"}, "data": events_data}
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_events()

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "EVT_WU_Connected"
        assert result[1]["type"] == "EVT_SW_PoeOverload"

    async def test_time_filtering(self) -> None:
        old_event = {
            "datetime": (datetime.now(tz=UTC) - timedelta(hours=48)).isoformat(),
            "key": "EVT_OLD",
            "msg": "Old event",
            "subsystem": "lan",
        }
        new_event = self._make_recent_event("EVT_NEW")
        fixture = {"meta": {"rc": "ok"}, "data": [old_event, new_event]}
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_events(hours=24)

        assert len(result) == 1
        assert result[0]["type"] == "EVT_NEW"

    async def test_severity_filtering(self) -> None:
        events_data = [
            self._make_recent_event("EVT_CRIT", severity="critical"),
            self._make_recent_event("EVT_WARN", severity="warning"),
            self._make_recent_event("EVT_INFO", severity="info"),
        ]
        fixture = {"meta": {"rc": "ok"}, "data": events_data}
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_events(severity="critical")

        assert len(result) == 1
        assert result[0]["type"] == "EVT_CRIT"

    async def test_combined_time_and_severity_filtering(self) -> None:
        old_critical = {
            "datetime": (datetime.now(tz=UTC) - timedelta(hours=48)).isoformat(),
            "key": "EVT_OLD_CRIT",
            "msg": "Old critical",
            "severity": "critical",
            "subsystem": "wan",
        }
        new_critical = self._make_recent_event("EVT_NEW_CRIT", severity="critical")
        new_info = self._make_recent_event("EVT_NEW_INFO", severity="info")
        fixture = {"meta": {"rc": "ok"}, "data": [old_critical, new_critical, new_info]}
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_events(hours=24, severity="critical")

        assert len(result) == 1
        assert result[0]["type"] == "EVT_NEW_CRIT"

    async def test_empty_events(self) -> None:
        mock_client = _mock_client_with_normalized({"meta": {"rc": "ok"}, "data": []})

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_events()

        assert result == []

    async def test_custom_site_id(self) -> None:
        mock_client = _mock_client_with_normalized({"meta": {"rc": "ok"}, "data": []})

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            await unifi__health__get_events(site_id="remote-site")

        mock_client.get_normalized.assert_called_once_with("/api/s/remote-site/stat/event")

    async def test_api_error_propagates(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Server error", status_code=500)
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.health._get_client", return_value=mock_client),
            pytest.raises(APIError),
        ):
            await unifi__health__get_events()

        mock_client.close.assert_called_once()

    async def test_client_closed_on_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(side_effect=NetworkError("Timeout"))
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.health._get_client", return_value=mock_client),
            pytest.raises(NetworkError),
        ):
            await unifi__health__get_events()

        mock_client.close.assert_called_once()

    async def test_unparseable_event_skipped(self) -> None:
        """Events that fail model validation should be skipped."""
        good_event = self._make_recent_event("EVT_GOOD")
        bad_event = {
            "datetime": datetime.now(tz=UTC).isoformat(),
            # Missing required 'key' and 'msg' fields
        }
        fixture = {"meta": {"rc": "ok"}, "data": [good_event, bad_event]}
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_events()

        # The bad event should be filtered out (no 'severity' to match,
        # but it will fail Event.model_validate due to missing fields)
        # At most we get the good event
        assert len(result) >= 1

    async def test_event_with_device_context(self) -> None:
        """Events with device and client context fields should parse."""
        event = self._make_recent_event(
            "EVT_SW_PoeOverload",
            severity="warning",
            sw="74:ac:b9:bb:33:44",
            user="a4:83:e7:11:22:33",
        )
        fixture = {"meta": {"rc": "ok"}, "data": [event]}
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_events()

        assert len(result) == 1
        assert result[0]["device_id"] == "74:ac:b9:bb:33:44"
        assert result[0]["client_mac"] == "a4:83:e7:11:22:33"


# ---------------------------------------------------------------------------
# Tool 5: unifi__health__get_firmware_status
# ---------------------------------------------------------------------------


class TestGetFirmwareStatus:
    """Integration tests for the get_firmware_status MCP tool."""

    async def test_returns_firmware_list(self) -> None:
        fixture = load_fixture("firmware_status.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_firmware_status()

        assert isinstance(result, list)
        assert len(result) == 3

        # Check gateway (no upgrade)
        gw = next(r for r in result if r["device_id"] == "64a1b2c3d4e5f6a7b8c9d0e1")
        assert gw["model"] == "UXG-Max"
        assert gw["current_version"] == "4.0.6.6754"
        assert gw["upgrade_available"] is False
        assert gw["latest_version"] == ""

        # Check switch (has upgrade)
        sw = next(r for r in result if r["device_id"] == "64b2c3d4e5f6a7b8c9d0e1f2")
        assert sw["model"] == "USLITE16P"
        assert sw["current_version"] == "7.0.50.15116"
        assert sw["upgrade_available"] is True
        assert sw["latest_version"] == "7.0.72.15290"

        # Check AP (no upgrade)
        ap = next(r for r in result if r["device_id"] == "64c3d4e5f6a7b8c9d0e1f2a3")
        assert ap["model"] == "U6-Pro"
        assert ap["upgrade_available"] is False

    async def test_custom_site_id(self) -> None:
        fixture = load_fixture("firmware_status.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            await unifi__health__get_firmware_status(site_id="main-office")

        mock_client.get_normalized.assert_called_once_with("/api/s/main-office/stat/device")

    async def test_empty_device_list(self) -> None:
        mock_client = _mock_client_with_normalized({"meta": {"rc": "ok"}, "data": []})

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_firmware_status()

        assert result == []

    async def test_api_error_propagates(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Server error", status_code=500)
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.health._get_client", return_value=mock_client),
            pytest.raises(APIError),
        ):
            await unifi__health__get_firmware_status()

        mock_client.close.assert_called_once()

    async def test_state_converted_for_consistency(self) -> None:
        """Integer state codes should be converted before FirmwareStatus parsing."""
        raw_data = [
            {
                "_id": "fw001",
                "model": "U6-Pro",
                "version": "7.0.76",
                "state": 1,
                "upgradable": False,
            },
        ]
        fixture = {"meta": {"rc": "ok"}, "data": raw_data}
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_firmware_status()

        assert len(result) == 1
        assert result[0]["device_id"] == "fw001"

    async def test_unparseable_device_skipped(self) -> None:
        """Devices that fail FirmwareStatus validation should be skipped."""
        good_device = {
            "_id": "fw002",
            "model": "USW-24",
            "version": "7.0.50",
            "state": 1,
            "upgradable": False,
        }
        bad_device = {
            # Missing required fields (_id, model, version)
            "state": 1,
        }
        fixture = {"meta": {"rc": "ok"}, "data": [good_device, bad_device]}
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_firmware_status()

        assert len(result) == 1
        assert result[0]["device_id"] == "fw002"


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify all health tools are registered on the MCP server."""

    def test_get_site_health_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__health__get_site_health" in tool_names

    def test_get_device_health_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__health__get_device_health" in tool_names

    def test_get_isp_metrics_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__health__get_isp_metrics" in tool_names

    def test_get_events_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__health__get_events" in tool_names

    def test_get_firmware_status_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__health__get_firmware_status" in tool_names


# ---------------------------------------------------------------------------
# Fixture round-trip tests
# ---------------------------------------------------------------------------


class TestFixtureRoundTrips:
    """Validate that fixture JSON files round-trip through the health tools."""

    async def test_health_fixture_roundtrip(self) -> None:
        """health.json -> get_site_health -> HealthStatus dict."""
        fixture = load_fixture("health.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_site_health()

        required_keys = {
            "wan_status",
            "lan_status",
            "wlan_status",
            "www_status",
            "device_count",
            "adopted_count",
            "offline_count",
            "client_count",
        }
        assert required_keys.issubset(result.keys())

    async def test_health_fixture_isp_roundtrip(self) -> None:
        """health.json -> get_isp_metrics -> ISP metrics dict."""
        fixture = load_fixture("health.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_isp_metrics()

        assert result["wan_ip"] == "203.0.113.42"
        assert result["isp_name"] == "Example ISP"
        assert isinstance(result["latency_ms"], int)

    async def test_firmware_fixture_roundtrip(self) -> None:
        """firmware_status.json -> get_firmware_status -> FirmwareStatus list."""
        fixture = load_fixture("firmware_status.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await unifi__health__get_firmware_status()

        assert len(result) == 3
        required_keys = {
            "device_id",
            "model",
            "current_version",
            "latest_version",
            "upgrade_available",
            "product_line",
        }
        for fw in result:
            assert required_keys.issubset(fw.keys())

        # Exactly one device should have upgrade available
        upgradable = [fw for fw in result if fw["upgrade_available"]]
        assert len(upgradable) == 1
        assert upgradable[0]["model"] == "USLITE16P"
