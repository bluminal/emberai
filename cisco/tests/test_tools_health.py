"""Tests for health MCP tool.

Mock-based: SSH client returns fixture text.
Covers: cisco__health__get_status, _format_uptime.
Tests happy path, auth failure, network errors, and uptime formatting.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from cisco.errors import AuthenticationError, NetworkError
from cisco.tools.health import (
    _format_uptime,
    cisco__health__get_status,
)
from tests.fixtures import load_fixture


def _make_mock_client() -> AsyncMock:
    """Build a mock SSH client that returns fixture output."""
    client = AsyncMock()
    client.connect = AsyncMock()

    command_map = {
        "show version": load_fixture("show_version.txt"),
        "show running-config": load_fixture("show_running_config.txt"),
        "show interfaces status": load_fixture("show_interfaces_status.txt"),
        "show lldp neighbors": load_fixture("show_lldp_neighbors.txt"),
    }

    async def _send(cmd: str) -> str:
        return command_map.get(cmd, "")

    client.send_command = AsyncMock(side_effect=_send)
    return client


# ---------------------------------------------------------------------------
# _format_uptime
# ---------------------------------------------------------------------------


class TestFormatUptime:
    """Tests for the uptime formatting helper."""

    def test_zero_returns_unknown(self) -> None:
        assert "unknown" in _format_uptime(0)

    def test_negative_returns_unknown(self) -> None:
        assert "unknown" in _format_uptime(-100)

    def test_less_than_one_minute(self) -> None:
        assert _format_uptime(30) == "<1m"

    def test_minutes_only(self) -> None:
        assert _format_uptime(300) == "5m"

    def test_hours_and_minutes(self) -> None:
        assert _format_uptime(3720) == "1h 2m"

    def test_days_hours_minutes(self) -> None:
        assert _format_uptime(90120) == "1d 1h 2m"

    def test_days_only(self) -> None:
        assert _format_uptime(86400) == "1d"

    def test_large_uptime(self) -> None:
        # 30 days
        result = _format_uptime(30 * 86400)
        assert "30d" in result


# ---------------------------------------------------------------------------
# cisco__health__get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    """Tests for the health status tool."""

    @pytest.mark.asyncio
    async def test_returns_health_dict(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.health.get_client", return_value=mock_client):
            result = await cisco__health__get_status()
            assert isinstance(result, dict)
            assert "device_info" in result
            assert "ports" in result
            assert "lldp_neighbor_count" in result
            assert "summary" in result

    @pytest.mark.asyncio
    async def test_ports_summary_has_counts(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.health.get_client", return_value=mock_client):
            result = await cisco__health__get_status()
            ports = result["ports"]
            assert "total" in ports
            assert "up" in ports
            assert "down" in ports
            assert ports["total"] == ports["up"] + ports["down"]

    @pytest.mark.asyncio
    async def test_summary_is_markdown(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.health.get_client", return_value=mock_client):
            result = await cisco__health__get_status()
            assert "##" in result["summary"]

    @pytest.mark.asyncio
    async def test_auth_error_returns_error(self) -> None:
        with patch(
            "cisco.tools.health.get_client",
            side_effect=AuthenticationError("missing creds", env_var="CISCO_HOST"),
        ):
            result = await cisco__health__get_status()
            assert "error" in result

    @pytest.mark.asyncio
    async def test_network_error_returns_error(self) -> None:
        mock_client = _make_mock_client()
        mock_client.send_command = AsyncMock(
            side_effect=NetworkError("connection lost"),
        )
        with patch("cisco.tools.health.get_client", return_value=mock_client):
            result = await cisco__health__get_status()
            assert "error" in result
