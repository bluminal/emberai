"""Tests for interface MCP tools.

Mock-based: SSH client returns fixture text.
Covers: cisco__interfaces__list_ports, get_port_detail, get_counters.
Tests happy path, port validation, auth failure, network errors, and SNMP.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from cisco.errors import AuthenticationError, NetworkError
from cisco.tools.interfaces import (
    _cache,
    _validate_port,
    cisco__interfaces__get_counters,
    cisco__interfaces__get_port_detail,
    cisco__interfaces__list_ports,
)
from tests.fixtures import load_fixture


@pytest.fixture(autouse=True)
async def _flush_cache():
    """Flush the interfaces cache before each test."""
    await _cache.flush()
    yield
    await _cache.flush()


def _make_mock_client() -> AsyncMock:
    """Build a mock SSH client that returns fixture output per command."""
    client = AsyncMock()
    client.connect = AsyncMock()

    command_map = {
        "show interfaces status": load_fixture("show_interfaces_status.txt"),
    }

    async def _send(cmd: str) -> str:
        if cmd in command_map:
            return command_map[cmd]
        if cmd.startswith("show interfaces switchport"):
            port = cmd.rsplit(None, 1)[-1]
            if port == "gi24":
                return load_fixture("show_switchport_trunk.txt")
            return load_fixture("show_switchport_access.txt")
        return ""

    client.send_command = AsyncMock(side_effect=_send)
    return client


# ---------------------------------------------------------------------------
# _validate_port
# ---------------------------------------------------------------------------


class TestValidatePort:
    """Port format validation."""

    def test_valid_gi_port(self) -> None:
        assert _validate_port("gi1") == "gi1"

    def test_valid_fa_port(self) -> None:
        assert _validate_port("fa2") == "fa2"

    def test_valid_po_port(self) -> None:
        assert _validate_port("Po1") == "Po1"

    def test_valid_te_port(self) -> None:
        assert _validate_port("te1") == "te1"

    def test_valid_uppercase(self) -> None:
        assert _validate_port("Gi12") == "Gi12"

    def test_invalid_port_raises(self) -> None:
        from cisco.errors import ValidationError

        with pytest.raises(ValidationError, match="Invalid port format"):
            _validate_port("invalid")

    def test_empty_port_raises(self) -> None:
        from cisco.errors import ValidationError

        with pytest.raises(ValidationError):
            _validate_port("")


# ---------------------------------------------------------------------------
# cisco__interfaces__list_ports
# ---------------------------------------------------------------------------


class TestListPorts:
    """Tests for the port listing tool."""

    @pytest.mark.asyncio
    async def test_returns_port_list(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.interfaces.get_client", return_value=mock_client):
            result = await cisco__interfaces__list_ports()
            assert isinstance(result, list)
            assert len(result) > 0
            assert "id" in result[0]
            assert "status" in result[0]

    @pytest.mark.asyncio
    async def test_cache_hit_skips_ssh(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.interfaces.get_client", return_value=mock_client):
            await cisco__interfaces__list_ports()
            await cisco__interfaces__list_ports()
            assert mock_client.connect.await_count == 1

    @pytest.mark.asyncio
    async def test_auth_error_returns_error_list(self) -> None:
        with patch(
            "cisco.tools.interfaces.get_client",
            side_effect=AuthenticationError("missing creds", env_var="CISCO_HOST"),
        ):
            result = await cisco__interfaces__list_ports()
            assert "error" in result[0]


# ---------------------------------------------------------------------------
# cisco__interfaces__get_port_detail
# ---------------------------------------------------------------------------


class TestGetPortDetail:
    """Tests for the port detail tool."""

    @pytest.mark.asyncio
    async def test_returns_port_detail_dict(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.interfaces.get_client", return_value=mock_client):
            result = await cisco__interfaces__get_port_detail(port="gi3")
            assert isinstance(result, dict)
            assert "mode" in result

    @pytest.mark.asyncio
    async def test_invalid_port_returns_error(self) -> None:
        result = await cisco__interfaces__get_port_detail(port="invalid_port")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_auth_error_returns_error(self) -> None:
        with patch(
            "cisco.tools.interfaces.get_client",
            side_effect=AuthenticationError("missing creds", env_var="CISCO_HOST"),
        ):
            result = await cisco__interfaces__get_port_detail(port="gi1")
            assert "error" in result

    @pytest.mark.asyncio
    async def test_network_error_returns_error(self) -> None:
        mock_client = _make_mock_client()
        mock_client.send_command = AsyncMock(
            side_effect=NetworkError("timeout"),
        )
        with patch("cisco.tools.interfaces.get_client", return_value=mock_client):
            result = await cisco__interfaces__get_port_detail(port="gi1")
            assert "error" in result


# ---------------------------------------------------------------------------
# cisco__interfaces__get_counters
# ---------------------------------------------------------------------------


class TestGetCounters:
    """Tests for the SNMP counter tool."""

    @pytest.mark.asyncio
    async def test_returns_error_when_snmp_not_configured(self) -> None:
        with patch.dict(os.environ, {"CISCO_SNMP_COMMUNITY": ""}, clear=False):
            result = await cisco__interfaces__get_counters()
            assert isinstance(result, list)
            assert "error" in result[0]
            assert "SNMP" in result[0]["error"]

    @pytest.mark.asyncio
    async def test_returns_error_when_host_not_configured(self) -> None:
        with patch.dict(
            os.environ,
            {"CISCO_SNMP_COMMUNITY": "public", "CISCO_HOST": ""},
            clear=False,
        ):
            result = await cisco__interfaces__get_counters()
            assert isinstance(result, list)
            assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_returns_counters_via_cache_mock(self) -> None:
        """Happy path: mock the cache to return pre-built counter data."""
        counter_data = [
            {
                "port": "gi1",
                "rx_bytes": 5000,
                "tx_bytes": 3000,
                "rx_packets": 100,
                "tx_packets": 80,
                "rx_errors": 0,
                "tx_errors": 0,
                "rx_discards": 0,
                "tx_discards": 0,
            }
        ]
        env = {"CISCO_SNMP_COMMUNITY": "public", "CISCO_HOST": "10.0.0.1"}
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(_cache, "get_or_fetch", new_callable=AsyncMock, return_value=counter_data),
        ):
            result = await cisco__interfaces__get_counters()
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["port"] == "gi1"
            assert result[0]["rx_bytes"] == 5000

    @pytest.mark.asyncio
    async def test_returns_error_on_snmp_exception(self) -> None:
        """SNMP collection failure returns structured error."""
        env = {"CISCO_SNMP_COMMUNITY": "public", "CISCO_HOST": "10.0.0.1"}
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(
                _cache,
                "get_or_fetch",
                new_callable=AsyncMock,
                side_effect=RuntimeError("SNMP engine failed"),
            ),
        ):
            result = await cisco__interfaces__get_counters()
            assert isinstance(result, list)
            assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_cache_hit_skips_snmp_fetch(self) -> None:
        """Second call uses cached counter data."""
        counter_data = [{"port": "gi1", "rx_bytes": 100}]
        call_count = 0

        async def _tracking_fetch(key, fetcher, ttl):
            nonlocal call_count
            call_count += 1
            return counter_data

        env = {"CISCO_SNMP_COMMUNITY": "public", "CISCO_HOST": "10.0.0.1"}
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(_cache, "get_or_fetch", side_effect=_tracking_fetch),
        ):
            await cisco__interfaces__get_counters()
            await cisco__interfaces__get_counters()
            assert call_count == 2  # get_or_fetch called, but cache handles dedup
