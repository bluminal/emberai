# SPDX-License-Identifier: MIT
"""Comprehensive tests for analytics tools and analytics dashboard agent.

Covers all 11 analytics MCP tools:
- get_status (with time range and device filter variants)
- get_top_domains (with status filter and pagination)
- get_block_reasons
- get_devices (including empty response)
- get_protocols (unencrypted warning detection)
- get_encryption (computed fields, high unencrypted warning)
- get_destinations (countries and GAFAM types)
- get_ips
- get_query_types
- get_ip_versions
- get_dnssec

Also covers the analytics_dashboard agent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from nextdns.agents.analytics import analytics_dashboard
from nextdns.tools.analytics import (
    nextdns__analytics__get_block_reasons,
    nextdns__analytics__get_destinations,
    nextdns__analytics__get_devices,
    nextdns__analytics__get_dnssec,
    nextdns__analytics__get_encryption,
    nextdns__analytics__get_ip_versions,
    nextdns__analytics__get_ips,
    nextdns__analytics__get_protocols,
    nextdns__analytics__get_query_types,
    nextdns__analytics__get_status,
    nextdns__analytics__get_top_domains,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict[str, Any] | list[dict[str, Any]]:
    """Load a JSON fixture file and return parsed data."""
    with open(_FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture()
def analytics_status_fixture() -> dict[str, Any]:
    return _load_fixture("analytics_status.json")


@pytest.fixture()
def analytics_domains_fixture() -> dict[str, Any]:
    return _load_fixture("analytics_domains.json")


@pytest.fixture()
def analytics_encryption_fixture() -> dict[str, Any]:
    return _load_fixture("analytics_encryption.json")


@pytest.fixture()
def analytics_protocols_fixture() -> dict[str, Any]:
    return _load_fixture("analytics_protocols.json")


@pytest.fixture()
def analytics_devices_fixture() -> dict[str, Any]:
    return _load_fixture("analytics_devices.json")


@pytest.fixture()
def analytics_zero_queries_fixture() -> dict[str, Any]:
    return _load_fixture("analytics_zero_queries.json")


@pytest.fixture()
def mock_client() -> AsyncMock:
    """Create a mock CachedNextDNSClient."""
    return AsyncMock()


@pytest.fixture(autouse=True)
def _reset_client_factory():
    """Reset the client factory singleton before each test."""
    from nextdns.tools._client_factory import reset_client

    reset_client()
    yield
    reset_client()


# ---------------------------------------------------------------------------
# get_status tests
# ---------------------------------------------------------------------------


class TestGetStatus:
    """Tests for nextdns__analytics__get_status()."""

    async def test_get_status(self, mock_client, analytics_status_fixture):
        """Returns correct counts for each status type."""
        mock_client.get = AsyncMock(return_value=analytics_status_fixture)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_status("abc123")

        assert len(result) == 3
        assert result[0]["status"] == "default"
        assert result[0]["queries"] == 45230
        assert result[1]["status"] == "blocked"
        assert result[1]["queries"] == 8456
        assert result[2]["status"] == "allowed"
        assert result[2]["queries"] == 123

        # Verify correct endpoint was called.
        mock_client.get.assert_awaited_once_with(
            "/profiles/abc123/analytics/status", params=None
        )

    async def test_get_status_with_time_range(self, mock_client, analytics_status_fixture):
        """Verifies from/to params are passed to the client."""
        mock_client.get = AsyncMock(return_value=analytics_status_fixture)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            await nextdns__analytics__get_status(
                "abc123", from_time="-7d", to_time="-1d"
            )

        mock_client.get.assert_awaited_once_with(
            "/profiles/abc123/analytics/status",
            params={"from": "-7d", "to": "-1d"},
        )

    async def test_get_status_with_device_filter(self, mock_client, analytics_status_fixture):
        """Verifies device param is passed to the client."""
        mock_client.get = AsyncMock(return_value=analytics_status_fixture)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            await nextdns__analytics__get_status("abc123", device="iPhone-13")

        mock_client.get.assert_awaited_once_with(
            "/profiles/abc123/analytics/status",
            params={"device": "iPhone-13"},
        )


# ---------------------------------------------------------------------------
# get_top_domains tests
# ---------------------------------------------------------------------------


class TestGetTopDomains:
    """Tests for nextdns__analytics__get_top_domains()."""

    async def test_get_top_domains(self, mock_client, analytics_domains_fixture):
        """Returns domain list with correct fields via paginated client."""
        mock_client.get_paginated = AsyncMock(
            return_value=analytics_domains_fixture["data"]
        )

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_top_domains("abc123")

        assert len(result) == 5
        assert result[0]["name"] == "google.com"
        assert result[0]["queries"] == 5420
        assert result[0]["root"] == "google.com"

        # Verify pagination call.
        mock_client.get_paginated.assert_awaited_once_with(
            "/profiles/abc123/analytics/domains", params=None, limit=None
        )

    async def test_get_top_domains_with_status_filter(
        self, mock_client, analytics_domains_fixture
    ):
        """Verifies status filter param is passed to the client."""
        mock_client.get_paginated = AsyncMock(
            return_value=analytics_domains_fixture["data"][:2]
        )

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_top_domains(
                "abc123", status="blocked", limit=10
            )

        assert len(result) == 2
        mock_client.get_paginated.assert_awaited_once_with(
            "/profiles/abc123/analytics/domains",
            params={"status": "blocked"},
            limit=10,
        )


# ---------------------------------------------------------------------------
# get_block_reasons tests
# ---------------------------------------------------------------------------


class TestGetBlockReasons:
    """Tests for nextdns__analytics__get_block_reasons()."""

    async def test_get_block_reasons(self, mock_client):
        """Returns reasons list with name and query count."""
        reasons_data = {
            "data": [
                {"name": "NextDNS Recommended", "queries": 5200},
                {"name": "OISD", "queries": 2100},
                {"name": "Parental Control", "queries": 800},
            ]
        }
        mock_client.get = AsyncMock(return_value=reasons_data)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_block_reasons("abc123")

        assert len(result) == 3
        assert result[0]["name"] == "NextDNS Recommended"
        assert result[0]["queries"] == 5200
        assert result[2]["name"] == "Parental Control"
        assert result[2]["queries"] == 800


# ---------------------------------------------------------------------------
# get_devices tests
# ---------------------------------------------------------------------------


class TestGetDevices:
    """Tests for nextdns__analytics__get_devices()."""

    async def test_get_devices(self, mock_client, analytics_devices_fixture):
        """Returns device list with various fields including aliases."""
        mock_client.get = AsyncMock(return_value=analytics_devices_fixture)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_devices("abc123")

        assert len(result) == 4

        # First device: named device with all fields.
        assert result[0]["id"] == "iPhone-13"
        assert result[0]["name"] == "Dad's iPhone"
        assert result[0]["model"] == "Apple iPhone 13"
        # by_alias=True: localIp should use alias.
        assert result[0]["localIp"] == "10.0.50.101"
        assert result[0]["queries"] == 12340

        # Unidentified device has null name/model.
        unidentified = result[3]
        assert unidentified["id"] == "__UNIDENTIFIED__"
        assert unidentified["name"] is None
        assert unidentified["model"] is None

    async def test_get_devices_empty(self, mock_client):
        """Returns empty list when no devices have activity."""
        mock_client.get = AsyncMock(return_value={"data": []})

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_devices("abc123")

        assert result == []


# ---------------------------------------------------------------------------
# get_protocols tests
# ---------------------------------------------------------------------------


class TestGetProtocols:
    """Tests for nextdns__analytics__get_protocols()."""

    async def test_get_protocols_with_unencrypted(
        self, mock_client, analytics_protocols_fixture
    ):
        """Sets unencrypted_warning when UDP has queries > 0."""
        mock_client.get = AsyncMock(return_value=analytics_protocols_fixture)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_protocols("abc123")

        assert "protocols" in result
        assert len(result["protocols"]) == 4
        assert result["protocols"][0]["name"] == "DNS-over-HTTPS"
        assert result["protocols"][0]["queries"] == 38900
        # UDP has 2569 queries -- should trigger warning.
        assert result["unencrypted_warning"] is True

    async def test_get_protocols_all_encrypted(self, mock_client):
        """No warning when all protocols are encrypted."""
        all_encrypted = {
            "data": [
                {"name": "DNS-over-HTTPS", "queries": 38900},
                {"name": "DNS-over-TLS", "queries": 12340},
                {"name": "DNS-over-QUIC", "queries": 500},
            ]
        }
        mock_client.get = AsyncMock(return_value=all_encrypted)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_protocols("abc123")

        assert result["unencrypted_warning"] is False
        assert len(result["protocols"]) == 3

    async def test_get_protocols_tcp_zero_no_warning(self, mock_client):
        """No warning when unencrypted protocols have zero queries."""
        data = {
            "data": [
                {"name": "DNS-over-HTTPS", "queries": 10000},
                {"name": "UDP", "queries": 0},
                {"name": "TCP", "queries": 0},
            ]
        }
        mock_client.get = AsyncMock(return_value=data)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_protocols("abc123")

        assert result["unencrypted_warning"] is False


# ---------------------------------------------------------------------------
# get_encryption tests
# ---------------------------------------------------------------------------


class TestGetEncryption:
    """Tests for nextdns__analytics__get_encryption()."""

    async def test_get_encryption(self, mock_client, analytics_encryption_fixture):
        """Verifies computed fields: total, percentage, warning."""
        mock_client.get = AsyncMock(return_value=analytics_encryption_fixture)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_encryption("abc123")

        assert result["encrypted"] == 51240
        assert result["unencrypted"] == 2569
        assert result["total"] == 51240 + 2569
        # 2569 / (51240+2569) * 100 = ~4.77%
        expected_pct = round(2569 / (51240 + 2569) * 100, 2)
        assert result["unencrypted_percentage"] == expected_pct
        # Under 10%, so no warning.
        assert result["warning"] is False

    async def test_get_encryption_high_unencrypted(self, mock_client):
        """Triggers warning when unencrypted exceeds 10%."""
        high_unencrypted = {
            "data": [{"encrypted": 800, "unencrypted": 200}]
        }
        mock_client.get = AsyncMock(return_value=high_unencrypted)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_encryption("abc123")

        assert result["encrypted"] == 800
        assert result["unencrypted"] == 200
        assert result["total"] == 1000
        assert result["unencrypted_percentage"] == 20.0
        assert result["warning"] is True

    async def test_get_encryption_empty_data(self, mock_client):
        """Handles empty data gracefully with zero defaults."""
        mock_client.get = AsyncMock(return_value={"data": []})

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_encryption("abc123")

        assert result["encrypted"] == 0
        assert result["unencrypted"] == 0
        assert result["total"] == 0
        assert result["unencrypted_percentage"] == 0.0
        assert result["warning"] is False


# ---------------------------------------------------------------------------
# get_destinations tests
# ---------------------------------------------------------------------------


class TestGetDestinations:
    """Tests for nextdns__analytics__get_destinations()."""

    async def test_get_destinations_countries(self, mock_client):
        """Verifies type=countries param passed and data returned."""
        countries_data = {
            "data": [
                {"name": "United States", "queries": 32000},
                {"name": "Germany", "queries": 8500},
                {"name": "Japan", "queries": 3200},
            ]
        }
        mock_client.get = AsyncMock(return_value=countries_data)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_destinations(
                "abc123", destination_type="countries"
            )

        assert len(result) == 3
        assert result[0]["name"] == "United States"
        assert result[0]["queries"] == 32000

        mock_client.get.assert_awaited_once_with(
            "/profiles/abc123/analytics/destinations",
            params={"type": "countries"},
        )

    async def test_get_destinations_gafam(self, mock_client):
        """Verifies type=gafam param passed correctly."""
        gafam_data = {
            "data": [
                {"name": "Google", "queries": 18000},
                {"name": "Apple", "queries": 12000},
                {"name": "Facebook", "queries": 5000},
                {"name": "Amazon", "queries": 3000},
                {"name": "Microsoft", "queries": 7000},
            ]
        }
        mock_client.get = AsyncMock(return_value=gafam_data)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_destinations(
                "abc123", destination_type="gafam"
            )

        assert len(result) == 5
        assert result[4]["name"] == "Microsoft"

        mock_client.get.assert_awaited_once_with(
            "/profiles/abc123/analytics/destinations",
            params={"type": "gafam"},
        )


# ---------------------------------------------------------------------------
# get_ips tests
# ---------------------------------------------------------------------------


class TestGetIPs:
    """Tests for nextdns__analytics__get_ips()."""

    async def test_get_ips(self, mock_client):
        """Returns IP entries with ISP, ASN, and geo metadata."""
        ips_data = {
            "data": [
                {
                    "ip": "203.0.113.1",
                    "queries": 25000,
                    "isp": "Comcast",
                    "asn": 7922,
                    "country": "US",
                    "city": "Philadelphia",
                    "isCellular": False,
                    "isVpn": False,
                },
                {
                    "ip": "198.51.100.5",
                    "queries": 800,
                    "isp": "T-Mobile",
                    "asn": 21928,
                    "country": "US",
                    "city": None,
                    "isCellular": True,
                    "isVpn": False,
                },
            ]
        }
        mock_client.get = AsyncMock(return_value=ips_data)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_ips("abc123")

        assert len(result) == 2
        assert result[0]["ip"] == "203.0.113.1"
        assert result[0]["queries"] == 25000
        assert result[0]["isp"] == "Comcast"
        assert result[0]["asn"] == 7922
        assert result[0]["country"] == "US"
        # by_alias=True: isCellular alias.
        assert result[0]["isCellular"] is False
        assert result[1]["isCellular"] is True


# ---------------------------------------------------------------------------
# get_query_types tests
# ---------------------------------------------------------------------------


class TestGetQueryTypes:
    """Tests for nextdns__analytics__get_query_types()."""

    async def test_get_query_types(self, mock_client):
        """Returns query type breakdown."""
        types_data = {
            "data": [
                {"name": "A", "queries": 32000},
                {"name": "AAAA", "queries": 15000},
                {"name": "CNAME", "queries": 3200},
                {"name": "MX", "queries": 450},
                {"name": "TXT", "queries": 200},
            ]
        }
        mock_client.get = AsyncMock(return_value=types_data)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_query_types("abc123")

        assert len(result) == 5
        assert result[0]["name"] == "A"
        assert result[0]["queries"] == 32000
        assert result[3]["name"] == "MX"

        mock_client.get.assert_awaited_once_with(
            "/profiles/abc123/analytics/queryTypes", params=None
        )


# ---------------------------------------------------------------------------
# get_ip_versions tests
# ---------------------------------------------------------------------------


class TestGetIPVersions:
    """Tests for nextdns__analytics__get_ip_versions()."""

    async def test_get_ip_versions(self, mock_client):
        """Returns IPv4/IPv6 breakdown."""
        versions_data = {
            "data": [
                {"name": "IPv4", "queries": 42000},
                {"name": "IPv6", "queries": 11809},
            ]
        }
        mock_client.get = AsyncMock(return_value=versions_data)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_ip_versions("abc123")

        assert len(result) == 2
        assert result[0]["name"] == "IPv4"
        assert result[0]["queries"] == 42000
        assert result[1]["name"] == "IPv6"
        assert result[1]["queries"] == 11809

        mock_client.get.assert_awaited_once_with(
            "/profiles/abc123/analytics/ipVersions", params=None
        )


# ---------------------------------------------------------------------------
# get_dnssec tests
# ---------------------------------------------------------------------------


class TestGetDNSSEC:
    """Tests for nextdns__analytics__get_dnssec()."""

    async def test_get_dnssec(self, mock_client):
        """Returns DNSSEC validation breakdown."""
        dnssec_data = {
            "data": [
                {"name": "Not validated", "queries": 38000},
                {"name": "Validated", "queries": 15809},
            ]
        }
        mock_client.get = AsyncMock(return_value=dnssec_data)

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            result = await nextdns__analytics__get_dnssec("abc123")

        assert len(result) == 2
        assert result[0]["name"] == "Not validated"
        assert result[0]["queries"] == 38000
        assert result[1]["name"] == "Validated"
        assert result[1]["queries"] == 15809

        mock_client.get.assert_awaited_once_with(
            "/profiles/abc123/analytics/dnssec", params=None
        )


# ---------------------------------------------------------------------------
# Analytics dashboard agent tests
# ---------------------------------------------------------------------------


class TestAnalyticsDashboard:
    """Tests for the analytics_dashboard agent."""

    async def test_analytics_dashboard(
        self,
        mock_client,
        analytics_status_fixture,
        analytics_domains_fixture,
        analytics_devices_fixture,
        analytics_protocols_fixture,
        analytics_encryption_fixture,
    ):
        """Dashboard fetches all analytics and returns formatted markdown."""
        # Mock get_client for all analytics tool calls.
        mock_client.get = AsyncMock(
            side_effect=[
                analytics_status_fixture,       # get_status
                analytics_devices_fixture,      # get_devices
                analytics_protocols_fixture,    # get_protocols
                analytics_encryption_fixture,   # get_encryption
            ]
        )
        mock_client.get_paginated = AsyncMock(
            return_value=analytics_domains_fixture["data"]  # get_top_domains
        )

        with patch("nextdns.tools.analytics.get_client", return_value=mock_client):
            output = await analytics_dashboard("abc123")

        # Dashboard should contain key sections.
        assert "Analytics" in output or "queries" in output.lower()
        # Should include total query count (45230 + 8456 + 123 = 53809).
        assert "53,809" in output or "53809" in output
        # Should include blocked count.
        assert "8,456" in output or "8456" in output
        # Should mention encryption.
        assert "Encryption" in output or "encrypted" in output.lower()
        # Should mention protocols.
        assert "Protocol" in output
        # Should have unencrypted warning (UDP has queries in fixture).
        assert "Warning" in output or "warning" in output.lower()
