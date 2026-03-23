"""Tests for the topology MCP tools (list_devices, get_device, get_vlans)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tests.fixtures import load_fixture
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

        with pytest.raises(APIError, match="credentials not configured"):
            _get_client()


# ---------------------------------------------------------------------------
# unifi__topology__list_devices
# ---------------------------------------------------------------------------


class TestListDevices:
    """Integration tests for the list_devices MCP tool."""

    @pytest.fixture()
    def mock_normalized_response(self, device_list_response: dict[str, Any]) -> NormalizedResponse:
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
            "_id": "abc123",
            "mac": "aa:bb:cc:dd:ee:ff",
            "model": "U6-Pro",
            "name": "Test-AP",
            "ip": "192.168.1.50",
            "state": 1,
            "uptime": 3600,
            "version": "7.0.76",
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
        network = {
            "_id": "002",
            "name": "Guest",
            "purpose": "guest",
            "vlan_enabled": True,
            "vlan": 10,
        }
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
    return NormalizedResponse(
        data=data, count=len(data), total_count=None, meta=fixture.get("meta", {})
    )


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
        data = {
            "meta": {"rc": "ok"},
            "data": [
                {"_id": "wan001", "name": "WAN", "purpose": "wan", "vlan_enabled": False},
                {
                    "_id": "lan001",
                    "name": "Default",
                    "purpose": "corporate",
                    "vlan_enabled": False,
                    "ip_subnet": "192.168.1.0/24",
                    "dhcpd_enabled": True,
                },
            ],
        }
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

    def test_builds_graph_from_fixture(self, device_list: list[dict[str, Any]]) -> None:
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
    def mock_normalized_response(self, device_list_response: dict[str, Any]) -> NormalizedResponse:
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
            "device_id",
            "device_name",
            "device_mac",
            "uplink_device_id",
            "uplink_device_name",
            "uplink_device_mac",
            "uplink_port",
            "uplink_type",
            "speed",
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


# ---------------------------------------------------------------------------
# Edge case tests for list_devices
# ---------------------------------------------------------------------------


class TestListDevicesEdgeCases:
    """Edge case tests for unifi__topology__list_devices."""

    async def test_device_missing_optional_fields(self) -> None:
        """A device with no port_table, uplink, or radio_table should parse cleanly."""
        raw_data = [
            {
                "_id": "minimal001",
                "mac": "aa:bb:cc:dd:ee:01",
                "model": "USW-Lite-8-PoE",
                "state": 1,
                "name": "Bare-Switch",
                "ip": "10.0.0.50",
                "version": "7.0.50",
                "uptime": 600,
            },
        ]

        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(data=raw_data, count=1, meta={"rc": "ok"})
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__list_devices()

        assert len(result) == 1
        device = result[0]
        assert device["device_id"] == "minimal001"
        assert device["name"] == "Bare-Switch"
        assert device["status"] == "connected"
        # Optional fields should default to None and appear (model_dump includes None by default)
        assert device.get("port_table") is None
        assert device.get("uplink") is None
        assert device.get("radio_table") is None

    async def test_device_with_unknown_state_code(self) -> None:
        """A device with an unmapped numeric state (e.g. 99) should get 'unknown(99)'."""
        raw_data = [
            {
                "_id": "unk001",
                "mac": "aa:bb:cc:dd:ee:02",
                "model": "U6-Pro",
                "state": 99,
                "name": "Mystery-AP",
                "ip": "10.0.0.51",
                "version": "7.0.76",
                "uptime": 100,
            },
        ]

        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(data=raw_data, count=1, meta={"rc": "ok"})
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__list_devices()

        assert result[0]["status"] == "unknown(99)"

    async def test_device_with_state_already_string(self) -> None:
        """A device whose state is already a string should pass through unchanged."""
        raw_data = [
            {
                "_id": "str001",
                "mac": "aa:bb:cc:dd:ee:03",
                "model": "UDM-Pro",
                "state": "connected",
                "name": "Already-String",
                "ip": "10.0.0.52",
                "version": "4.0.6",
                "uptime": 500,
            },
        ]

        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(data=raw_data, count=1, meta={"rc": "ok"})
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__list_devices()

        assert result[0]["status"] == "connected"

    async def test_mixed_online_and_offline_devices(self) -> None:
        """A mix of state=1 (connected) and state=0 (disconnected) devices."""
        raw_data = [
            {
                "_id": "on001",
                "mac": "aa:bb:cc:dd:ee:10",
                "model": "USW-24",
                "state": 1,
                "name": "Online-Switch",
                "ip": "10.0.0.60",
                "version": "7.0.50",
                "uptime": 86400,
            },
            {
                "_id": "off001",
                "mac": "aa:bb:cc:dd:ee:11",
                "model": "U6-LR",
                "state": 0,
                "name": "Offline-AP",
                "ip": "10.0.0.61",
                "version": "7.0.76",
                "uptime": 0,
            },
            {
                "_id": "on002",
                "mac": "aa:bb:cc:dd:ee:12",
                "model": "UXG-Max",
                "state": 1,
                "name": "Online-Gateway",
                "ip": "10.0.0.1",
                "version": "4.0.6",
                "uptime": 172800,
            },
            {
                "_id": "off002",
                "mac": "aa:bb:cc:dd:ee:13",
                "model": "U6-Mesh",
                "state": 0,
                "name": "Offline-Mesh",
                "ip": "10.0.0.62",
                "version": "7.0.76",
                "uptime": 0,
            },
        ]

        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(data=raw_data, count=4, meta={"rc": "ok"})
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__list_devices()

        assert len(result) == 4

        statuses = [d["status"] for d in result]
        assert statuses == ["connected", "disconnected", "connected", "disconnected"]

        # Verify all devices parsed correctly despite mixed states
        assert result[0]["name"] == "Online-Switch"
        assert result[1]["name"] == "Offline-AP"
        assert result[2]["name"] == "Online-Gateway"
        assert result[3]["name"] == "Offline-Mesh"


# ---------------------------------------------------------------------------
# Edge case tests for get_vlans
# ---------------------------------------------------------------------------


class TestGetVlansEdgeCases:
    """Edge case tests for unifi__topology__get_vlans."""

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

    async def test_vlan_enabled_but_no_vlan_field_excluded(self) -> None:
        """A network with vlan_enabled=True but missing 'vlan' key should be excluded.

        The _is_vlan_network filter requires both vlan_enabled=True AND
        a 'vlan' key present for tagged VLANs. Without the vlan tag number,
        it is not a valid tagged VLAN and should also not match the
        default-LAN path (because vlan_enabled is True).
        """
        data = {
            "meta": {"rc": "ok"},
            "data": [
                {
                    "_id": "broken001",
                    "name": "Broken-VLAN",
                    "purpose": "corporate",
                    "vlan_enabled": True,
                    # Note: no "vlan" key
                    "ip_subnet": "192.168.50.0/24",
                    "dhcpd_enabled": True,
                },
                {
                    "_id": "good001",
                    "name": "Good-Default",
                    "purpose": "corporate",
                    "vlan_enabled": False,
                    "ip_subnet": "192.168.1.0/24",
                    "dhcpd_enabled": True,
                },
            ],
        }
        with self._patch_client(data):
            result = await unifi__topology__get_vlans()

        # Only the default LAN should survive; the broken VLAN should be filtered
        assert len(result) == 1
        assert result[0]["name"] == "Good-Default"

    async def test_network_with_empty_purpose_included(self) -> None:
        """A network with purpose='' (empty string) should be included.

        Empty purpose is not 'wan' or 'wan2', so it passes the WAN filter.
        With vlan_enabled=False and purpose not in WAN_PURPOSES, it matches
        the default-LAN path.
        """
        data = {
            "meta": {"rc": "ok"},
            "data": [
                {
                    "_id": "empty001",
                    "name": "No-Purpose-Net",
                    "purpose": "",
                    "vlan_enabled": False,
                    "ip_subnet": "10.0.0.0/24",
                    "dhcpd_enabled": False,
                },
            ],
        }
        with self._patch_client(data):
            result = await unifi__topology__get_vlans()

        assert len(result) == 1
        assert result[0]["name"] == "No-Purpose-Net"

    async def test_all_wan_networks_returns_empty(self) -> None:
        """When every network has purpose='wan' or 'wan2', result should be empty."""
        data = {
            "meta": {"rc": "ok"},
            "data": [
                {
                    "_id": "wan001",
                    "name": "WAN",
                    "purpose": "wan",
                    "vlan_enabled": False,
                    "ip_subnet": "203.0.113.0/24",
                    "dhcpd_enabled": False,
                },
                {
                    "_id": "wan002",
                    "name": "WAN2-Backup",
                    "purpose": "wan2",
                    "vlan_enabled": False,
                    "ip_subnet": "198.51.100.0/24",
                    "dhcpd_enabled": False,
                },
            ],
        }
        with self._patch_client(data):
            result = await unifi__topology__get_vlans()

        assert result == []

    async def test_unparseable_network_skipped_gracefully(self) -> None:
        """A network that passes _is_vlan_network but fails VLAN.model_validate
        should be skipped without raising, and other valid networks should
        still be returned."""
        data = {
            "meta": {"rc": "ok"},
            "data": [
                {
                    # Missing required '_id' field -- will fail model_validate
                    "name": "Bad-Network",
                    "purpose": "corporate",
                    "vlan_enabled": False,
                },
                {
                    "_id": "good002",
                    "name": "Good-Network",
                    "purpose": "corporate",
                    "vlan_enabled": False,
                    "ip_subnet": "192.168.2.0/24",
                    "dhcpd_enabled": True,
                },
            ],
        }
        with self._patch_client(data):
            result = await unifi__topology__get_vlans()

        # The bad network should be skipped, the good one should survive
        assert len(result) == 1
        assert result[0]["name"] == "Good-Network"


# ---------------------------------------------------------------------------
# Edge case tests for get_uplinks / _build_uplink_graph
# ---------------------------------------------------------------------------


class TestGetUplinksEdgeCases:
    """Edge case tests for uplink graph building."""

    def test_all_root_devices_empty_graph(self) -> None:
        """When every device is a root (no uplink field), the graph should be empty."""
        devices = [
            {"_id": "gw1", "mac": "aa:bb:cc:dd:ee:01", "name": "Gateway-1"},
            {"_id": "gw2", "mac": "aa:bb:cc:dd:ee:02", "name": "Gateway-2"},
            {"_id": "gw3", "mac": "aa:bb:cc:dd:ee:03", "name": "Gateway-3"},
        ]
        graph = _build_uplink_graph(devices)
        assert graph == []

    def test_uplink_missing_speed_field(self) -> None:
        """A device with an uplink but no speed field should have speed=None."""
        devices = [
            {"_id": "parent01", "mac": "aa:bb:cc:dd:ee:10", "name": "Parent-Switch"},
            {
                "_id": "child01",
                "mac": "aa:bb:cc:dd:ee:11",
                "name": "Child-AP",
                "uplink": {
                    "uplink_mac": "aa:bb:cc:dd:ee:10",
                    "uplink_remote_port": 5,
                    "type": "wire",
                    # No "speed" key
                },
            },
        ]
        graph = _build_uplink_graph(devices)

        assert len(graph) == 1
        assert graph[0]["device_name"] == "Child-AP"
        assert graph[0]["uplink_device_name"] == "Parent-Switch"
        assert graph[0]["speed"] is None

    def test_large_device_list_performance(self) -> None:
        """Verify _build_uplink_graph handles 10+ devices with O(1) MAC lookup.

        This test generates a chain of 15 devices where each device's uplink
        points to the previous one. The MAC-indexed dict should make parent
        resolution constant-time per device.
        """
        devices: list[dict[str, Any]] = []
        for i in range(15):
            mac = f"aa:bb:cc:dd:{i:02x}:00"
            device: dict[str, Any] = {
                "_id": f"dev{i:03d}",
                "mac": mac,
                "name": f"Device-{i}",
            }
            if i > 0:
                parent_mac = f"aa:bb:cc:dd:{(i - 1):02x}:00"
                device["uplink"] = {
                    "uplink_mac": parent_mac,
                    "uplink_remote_port": 1,
                    "speed": 1000,
                    "type": "wire",
                }
            devices.append(device)

        graph = _build_uplink_graph(devices)

        # 14 non-root devices should produce 14 uplink entries
        assert len(graph) == 14

        # Verify each link resolves the correct parent
        for i, link in enumerate(graph):
            child_idx = i + 1
            parent_idx = i
            assert link["device_id"] == f"dev{child_idx:03d}"
            assert link["device_name"] == f"Device-{child_idx}"
            assert link["uplink_device_id"] == f"dev{parent_idx:03d}"
            assert link["uplink_device_name"] == f"Device-{parent_idx}"

    def test_uplink_with_missing_remote_port(self) -> None:
        """A device whose uplink has no uplink_remote_port should get port=None."""
        devices = [
            {"_id": "parent02", "mac": "aa:bb:cc:dd:ee:20", "name": "Parent"},
            {
                "_id": "child02",
                "mac": "aa:bb:cc:dd:ee:21",
                "name": "Child",
                "uplink": {
                    "uplink_mac": "aa:bb:cc:dd:ee:20",
                    "type": "wire",
                    "speed": 1000,
                    # No "uplink_remote_port" key
                },
            },
        ]
        graph = _build_uplink_graph(devices)

        assert len(graph) == 1
        assert graph[0]["uplink_port"] is None
        assert graph[0]["speed"] == 1000

    async def test_get_uplinks_tool_all_roots(self) -> None:
        """The MCP tool should return an empty list when all devices are root."""
        raw_data = [
            {"_id": "gw1", "mac": "ff:00:00:00:00:01", "name": "Root-GW"},
            {"_id": "gw2", "mac": "ff:00:00:00:00:02", "name": "Root-GW-2"},
        ]

        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(data=raw_data, count=2, meta={"rc": "ok"})
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__get_uplinks()

        assert result == []
        mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# Fixture validation tests (round-trip through tools)
# ---------------------------------------------------------------------------


class TestFixtureValidation:
    """Validate that fixture JSON files round-trip through the MCP tools correctly.

    These tests load the real fixture files and verify that they can be
    parsed by the tools without errors, producing the expected model
    output shapes.
    """

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "test-api-key")

    async def test_device_list_fixture_roundtrip(
        self, device_list_response: dict[str, Any]
    ) -> None:
        """device_list.json -> list_devices -> list of Device-shaped dicts."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(
                data=device_list_response["data"],
                count=len(device_list_response["data"]),
                meta=device_list_response["meta"],
            )
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__list_devices()

        assert len(result) == 3

        # Every device dict must have all core Device model fields
        required_keys = {"device_id", "name", "model", "mac", "ip", "status", "uptime", "firmware"}
        for device in result:
            assert required_keys.issubset(device.keys()), (
                f"Device {device.get('name', '?')} missing keys: {required_keys - device.keys()}"
            )
            # status must be a string, not an int
            assert isinstance(device["status"], str)

        # Verify specific fixture devices were parsed correctly
        names = [d["name"] for d in result]
        assert "USG-Gateway" in names
        assert "Office-Switch-16" in names
        assert "Office-AP-Main" in names

    async def test_vlan_config_fixture_roundtrip(
        self, vlan_config_response: dict[str, Any]
    ) -> None:
        """vlan_config.json -> get_vlans -> list of VLAN-shaped dicts."""
        normalized = _normalized_from_fixture(vlan_config_response)
        mock_client = AsyncMock()
        mock_client.get_normalized.return_value = normalized
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__get_vlans()

        assert len(result) == 4

        # Every VLAN dict must have all VLAN model fields
        required_keys = {"vlan_id", "name", "subnet", "purpose", "dhcp_enabled"}
        for vlan in result:
            assert required_keys.issubset(vlan.keys()), (
                f"VLAN {vlan.get('name', '?')} missing keys: {required_keys - vlan.keys()}"
            )

        # Verify specific fixture VLANs were parsed correctly
        vlan_names = [v["name"] for v in result]
        assert "Default" in vlan_names
        assert "Guest" in vlan_names
        assert "IoT" in vlan_names
        assert "Management" in vlan_names

        # Verify VLAN tag values are correct for tagged VLANs
        guest = next(v for v in result if v["name"] == "Guest")
        assert guest["purpose"] == "guest"

        iot = next(v for v in result if v["name"] == "IoT")
        assert iot["subnet"] == "192.168.30.0/24"

    async def test_device_list_fixture_uplinks_roundtrip(
        self, device_list_response: dict[str, Any]
    ) -> None:
        """device_list.json -> get_uplinks -> uplink graph with correct topology."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(
                data=device_list_response["data"],
                count=len(device_list_response["data"]),
                meta=device_list_response["meta"],
            )
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__get_uplinks()

        # The fixture has 3 devices: gateway (root), switch -> gateway, AP -> switch
        assert len(result) == 2

        expected_keys = {
            "device_id",
            "device_name",
            "device_mac",
            "uplink_device_id",
            "uplink_device_name",
            "uplink_device_mac",
            "uplink_port",
            "uplink_type",
            "speed",
        }
        for link in result:
            assert set(link.keys()) == expected_keys

        # Verify the topology chain: switch -> gateway, AP -> switch
        link_map = {link["device_name"]: link for link in result}

        switch_link = link_map["Office-Switch-16"]
        assert switch_link["uplink_device_name"] == "USG-Gateway"
        assert switch_link["uplink_type"] == "wire"
        assert switch_link["speed"] == 10000

        ap_link = link_map["Office-AP-Main"]
        assert ap_link["uplink_device_name"] == "Office-Switch-16"
        assert ap_link["uplink_type"] == "wire"
        assert ap_link["speed"] == 1000

    async def test_device_single_fixture_roundtrip(
        self, device_single_response: dict[str, Any]
    ) -> None:
        """device_single.json -> get_device -> Device dict with detail fields."""
        device_data = device_single_response["data"][0]

        mock_client = AsyncMock()
        mock_client.get_single = AsyncMock(return_value=device_data)
        mock_client.close = AsyncMock()

        with patch("unifi.tools.topology._get_client", return_value=mock_client):
            result = await unifi__topology__get_device(
                device_id=device_data["mac"],
            )

        # Core fields
        assert result["device_id"] == device_data["_id"]
        assert result["mac"] == device_data["mac"]
        assert result["status"] == "connected"  # state=1 -> "connected"

        # Detail fields (present in single-device fixture)
        assert result["port_table"] is not None
        assert isinstance(result["port_table"], list)
        assert len(result["port_table"]) > 0

        assert result["uplink"] is not None
        assert isinstance(result["uplink"], dict)
