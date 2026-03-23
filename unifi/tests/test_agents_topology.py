"""Tests for the topology agent (scan_site orchestrator)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from tests.fixtures import load_fixture
from unifi.agents.topology import _format_speed, _format_uptime, scan_site
from unifi.tools.topology import _is_vlan_network

# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestFormatUptime:
    """Verify uptime formatting helper."""

    def test_days_hours_minutes(self) -> None:
        assert _format_uptime(90061) == "1d 1h 1m"

    def test_hours_minutes(self) -> None:
        assert _format_uptime(3660) == "1h 1m"

    def test_zero(self) -> None:
        assert _format_uptime(0) == "0m"

    def test_exact_day(self) -> None:
        assert _format_uptime(86400) == "1d 0h 0m"

    def test_exact_hour(self) -> None:
        assert _format_uptime(3600) == "1h 0m"

    def test_large_uptime(self) -> None:
        # 20 days, 3 hours, 27 minutes
        seconds = 20 * 86400 + 3 * 3600 + 27 * 60
        assert _format_uptime(seconds) == "20d 3h 27m"

    def test_minutes_only(self) -> None:
        assert _format_uptime(300) == "5m"


class TestFormatSpeed:
    """Verify speed formatting helper."""

    def test_10gbps(self) -> None:
        assert _format_speed(10000) == "10 Gbps"

    def test_1gbps(self) -> None:
        assert _format_speed(1000) == "1 Gbps"

    def test_100mbps(self) -> None:
        assert _format_speed(100) == "100 Mbps"

    def test_none(self) -> None:
        assert _format_speed(None) == ""

    def test_2_5gbps(self) -> None:
        assert _format_speed(2500) == "2 Gbps"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _build_device_dicts() -> list[dict[str, Any]]:
    """Build normalized device dicts matching what list_devices returns.

    These mirror the fixture data after Pydantic normalization (by_alias=False).
    """
    return [
        {
            "device_id": "64a1b2c3d4e5f6a7b8c9d0e1",
            "name": "USG-Gateway",
            "model": "UXG-Max",
            "mac": "f0:9f:c2:aa:11:22",
            "ip": "192.168.1.1",
            "status": "connected",
            "uptime": 1728432,
            "firmware": "4.0.6.6754",
            "product_line": "",
            "is_console": False,
            "port_table": None,
            "uplink": None,
            "vlan_assignments": None,
            "radio_table": None,
            "config_network": {
                "type": "dhcp",
                "ip": "192.168.1.1",
            },
        },
        {
            "device_id": "64b2c3d4e5f6a7b8c9d0e1f2",
            "name": "Office-Switch-16",
            "model": "USLITE16P",
            "mac": "74:ac:b9:bb:33:44",
            "ip": "192.168.1.10",
            "status": "connected",
            "uptime": 864210,
            "firmware": "7.0.50.15116",
            "product_line": "",
            "is_console": False,
            "port_table": None,
            "uplink": None,
            "vlan_assignments": None,
            "radio_table": None,
            "config_network": None,
        },
        {
            "device_id": "64c3d4e5f6a7b8c9d0e1f2a3",
            "name": "Office-AP-Main",
            "model": "U6-Pro",
            "mac": "e0:63:da:cc:55:66",
            "ip": "192.168.1.20",
            "status": "connected",
            "uptime": 1728430,
            "firmware": "7.0.76.15293",
            "product_line": "",
            "is_console": False,
            "port_table": None,
            "uplink": None,
            "vlan_assignments": None,
            "radio_table": None,
            "config_network": None,
        },
    ]


def _build_vlan_dicts() -> list[dict[str, Any]]:
    """Build normalized VLAN dicts matching what get_vlans returns.

    Filtered to only LAN/VLAN entries (no WANs) and normalized via Pydantic.
    """
    raw_fixture = load_fixture("vlan_config.json")
    vlans: list[dict[str, Any]] = []
    for network in raw_fixture["data"]:
        if not _is_vlan_network(network):
            continue
        vlans.append(
            {
                "vlan_id": network["_id"],
                "name": network["name"],
                "subnet": network.get("ip_subnet", ""),
                "purpose": network.get("purpose", "corporate"),
                "dhcp_enabled": network.get("dhcpd_enabled", False),
                "domain_name": network.get("domain_name"),
            }
        )
    return vlans


def _build_uplink_dicts() -> list[dict[str, Any]]:
    """Build uplink graph dicts matching what get_uplinks returns."""
    return [
        {
            "device_id": "64b2c3d4e5f6a7b8c9d0e1f2",
            "device_name": "Office-Switch-16",
            "device_mac": "74:ac:b9:bb:33:44",
            "uplink_device_id": "64a1b2c3d4e5f6a7b8c9d0e1",
            "uplink_device_name": "USG-Gateway",
            "uplink_device_mac": "f0:9f:c2:aa:11:22",
            "uplink_port": 1,
            "uplink_type": "wire",
            "speed": 10000,
        },
        {
            "device_id": "64c3d4e5f6a7b8c9d0e1f2a3",
            "device_name": "Office-AP-Main",
            "device_mac": "e0:63:da:cc:55:66",
            "uplink_device_id": "64b2c3d4e5f6a7b8c9d0e1f2",
            "uplink_device_name": "Office-Switch-16",
            "uplink_device_mac": "74:ac:b9:bb:33:44",
            "uplink_port": 1,
            "uplink_type": "wire",
            "speed": 1000,
        },
    ]


# ---------------------------------------------------------------------------
# scan_site tests
# ---------------------------------------------------------------------------


class TestScanSite:
    """Test the scan_site topology agent."""

    async def test_scan_with_fixture_data(self) -> None:
        """Full scan with realistic fixture data produces expected report."""
        mock_list_devices = AsyncMock(return_value=_build_device_dicts())
        mock_get_vlans = AsyncMock(return_value=_build_vlan_dicts())
        mock_get_uplinks = AsyncMock(return_value=_build_uplink_dicts())

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site(site_id="default")

        # Tools called with correct site_id
        mock_list_devices.assert_called_once_with("default")
        mock_get_vlans.assert_called_once_with("default")
        mock_get_uplinks.assert_called_once_with("default")

        # Summary section
        assert "## Site Scan Complete" in result
        assert "**Devices:** 3" in result
        assert "**VLANs:** 4" in result
        assert "**Uplinks:** 2" in result

    async def test_scan_device_table_content(self) -> None:
        """Device table contains correct headers and device data."""
        mock_list_devices = AsyncMock(return_value=_build_device_dicts())
        mock_get_vlans = AsyncMock(return_value=_build_vlan_dicts())
        mock_get_uplinks = AsyncMock(return_value=_build_uplink_dicts())

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site()

        # Device table headers
        assert "### Devices" in result
        assert "| Name" in result
        assert "Model" in result
        assert "IP" in result
        assert "Status" in result
        assert "Firmware" in result
        assert "Uptime" in result

        # Device data
        assert "USG-Gateway" in result
        assert "UXG-Max" in result
        assert "192.168.1.1" in result
        assert "connected" in result
        assert "4.0.6.6754" in result
        assert "Office-Switch-16" in result
        assert "Office-AP-Main" in result

    async def test_scan_vlan_table_content(self) -> None:
        """VLAN table contains correct headers and VLAN data."""
        mock_list_devices = AsyncMock(return_value=_build_device_dicts())
        mock_get_vlans = AsyncMock(return_value=_build_vlan_dicts())
        mock_get_uplinks = AsyncMock(return_value=_build_uplink_dicts())

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site()

        # VLAN table headers
        assert "### VLANs" in result
        assert "VLAN ID" in result
        assert "Subnet" in result
        assert "DHCP" in result
        assert "Purpose" in result

        # VLAN data
        assert "Default" in result
        assert "192.168.1.0/24" in result
        assert "Guest" in result
        assert "192.168.10.0/24" in result
        assert "IoT" in result
        assert "Management" in result

    async def test_scan_uplink_table_content(self) -> None:
        """Uplink table contains correct headers and topology data."""
        mock_list_devices = AsyncMock(return_value=_build_device_dicts())
        mock_get_vlans = AsyncMock(return_value=_build_vlan_dicts())
        mock_get_uplinks = AsyncMock(return_value=_build_uplink_dicts())

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site()

        # Uplink table headers
        assert "### Uplinks" in result
        assert "Device -> Parent" in result
        assert "Port" in result
        assert "Speed" in result
        assert "Type" in result

        # Uplink data
        assert "Office-Switch-16 -> USG-Gateway" in result
        assert "10 Gbps" in result
        assert "Office-AP-Main -> Office-Switch-16" in result
        assert "1 Gbps" in result
        assert "wire" in result

    async def test_scan_empty_site(self) -> None:
        """Scan of an empty site returns summary with zero counts and no tables."""
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_vlans = AsyncMock(return_value=[])
        mock_get_uplinks = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site(site_id="empty-site")

        # Summary present with zero counts
        assert "## Site Scan Complete" in result
        assert "**Devices:** 0" in result
        assert "**VLANs:** 0" in result
        assert "**Uplinks:** 0" in result

        # No table sections when empty
        assert "### Devices" not in result
        assert "### VLANs" not in result
        assert "### Uplinks" not in result

    async def test_scan_custom_site_id(self) -> None:
        """Custom site_id is passed through to all tool calls."""
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_vlans = AsyncMock(return_value=[])
        mock_get_uplinks = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            await scan_site(site_id="my-remote-site")

        mock_list_devices.assert_called_once_with("my-remote-site")
        mock_get_vlans.assert_called_once_with("my-remote-site")
        mock_get_uplinks.assert_called_once_with("my-remote-site")

    async def test_scan_uses_ox_format_table(self) -> None:
        """Verify output uses OX format_table (markdown table structure)."""
        mock_list_devices = AsyncMock(return_value=_build_device_dicts())
        mock_get_vlans = AsyncMock(return_value=_build_vlan_dicts())
        mock_get_uplinks = AsyncMock(return_value=_build_uplink_dicts())

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site()

        # OX format_table produces markdown tables with pipes and separator rows
        table_lines = [line for line in result.split("\n") if line.startswith("|")]
        # We expect: 3 tables x (header + separator + data rows)
        # Devices: 1 header + 1 sep + 3 rows = 5
        # VLANs: 1 header + 1 sep + 4 rows = 6
        # Uplinks: 1 header + 1 sep + 2 rows = 4
        assert len(table_lines) == 15

        # Separator rows use dashes
        sep_lines = [line for line in table_lines if "---" in line]
        assert len(sep_lines) == 3  # One per table

    async def test_scan_uses_ox_format_summary(self) -> None:
        """Verify output uses OX format_summary (pipe-separated stats line)."""
        mock_list_devices = AsyncMock(return_value=_build_device_dicts())
        mock_get_vlans = AsyncMock(return_value=[])
        mock_get_uplinks = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site()

        # OX format_summary uses pipe-separated stats
        assert "**Devices:** 3 | **VLANs:** 0 | **Uplinks:** 0" in result

    async def test_scan_devices_only(self) -> None:
        """Scan with devices but no VLANs/uplinks shows only device table."""
        mock_list_devices = AsyncMock(return_value=_build_device_dicts()[:1])
        mock_get_vlans = AsyncMock(return_value=[])
        mock_get_uplinks = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site()

        assert "### Devices" in result
        assert "### VLANs" not in result
        assert "### Uplinks" not in result
        assert "**Devices:** 1" in result

    async def test_scan_uptime_formatting(self) -> None:
        """Device uptime values are human-readable in the report."""
        mock_list_devices = AsyncMock(return_value=_build_device_dicts())
        mock_get_vlans = AsyncMock(return_value=[])
        mock_get_uplinks = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site()

        # 1728432 seconds = 20d 0h 7m
        assert "20d 0h 7m" in result
        # 864210 seconds = 10d 0h 3m
        assert "10d 0h 3m" in result

    async def test_scan_default_site_id(self) -> None:
        """Calling scan_site without arguments defaults to 'default' site."""
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_vlans = AsyncMock(return_value=[])
        mock_get_uplinks = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            await scan_site()

        mock_list_devices.assert_called_once_with("default")
        mock_get_vlans.assert_called_once_with("default")
        mock_get_uplinks.assert_called_once_with("default")
