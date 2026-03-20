"""Tests for the Traffic MCP tools (bandwidth, DPI, port stats, WAN usage)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, NetworkError
from unifi.server import mcp_server
from unifi.tools.traffic import (
    _bytes_to_mbps,
    _get_client,
    unifi__traffic__get_bandwidth,
    unifi__traffic__get_dpi_stats,
    unifi__traffic__get_port_stats,
    unifi__traffic__get_wan_usage,
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
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "traffic-key-456")

        client = _get_client()

        assert client._host == "10.0.0.1"
        assert client._api_key == "traffic-key-456"

    def test_defaults_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNIFI_LOCAL_HOST", raising=False)
        monkeypatch.delenv("UNIFI_LOCAL_KEY", raising=False)

        client = _get_client()

        assert client._host == ""
        assert client._api_key == ""


# ---------------------------------------------------------------------------
# _bytes_to_mbps
# ---------------------------------------------------------------------------


class TestBytesToMbps:
    """Verify bytes/sec to Mbps conversion."""

    def test_zero(self) -> None:
        assert _bytes_to_mbps(0) == 0.0

    def test_one_megabyte_per_sec(self) -> None:
        # 1 MB/s = 8 Mbps
        assert _bytes_to_mbps(1_000_000) == 8.0

    def test_gigabit_rate(self) -> None:
        # 125 MB/s = 1000 Mbps (1 Gbps)
        assert _bytes_to_mbps(125_000_000) == 1000.0

    def test_float_input(self) -> None:
        result = _bytes_to_mbps(500_000.0)
        assert abs(result - 4.0) < 0.01


# ---------------------------------------------------------------------------
# Tool 1: unifi__traffic__get_bandwidth
# ---------------------------------------------------------------------------


class TestGetBandwidth:
    """Tests for the get_bandwidth MCP tool."""

    async def test_returns_bandwidth_data(self) -> None:
        health_data = [
            {"subsystem": "wan", "rx_bytes-r": 12_500_000, "tx_bytes-r": 2_500_000},
            {"subsystem": "lan", "rx_bytes-r": 25_000_000, "tx_bytes-r": 5_000_000},
        ]
        stat_data = [
            {
                "time": 1700000000,
                "wan-rx_bytes": 1_000_000_000,
                "wan-tx_bytes": 200_000_000,
                "lan-rx_bytes": 2_000_000_000,
                "lan-tx_bytes": 400_000_000,
            },
        ]

        mock = AsyncMock()
        mock.get_normalized = AsyncMock(
            side_effect=[_normalized(health_data), _normalized(stat_data)]
        )
        mock.close = AsyncMock()

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_bandwidth()

        assert result["wan"]["rx_mbps"] == 100.0
        assert result["wan"]["tx_mbps"] == 20.0
        assert result["lan"]["rx_mbps"] == 200.0
        assert result["lan"]["tx_mbps"] == 40.0
        assert len(result["wan"]["history"]) == 1

    async def test_custom_site_id(self) -> None:
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(
            side_effect=[_normalized([]), _normalized([])]
        )
        mock.close = AsyncMock()

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            await unifi__traffic__get_bandwidth(site_id="branch")

        calls = mock.get_normalized.call_args_list
        assert calls[0][0][0] == "/api/s/branch/stat/health"
        assert calls[1][0][0] == "/api/s/branch/stat/report/hourly.site"

    async def test_empty_health_data(self) -> None:
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(
            side_effect=[_normalized([]), _normalized([])]
        )
        mock.close = AsyncMock()

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_bandwidth()

        assert result["wan"]["rx_mbps"] == 0.0
        assert result["wan"]["tx_mbps"] == 0.0
        assert result["wan"]["history"] == []

    async def test_api_error_propagates(self) -> None:
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(
            side_effect=APIError("Server error", status_code=500)
        )
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.traffic._get_client", return_value=mock),
            pytest.raises(APIError, match="Server error"),
        ):
            await unifi__traffic__get_bandwidth()

        mock.close.assert_called_once()

    async def test_client_closed_on_error(self) -> None:
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(side_effect=NetworkError("Timeout"))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.traffic._get_client", return_value=mock),
            pytest.raises(NetworkError),
        ):
            await unifi__traffic__get_bandwidth()

        mock.close.assert_called_once()

    async def test_history_limited_by_hours(self) -> None:
        stat_data = [
            {"time": i, "wan-rx_bytes": 1000, "wan-tx_bytes": 500}
            for i in range(48)
        ]
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(
            side_effect=[_normalized([]), _normalized(stat_data)]
        )
        mock.close = AsyncMock()

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_bandwidth(hours=12)

        assert len(result["wan"]["history"]) == 12


# ---------------------------------------------------------------------------
# Tool 2: unifi__traffic__get_dpi_stats
# ---------------------------------------------------------------------------


class TestGetDpiStats:
    """Tests for the get_dpi_stats MCP tool."""

    async def test_returns_app_level_dpi(self) -> None:
        dpi_data = [
            {
                "by_app": [
                    {"app": "YouTube", "cat": "Streaming", "tx_bytes": 100, "rx_bytes": 5000, "clients": 3},
                    {"app": "Netflix", "cat": "Streaming", "tx_bytes": 50, "rx_bytes": 8000, "clients": 2},
                ],
            },
        ]
        mock = _mock_client_normalized(dpi_data)

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_dpi_stats()

        assert len(result) == 2
        assert result[0]["application"] == "YouTube"
        assert result[0]["category"] == "Streaming"
        assert result[0]["rx_bytes"] == 5000
        assert result[0]["session_count"] == 3
        assert result[1]["application"] == "Netflix"

    async def test_category_level_dpi(self) -> None:
        dpi_data = [
            {
                "by_cat": [
                    {"cat": "Social Media", "tx_bytes": 200, "rx_bytes": 3000, "clients": 5},
                ],
            },
        ]
        mock = _mock_client_normalized(dpi_data)

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_dpi_stats()

        assert len(result) == 1
        assert result[0]["category"] == "Social Media"
        assert result[0]["application"] == ""

    async def test_flat_dpi_format(self) -> None:
        dpi_data = [
            {"app": "Zoom", "cat": "Video", "tx_bytes": 300, "rx_bytes": 600, "clients": 1},
        ]
        mock = _mock_client_normalized(dpi_data)

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_dpi_stats()

        assert len(result) == 1
        assert result[0]["application"] == "Zoom"

    async def test_empty_dpi_data(self) -> None:
        mock = _mock_client_normalized([])

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_dpi_stats()

        assert result == []

    async def test_custom_site_id(self) -> None:
        mock = _mock_client_normalized([])

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            await unifi__traffic__get_dpi_stats(site_id="campus")

        mock.get_normalized.assert_called_once_with("/api/s/campus/stat/sitedpi")

    async def test_api_error_propagates(self) -> None:
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(side_effect=APIError("Fail", status_code=500))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.traffic._get_client", return_value=mock),
            pytest.raises(APIError),
        ):
            await unifi__traffic__get_dpi_stats()

        mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool 3: unifi__traffic__get_port_stats
# ---------------------------------------------------------------------------


class TestGetPortStats:
    """Tests for the get_port_stats MCP tool."""

    async def test_returns_port_list(self) -> None:
        raw = {
            "_id": "sw001",
            "port_table": [
                {
                    "port_idx": 1,
                    "name": "Port 1",
                    "tx_bytes": 1_000_000,
                    "rx_bytes": 2_000_000,
                    "tx_errors": 0,
                    "rx_errors": 0,
                    "is_uplink": True,
                    "poe_power": 12.5,
                },
                {
                    "port_idx": 2,
                    "name": "Port 2",
                    "tx_bytes": 500_000,
                    "rx_bytes": 750_000,
                    "tx_errors": 3,
                    "rx_errors": 1,
                    "is_uplink": False,
                },
            ],
        }
        mock = _mock_client_single(raw)

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_port_stats(device_id="74:ac:b9:bb:33:44")

        assert len(result) == 2
        assert result[0]["port_idx"] == 1
        assert result[0]["tx_bytes"] == 1_000_000
        assert result[0]["is_uplink"] is True
        assert result[0]["poe_power_w"] == 12.5
        assert result[1]["port_idx"] == 2
        assert result[1]["tx_errors"] == 3
        assert result[1]["poe_power_w"] is None

    async def test_custom_site_id(self) -> None:
        raw = {"_id": "sw001", "port_table": []}
        mock = _mock_client_single(raw)

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            await unifi__traffic__get_port_stats(device_id="mac1", site_id="remote")

        mock.get_single.assert_called_once_with("/api/s/remote/stat/device/mac1")

    async def test_no_port_table(self) -> None:
        raw = {"_id": "sw002"}
        mock = _mock_client_single(raw)

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_port_stats(device_id="mac2")

        assert result == []

    async def test_api_error_propagates(self) -> None:
        mock = AsyncMock()
        mock.get_single = AsyncMock(side_effect=APIError("Not found", status_code=404))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.traffic._get_client", return_value=mock),
            pytest.raises(APIError, match="Not found"),
        ):
            await unifi__traffic__get_port_stats(device_id="bad-mac")

        mock.close.assert_called_once()

    async def test_client_closed_on_success(self) -> None:
        raw = {"_id": "sw003", "port_table": []}
        mock = _mock_client_single(raw)

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            await unifi__traffic__get_port_stats(device_id="mac3")

        mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool 4: unifi__traffic__get_wan_usage
# ---------------------------------------------------------------------------


class TestGetWanUsage:
    """Tests for the get_wan_usage MCP tool."""

    async def test_returns_daily_usage(self) -> None:
        daily_data = [
            {"time": "2026-03-18", "wan-rx_bytes": 5_368_709_120, "wan-tx_bytes": 1_073_741_824},
            {"time": "2026-03-19", "wan-rx_bytes": 3_221_225_472, "wan-tx_bytes": 536_870_912},
        ]
        mock = _mock_client_normalized(daily_data)

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_wan_usage()

        assert len(result) == 2
        assert result[0]["date"] == "2026-03-18"
        assert result[0]["download_gb"] == 5.0
        assert result[0]["upload_gb"] == 1.0
        assert result[1]["download_gb"] == 3.0
        assert result[1]["upload_gb"] == 0.5

    async def test_custom_days(self) -> None:
        daily_data = [
            {"time": f"2026-03-{i:02d}", "wan-rx_bytes": 1_073_741_824, "wan-tx_bytes": 0}
            for i in range(1, 31)
        ]
        mock = _mock_client_normalized(daily_data)

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_wan_usage(days=7)

        assert len(result) == 7

    async def test_custom_site_id(self) -> None:
        mock = _mock_client_normalized([])

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            await unifi__traffic__get_wan_usage(site_id="office")

        mock.get_normalized.assert_called_once_with("/api/s/office/stat/report/daily.site")

    async def test_empty_daily_data(self) -> None:
        mock = _mock_client_normalized([])

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_wan_usage()

        assert result == []

    async def test_zero_bytes(self) -> None:
        daily_data = [{"time": "2026-03-19", "wan-rx_bytes": 0, "wan-tx_bytes": 0}]
        mock = _mock_client_normalized(daily_data)

        with patch("unifi.tools.traffic._get_client", return_value=mock):
            result = await unifi__traffic__get_wan_usage()

        assert result[0]["download_gb"] == 0.0
        assert result[0]["upload_gb"] == 0.0

    async def test_api_error_propagates(self) -> None:
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(side_effect=APIError("Fail", status_code=500))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.traffic._get_client", return_value=mock),
            pytest.raises(APIError),
        ):
            await unifi__traffic__get_wan_usage()

        mock.close.assert_called_once()

    async def test_client_closed_on_error(self) -> None:
        mock = AsyncMock()
        mock.get_normalized = AsyncMock(side_effect=NetworkError("Timeout"))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.traffic._get_client", return_value=mock),
            pytest.raises(NetworkError),
        ):
            await unifi__traffic__get_wan_usage()

        mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify all traffic tools are registered on the MCP server."""

    def test_get_bandwidth_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__traffic__get_bandwidth" in tool_names

    def test_get_dpi_stats_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__traffic__get_dpi_stats" in tool_names

    def test_get_port_stats_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__traffic__get_port_stats" in tool_names

    def test_get_wan_usage_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__traffic__get_wan_usage" in tool_names
