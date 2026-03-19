"""Tests for the topology MCP tools (list_devices)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, NetworkError
from unifi.server import mcp_server
from unifi.tools.topology import (
    _get_client,
    _state_to_str,
    unifi__topology__list_devices,
)

# ---------------------------------------------------------------------------
# _state_to_str unit tests
# ---------------------------------------------------------------------------


class TestStateToStr:
    """Verify numeric state codes map to human-readable strings."""

    def test_connected(self) -> None:
        assert _state_to_str(1) == "connected"

    def test_disconnected(self) -> None:
        assert _state_to_str(0) == "disconnected"

    def test_upgrading(self) -> None:
        assert _state_to_str(4) == "upgrading"

    def test_provisioning(self) -> None:
        assert _state_to_str(5) == "provisioning"

    def test_unknown_code(self) -> None:
        assert _state_to_str(99) == "unknown(99)"

    def test_string_passthrough(self) -> None:
        assert _state_to_str("connected") == "connected"

    def test_string_arbitrary(self) -> None:
        assert _state_to_str("custom_state") == "custom_state"


# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------


class TestGetClient:
    """Verify the helper builds a client from env vars."""

    def test_creates_client_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "test-key-123")

        client = _get_client()

        assert client._host == "192.168.1.1"
        assert client._api_key == "test-key-123"

    def test_defaults_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNIFI_LOCAL_HOST", raising=False)
        monkeypatch.delenv("UNIFI_LOCAL_KEY", raising=False)

        client = _get_client()

        assert client._host == ""
        assert client._api_key == ""


# ---------------------------------------------------------------------------
# unifi__topology__list_devices
# ---------------------------------------------------------------------------


class TestListDevices:
    """Integration tests for the list_devices MCP tool."""

    @pytest.fixture()
    def mock_normalized_response(
        self, device_list_response: dict[str, Any]
    ) -> NormalizedResponse:
        """Build a NormalizedResponse from the device_list fixture."""
        return NormalizedResponse(
            data=device_list_response["data"],
            count=len(device_list_response["data"]),
            meta=device_list_response["meta"],
        )

    async def test_returns_device_dicts(
        self,
        mock_normalized_response: NormalizedResponse,
    ) -> None:
        """Tool should return a list of dicts with Device model fields."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(return_value=mock_normalized_response)
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__list_devices(site_id="default")

        assert isinstance(result, list)
        assert len(result) == 3

        # Verify the client was called with the correct endpoint
        mock_client.get_normalized.assert_called_once_with("/api/s/default/stat/device")
        mock_client.close.assert_called_once()

    async def test_device_fields_correct(
        self,
        mock_normalized_response: NormalizedResponse,
    ) -> None:
        """Each device dict should contain the expected fields with correct values."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(return_value=mock_normalized_response)
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__list_devices()

        # Check gateway (first device)
        gateway = result[0]
        assert gateway["device_id"] == "64a1b2c3d4e5f6a7b8c9d0e1"
        assert gateway["name"] == "USG-Gateway"
        assert gateway["model"] == "UXG-Max"
        assert gateway["mac"] == "f0:9f:c2:aa:11:22"
        assert gateway["ip"] == "192.168.1.1"
        assert gateway["status"] == "connected"
        assert gateway["uptime"] == 1728432
        assert gateway["firmware"] == "4.0.6.6754"

        # Check switch (second device)
        switch = result[1]
        assert switch["device_id"] == "64b2c3d4e5f6a7b8c9d0e1f2"
        assert switch["name"] == "Office-Switch-16"
        assert switch["model"] == "USLITE16P"
        assert switch["status"] == "connected"

        # Check AP (third device)
        ap = result[2]
        assert ap["device_id"] == "64c3d4e5f6a7b8c9d0e1f2a3"
        assert ap["name"] == "Office-AP-Main"
        assert ap["model"] == "U6-Pro"
        assert ap["status"] == "connected"

    async def test_state_int_converted_to_str(
        self,
    ) -> None:
        """Integer state codes from the API must be converted to strings."""
        raw_data = [
            {
                "_id": "abc123",
                "mac": "aa:bb:cc:dd:ee:ff",
                "model": "U6-Pro",
                "state": 1,
                "name": "Test-AP",
                "ip": "10.0.0.1",
                "version": "7.0.0",
                "uptime": 100,
            },
            {
                "_id": "def456",
                "mac": "11:22:33:44:55:66",
                "model": "USW-24",
                "state": 0,
                "name": "Test-Switch",
                "ip": "10.0.0.2",
                "version": "6.0.0",
                "uptime": 200,
            },
        ]

        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(data=raw_data, count=2, meta={"rc": "ok"})
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__list_devices()

        assert result[0]["status"] == "connected"
        assert result[1]["status"] == "disconnected"

    async def test_custom_site_id(self) -> None:
        """Tool should pass a custom site_id to the API endpoint."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(data=[], count=0, meta={"rc": "ok"})
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            await unifi__topology__list_devices(site_id="my-site")

        mock_client.get_normalized.assert_called_once_with("/api/s/my-site/stat/device")

    async def test_empty_device_list(self) -> None:
        """Tool should return an empty list when no devices exist."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(data=[], count=0, meta={"rc": "ok"})
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__list_devices()

        assert result == []
        mock_client.close.assert_called_once()

    async def test_api_error_propagates(self) -> None:
        """APIError from the client should propagate to the caller."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError(
                "UniFi API error: api.err.Invalid",
                status_code=200,
            )
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.topology._get_client", return_value=mock_client),
            pytest.raises(APIError, match=r"api\.err\.Invalid"),
        ):
            await unifi__topology__list_devices()

        # Client should still be closed even on error
        mock_client.close.assert_called_once()

    async def test_network_error_propagates(self) -> None:
        """NetworkError from the client should propagate to the caller."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=NetworkError("Connection refused: https://192.168.1.1/proxy/network")
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.topology._get_client", return_value=mock_client),
            pytest.raises(NetworkError, match="Connection refused"),
        ):
            await unifi__topology__list_devices()

        mock_client.close.assert_called_once()

    async def test_client_closed_on_success(
        self,
        mock_normalized_response: NormalizedResponse,
    ) -> None:
        """Client should always be closed, even on successful requests."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(return_value=mock_normalized_response)
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            await unifi__topology__list_devices()

        mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify the tool is registered on the MCP server."""

    def test_tool_is_registered(self) -> None:
        """unifi__topology__list_devices should be registered on mcp_server."""
        # FastMCP stores tools in an internal registry; check the tool list
        # by verifying the decorated function can be found.
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__topology__list_devices" in tool_names
