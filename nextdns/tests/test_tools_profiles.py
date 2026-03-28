# SPDX-License-Identifier: MIT
"""Comprehensive tests for profile read tools and security posture tools.

Covers:
- Client factory (singleton creation, auth error on missing key)
- Profile list with summary fields
- Individual profile detail
- Sub-resource tools (security, privacy, parental control, denylist, allowlist, settings)
- Security posture audit (all-secure, weak, all-off profiles)
- Profile comparison (identical, divergent)
- Agents (profile summary, profile detail, security audit, security compare)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# Import tool modules so patch() targets can resolve.
from nextdns.agents.profiles import profile_detail, profile_list_summary
from nextdns.agents.security_posture import security_audit, security_compare
from nextdns.tools.profiles import (
    nextdns__profiles__get_allowlist,
    nextdns__profiles__get_denylist,
    nextdns__profiles__get_parental_control,
    nextdns__profiles__get_privacy,
    nextdns__profiles__get_profile,
    nextdns__profiles__get_security,
    nextdns__profiles__get_settings,
    nextdns__profiles__list_profiles,
)
from nextdns.tools.security_posture import (
    nextdns__security_posture__audit,
    nextdns__security_posture__compare,
)

# ---------------------------------------------------------------------------
# Fixtures -- load JSON fixtures
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict[str, Any] | list[dict[str, Any]]:
    """Load a JSON fixture file and return parsed data."""
    with open(_FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture()
def profiles_list_fixture() -> dict[str, Any]:
    return _load_fixture("profiles_list.json")


@pytest.fixture()
def profile_single_fixture() -> dict[str, Any]:
    return _load_fixture("profile_single.json")


@pytest.fixture()
def profile_empty_fixture() -> dict[str, Any]:
    return _load_fixture("profile_empty.json")


@pytest.fixture()
def mock_client() -> AsyncMock:
    """Create a mock CachedNextDNSClient."""
    client = AsyncMock()
    return client


@pytest.fixture(autouse=True)
def _reset_client_factory():
    """Reset the client factory singleton before each test."""
    from nextdns.tools._client_factory import reset_client

    reset_client()
    yield
    reset_client()


# ---------------------------------------------------------------------------
# Client factory tests
# ---------------------------------------------------------------------------


class TestClientFactory:
    """Tests for _client_factory.get_client()."""

    def test_missing_api_key_raises_auth_error(self):
        """get_client() raises AuthenticationError when NEXTDNS_API_KEY is not set."""
        from nextdns.errors import AuthenticationError
        from nextdns.tools._client_factory import get_client

        with patch.dict("os.environ", {"NEXTDNS_API_KEY": ""}, clear=False):
            with pytest.raises(AuthenticationError, match="NEXTDNS_API_KEY"):
                get_client()

    def test_creates_client_with_key(self):
        """get_client() returns a CachedNextDNSClient when API key is set."""
        from nextdns.api.nextdns_client import CachedNextDNSClient
        from nextdns.tools._client_factory import get_client

        with patch.dict("os.environ", {"NEXTDNS_API_KEY": "test-key-1234"}, clear=False):
            client = get_client()
            assert isinstance(client, CachedNextDNSClient)

    def test_singleton_returns_same_instance(self):
        """get_client() returns the same instance on repeated calls."""
        from nextdns.tools._client_factory import get_client

        with patch.dict("os.environ", {"NEXTDNS_API_KEY": "test-key-1234"}, clear=False):
            client1 = get_client()
            client2 = get_client()
            assert client1 is client2


# ---------------------------------------------------------------------------
# Profile list tool tests
# ---------------------------------------------------------------------------


class TestListProfiles:
    """Tests for nextdns__profiles__list_profiles()."""

    async def test_list_two_profiles(self, mock_client, profiles_list_fixture):
        """Returns correct summary fields for two profiles."""
        mock_client.get = AsyncMock(return_value=profiles_list_fixture)

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            result = await nextdns__profiles__list_profiles()

        assert len(result) == 2

        # First profile: "Home" -- 11 of 12 security toggles (ddns=false)
        home = result[0]
        assert home["id"] == "abc123"
        assert home["name"] == "Home"
        assert home["security_enabled_count"] == 11
        assert home["security_total"] == 12
        assert home["blocklist_count"] == 2
        assert home["parental_control_active"] is False
        assert home["denylist_count"] == 1
        assert home["allowlist_count"] == 0
        assert home["logging_enabled"] is True

        # Second profile: "Kids" -- 12 of 12 security toggles
        kids = result[1]
        assert kids["id"] == "def456"
        assert kids["name"] == "Kids"
        assert kids["security_enabled_count"] == 12
        assert kids["security_total"] == 12
        assert kids["blocklist_count"] == 3
        assert kids["parental_control_active"] is True
        assert kids["denylist_count"] == 2
        assert kids["allowlist_count"] == 1
        assert kids["logging_enabled"] is True

    async def test_list_empty_profiles(self, mock_client):
        """Returns empty list when no profiles exist."""
        mock_client.get = AsyncMock(return_value={"data": []})

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            result = await nextdns__profiles__list_profiles()

        assert result == []


# ---------------------------------------------------------------------------
# Get profile tool tests
# ---------------------------------------------------------------------------


class TestGetProfile:
    """Tests for nextdns__profiles__get_profile()."""

    async def test_get_full_profile(self, mock_client, profile_single_fixture):
        """Returns full profile data with by_alias=True."""
        mock_client.get_profile = AsyncMock(return_value=profile_single_fixture)

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            result = await nextdns__profiles__get_profile("def456")

        assert result["id"] == "def456"
        assert result["name"] == "Kids"
        # by_alias=True means camelCase keys
        assert "parentalControl" in result
        assert result["parentalControl"]["safeSearch"] is True
        assert result["security"]["threatIntelligenceFeeds"] is True

    async def test_get_profile_calls_client(self, mock_client, profile_single_fixture):
        """Verifies the correct client method is called."""
        mock_client.get_profile = AsyncMock(return_value=profile_single_fixture)

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            await nextdns__profiles__get_profile("def456")

        mock_client.get_profile.assert_awaited_once_with("def456")


# ---------------------------------------------------------------------------
# Sub-resource tool tests
# ---------------------------------------------------------------------------


class TestGetSecurity:
    """Tests for nextdns__profiles__get_security()."""

    async def test_returns_security_settings(self, mock_client, profile_single_fixture):
        """Returns security settings with alias keys."""
        security_data = profile_single_fixture["data"]["security"]
        mock_client.get_sub_resource = AsyncMock(return_value={"data": security_data})

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            result = await nextdns__profiles__get_security("def456")

        assert result["threatIntelligenceFeeds"] is True
        assert result["csam"] is True
        mock_client.get_sub_resource.assert_awaited_once_with("def456", "security")


class TestGetPrivacy:
    """Tests for nextdns__profiles__get_privacy()."""

    async def test_returns_privacy_settings(self, mock_client, profile_single_fixture):
        """Returns privacy settings including blocklists."""
        privacy_data = profile_single_fixture["data"]["privacy"]
        mock_client.get_sub_resource = AsyncMock(return_value={"data": privacy_data})

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            result = await nextdns__profiles__get_privacy("def456")

        assert len(result["blocklists"]) == 3
        assert result["disguisedTrackers"] is True
        mock_client.get_sub_resource.assert_awaited_once_with("def456", "privacy")


class TestGetParentalControl:
    """Tests for nextdns__profiles__get_parental_control()."""

    async def test_returns_parental_settings(self, mock_client, profile_single_fixture):
        """Returns parental control settings."""
        pc_data = profile_single_fixture["data"]["parentalControl"]
        mock_client.get_sub_resource = AsyncMock(return_value={"data": pc_data})

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            result = await nextdns__profiles__get_parental_control("def456")

        assert result["safeSearch"] is True
        assert len(result["services"]) == 4
        assert len(result["categories"]) == 3
        mock_client.get_sub_resource.assert_awaited_once_with("def456", "parentalControl")


class TestGetDenylist:
    """Tests for nextdns__profiles__get_denylist()."""

    async def test_returns_denylist_entries(self, mock_client, profile_single_fixture):
        """Returns denylist entries."""
        denylist_data = profile_single_fixture["data"]["denylist"]
        mock_client.get_array = AsyncMock(return_value=denylist_data)

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            result = await nextdns__profiles__get_denylist("def456")

        assert len(result) == 2
        assert result[0]["id"] == "ads.example.com"
        assert result[0]["active"] is True
        mock_client.get_array.assert_awaited_once_with("def456", "denylist")

    async def test_returns_empty_denylist(self, mock_client):
        """Returns empty list when no denylist entries."""
        mock_client.get_array = AsyncMock(return_value=[])

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            result = await nextdns__profiles__get_denylist("abc123")

        assert result == []


class TestGetAllowlist:
    """Tests for nextdns__profiles__get_allowlist()."""

    async def test_returns_allowlist_entries(self, mock_client, profile_single_fixture):
        """Returns allowlist entries."""
        allowlist_data = profile_single_fixture["data"]["allowlist"]
        mock_client.get_array = AsyncMock(return_value=allowlist_data)

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            result = await nextdns__profiles__get_allowlist("def456")

        assert len(result) == 1
        assert result[0]["id"] == "safe.example.com"
        mock_client.get_array.assert_awaited_once_with("def456", "allowlist")


class TestGetSettings:
    """Tests for nextdns__profiles__get_settings()."""

    async def test_returns_profile_settings(self, mock_client, profile_single_fixture):
        """Returns general settings."""
        settings_data = profile_single_fixture["data"]["settings"]
        mock_client.get_sub_resource = AsyncMock(return_value={"data": settings_data})

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            result = await nextdns__profiles__get_settings("def456")

        assert result["logs"]["enabled"] is True
        assert result["blockPage"]["enabled"] is True
        assert result["performance"]["ecs"] is True
        mock_client.get_sub_resource.assert_awaited_once_with("def456", "settings")


# ---------------------------------------------------------------------------
# Security posture audit tests
# ---------------------------------------------------------------------------


class TestSecurityPostureAudit:
    """Tests for nextdns__security_posture__audit()."""

    async def test_all_secure_profile_minimal_findings(
        self, mock_client, profile_single_fixture
    ):
        """A fully-secured profile (Kids) produces minimal findings."""
        mock_client.get_profile = AsyncMock(return_value=profile_single_fixture)

        with patch(
            "nextdns.tools.security_posture.get_client",
            return_value=mock_client,
        ):
            findings = await nextdns__security_posture__audit(profile_id="def456")

        # Kids profile has 12/12 security, blocklists, logging, block page.
        # Should only have informational findings (perf settings are enabled).
        severities = [f["severity"] for f in findings]
        assert "critical" not in severities
        assert "high" not in severities

    async def test_empty_profile_many_findings(self, mock_client, profile_empty_fixture):
        """A profile with everything off produces CRITICAL and HIGH findings."""
        mock_client.get_profile = AsyncMock(return_value=profile_empty_fixture)

        with patch(
            "nextdns.tools.security_posture.get_client",
            return_value=mock_client,
        ):
            findings = await nextdns__security_posture__audit(profile_id="empty01")

        severities = [f["severity"] for f in findings]

        # CRITICAL: csam disabled
        assert "critical" in severities
        critical_findings = [f for f in findings if f["severity"] == "critical"]
        assert any("CSAM" in f["title"] for f in critical_findings)

        # HIGH: low security coverage, no blocklists, logging disabled
        high_findings = [f for f in findings if f["severity"] == "high"]
        assert len(high_findings) >= 3

        # WARNING: block page disabled
        warning_findings = [f for f in findings if f["severity"] == "warning"]
        assert any("Block page" in f["title"] for f in warning_findings)

        # INFORMATIONAL: no parental controls, perf disabled
        info_findings = [f for f in findings if f["severity"] == "informational"]
        assert len(info_findings) >= 1

    async def test_audit_all_profiles(self, mock_client, profiles_list_fixture):
        """Auditing without profile_id fetches and audits all profiles."""
        mock_client.get = AsyncMock(return_value=profiles_list_fixture)

        with patch(
            "nextdns.tools.security_posture.get_client",
            return_value=mock_client,
        ):
            findings = await nextdns__security_posture__audit(profile_id=None)

        # Should have findings from both Home and Kids profiles
        titles = [f["title"] for f in findings]
        has_home = any("[Home]" in t for t in titles)
        has_kids = any("[Kids]" in t for t in titles)
        # Home profile has ddns=false (10/12), so it should have at least a warning
        assert has_home or has_kids

    async def test_overly_broad_allowlist_detected(self, mock_client):
        """Detects known tracker domains in allowlist."""
        profile_data = {
            "data": {
                "id": "test01",
                "name": "Tracker Allow",
                "security": {
                    "threatIntelligenceFeeds": True,
                    "aiThreatDetection": True,
                    "googleSafeBrowsing": True,
                    "cryptojacking": True,
                    "dnsRebinding": True,
                    "idnHomographs": True,
                    "typosquatting": True,
                    "dga": True,
                    "nrd": True,
                    "ddns": True,
                    "parking": True,
                    "csam": True,
                    "tlds": [],
                },
                "privacy": {
                    "blocklists": [{"id": "nextdns-recommended"}],
                    "natives": [],
                    "disguisedTrackers": True,
                    "allowAffiliate": False,
                },
                "parentalControl": {
                    "services": [],
                    "categories": [],
                    "safeSearch": True,
                    "youtubeRestrictedMode": False,
                    "blockBypass": False,
                },
                "denylist": [],
                "allowlist": [
                    {"id": "doubleclick.net", "active": True},
                    {"id": "google-analytics.com", "active": True},
                ],
                "settings": {
                    "logs": {"enabled": True, "retention": 7776000},
                    "blockPage": {"enabled": True},
                    "performance": {"ecs": True, "cacheBoost": True, "cnameFlattening": False},
                    "web3": False,
                },
            }
        }
        mock_client.get_profile = AsyncMock(return_value=profile_data)

        with patch(
            "nextdns.tools.security_posture.get_client",
            return_value=mock_client,
        ):
            findings = await nextdns__security_posture__audit(profile_id="test01")

        warning_findings = [f for f in findings if f["severity"] == "warning"]
        broad_findings = [f for f in warning_findings if "broad allowlist" in f["title"].lower()]
        assert len(broad_findings) == 1
        assert "doubleclick.net" in broad_findings[0]["detail"]


# ---------------------------------------------------------------------------
# Security posture compare tests
# ---------------------------------------------------------------------------


class TestSecurityPostureCompare:
    """Tests for nextdns__security_posture__compare()."""

    async def test_identical_profiles_no_diffs(self, mock_client, profile_single_fixture):
        """Two identical profiles produce no diffs."""
        mock_client.get_profile = AsyncMock(return_value=profile_single_fixture)

        with patch(
            "nextdns.tools.security_posture.get_client",
            return_value=mock_client,
        ):
            result = await nextdns__security_posture__compare("def456", "def456")

        assert result["security_diff"] == {}
        assert result["privacy_diff"] == {}
        assert result["parental_diff"] == {}
        assert result["settings_diff"] == {}

    async def test_divergent_profiles_have_diffs(
        self, mock_client, profile_single_fixture, profile_empty_fixture
    ):
        """Two different profiles produce differences in all sections."""
        # Return different fixtures for each call
        mock_client.get_profile = AsyncMock(
            side_effect=[profile_single_fixture, profile_empty_fixture]
        )

        with patch(
            "nextdns.tools.security_posture.get_client",
            return_value=mock_client,
        ):
            result = await nextdns__security_posture__compare("def456", "empty01")

        assert result["profile_a_name"] == "Kids"
        assert result["profile_b_name"] == "Empty Test"

        # Security: all 12 toggles differ
        assert len(result["security_diff"]) > 0

        # Privacy: blocklists differ
        assert "blocklists" in result["privacy_diff"]

        # Parental: safe_search differs
        assert "safe_search" in result["parental_diff"]

        # Settings: logs_enabled and block_page_enabled differ
        assert "logs_enabled" in result["settings_diff"]
        assert "block_page_enabled" in result["settings_diff"]


# ---------------------------------------------------------------------------
# Agent tests
# ---------------------------------------------------------------------------


class TestProfilesAgent:
    """Tests for the profiles agent."""

    async def test_profile_list_summary(self, mock_client, profiles_list_fixture):
        """profile_list_summary returns formatted markdown."""
        mock_client.get = AsyncMock(return_value=profiles_list_fixture)

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            output = await profile_list_summary()

        assert "Profiles" in output
        assert "Home" in output
        assert "Kids" in output

    async def test_profile_detail(self, mock_client, profile_single_fixture):
        """profile_detail returns formatted markdown with profile name."""
        mock_client.get_profile = AsyncMock(return_value=profile_single_fixture)

        with patch("nextdns.tools.profiles.get_client", return_value=mock_client):
            output = await profile_detail("def456")

        assert "Kids" in output
        assert "def456" in output


class TestSecurityPostureAgent:
    """Tests for the security posture agent."""

    async def test_security_audit_formatted(self, mock_client, profile_empty_fixture):
        """security_audit returns formatted severity report."""
        mock_client.get_profile = AsyncMock(return_value=profile_empty_fixture)

        with patch(
            "nextdns.tools.security_posture.get_client",
            return_value=mock_client,
        ):
            output = await security_audit(profile_id="empty01")

        assert "Security Posture" in output
        assert "CRITICAL" in output

    async def test_security_compare_formatted(
        self, mock_client, profile_single_fixture, profile_empty_fixture
    ):
        """security_compare returns formatted comparison."""
        mock_client.get_profile = AsyncMock(
            side_effect=[profile_single_fixture, profile_empty_fixture]
        )

        with patch(
            "nextdns.tools.security_posture.get_client",
            return_value=mock_client,
        ):
            output = await security_compare("def456", "empty01")

        assert "Profile Comparison" in output
        assert "Kids" in output
        assert "Empty Test" in output
