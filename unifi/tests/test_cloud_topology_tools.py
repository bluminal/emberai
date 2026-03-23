# SPDX-License-Identifier: MIT
"""Tests for Cloud V1 topology tools (list_sites, list_hosts) and multi-site scan.

Covers Tasks 49, 50, 51, and 56 from the implementation plan:
- Task 49: unifi__topology__list_sites()
- Task 51: unifi__topology__list_hosts()
- Task 50: Multi-site scan_site() flow
- Task 56: Firmware status Cloud V1 fallback
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, AuthenticationError, NetworkError
from unifi.server import mcp_server
from unifi.tools.topology import (
    _get_cloud_client,
    unifi__topology__list_hosts,
    unifi__topology__list_sites,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cloud_normalized(data: list[dict[str, Any]]) -> NormalizedResponse:
    """Build a NormalizedResponse like CloudV1Client.get_normalized returns."""
    return NormalizedResponse(
        data=data,
        count=len(data),
        total_count=None,
        meta={"httpStatusCode": 200, "traceId": "test-trace-id"},
    )


def _mock_cloud_client(data: list[dict[str, Any]]) -> AsyncMock:
    """Create a mock CloudV1Client returning the given data."""
    mock_client = AsyncMock()
    mock_client.get_normalized = AsyncMock(
        return_value=_cloud_normalized(data),
    )
    mock_client.close = AsyncMock()
    return mock_client


# ---------------------------------------------------------------------------
# _get_cloud_client
# ---------------------------------------------------------------------------


class TestGetCloudClient:
    """Verify the Cloud V1 client factory."""

    def test_creates_client_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "test-cloud-key-123")

        client = _get_cloud_client()

        assert client._api_key == "test-cloud-key-123"

    def test_raises_when_api_key_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNIFI_API_KEY", raising=False)

        with pytest.raises(AuthenticationError, match="UNIFI_API_KEY is not configured"):
            _get_cloud_client()

    def test_raises_when_api_key_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "")

        with pytest.raises(AuthenticationError, match="UNIFI_API_KEY is not configured"):
            _get_cloud_client()

    def test_raises_when_api_key_whitespace_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "   ")

        with pytest.raises(AuthenticationError, match="UNIFI_API_KEY is not configured"):
            _get_cloud_client()

    def test_strips_whitespace_from_api_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "  my-key  ")

        client = _get_cloud_client()

        assert client._api_key == "my-key"


# ---------------------------------------------------------------------------
# Task 49: unifi__topology__list_sites
# ---------------------------------------------------------------------------


class TestListSites:
    """Tests for the unifi__topology__list_sites MCP tool."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "test-cloud-key")

    async def test_returns_site_dicts(self) -> None:
        """Tool should return a list of dicts with Site model fields."""
        raw_sites = [
            {
                "_id": "site001",
                "name": "Main Office",
                "desc": "Primary site",
                "num_d": 12,
                "num_sta": 45,
            },
            {
                "_id": "site002",
                "name": "Branch Office",
                "desc": "Secondary site",
                "num_d": 5,
                "num_sta": 15,
            },
        ]
        mock_client = _mock_cloud_client(raw_sites)

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            result = await unifi__topology__list_sites()

        assert isinstance(result, list)
        assert len(result) == 2

        mock_client.get_normalized.assert_called_once_with("sites")
        mock_client.close.assert_called_once()

    async def test_site_fields_correct(self) -> None:
        """Each site dict should contain all Site model fields."""
        raw_sites = [
            {
                "_id": "site001",
                "name": "Main Office",
                "desc": "Primary site",
                "num_d": 12,
                "num_sta": 45,
            },
        ]
        mock_client = _mock_cloud_client(raw_sites)

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            result = await unifi__topology__list_sites()

        site = result[0]
        assert site["site_id"] == "site001"
        assert site["name"] == "Main Office"
        assert site["description"] == "Primary site"
        assert site["device_count"] == 12
        assert site["client_count"] == 45

    async def test_empty_site_list(self) -> None:
        """Tool should return empty list when no sites exist."""
        mock_client = _mock_cloud_client([])

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            result = await unifi__topology__list_sites()

        assert result == []
        mock_client.close.assert_called_once()

    async def test_site_with_defaults(self) -> None:
        """Site with missing optional fields should use defaults."""
        raw_sites = [
            {
                "_id": "site003",
                "name": "Minimal Site",
            },
        ]
        mock_client = _mock_cloud_client(raw_sites)

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            result = await unifi__topology__list_sites()

        site = result[0]
        assert site["site_id"] == "site003"
        assert site["name"] == "Minimal Site"
        assert site["description"] == ""
        assert site["device_count"] == 0
        assert site["client_count"] == 0

    async def test_unparseable_site_skipped(self) -> None:
        """Sites that fail model validation should be skipped gracefully."""
        raw_sites = [
            {
                # Missing required _id field
                "name": "Bad Site",
            },
            {
                "_id": "site004",
                "name": "Good Site",
            },
        ]
        mock_client = _mock_cloud_client(raw_sites)

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            result = await unifi__topology__list_sites()

        assert len(result) == 1
        assert result[0]["name"] == "Good Site"

    async def test_api_error_propagates(self) -> None:
        """APIError from the Cloud V1 client should propagate."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Cloud V1 error", status_code=500),
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.topology._get_cloud_client", return_value=mock_client),
            pytest.raises(APIError, match="Cloud V1 error"),
        ):
            await unifi__topology__list_sites()

        mock_client.close.assert_called_once()

    async def test_auth_error_propagates(self) -> None:
        """AuthenticationError should propagate for invalid API key."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=AuthenticationError(
                "Authentication failed",
                env_var="UNIFI_API_KEY",
            ),
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.topology._get_cloud_client", return_value=mock_client),
            pytest.raises(AuthenticationError, match="Authentication failed"),
        ):
            await unifi__topology__list_sites()

        mock_client.close.assert_called_once()

    async def test_network_error_propagates(self) -> None:
        """NetworkError should propagate for connection failures."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=NetworkError("Connection refused"),
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.topology._get_cloud_client", return_value=mock_client),
            pytest.raises(NetworkError, match="Connection refused"),
        ):
            await unifi__topology__list_sites()

        mock_client.close.assert_called_once()

    async def test_client_closed_on_success(self) -> None:
        """Client should be closed even on successful requests."""
        mock_client = _mock_cloud_client([{"_id": "s1", "name": "Site"}])

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            await unifi__topology__list_sites()

        mock_client.close.assert_called_once()

    async def test_client_closed_on_error(self) -> None:
        """Client should be closed even when the API call fails."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Server error", status_code=500),
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.topology._get_cloud_client", return_value=mock_client),
            pytest.raises(APIError),
        ):
            await unifi__topology__list_sites()

        mock_client.close.assert_called_once()

    async def test_multiple_sites_with_varying_data(self) -> None:
        """Verify parsing of multiple sites with varying field completeness."""
        raw_sites = [
            {"_id": "s1", "name": "Full", "desc": "All fields", "num_d": 10, "num_sta": 50},
            {"_id": "s2", "name": "Partial", "num_d": 3},
            {"_id": "s3", "name": "Minimal"},
        ]
        mock_client = _mock_cloud_client(raw_sites)

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            result = await unifi__topology__list_sites()

        assert len(result) == 3
        assert result[0]["device_count"] == 10
        assert result[0]["client_count"] == 50
        assert result[1]["device_count"] == 3
        assert result[1]["client_count"] == 0
        assert result[2]["device_count"] == 0

    def test_tool_registered(self) -> None:
        """The list_sites tool should be registered on the MCP server."""
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__topology__list_sites" in tool_names


# ---------------------------------------------------------------------------
# Task 51: unifi__topology__list_hosts
# ---------------------------------------------------------------------------


class TestListHosts:
    """Tests for the unifi__topology__list_hosts MCP tool."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "test-cloud-key")

    async def test_returns_host_dicts(self) -> None:
        """Tool should return a list of dicts with host fields."""
        raw_hosts = [
            {
                "_id": "host001",
                "hostname": "UDM-Pro-Main",
                "ip": "192.168.1.1",
                "type": "udm",
                "firmware_version": "4.0.6",
            },
            {
                "_id": "host002",
                "hostname": "UCK-G2-Branch",
                "ip": "10.0.0.1",
                "type": "uck",
                "firmware_version": "3.1.15",
            },
        ]
        mock_client = _mock_cloud_client(raw_hosts)

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            result = await unifi__topology__list_hosts()

        assert isinstance(result, list)
        assert len(result) == 2

        mock_client.get_normalized.assert_called_once_with("hosts")
        mock_client.close.assert_called_once()

    async def test_host_fields_correct(self) -> None:
        """Each host dict should contain all expected fields."""
        raw_hosts = [
            {
                "_id": "host001",
                "hostname": "UDM-Pro-Main",
                "ip": "192.168.1.1",
                "type": "udm",
                "firmware_version": "4.0.6",
            },
        ]
        mock_client = _mock_cloud_client(raw_hosts)

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            result = await unifi__topology__list_hosts()

        host = result[0]
        assert host["host_id"] == "host001"
        assert host["name"] == "UDM-Pro-Main"
        assert host["ip"] == "192.168.1.1"
        assert host["type"] == "udm"
        assert host["firmware_version"] == "4.0.6"

    async def test_host_with_alternate_field_names(self) -> None:
        """Host data may use alternate field names (id, name, wan_ip, etc.)."""
        raw_hosts = [
            {
                "id": "host003",
                "name": "Cloud-Console",
                "wan_ip": "203.0.113.10",
                "hardware_type": "ucg-ultra",
                "version": "3.2.7",
            },
        ]
        mock_client = _mock_cloud_client(raw_hosts)

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            result = await unifi__topology__list_hosts()

        host = result[0]
        assert host["host_id"] == "host003"
        assert host["name"] == "Cloud-Console"
        assert host["ip"] == "203.0.113.10"
        assert host["type"] == "ucg-ultra"
        assert host["firmware_version"] == "3.2.7"

    async def test_empty_host_list(self) -> None:
        """Tool should return empty list when no hosts exist."""
        mock_client = _mock_cloud_client([])

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            result = await unifi__topology__list_hosts()

        assert result == []
        mock_client.close.assert_called_once()

    async def test_host_with_missing_fields(self) -> None:
        """Host with missing fields should use empty string defaults."""
        raw_hosts = [
            {"_id": "host004"},
        ]
        mock_client = _mock_cloud_client(raw_hosts)

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            result = await unifi__topology__list_hosts()

        host = result[0]
        assert host["host_id"] == "host004"
        assert host["name"] == ""
        assert host["ip"] == ""
        assert host["type"] == ""
        assert host["firmware_version"] == ""

    async def test_api_error_propagates(self) -> None:
        """APIError from the Cloud V1 client should propagate."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Server error", status_code=500),
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.topology._get_cloud_client", return_value=mock_client),
            pytest.raises(APIError, match="Server error"),
        ):
            await unifi__topology__list_hosts()

        mock_client.close.assert_called_once()

    async def test_client_closed_on_success(self) -> None:
        """Client should be closed on successful requests."""
        mock_client = _mock_cloud_client([{"_id": "h1"}])

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            await unifi__topology__list_hosts()

        mock_client.close.assert_called_once()

    async def test_client_closed_on_error(self) -> None:
        """Client should be closed even when the API call fails."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=NetworkError("Timeout"),
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.topology._get_cloud_client", return_value=mock_client),
            pytest.raises(NetworkError),
        ):
            await unifi__topology__list_hosts()

        mock_client.close.assert_called_once()

    async def test_multiple_hosts(self) -> None:
        """Verify parsing of multiple hosts with varying field sets."""
        raw_hosts = [
            {
                "_id": "h1",
                "hostname": "UDM-Pro",
                "ip": "192.168.1.1",
                "type": "udm",
                "firmware_version": "4.0.6",
            },
            {
                "id": "h2",
                "name": "UCK-G2",
                "wan_ip": "10.0.0.1",
                "hardware_type": "uck",
                "version": "3.1.15",
            },
            {"_id": "h3"},
        ]
        mock_client = _mock_cloud_client(raw_hosts)

        with patch("unifi.tools.topology._get_cloud_client", return_value=mock_client):
            result = await unifi__topology__list_hosts()

        assert len(result) == 3
        assert result[0]["host_id"] == "h1"
        assert result[1]["host_id"] == "h2"
        assert result[2]["host_id"] == "h3"

    def test_tool_registered(self) -> None:
        """The list_hosts tool should be registered on the MCP server."""
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__topology__list_hosts" in tool_names


# ---------------------------------------------------------------------------
# Task 49/51: Tool registration
# ---------------------------------------------------------------------------


class TestCloudToolRegistration:
    """Verify Cloud V1 topology tools are registered on the MCP server."""

    def test_list_sites_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__topology__list_sites" in tool_names

    def test_list_hosts_registered(self) -> None:
        tool_names = [tool.name for tool in mcp_server._tool_manager.list_tools()]
        assert "unifi__topology__list_hosts" in tool_names

    def test_list_sites_no_parameters_required(self) -> None:
        """list_sites should have no required parameters."""
        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        sites_tool = tools["unifi__topology__list_sites"]
        schema = sites_tool.parameters
        required = schema.get("required", [])
        assert required == []

    def test_list_hosts_no_parameters_required(self) -> None:
        """list_hosts should have no required parameters."""
        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        hosts_tool = tools["unifi__topology__list_hosts"]
        schema = hosts_tool.parameters
        required = schema.get("required", [])
        assert required == []
