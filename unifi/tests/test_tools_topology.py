"""Tests for the topology MCP tools (list_devices, get_device, get_vlans)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, NetworkError
from unifi.server import mcp_server
from unifi.tools.topology import (
    _build_uplink_graph,
    _get_client,
    _is_vlan_network,
    _state_to_str,
    unifi__topology__get_device,
    unifi__topology__get_uplinks,
    unifi__topology__get_vlans,
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
    """Verify the tools are registered on the MCP server."""

    def test_list_devices_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__topology__list_devices" in tool_names

    def test_get_device_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__topology__get_device" in tool_names

    def test_get_vlans_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__topology__get_vlans" in tool_names


# ---------------------------------------------------------------------------
# unifi__topology__get_device tests
# ---------------------------------------------------------------------------


class TestGetDevice:
    """Test the unifi__topology__get_device MCP tool."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "test-key")

    async def test_returns_full_device_with_detail_fields(self) -> None:
        """Verify port_table, uplink, config_network are included."""
        device_data = load_fixture("device_single.json")["data"][0]

        mock_client = AsyncMock()
        mock_client.get_single = AsyncMock(return_value=device_data)
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__get_device(device_id="74:ac:b9:bb:33:44")

        assert result["mac"] == "74:ac:b9:bb:33:44"
        assert result["status"] == "connected"
        assert result["port_table"] is not None
        assert result["uplink"] is not None
        mock_client.close.assert_called_once()

    async def test_device_not_found(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_single = AsyncMock(
            side_effect=APIError("data array is empty", status_code=200),
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.topology._get_client", return_value=mock_client),
            pytest.raises(APIError, match="data array is empty"),
        ):
            await unifi__topology__get_device(device_id="00:00:00:00:00:00")

        mock_client.close.assert_called_once()

    async def test_api_error_propagation(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_single = AsyncMock(
            side_effect=APIError("Server error", status_code=500),
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.topology._get_client", return_value=mock_client),
            pytest.raises(APIError, match="Server error"),
        ):
            await unifi__topology__get_device(device_id="bad-id")

    async def test_unexpected_error_wrapped(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_single = AsyncMock(side_effect=RuntimeError("reset"))
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.topology._get_client", return_value=mock_client),
            pytest.raises(APIError, match="Failed to fetch device"),
        ):
            await unifi__topology__get_device(device_id="74:ac:b9:bb:33:44")

    async def test_optional_fields_excluded_when_none(self) -> None:
        minimal = {
            "_id": "abc123", "mac": "aa:bb:cc:dd:ee:ff", "model": "U6-Pro",
            "name": "Test-AP", "ip": "192.168.1.50", "state": 1,
            "uptime": 3600, "version": "7.0.76",
        }
        mock_client = AsyncMock()
        mock_client.get_single = AsyncMock(return_value=minimal)
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__get_device(device_id="aa:bb:cc:dd:ee:ff")

        assert "port_table" not in result
        assert "radio_table" not in result


# ---------------------------------------------------------------------------
# VLAN filtering tests
# ---------------------------------------------------------------------------


class TestIsVlanNetwork:
    """Tests for the VLAN/LAN network filter function."""

    def test_default_lan_included(self) -> None:
        network = {"_id": "001", "name": "Default", "purpose": "corporate", "vlan_enabled": False}
        assert _is_vlan_network(network) is True

    def test_tagged_vlan_included(self) -> None:
        network = {"_id": "002", "name": "Guest", "purpose": "guest", "vlan_enabled": True, "vlan": 10}
        assert _is_vlan_network(network) is True

    def test_wan_excluded(self) -> None:
        network = {"_id": "003", "name": "WAN", "purpose": "wan", "vlan_enabled": False}
        assert _is_vlan_network(network) is False

    def test_wan2_excluded(self) -> None:
        network = {"_id": "004", "name": "WAN2", "purpose": "wan2", "vlan_enabled": False}
        assert _is_vlan_network(network) is False


# ---------------------------------------------------------------------------
# unifi__topology__get_vlans tests
# ---------------------------------------------------------------------------


def _normalized_from_fixture(fixture: dict[str, Any]) -> NormalizedResponse:
    data = fixture.get("data", [])
    return NormalizedResponse(data=data, count=len(data), total_count=None, meta=fixture.get("meta", {}))


class TestGetVlans:
    """Test the unifi__topology__get_vlans MCP tool."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "test-api-key")

    def _patch_client(self, fixture_data: dict[str, Any]) -> Any:
        normalized = _normalized_from_fixture(fixture_data)
        mock_client = AsyncMock()
        mock_client.get_normalized.return_value = normalized
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        return patch("unifi.tools.topology._get_client", return_value=mock_client)

    async def test_parses_vlan_fixture(self) -> None:
        fixture = load_fixture("vlan_config.json")
        with self._patch_client(fixture):
            result = await unifi__topology__get_vlans()
        assert len(result) == 4

    async def test_empty_vlan_list(self) -> None:
        with self._patch_client({"meta": {"rc": "ok"}, "data": []}):
            result = await unifi__topology__get_vlans()
        assert result == []

    async def test_wan_filtered_out(self) -> None:
        data = {"meta": {"rc": "ok"}, "data": [
            {"_id": "wan001", "name": "WAN", "purpose": "wan", "vlan_enabled": False},
            {"_id": "lan001", "name": "Default", "purpose": "corporate",
             "vlan_enabled": False, "ip_subnet": "192.168.1.0/24", "dhcpd_enabled": True},
        ]}
        with self._patch_client(data):
            result = await unifi__topology__get_vlans()
        assert len(result) == 1
        assert result[0]["name"] == "Default"

    async def test_custom_site_id(self) -> None:
        normalized = _normalized_from_fixture({"meta": {"rc": "ok"}, "data": []})
        mock_client = AsyncMock()
        mock_client.get_normalized.return_value = normalized
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            await unifi__topology__get_vlans(site_id="site-abc")

        mock_client.get_normalized.assert_called_once_with("/api/s/site-abc/rest/networkconf")


# ---------------------------------------------------------------------------
# _build_uplink_graph unit tests
# ---------------------------------------------------------------------------


class TestBuildUplinkGraph:
    """Unit tests for the _build_uplink_graph helper."""

    def test_builds_graph_from_fixture(
        self, device_list: list[dict[str, Any]]
    ) -> None:
        """Fixture has 3 devices: gateway (root), switch -> gateway, AP -> switch."""
        graph = _build_uplink_graph(device_list)

        assert len(graph) == 2

        # Switch -> Gateway
        switch_link = next(g for g in graph if g["device_name"] == "Office-Switch-16")
        assert switch_link["device_id"] == "64b2c3d4e5f6a7b8c9d0e1f2"
        assert switch_link["device_mac"] == "74:ac:b9:bb:33:44"
        assert switch_link["uplink_device_id"] == "64a1b2c3d4e5f6a7b8c9d0e1"
        assert switch_link["uplink_device_name"] == "USG-Gateway"
        assert switch_link["uplink_device_mac"] == "f0:9f:c2:aa:11:22"
        assert switch_link["uplink_port"] == 1
        assert switch_link["uplink_type"] == "wire"
        assert switch_link["speed"] == 10000

        # AP -> Switch
        ap_link = next(g for g in graph if g["device_name"] == "Office-AP-Main")
        assert ap_link["device_id"] == "64c3d4e5f6a7b8c9d0e1f2a3"
        assert ap_link["uplink_device_id"] == "64b2c3d4e5f6a7b8c9d0e1f2"
        assert ap_link["uplink_device_name"] == "Office-Switch-16"
        assert ap_link["uplink_device_mac"] == "74:ac:b9:bb:33:44"
        assert ap_link["uplink_port"] == 1
        assert ap_link["uplink_type"] == "wire"
        assert ap_link["speed"] == 1000

    def test_root_device_excluded(self) -> None:
        """A gateway with no uplink field should not appear in the graph."""
        devices = [
            {"_id": "gw1", "mac": "aa:bb:cc:dd:ee:ff", "name": "Gateway"},
        ]
        graph = _build_uplink_graph(devices)
        assert graph == []

    def test_empty_device_list(self) -> None:
        """An empty device list should produce an empty graph."""
        assert _build_uplink_graph([]) == []

    def test_self_referencing_uplink_skipped(self) -> None:
        """A device whose uplink_mac matches its own MAC should be skipped."""
        devices = [
            {
                "_id": "dev1",
                "mac": "aa:bb:cc:dd:ee:ff",
                "name": "Self-Link",
                "uplink": {
                    "uplink_mac": "aa:bb:cc:dd:ee:ff",
                    "uplink_remote_port": 1,
                    "speed": 1000,
                    "type": "wire",
                },
            },
        ]
        graph = _build_uplink_graph(devices)
        assert graph == []

    def test_uplink_to_unknown_parent(self) -> None:
        """Uplink referencing a MAC not in the device list should still appear
        but with empty parent fields."""
        devices = [
            {
                "_id": "dev1",
                "mac": "11:22:33:44:55:66",
                "name": "Orphan-Switch",
                "uplink": {
                    "uplink_mac": "ff:ff:ff:ff:ff:ff",
                    "uplink_remote_port": 2,
                    "speed": 1000,
                    "type": "wire",
                },
            },
        ]
        graph = _build_uplink_graph(devices)

        assert len(graph) == 1
        link = graph[0]
        assert link["device_id"] == "dev1"
        assert link["device_name"] == "Orphan-Switch"
        assert link["uplink_device_id"] == ""
        assert link["uplink_device_name"] == ""
        assert link["uplink_device_mac"] == "ff:ff:ff:ff:ff:ff"

    def test_uplink_missing_uplink_mac_skipped(self) -> None:
        """A device with an uplink dict but no uplink_mac key should be skipped."""
        devices = [
            {
                "_id": "dev1",
                "mac": "11:22:33:44:55:66",
                "name": "Partial-Uplink",
                "uplink": {
                    "speed": 1000,
                    "type": "wire",
                },
            },
        ]
        graph = _build_uplink_graph(devices)
        assert graph == []


# ---------------------------------------------------------------------------
# unifi__topology__get_uplinks MCP tool tests
# ---------------------------------------------------------------------------


class TestGetUplinks:
    """Integration tests for the unifi__topology__get_uplinks MCP tool."""

    @pytest.fixture()
    def mock_normalized_response(
        self, device_list_response: dict[str, Any]
    ) -> NormalizedResponse:
        return NormalizedResponse(
            data=device_list_response["data"],
            count=len(device_list_response["data"]),
            meta=device_list_response["meta"],
        )

    async def test_returns_uplink_graph(
        self,
        mock_normalized_response: NormalizedResponse,
    ) -> None:
        """Tool should return the uplink graph derived from the device list."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(return_value=mock_normalized_response)
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__get_uplinks(site_id="default")

        assert isinstance(result, list)
        assert len(result) == 2

        mock_client.get_normalized.assert_called_once_with("/api/s/default/stat/device")
        mock_client.close.assert_called_once()

    async def test_uplink_graph_structure(
        self,
        mock_normalized_response: NormalizedResponse,
    ) -> None:
        """Each entry should contain all expected fields."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(return_value=mock_normalized_response)
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__get_uplinks()

        expected_keys = {
            "device_id", "device_name", "device_mac",
            "uplink_device_id", "uplink_device_name", "uplink_device_mac",
            "uplink_port", "uplink_type", "speed",
        }
        for entry in result:
            assert set(entry.keys()) == expected_keys

    async def test_empty_device_list(self) -> None:
        """Tool should return an empty list when no devices exist."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(data=[], count=0, meta={"rc": "ok"})
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__get_uplinks()

        assert result == []
        mock_client.close.assert_called_once()

    async def test_custom_site_id(self) -> None:
        """Tool should pass a custom site_id to the API endpoint."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(data=[], count=0, meta={"rc": "ok"})
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            await unifi__topology__get_uplinks(site_id="my-site")

        mock_client.get_normalized.assert_called_once_with("/api/s/my-site/stat/device")

    async def test_client_closed_on_error(self) -> None:
        """Client should be closed even when the API call fails."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Server error", status_code=500)
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.topology._get_client", return_value=mock_client),
            pytest.raises(APIError, match="Server error"),
        ):
            await unifi__topology__get_uplinks()

        mock_client.close.assert_called_once()

    async def test_tool_registered(self) -> None:
        """The get_uplinks tool should be registered on the MCP server."""
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__topology__get_uplinks" in tool_names
