"""Tests for the client MCP tools (list, get, traffic, search)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tests.fixtures import load_fixture
from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, NetworkError
from unifi.tools.clients import (
    _client_matches_query,
    _get_client,
    unifi__clients__get_client,
    unifi__clients__get_client_traffic,
    unifi__clients__list_clients,
    unifi__clients__search_clients,
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


def _mock_client_with_single(raw_item: dict[str, Any]) -> AsyncMock:
    """Create a mock client that returns a single item dict."""
    mock_client = AsyncMock()
    mock_client.get_single = AsyncMock(return_value=raw_item)
    mock_client.close = AsyncMock()
    return mock_client


def _mock_client_raising(exc: Exception) -> AsyncMock:
    """Create a mock client that raises an exception on any API call."""
    mock_client = AsyncMock()
    mock_client.get_normalized = AsyncMock(side_effect=exc)
    mock_client.get_single = AsyncMock(side_effect=exc)
    mock_client.close = AsyncMock()
    return mock_client


# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------


class TestGetClientHelper:
    """Verify the helper builds a client from env vars."""

    def test_creates_client_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "10.0.0.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "client-key-123")

        client = _get_client()

        assert client._host == "10.0.0.1"
        assert client._api_key == "client-key-123"

    def test_defaults_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNIFI_LOCAL_HOST", raising=False)
        monkeypatch.delenv("UNIFI_LOCAL_KEY", raising=False)

        with pytest.raises(APIError, match="credentials not configured"):
            _get_client()


# ---------------------------------------------------------------------------
# _client_matches_query
# ---------------------------------------------------------------------------


class TestClientMatchesQuery:
    """Unit tests for the client-side search filter function."""

    def test_matches_mac(self) -> None:
        raw = {
            "mac": "a4:83:e7:11:22:33",
            "hostname": "test",
            "ip": "1.2.3.4",
            "name": "",
        }
        assert _client_matches_query(raw, "a4:83") is True

    def test_matches_hostname(self) -> None:
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": "macbook-pro",
            "ip": "1.2.3.4",
            "name": "",
        }
        assert _client_matches_query(raw, "macbook") is True

    def test_matches_ip(self) -> None:
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": "test",
            "ip": "192.168.1.101",
            "name": "",
        }
        assert _client_matches_query(raw, "192.168.1") is True

    def test_matches_name_alias(self) -> None:
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": "test",
            "ip": "1.2.3.4",
            "name": "John's MacBook Pro",
        }
        assert _client_matches_query(raw, "john") is True

    def test_case_insensitive_mac(self) -> None:
        raw = {"mac": "A4:83:E7:11:22:33", "hostname": "", "ip": "", "name": ""}
        assert _client_matches_query(raw, "a4:83:e7") is True

    def test_case_insensitive_hostname(self) -> None:
        raw = {"mac": "", "hostname": "MacBook-Pro", "ip": "", "name": ""}
        # _client_matches_query expects a pre-lowered query string
        assert _client_matches_query(raw, "macbook") is True

    def test_no_match(self) -> None:
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": "test",
            "ip": "1.2.3.4",
            "name": "Device",
        }
        assert _client_matches_query(raw, "nonexistent") is False

    def test_empty_query_matches_all(self) -> None:
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": "test",
            "ip": "1.2.3.4",
            "name": "",
        }
        assert _client_matches_query(raw, "") is True

    def test_missing_fields_no_crash(self) -> None:
        raw: dict[str, Any] = {}
        assert _client_matches_query(raw, "test") is False

    def test_none_field_values(self) -> None:
        raw: dict[str, Any] = {
            "mac": None,
            "hostname": None,
            "ip": None,
            "name": None,
        }
        assert _client_matches_query(raw, "test") is False

    def test_partial_mac_match(self) -> None:
        raw = {"mac": "a4:83:e7:11:22:33", "hostname": "", "ip": "", "name": ""}
        assert _client_matches_query(raw, "11:22:33") is True


# ---------------------------------------------------------------------------
# unifi__clients__list_clients
# ---------------------------------------------------------------------------


class TestListClients:
    """Integration tests for the list_clients MCP tool."""

    @pytest.fixture()
    def fixture_data(self) -> dict[str, Any]:
        return load_fixture("client_list.json")

    async def test_returns_all_clients(self, fixture_data: dict[str, Any]) -> None:
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__list_clients(site_id="default")

        assert isinstance(result, list)
        assert len(result) == 6
        mock.get_normalized.assert_called_once_with("/api/s/default/stat/sta")
        mock.close.assert_called_once()

    async def test_client_has_expected_fields(self, fixture_data: dict[str, Any]) -> None:
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__list_clients()

        first = result[0]
        assert "client_mac" in first
        assert "ip" in first
        assert "vlan_id" in first
        assert "is_wired" in first
        assert "uptime" in first

    async def test_vlan_filter_narrows_results(self, fixture_data: dict[str, Any]) -> None:
        """Filter by LAN VLAN ID should only return LAN clients."""
        mock = _mock_client_with_normalized(fixture_data)
        lan_vlan_id = "5f9a8b7c6d5e4f3a2b1c0001"

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__list_clients(vlan_id=lan_vlan_id)

        # LAN clients: macbook-pro, pixel-8, synology-nas
        assert len(result) == 3
        for client in result:
            assert client["vlan_id"] == lan_vlan_id

    async def test_vlan_filter_guest(self, fixture_data: dict[str, Any]) -> None:
        """Filter by Guest VLAN ID should return only guest clients."""
        mock = _mock_client_with_normalized(fixture_data)
        guest_vlan_id = "5f9a8b7c6d5e4f3a2b1c0002"

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__list_clients(vlan_id=guest_vlan_id)

        # Guest client: iphone-guest-1
        assert len(result) == 1
        assert result[0]["client_mac"] == "3c:22:fb:44:55:66"

    async def test_vlan_filter_iot(self, fixture_data: dict[str, Any]) -> None:
        """Filter by IoT VLAN ID should return IoT devices."""
        mock = _mock_client_with_normalized(fixture_data)
        iot_vlan_id = "5f9a8b7c6d5e4f3a2b1c0003"

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__list_clients(vlan_id=iot_vlan_id)

        # IoT clients: sonos-livingroom, ring-doorbell
        assert len(result) == 2

    async def test_vlan_filter_no_match(self, fixture_data: dict[str, Any]) -> None:
        """Filter by nonexistent VLAN ID returns empty list."""
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__list_clients(vlan_id="nonexistent-vlan")

        assert result == []

    async def test_custom_site_id(self, fixture_data: dict[str, Any]) -> None:
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            await unifi__clients__list_clients(site_id="site-42")

        mock.get_normalized.assert_called_once_with("/api/s/site-42/stat/sta")

    async def test_empty_data(self) -> None:
        fixture = {"data": [], "meta": {"rc": "ok"}}
        mock = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__list_clients()

        assert result == []

    async def test_closes_client_on_error(self) -> None:
        mock = _mock_client_raising(NetworkError("timeout", endpoint="/test"))

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(NetworkError),
        ):
            await unifi__clients__list_clients()

        mock.close.assert_called_once()

    async def test_skips_unparseable_clients(self) -> None:
        """Clients that fail model validation are skipped, not fatal."""
        bad_data = {
            "data": [
                {"mac": "aa:bb:cc:dd:ee:ff", "ip": "1.2.3.4", "network_id": "vlan1"},
                {"bad_field": "no mac or ip"},  # will fail validation
            ],
            "meta": {"rc": "ok"},
        }
        mock = _mock_client_with_normalized(bad_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__list_clients()

        assert len(result) == 1

    async def test_exclude_none_in_output(self, fixture_data: dict[str, Any]) -> None:
        """Verify that None fields are excluded from output."""
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__list_clients()

        # The synology-nas is wired, so ap_id should be None -> excluded
        nas = next(c for c in result if c["client_mac"] == "b0:be:76:33:44:55")
        assert "ap_id" not in nas
        assert "ssid" not in nas
        assert "rssi" not in nas


# ---------------------------------------------------------------------------
# unifi__clients__get_client
# ---------------------------------------------------------------------------


class TestGetClientTool:
    """Integration tests for the get_client MCP tool."""

    @pytest.fixture()
    def raw_macbook(self) -> dict[str, Any]:
        data = load_fixture("client_list.json")
        return data["data"][0]  # macbook-pro-jdoe

    async def test_returns_client_dict(self, raw_macbook: dict[str, Any]) -> None:
        mock = _mock_client_with_single(raw_macbook)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__get_client(
                client_mac="a4:83:e7:11:22:33",
                site_id="default",
            )

        assert isinstance(result, dict)
        assert result["client_mac"] == "a4:83:e7:11:22:33"
        assert result["hostname"] == "macbook-pro-jdoe"
        assert result["ip"] == "192.168.1.101"

    async def test_calls_correct_endpoint(self, raw_macbook: dict[str, Any]) -> None:
        mock = _mock_client_with_single(raw_macbook)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            await unifi__clients__get_client(
                client_mac="a4:83:e7:11:22:33",
                site_id="mysite",
            )

        mock.get_single.assert_called_once_with(
            "/api/s/mysite/stat/sta/a4:83:e7:11:22:33",
        )

    async def test_includes_detail_fields(self, raw_macbook: dict[str, Any]) -> None:
        mock = _mock_client_with_single(raw_macbook)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__get_client(
                client_mac="a4:83:e7:11:22:33",
            )

        assert result["rssi"] == 56
        assert result["tx_bytes"] == 2847291038
        assert result["rx_bytes"] == 18293746501
        assert result["device_vendor"] == "Apple"

    async def test_propagates_api_error(self) -> None:
        mock = _mock_client_raising(APIError("Not found", status_code=404, endpoint="/test"))

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(APIError, match="Not found"),
        ):
            await unifi__clients__get_client(client_mac="aa:bb:cc:dd:ee:ff")

    async def test_wraps_unexpected_exception(self) -> None:
        mock = AsyncMock()
        mock.get_single = AsyncMock(side_effect=RuntimeError("boom"))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(APIError, match="Failed to fetch client"),
        ):
            await unifi__clients__get_client(client_mac="aa:bb:cc:dd:ee:ff")

    async def test_closes_client_on_success(self, raw_macbook: dict[str, Any]) -> None:
        mock = _mock_client_with_single(raw_macbook)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            await unifi__clients__get_client(client_mac="a4:83:e7:11:22:33")

        mock.close.assert_called_once()

    async def test_closes_client_on_api_error(self) -> None:
        mock = _mock_client_raising(APIError("fail", status_code=500, endpoint="/test"))

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(APIError),
        ):
            await unifi__clients__get_client(client_mac="aa:bb:cc:dd:ee:ff")

        mock.close.assert_called_once()

    async def test_closes_client_on_unexpected_error(self) -> None:
        mock = AsyncMock()
        mock.get_single = AsyncMock(side_effect=ValueError("bad"))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(APIError),
        ):
            await unifi__clients__get_client(client_mac="aa:bb:cc:dd:ee:ff")

        mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# unifi__clients__get_client_traffic
# ---------------------------------------------------------------------------


class TestGetClientTraffic:
    """Integration tests for the get_client_traffic MCP tool."""

    @pytest.fixture()
    def raw_macbook(self) -> dict[str, Any]:
        data = load_fixture("client_list.json")
        return data["data"][0]

    async def test_returns_traffic_dict(self, raw_macbook: dict[str, Any]) -> None:
        mock = _mock_client_with_single(raw_macbook)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__get_client_traffic(
                client_mac="a4:83:e7:11:22:33",
            )

        assert result["client_mac"] == "a4:83:e7:11:22:33"
        assert result["tx_bytes"] == 2847291038
        assert result["rx_bytes"] == 18293746501
        assert result["tx_packets"] == 2847291
        assert result["rx_packets"] == 18293746

    async def test_calls_user_endpoint(self, raw_macbook: dict[str, Any]) -> None:
        mock = _mock_client_with_single(raw_macbook)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            await unifi__clients__get_client_traffic(
                client_mac="a4:83:e7:11:22:33",
                site_id="mysite",
            )

        mock.get_single.assert_called_once_with(
            "/api/s/mysite/stat/user/a4:83:e7:11:22:33",
        )

    async def test_includes_hostname_and_ip(self, raw_macbook: dict[str, Any]) -> None:
        mock = _mock_client_with_single(raw_macbook)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__get_client_traffic(
                client_mac="a4:83:e7:11:22:33",
            )

        assert result["hostname"] == "macbook-pro-jdoe"
        assert result["ip"] == "192.168.1.101"

    async def test_includes_dpi_data_when_present(self) -> None:
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": "test",
            "ip": "10.0.0.1",
            "tx_bytes": 1000,
            "rx_bytes": 2000,
            "tx_packets": 10,
            "rx_packets": 20,
            "dpi_stats": [
                {
                    "cat": "streaming",
                    "app": "netflix",
                    "tx_bytes": 500,
                    "rx_bytes": 1500,
                }
            ],
        }
        mock = _mock_client_with_single(raw)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__get_client_traffic(
                client_mac="aa:bb:cc:dd:ee:ff",
            )

        assert "dpi_stats" in result
        assert result["dpi_stats"][0]["app"] == "netflix"

    async def test_excludes_dpi_when_absent(self, raw_macbook: dict[str, Any]) -> None:
        mock = _mock_client_with_single(raw_macbook)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__get_client_traffic(
                client_mac="a4:83:e7:11:22:33",
            )

        assert "dpi_stats" not in result

    async def test_defaults_to_zero_when_missing(self) -> None:
        raw: dict[str, Any] = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": "minimal",
            "ip": "10.0.0.1",
        }
        mock = _mock_client_with_single(raw)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__get_client_traffic(
                client_mac="aa:bb:cc:dd:ee:ff",
            )

        assert result["tx_bytes"] == 0
        assert result["rx_bytes"] == 0
        assert result["tx_packets"] == 0
        assert result["rx_packets"] == 0

    async def test_propagates_api_error(self) -> None:
        mock = _mock_client_raising(APIError("Not found", status_code=404, endpoint="/test"))

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(APIError, match="Not found"),
        ):
            await unifi__clients__get_client_traffic(
                client_mac="aa:bb:cc:dd:ee:ff",
            )

    async def test_wraps_unexpected_exception(self) -> None:
        mock = AsyncMock()
        mock.get_single = AsyncMock(side_effect=RuntimeError("boom"))
        mock.close = AsyncMock()

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(APIError, match="Failed to fetch traffic"),
        ):
            await unifi__clients__get_client_traffic(
                client_mac="aa:bb:cc:dd:ee:ff",
            )

    async def test_closes_client_on_success(self, raw_macbook: dict[str, Any]) -> None:
        mock = _mock_client_with_single(raw_macbook)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            await unifi__clients__get_client_traffic(
                client_mac="a4:83:e7:11:22:33",
            )

        mock.close.assert_called_once()

    async def test_closes_client_on_error(self) -> None:
        mock = _mock_client_raising(APIError("fail", status_code=500, endpoint="/test"))

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(APIError),
        ):
            await unifi__clients__get_client_traffic(
                client_mac="aa:bb:cc:dd:ee:ff",
            )

        mock.close.assert_called_once()

    async def test_uses_client_mac_param_as_fallback(self) -> None:
        """If 'mac' is missing from response, use the param as fallback."""
        raw: dict[str, Any] = {
            "hostname": "no-mac-client",
            "ip": "10.0.0.1",
        }
        mock = _mock_client_with_single(raw)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__get_client_traffic(
                client_mac="aa:bb:cc:dd:ee:ff",
            )

        assert result["client_mac"] == "aa:bb:cc:dd:ee:ff"


# ---------------------------------------------------------------------------
# unifi__clients__search_clients
# ---------------------------------------------------------------------------


class TestSearchClients:
    """Integration tests for the search_clients MCP tool."""

    @pytest.fixture()
    def fixture_data(self) -> dict[str, Any]:
        return load_fixture("client_list.json")

    async def test_search_by_mac(self, fixture_data: dict[str, Any]) -> None:
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__search_clients(query="a4:83:e7")

        assert len(result) == 1
        assert result[0]["client_mac"] == "a4:83:e7:11:22:33"

    async def test_search_by_hostname(self, fixture_data: dict[str, Any]) -> None:
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__search_clients(query="macbook")

        assert len(result) == 1
        assert result[0]["hostname"] == "macbook-pro-jdoe"

    async def test_search_by_ip(self, fixture_data: dict[str, Any]) -> None:
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__search_clients(query="192.168.1.101")

        assert len(result) == 1
        assert result[0]["ip"] == "192.168.1.101"

    async def test_search_by_ip_subnet(self, fixture_data: dict[str, Any]) -> None:
        """Partial IP match should find multiple clients on the same subnet."""
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__search_clients(query="192.168.1.")

        # macbook (192.168.1.101), pixel (192.168.1.142), synology (192.168.1.50)
        assert len(result) == 3

    async def test_search_by_name_alias(self, fixture_data: dict[str, Any]) -> None:
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__search_clients(query="Synology NAS")

        assert len(result) == 1
        assert result[0]["client_mac"] == "b0:be:76:33:44:55"

    async def test_search_case_insensitive(self, fixture_data: dict[str, Any]) -> None:
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__search_clients(query="MACBOOK")

        assert len(result) == 1
        assert result[0]["hostname"] == "macbook-pro-jdoe"

    async def test_search_no_match(self, fixture_data: dict[str, Any]) -> None:
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__search_clients(
                query="zzz-no-match-zzz",
            )

        assert result == []

    async def test_search_multiple_results(self, fixture_data: dict[str, Any]) -> None:
        """Searching by IoT subnet should find IoT devices."""
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__search_clients(query="192.168.30")

        # sonos (192.168.30.12) + ring-doorbell (192.168.30.25)
        assert len(result) == 2

    async def test_search_empty_data(self) -> None:
        fixture = {"data": [], "meta": {"rc": "ok"}}
        mock = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__search_clients(query="anything")

        assert result == []

    async def test_search_custom_site_id(self, fixture_data: dict[str, Any]) -> None:
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            await unifi__clients__search_clients(query="test", site_id="site-42")

        mock.get_normalized.assert_called_once_with("/api/s/site-42/stat/sta")

    async def test_search_closes_client_on_error(self) -> None:
        mock = _mock_client_raising(NetworkError("timeout", endpoint="/test"))

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(NetworkError),
        ):
            await unifi__clients__search_clients(query="test")

        mock.close.assert_called_once()

    async def test_search_skips_unparseable(self) -> None:
        """Matching but unparseable clients are skipped gracefully."""
        bad_data = {
            "data": [
                {
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "hostname": "good",
                    "ip": "1.2.3.4",
                    "network_id": "vlan1",
                },
                {
                    "mac": "bad-client",
                    "hostname": "bad",
                    # Missing required field 'ip' and 'network_id'
                },
            ],
            "meta": {"rc": "ok"},
        }
        mock = _mock_client_with_normalized(bad_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            # Search for something that matches both
            result = await unifi__clients__search_clients(query="")

        # Both match empty query, but only one parses
        # "bad" client has mac and hostname so matches, but fails validation
        assert len(result) == 1
        assert result[0]["client_mac"] == "aa:bb:cc:dd:ee:ff"

    async def test_search_by_partial_hostname(self, fixture_data: dict[str, Any]) -> None:
        """Search by partial hostname prefix."""
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__search_clients(query="pixel")

        assert len(result) == 1
        assert result[0]["hostname"] == "pixel-8-jsmith"

    async def test_search_doorbell(self, fixture_data: dict[str, Any]) -> None:
        """Search for 'doorbell' should match ring-doorbell hostname."""
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__search_clients(query="doorbell")

        assert len(result) == 1
        assert result[0]["hostname"] == "ring-doorbell"

    async def test_search_by_name_front_door(self, fixture_data: dict[str, Any]) -> None:
        """Search for 'Front Door' should match via the name/alias field."""
        mock = _mock_client_with_normalized(fixture_data)

        with patch("unifi.tools.clients._get_client", return_value=mock):
            result = await unifi__clients__search_clients(query="Front Door")

        assert len(result) == 1
        assert result[0]["client_mac"] == "dc:a6:32:66:77:88"


# ---------------------------------------------------------------------------
# Error propagation and edge cases
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    """Cross-cutting error handling tests."""

    async def test_list_clients_network_error(self) -> None:
        mock = _mock_client_raising(
            NetworkError(
                "Connection refused",
                endpoint="/api/s/default/stat/sta",
            )
        )

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(NetworkError, match="Connection refused"),
        ):
            await unifi__clients__list_clients()

    async def test_get_client_network_error(self) -> None:
        mock = _mock_client_raising(NetworkError("Timeout", endpoint="/test"))

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(NetworkError, match="Timeout"),
        ):
            await unifi__clients__get_client(client_mac="aa:bb:cc:dd:ee:ff")

    async def test_search_clients_api_error(self) -> None:
        mock = _mock_client_raising(APIError("Server error", status_code=500, endpoint="/test"))

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(APIError, match="Server error"),
        ):
            await unifi__clients__search_clients(query="test")

    async def test_traffic_network_error(self) -> None:
        mock = _mock_client_raising(NetworkError("DNS failure", endpoint="/test"))

        with (
            patch("unifi.tools.clients._get_client", return_value=mock),
            pytest.raises(NetworkError, match="DNS failure"),
        ):
            await unifi__clients__get_client_traffic(
                client_mac="aa:bb:cc:dd:ee:ff",
            )
