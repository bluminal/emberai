# SPDX-License-Identifier: MIT
"""Tests for multi-site scan flow (Task 50).

Verifies that scan_site() uses Cloud V1 API for site discovery when
UNIFI_API_KEY is configured, and falls back to single-site mode otherwise.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from unifi.agents.topology import (
    _format_site_list,
    _has_cloud_api_key,
    scan_site,
)
from unifi.errors import AuthenticationError

# ---------------------------------------------------------------------------
# _has_cloud_api_key
# ---------------------------------------------------------------------------


class TestHasCloudApiKey:
    """Verify the Cloud API key detection helper."""

    def test_key_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "my-cloud-key")
        assert _has_cloud_api_key() is True

    def test_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNIFI_API_KEY", raising=False)
        assert _has_cloud_api_key() is False

    def test_key_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "")
        assert _has_cloud_api_key() is False

    def test_key_whitespace_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "   ")
        assert _has_cloud_api_key() is False


# ---------------------------------------------------------------------------
# _format_site_list
# ---------------------------------------------------------------------------


class TestFormatSiteList:
    """Verify the site list formatting helper."""

    def test_formats_multiple_sites(self) -> None:
        sites: list[dict[str, object]] = [
            {
                "name": "Main Office",
                "site_id": "site001",
                "description": "Primary site",
                "device_count": 12,
                "client_count": 45,
            },
            {
                "name": "Branch",
                "site_id": "site002",
                "description": "Secondary",
                "device_count": 5,
                "client_count": 15,
            },
        ]
        result = _format_site_list(sites)

        assert "## Multiple Sites Found" in result
        assert "**Sites:** 2" in result
        assert "### Available Sites" in result
        assert "Main Office" in result
        assert "Branch" in result
        assert "site001" in result
        assert "site002" in result

    def test_formats_empty_sites(self) -> None:
        result = _format_site_list([])

        assert "## Multiple Sites Found" in result
        assert "**Sites:** 0" in result

    def test_contains_usage_hint(self) -> None:
        sites: list[dict[str, object]] = [
            {
                "name": "Site A",
                "site_id": "s1",
                "description": "",
                "device_count": 1,
                "client_count": 0,
            },
        ]
        result = _format_site_list(sites)

        assert "site_id" in result

    def test_table_headers_present(self) -> None:
        sites: list[dict[str, object]] = [
            {
                "name": "Site",
                "site_id": "s1",
                "description": "D",
                "device_count": 1,
                "client_count": 2,
            },
        ]
        result = _format_site_list(sites)

        assert "Name" in result
        assert "Site ID" in result
        assert "Description" in result
        assert "Devices" in result
        assert "Clients" in result


# ---------------------------------------------------------------------------
# scan_site: Multi-site flow with UNIFI_API_KEY
# ---------------------------------------------------------------------------


class TestScanSiteMultiSite:
    """Test scan_site when UNIFI_API_KEY is configured."""

    @pytest.fixture(autouse=True)
    def _set_cloud_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "test-cloud-key")

    async def test_multiple_sites_returns_site_list(self) -> None:
        """When multiple sites are discovered, return a site list instead of scanning."""
        mock_list_sites = AsyncMock(
            return_value=[
                {
                    "name": "Main",
                    "site_id": "s1",
                    "description": "",
                    "device_count": 5,
                    "client_count": 20,
                },
                {
                    "name": "Branch",
                    "site_id": "s2",
                    "description": "",
                    "device_count": 3,
                    "client_count": 10,
                },
            ],
        )

        with patch("unifi.agents.topology.unifi__topology__list_sites", mock_list_sites):
            result = await scan_site()

        mock_list_sites.assert_called_once()
        assert "## Multiple Sites Found" in result
        assert "Main" in result
        assert "Branch" in result

    async def test_single_site_proceeds_with_scan(self) -> None:
        """When only one site is discovered, scan it automatically."""
        mock_list_sites = AsyncMock(
            return_value=[
                {
                    "name": "OnlySite",
                    "site_id": "only1",
                    "description": "",
                    "device_count": 3,
                    "client_count": 10,
                },
            ],
        )
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_vlans = AsyncMock(return_value=[])
        mock_get_uplinks = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.topology.unifi__topology__list_sites", mock_list_sites),
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site()

        # Should have called list_sites, then proceeded with single-site scan
        mock_list_sites.assert_called_once()
        # The discovered site name is used as the site_id
        mock_list_devices.assert_called_once_with("OnlySite")
        mock_get_vlans.assert_called_once_with("OnlySite")
        mock_get_uplinks.assert_called_once_with("OnlySite")
        assert "## Site Scan Complete" in result

    async def test_no_sites_falls_back_to_default(self) -> None:
        """When list_sites returns empty, fall back to 'default' site."""
        mock_list_sites = AsyncMock(return_value=[])
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_vlans = AsyncMock(return_value=[])
        mock_get_uplinks = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.topology.unifi__topology__list_sites", mock_list_sites),
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site()

        mock_list_sites.assert_called_once()
        mock_list_devices.assert_called_once_with("default")
        assert "## Site Scan Complete" in result

    async def test_auth_error_falls_back_to_single_site(self) -> None:
        """When Cloud V1 auth fails, fall back to single-site scan gracefully."""
        mock_list_sites = AsyncMock(
            side_effect=AuthenticationError(
                "Authentication failed",
                env_var="UNIFI_API_KEY",
            ),
        )
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_vlans = AsyncMock(return_value=[])
        mock_get_uplinks = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.topology.unifi__topology__list_sites", mock_list_sites),
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site()

        # Should not raise -- falls back to default scan
        mock_list_devices.assert_called_once_with("default")
        assert "## Site Scan Complete" in result

    async def test_explicit_site_id_skips_discovery(self) -> None:
        """When an explicit site_id is provided, skip Cloud V1 discovery."""
        mock_list_sites = AsyncMock()
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_vlans = AsyncMock(return_value=[])
        mock_get_uplinks = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.topology.unifi__topology__list_sites", mock_list_sites),
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site(site_id="explicit-site")

        # list_sites should NOT be called when site_id is explicit
        mock_list_sites.assert_not_called()
        mock_list_devices.assert_called_once_with("explicit-site")
        assert "## Site Scan Complete" in result

    async def test_three_sites_returns_all_in_list(self) -> None:
        """When 3+ sites are found, all should appear in the site list."""
        mock_list_sites = AsyncMock(
            return_value=[
                {
                    "name": "HQ",
                    "site_id": "s1",
                    "description": "Headquarters",
                    "device_count": 20,
                    "client_count": 100,
                },
                {
                    "name": "Branch A",
                    "site_id": "s2",
                    "description": "Branch A",
                    "device_count": 5,
                    "client_count": 15,
                },
                {
                    "name": "Branch B",
                    "site_id": "s3",
                    "description": "Branch B",
                    "device_count": 3,
                    "client_count": 8,
                },
            ],
        )

        with patch("unifi.agents.topology.unifi__topology__list_sites", mock_list_sites):
            result = await scan_site()

        assert "## Multiple Sites Found" in result
        assert "**Sites:** 3" in result
        assert "HQ" in result
        assert "Branch A" in result
        assert "Branch B" in result


# ---------------------------------------------------------------------------
# scan_site: Single-site mode (no UNIFI_API_KEY)
# ---------------------------------------------------------------------------


class TestScanSiteSingleSite:
    """Test scan_site when UNIFI_API_KEY is NOT configured (Phase 1 behavior)."""

    @pytest.fixture(autouse=True)
    def _clear_cloud_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNIFI_API_KEY", raising=False)

    async def test_no_cloud_key_uses_default_site(self) -> None:
        """Without UNIFI_API_KEY, scan proceeds with default site_id."""
        mock_list_sites = AsyncMock()
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_vlans = AsyncMock(return_value=[])
        mock_get_uplinks = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.topology.unifi__topology__list_sites", mock_list_sites),
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site()

        # list_sites should NOT be called
        mock_list_sites.assert_not_called()
        mock_list_devices.assert_called_once_with("default")
        assert "## Site Scan Complete" in result

    async def test_no_cloud_key_custom_site_id(self) -> None:
        """Without UNIFI_API_KEY, custom site_id is used directly."""
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_vlans = AsyncMock(return_value=[])
        mock_get_uplinks = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site(site_id="my-site")

        mock_list_devices.assert_called_once_with("my-site")
        mock_get_vlans.assert_called_once_with("my-site")
        mock_get_uplinks.assert_called_once_with("my-site")
        assert "## Site Scan Complete" in result

    async def test_scan_report_structure_preserved(self) -> None:
        """The scan report should maintain the same structure as before."""
        devices = [
            {
                "device_id": "d1",
                "name": "Gateway",
                "model": "UXG-Max",
                "mac": "aa:bb:cc:dd:ee:ff",
                "ip": "192.168.1.1",
                "status": "connected",
                "uptime": 86400,
                "firmware": "4.0.6",
            },
        ]
        vlans = [
            {
                "name": "Default",
                "vlan_id": "v1",
                "subnet": "192.168.1.0/24",
                "dhcp_enabled": True,
                "purpose": "corporate",
            },
        ]
        uplinks: list[dict[str, Any]] = []

        mock_list_devices = AsyncMock(return_value=devices)
        mock_get_vlans = AsyncMock(return_value=vlans)
        mock_get_uplinks = AsyncMock(return_value=uplinks)

        with (
            patch("unifi.agents.topology.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.topology.unifi__topology__get_vlans", mock_get_vlans),
            patch("unifi.agents.topology.unifi__topology__get_uplinks", mock_get_uplinks),
        ):
            result = await scan_site()

        assert "## Site Scan Complete" in result
        assert "**Devices:** 1" in result
        assert "**VLANs:** 1" in result
        assert "**Uplinks:** 0" in result
        assert "### Devices" in result
        assert "Gateway" in result
        assert "### VLANs" in result
        assert "Default" in result


# ---------------------------------------------------------------------------
# unifi_scan command tool (Task 50)
# ---------------------------------------------------------------------------


class TestUnifiScanCommand:
    """Verify the unifi_scan command delegates correctly."""

    async def test_scan_delegates_to_scan_site(self) -> None:
        """unifi_scan should still delegate to scan_site."""
        from unifi.tools.commands import unifi_scan

        mock_scan = AsyncMock(return_value="## Site Scan Complete\nreport")

        with patch("unifi.agents.topology.scan_site", mock_scan):
            result = await unifi_scan()

        assert result == "## Site Scan Complete\nreport"
        mock_scan.assert_called_once_with("default")

    async def test_scan_passes_site_id(self) -> None:
        """unifi_scan should pass custom site_id to scan_site."""
        from unifi.tools.commands import unifi_scan

        mock_scan = AsyncMock(return_value="report")

        with patch("unifi.agents.topology.scan_site", mock_scan):
            await unifi_scan(site_id="branch")

        mock_scan.assert_called_once_with("branch")
