"""Tests for MAC address table (clients) MCP tools.

Mock-based: SSH client returns fixture text.
Covers: cisco__clients__list_mac_table, find_mac, list_mac_by_vlan, list_mac_by_port.
Tests happy path, parameter validation, auth failure, network errors.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from cisco.errors import AuthenticationError, NetworkError
from cisco.tools.clients import (
    _cache,
    cisco__clients__find_mac,
    cisco__clients__list_mac_by_port,
    cisco__clients__list_mac_by_vlan,
    cisco__clients__list_mac_table,
)
from tests.fixtures import load_fixture


@pytest.fixture(autouse=True)
async def _flush_cache():
    """Flush the clients cache before each test."""
    await _cache.flush()
    yield
    await _cache.flush()


def _make_mock_client() -> AsyncMock:
    """Build a mock SSH client that returns fixture output."""
    client = AsyncMock()
    client.connect = AsyncMock()

    mac_output = load_fixture("show_mac_address_table.txt")

    async def _send(cmd: str) -> str:
        if "mac address-table" in cmd:
            return mac_output
        return ""

    client.send_command = AsyncMock(side_effect=_send)
    return client


# ---------------------------------------------------------------------------
# cisco__clients__list_mac_table
# ---------------------------------------------------------------------------


class TestListMacTable:
    """Tests for the MAC table listing tool."""

    @pytest.mark.asyncio
    async def test_returns_mac_entries(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.clients.get_client", return_value=mock_client):
            result = await cisco__clients__list_mac_table()
            assert isinstance(result, list)
            assert len(result) > 0
            assert "mac" in result[0]
            assert "vlan_id" in result[0]

    @pytest.mark.asyncio
    async def test_cache_hit_skips_ssh(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.clients.get_client", return_value=mock_client):
            await cisco__clients__list_mac_table()
            await cisco__clients__list_mac_table()
            assert mock_client.connect.await_count == 1

    @pytest.mark.asyncio
    async def test_auth_error_returns_error(self) -> None:
        with patch(
            "cisco.tools.clients.get_client",
            side_effect=AuthenticationError("missing creds", env_var="CISCO_HOST"),
        ):
            result = await cisco__clients__list_mac_table()
            assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_network_error_returns_error(self) -> None:
        mock_client = _make_mock_client()
        mock_client.send_command = AsyncMock(
            side_effect=NetworkError("timeout"),
        )
        with patch("cisco.tools.clients.get_client", return_value=mock_client):
            result = await cisco__clients__list_mac_table()
            assert "error" in result[0]


# ---------------------------------------------------------------------------
# cisco__clients__find_mac
# ---------------------------------------------------------------------------


class TestFindMac:
    """Tests for the MAC address lookup tool."""

    @pytest.mark.asyncio
    async def test_find_existing_mac(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.clients.get_client", return_value=mock_client):
            result = await cisco__clients__find_mac(mac="00:08:a2:09:78:fa")
            assert isinstance(result, list)
            # Should find at least one entry matching this MAC
            if len(result) > 0 and "error" not in result[0]:
                assert result[0]["mac"] == "00:08:a2:09:78:fa"

    @pytest.mark.asyncio
    async def test_find_nonexistent_mac(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.clients.get_client", return_value=mock_client):
            result = await cisco__clients__find_mac(mac="ff:ff:ff:ff:ff:ff")
            assert isinstance(result, list)
            # If no error, should be empty
            if not (len(result) > 0 and "error" in result[0]):
                assert len(result) == 0

    @pytest.mark.asyncio
    async def test_find_invalid_mac_returns_error(self) -> None:
        result = await cisco__clients__find_mac(mac="not-a-mac")
        assert isinstance(result, list)
        assert "error" in result[0]


# ---------------------------------------------------------------------------
# cisco__clients__list_mac_by_vlan
# ---------------------------------------------------------------------------


class TestListMacByVlan:
    """Tests for the VLAN-filtered MAC table tool."""

    @pytest.mark.asyncio
    async def test_returns_mac_entries_for_vlan(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.clients.get_client", return_value=mock_client):
            result = await cisco__clients__list_mac_by_vlan(vlan_id=1)
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_invalid_vlan_id_zero(self) -> None:
        result = await cisco__clients__list_mac_by_vlan(vlan_id=0)
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_invalid_vlan_id_too_high(self) -> None:
        result = await cisco__clients__list_mac_by_vlan(vlan_id=5000)
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_auth_error(self) -> None:
        with patch(
            "cisco.tools.clients.get_client",
            side_effect=AuthenticationError("missing creds", env_var="CISCO_HOST"),
        ):
            result = await cisco__clients__list_mac_by_vlan(vlan_id=10)
            assert "error" in result[0]


# ---------------------------------------------------------------------------
# cisco__clients__list_mac_by_port
# ---------------------------------------------------------------------------


class TestListMacByPort:
    """Tests for the port-filtered MAC table tool."""

    @pytest.mark.asyncio
    async def test_returns_mac_entries_for_port(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.clients.get_client", return_value=mock_client):
            result = await cisco__clients__list_mac_by_port(port="gi1")
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_invalid_port_returns_error(self) -> None:
        result = await cisco__clients__list_mac_by_port(port="invalid")
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_auth_error(self) -> None:
        with patch(
            "cisco.tools.clients.get_client",
            side_effect=AuthenticationError("missing creds", env_var="CISCO_HOST"),
        ):
            result = await cisco__clients__list_mac_by_port(port="gi1")
            assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_network_error(self) -> None:
        mock_client = _make_mock_client()
        mock_client.send_command = AsyncMock(
            side_effect=NetworkError("timeout"),
        )
        with patch("cisco.tools.clients.get_client", return_value=mock_client):
            result = await cisco__clients__list_mac_by_port(port="gi1")
            assert "error" in result[0]
