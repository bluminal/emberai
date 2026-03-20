"""Tests for the clients agent (list_clients_report orchestrator)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from unifi.agents.clients import (
    _client_display_name,
    _connection_info,
    _filter_by_ap,
    _format_bytes,
    _format_signal,
    _format_uptime,
    _traffic_summary,
    list_clients_report,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _build_wireless_client(**overrides: Any) -> dict[str, Any]:
    """Build a wireless client dict matching what list_clients returns."""
    base: dict[str, Any] = {
        "client_mac": "a4:83:e7:11:22:33",
        "hostname": "macbook-pro-jdoe",
        "ip": "192.168.1.101",
        "vlan_id": "5f9a8b7c6d5e4f3a2b1c0001",
        "ap_id": "e0:63:da:cc:55:66",
        "port_id": None,
        "connection_type": "",
        "is_wired": False,
        "is_guest": False,
        "uptime": 43210,
        "ssid": "HomeNet",
        "rssi": 56,
        "tx_bytes": 2847291038,
        "rx_bytes": 18293746501,
    }
    base.update(overrides)
    return base


def _build_wired_client(**overrides: Any) -> dict[str, Any]:
    """Build a wired client dict matching what list_clients returns."""
    base: dict[str, Any] = {
        "client_mac": "b0:be:76:33:44:55",
        "hostname": "synology-nas",
        "ip": "192.168.1.50",
        "vlan_id": "5f9a8b7c6d5e4f3a2b1c0001",
        "ap_id": None,
        "port_id": 4,
        "connection_type": "",
        "is_wired": True,
        "is_guest": False,
        "uptime": 1728432,
        "tx_bytes": 829103847291,
        "rx_bytes": 293847102938,
    }
    base.update(overrides)
    return base


def _build_guest_client(**overrides: Any) -> dict[str, Any]:
    """Build a guest wireless client dict."""
    base: dict[str, Any] = {
        "client_mac": "3c:22:fb:44:55:66",
        "hostname": "iphone-guest-1",
        "ip": "192.168.10.102",
        "vlan_id": "5f9a8b7c6d5e4f3a2b1c0002",
        "ap_id": "e0:63:da:cc:55:66",
        "port_id": None,
        "connection_type": "",
        "is_wired": False,
        "is_guest": True,
        "uptime": 1823,
        "rssi": 32,
        "tx_bytes": 29384710,
        "rx_bytes": 192837465,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestFormatBytes:
    """Verify byte formatting helper."""

    def test_zero(self) -> None:
        assert _format_bytes(0) == "0 B"

    def test_none(self) -> None:
        assert _format_bytes(None) == "0 B"

    def test_bytes(self) -> None:
        assert _format_bytes(512) == "512 B"

    def test_kilobytes(self) -> None:
        assert _format_bytes(1024) == "1.0 KB"

    def test_megabytes(self) -> None:
        assert _format_bytes(1048576) == "1.0 MB"

    def test_gigabytes(self) -> None:
        assert _format_bytes(1073741824) == "1.0 GB"

    def test_terabytes(self) -> None:
        assert _format_bytes(1099511627776) == "1.0 TB"

    def test_large_value(self) -> None:
        # 2.65 GB
        result = _format_bytes(2847291038)
        assert "GB" in result


class TestFormatSignal:
    """Verify signal quality formatting helper."""

    def test_excellent(self) -> None:
        assert _format_signal(55) == "55 (Excellent)"

    def test_good(self) -> None:
        assert _format_signal(40) == "40 (Good)"

    def test_fair(self) -> None:
        assert _format_signal(25) == "25 (Fair)"

    def test_poor(self) -> None:
        assert _format_signal(15) == "15 (Poor)"

    def test_none(self) -> None:
        assert _format_signal(None) == ""

    def test_boundary_excellent(self) -> None:
        assert _format_signal(50) == "50 (Excellent)"

    def test_boundary_good(self) -> None:
        assert _format_signal(35) == "35 (Good)"

    def test_boundary_fair(self) -> None:
        assert _format_signal(20) == "20 (Fair)"


class TestFormatUptime:
    """Verify uptime formatting helper."""

    def test_days_hours_minutes(self) -> None:
        assert _format_uptime(90061) == "1d 1h 1m"

    def test_hours_minutes(self) -> None:
        assert _format_uptime(3660) == "1h 1m"

    def test_zero(self) -> None:
        assert _format_uptime(0) == "0m"

    def test_minutes_only(self) -> None:
        assert _format_uptime(300) == "5m"


class TestClientDisplayName:
    """Verify client display name helper."""

    def test_hostname_present(self) -> None:
        client = _build_wireless_client()
        assert _client_display_name(client) == "macbook-pro-jdoe"

    def test_hostname_missing_falls_back_to_mac(self) -> None:
        client = _build_wireless_client(hostname=None)
        assert _client_display_name(client) == "a4:83:e7:11:22:33"

    def test_empty_hostname_falls_back_to_mac(self) -> None:
        client = _build_wireless_client(hostname="")
        assert _client_display_name(client) == "a4:83:e7:11:22:33"


class TestConnectionInfo:
    """Verify connection info helper."""

    def test_wired_with_port(self) -> None:
        client = _build_wired_client()
        assert _connection_info(client) == "Port 4"

    def test_wired_no_port(self) -> None:
        client = _build_wired_client(port_id=None)
        assert _connection_info(client) == "Wired"

    def test_wireless_with_ap_and_ssid(self) -> None:
        client = _build_wireless_client()
        assert _connection_info(client) == "e0:63:da:cc:55:66 (HomeNet)"

    def test_wireless_with_ap_only(self) -> None:
        client = _build_wireless_client(ssid=None)
        result = _connection_info(client)
        assert "e0:63:da:cc:55:66" in result

    def test_wireless_no_ap(self) -> None:
        client = _build_wireless_client(ap_id=None, ssid=None)
        assert _connection_info(client) == "Wireless"


class TestTrafficSummary:
    """Verify traffic summary helper."""

    def test_both_tx_rx(self) -> None:
        client = _build_wireless_client(tx_bytes=1024, rx_bytes=2048)
        result = _traffic_summary(client)
        assert "TX:" in result
        assert "RX:" in result

    def test_no_traffic(self) -> None:
        client = _build_wireless_client(tx_bytes=None, rx_bytes=None)
        assert _traffic_summary(client) == ""


class TestFilterByAp:
    """Verify AP filter helper."""

    def test_no_filter(self) -> None:
        clients = [_build_wireless_client(), _build_wired_client()]
        result = _filter_by_ap(clients, None)
        assert len(result) == 2

    def test_filter_matches(self) -> None:
        clients = [
            _build_wireless_client(ap_id="e0:63:da:cc:55:66"),
            _build_wireless_client(
                client_mac="xx:xx:xx:xx:xx:xx",
                ap_id="aa:bb:cc:dd:ee:ff",
            ),
        ]
        result = _filter_by_ap(clients, "e0:63:da:cc:55:66")
        assert len(result) == 1
        assert result[0]["client_mac"] == "a4:83:e7:11:22:33"

    def test_filter_no_match(self) -> None:
        clients = [_build_wireless_client()]
        result = _filter_by_ap(clients, "ff:ff:ff:ff:ff:ff")
        assert len(result) == 0

    def test_filter_wired_clients_excluded(self) -> None:
        clients = [_build_wired_client()]
        result = _filter_by_ap(clients, "e0:63:da:cc:55:66")
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Agent orchestration tests
# ---------------------------------------------------------------------------


class TestListClientsReport:
    """Tests for the list_clients_report agent function."""

    async def test_report_with_clients(self) -> None:
        """Report includes summary and client table."""
        mock_list = AsyncMock(return_value=[
            _build_wireless_client(),
            _build_wired_client(),
        ])

        with patch(
            "unifi.agents.clients.unifi__clients__list_clients", mock_list,
        ):
            result = await list_clients_report()

        assert "## Client Inventory" in result
        assert "**Total:** 2" in result
        assert "**Wireless:** 1" in result
        assert "**Wired:** 1" in result
        assert "macbook-pro-jdoe" in result
        assert "synology-nas" in result

    async def test_report_empty(self) -> None:
        """Report handles empty client list gracefully."""
        mock_list = AsyncMock(return_value=[])

        with patch(
            "unifi.agents.clients.unifi__clients__list_clients", mock_list,
        ):
            result = await list_clients_report()

        assert "## Client Inventory" in result
        assert "**Total:** 0" in result
        assert "No clients found" in result

    async def test_report_passes_vlan_filter(self) -> None:
        """VLAN filter is passed through to list_clients."""
        mock_list = AsyncMock(return_value=[])

        with patch(
            "unifi.agents.clients.unifi__clients__list_clients", mock_list,
        ):
            await list_clients_report(vlan_id="vlan-123")

        mock_list.assert_called_once_with("default", vlan_id="vlan-123")

    async def test_report_applies_ap_filter(self) -> None:
        """AP filter is applied client-side after fetching."""
        mock_list = AsyncMock(return_value=[
            _build_wireless_client(ap_id="e0:63:da:cc:55:66"),
            _build_wireless_client(
                client_mac="xx:xx:xx:xx:xx:xx",
                hostname="other-device",
                ap_id="aa:bb:cc:dd:ee:ff",
            ),
        ])

        with patch(
            "unifi.agents.clients.unifi__clients__list_clients", mock_list,
        ):
            result = await list_clients_report(ap_id="e0:63:da:cc:55:66")

        assert "**Total:** 1" in result
        assert "macbook-pro-jdoe" in result
        assert "other-device" not in result

    async def test_report_custom_site_id(self) -> None:
        """Custom site_id is passed through to list_clients."""
        mock_list = AsyncMock(return_value=[])

        with patch(
            "unifi.agents.clients.unifi__clients__list_clients", mock_list,
        ):
            await list_clients_report(site_id="branch")

        mock_list.assert_called_once_with("branch", vlan_id=None)

    async def test_report_guest_count(self) -> None:
        """Report shows guest count when guests are present."""
        mock_list = AsyncMock(return_value=[
            _build_wireless_client(),
            _build_guest_client(),
        ])

        with patch(
            "unifi.agents.clients.unifi__clients__list_clients", mock_list,
        ):
            result = await list_clients_report()

        assert "**Guests:** 1" in result

    async def test_report_no_guest_count_when_zero(self) -> None:
        """Report omits guest count when no guests."""
        mock_list = AsyncMock(return_value=[_build_wireless_client()])

        with patch(
            "unifi.agents.clients.unifi__clients__list_clients", mock_list,
        ):
            result = await list_clients_report()

        assert "Guests" not in result

    async def test_report_filters_detail_line(self) -> None:
        """Report shows filter details when filters are applied."""
        mock_list = AsyncMock(return_value=[])

        with patch(
            "unifi.agents.clients.unifi__clients__list_clients", mock_list,
        ):
            result = await list_clients_report(
                vlan_id="vlan-123", ap_id="aa:bb:cc:dd:ee:ff",
            )

        assert "Filters:" in result
        assert "VLAN: vlan-123" in result
        assert "AP: aa:bb:cc:dd:ee:ff" in result

    async def test_report_signal_column_for_wireless(self) -> None:
        """Wireless clients show signal quality in the table."""
        mock_list = AsyncMock(return_value=[_build_wireless_client(rssi=56)])

        with patch(
            "unifi.agents.clients.unifi__clients__list_clients", mock_list,
        ):
            result = await list_clients_report()

        assert "Excellent" in result

    async def test_report_returns_string(self) -> None:
        """list_clients_report returns a string."""
        mock_list = AsyncMock(return_value=[])

        with patch(
            "unifi.agents.clients.unifi__clients__list_clients", mock_list,
        ):
            result = await list_clients_report()

        assert isinstance(result, str)
