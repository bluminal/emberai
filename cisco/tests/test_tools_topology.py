"""Tests for topology MCP tools.

Mock-based: SSH client returns fixture text, parsers produce models.
Covers: cisco__topology__get_device_info, list_vlans, get_lldp_neighbors.
Tests happy path, cache integration, auth failure, and network errors.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from cisco.errors import AuthenticationError, NetworkError
from cisco.tools.topology import (
    _cache,
    cisco__topology__get_device_info,
    cisco__topology__get_lldp_neighbors,
    cisco__topology__list_vlans,
)
from tests.fixtures import load_fixture


@pytest.fixture(autouse=True)
async def _flush_cache():
    """Flush the topology cache before each test."""
    await _cache.flush()
    yield
    await _cache.flush()


def _make_mock_client() -> AsyncMock:
    """Build a mock SSH client that returns fixture output per command."""
    client = AsyncMock()
    client.connect = AsyncMock()

    command_map = {
        "show version": load_fixture("show_version.txt"),
        "show running-config": load_fixture("show_running_config.txt"),
        "show vlan": load_fixture("show_vlan.txt"),
        "show lldp neighbors": load_fixture("show_lldp_neighbors.txt"),
    }

    async def _send(cmd: str) -> str:
        return command_map.get(cmd, "")

    client.send_command = AsyncMock(side_effect=_send)
    return client


# ---------------------------------------------------------------------------
# cisco__topology__get_device_info
# ---------------------------------------------------------------------------


class TestGetDeviceInfo:
    """Tests for the device info tool."""

    @pytest.mark.asyncio
    async def test_returns_device_info_dict(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.topology.get_client", return_value=mock_client):
            result = await cisco__topology__get_device_info()
            assert isinstance(result, dict)
            assert "firmware_version" in result
            assert "3.0.0.37" in result["firmware_version"]

    @pytest.mark.asyncio
    async def test_cache_hit_skips_ssh(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.topology.get_client", return_value=mock_client):
            result1 = await cisco__topology__get_device_info()
            result2 = await cisco__topology__get_device_info()
            assert result1 == result2
            # connect should only be called once (cached second time)
            assert mock_client.connect.await_count == 1

    @pytest.mark.asyncio
    async def test_auth_error_returns_error_dict(self) -> None:
        with patch(
            "cisco.tools.topology.get_client",
            side_effect=AuthenticationError("missing creds", env_var="CISCO_HOST"),
        ):
            result = await cisco__topology__get_device_info()
            assert "error" in result

    @pytest.mark.asyncio
    async def test_network_error_returns_error_dict(self) -> None:
        mock_client = _make_mock_client()
        mock_client.send_command = AsyncMock(
            side_effect=NetworkError("connection lost"),
        )
        with patch("cisco.tools.topology.get_client", return_value=mock_client):
            result = await cisco__topology__get_device_info()
            assert "error" in result


# ---------------------------------------------------------------------------
# cisco__topology__list_vlans
# ---------------------------------------------------------------------------


class TestListVlans:
    """Tests for the VLAN listing tool."""

    @pytest.mark.asyncio
    async def test_returns_vlan_list(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.topology.get_client", return_value=mock_client):
            result = await cisco__topology__list_vlans()
            assert isinstance(result, list)
            assert len(result) > 0
            # Check that each entry has expected keys
            assert "id" in result[0]
            assert "name" in result[0]

    @pytest.mark.asyncio
    async def test_cache_hit_skips_ssh(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.topology.get_client", return_value=mock_client):
            await cisco__topology__list_vlans()
            await cisco__topology__list_vlans()
            assert mock_client.connect.await_count == 1

    @pytest.mark.asyncio
    async def test_auth_error_returns_error_list(self) -> None:
        with patch(
            "cisco.tools.topology.get_client",
            side_effect=AuthenticationError("missing creds", env_var="CISCO_HOST"),
        ):
            result = await cisco__topology__list_vlans()
            assert isinstance(result, list)
            assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_network_error_returns_error_list(self) -> None:
        mock_client = _make_mock_client()
        mock_client.send_command = AsyncMock(
            side_effect=NetworkError("timeout"),
        )
        with patch("cisco.tools.topology.get_client", return_value=mock_client):
            result = await cisco__topology__list_vlans()
            assert isinstance(result, list)
            assert "error" in result[0]


# ---------------------------------------------------------------------------
# cisco__topology__get_lldp_neighbors
# ---------------------------------------------------------------------------


class TestGetLLDPNeighbors:
    """Tests for the LLDP neighbor tool."""

    @pytest.mark.asyncio
    async def test_returns_neighbor_list(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.topology.get_client", return_value=mock_client):
            result = await cisco__topology__get_lldp_neighbors()
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_neighbor_has_expected_keys(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.topology.get_client", return_value=mock_client):
            result = await cisco__topology__get_lldp_neighbors()
            if len(result) > 0:
                assert "local_port" in result[0]
                assert "remote_device" in result[0]

    @pytest.mark.asyncio
    async def test_cache_hit_skips_ssh(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.topology.get_client", return_value=mock_client):
            await cisco__topology__get_lldp_neighbors()
            await cisco__topology__get_lldp_neighbors()
            assert mock_client.connect.await_count == 1

    @pytest.mark.asyncio
    async def test_auth_error_returns_error_list(self) -> None:
        with patch(
            "cisco.tools.topology.get_client",
            side_effect=AuthenticationError("missing creds", env_var="CISCO_HOST"),
        ):
            result = await cisco__topology__get_lldp_neighbors()
            assert isinstance(result, list)
            assert "error" in result[0]
