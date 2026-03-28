# SPDX-License-Identifier: MIT
"""Comprehensive tests for profile write tools (Tasks 236-244, 246).

Covers all 13 write MCP tools:
- create_profile (POST, response parsing)
- update_profile (PATCH, field selection)
- delete_profile (DELETE, delete_profile_gate enforcement)
- update_security (PATCH, camelCase conversion, partial update)
- update_privacy (PUT for blocklists, PATCH for booleans)
- update_parental_control (PUT for services/categories, PATCH for booleans)
- add/remove_denylist_entry (POST/DELETE array operations)
- add/remove_allowlist_entry (POST/DELETE array operations)
- update_settings (nested sub-resource patches)
- apply_template (bulk diff and apply across profiles)

Every write tool is tested for:
1. Write gate enforcement (env var missing, apply flag missing)
2. Successful operation with correct API calls
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, call, patch

import pytest

from nextdns.errors import WriteGateError
from nextdns.tools.profile_writes import (
    nextdns__profiles__add_allowlist_entry,
    nextdns__profiles__add_denylist_entry,
    nextdns__profiles__apply_template,
    nextdns__profiles__create_profile,
    nextdns__profiles__delete_profile,
    nextdns__profiles__remove_allowlist_entry,
    nextdns__profiles__remove_denylist_entry,
    nextdns__profiles__update_parental_control,
    nextdns__profiles__update_privacy,
    nextdns__profiles__update_profile,
    nextdns__profiles__update_security,
    nextdns__profiles__update_settings,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_client() -> AsyncMock:
    """Create a mock CachedNextDNSClient with default return values."""
    client = AsyncMock()
    # Default return values for common operations.
    client.post = AsyncMock(return_value={"data": {"id": "new123"}})
    client.patch = AsyncMock(return_value={})
    client.put = AsyncMock(return_value={})
    client.delete = AsyncMock(return_value={})
    client.patch_sub_resource = AsyncMock(return_value={})
    client.add_to_array = AsyncMock(return_value={})
    client.delete_array_child = AsyncMock(return_value={})
    client.get_profile = AsyncMock(return_value={
        "data": {
            "id": "abc123",
            "name": "Test Profile",
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
                "ddns": False,
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
                "safeSearch": False,
                "youtubeRestrictedMode": False,
                "blockBypass": False,
            },
            "denylist": [],
            "allowlist": [],
            "settings": {
                "logs": {"enabled": True, "retention": 2592000},
                "blockPage": {"enabled": True},
                "performance": {"ecs": True, "cacheBoost": True, "cnameFlattening": False},
                "web3": False,
            },
        }
    })
    return client


@pytest.fixture(autouse=True)
def _reset_client_factory():
    """Reset the client factory singleton before each test."""
    from nextdns.tools._client_factory import reset_client

    reset_client()
    yield
    reset_client()


# ===========================================================================
# Write gate enforcement tests (common pattern for all write tools)
# ===========================================================================


class TestWriteGateEnforcement:
    """Verify that every write tool enforces env var and apply flag gates."""

    # All write-gated tools and their minimal arguments for invocation.
    _WRITE_GATED_TOOLS: list[tuple[Any, dict[str, Any]]] = [
        (nextdns__profiles__create_profile, {"name": "Test"}),
        (nextdns__profiles__update_profile, {"profile_id": "abc123", "name": "New"}),
        (nextdns__profiles__update_security, {"profile_id": "abc123", "csam": True}),
        (nextdns__profiles__update_privacy, {"profile_id": "abc123", "disguised_trackers": True}),
        (
            nextdns__profiles__update_parental_control,
            {"profile_id": "abc123", "safe_search": True},
        ),
        (nextdns__profiles__add_denylist_entry, {"profile_id": "abc123", "domain": "bad.com"}),
        (nextdns__profiles__remove_denylist_entry, {"profile_id": "abc123", "domain": "bad.com"}),
        (nextdns__profiles__add_allowlist_entry, {"profile_id": "abc123", "domain": "good.com"}),
        (
            nextdns__profiles__remove_allowlist_entry,
            {"profile_id": "abc123", "domain": "good.com"},
        ),
        (nextdns__profiles__update_settings, {"profile_id": "abc123", "web3": True}),
        (nextdns__profiles__apply_template, {"profile_ids": ["abc123"]}),
    ]

    @pytest.mark.parametrize(
        "tool_func,kwargs",
        _WRITE_GATED_TOOLS,
        ids=[t[0].__name__ for t in _WRITE_GATED_TOOLS],
    )
    async def test_env_var_disabled_raises(
        self, mock_client: AsyncMock, tool_func: Any, kwargs: dict[str, Any]
    ):
        """WriteGateError raised when NEXTDNS_WRITE_ENABLED is not set."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": ""}, clear=False),
            pytest.raises(WriteGateError, match="disabled"),
        ):
            await tool_func(**kwargs, apply=True)

    @pytest.mark.parametrize(
        "tool_func,kwargs",
        _WRITE_GATED_TOOLS,
        ids=[t[0].__name__ for t in _WRITE_GATED_TOOLS],
    )
    async def test_apply_flag_missing_raises(
        self, mock_client: AsyncMock, tool_func: Any, kwargs: dict[str, Any]
    ):
        """WriteGateError raised when apply=False."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
            pytest.raises(WriteGateError, match="--apply"),
        ):
            await tool_func(**kwargs, apply=False)


class TestDeleteProfileGateEnforcement:
    """Verify delete_profile extra safety gate."""

    async def test_env_var_disabled_raises(self, mock_client: AsyncMock):
        """WriteGateError raised when NEXTDNS_WRITE_ENABLED is not set."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": ""}, clear=False),
            pytest.raises(WriteGateError, match="disabled"),
        ):
            await nextdns__profiles__delete_profile(
                "abc123", apply=True, delete_profile=True
            )

    async def test_apply_flag_missing_raises(self, mock_client: AsyncMock):
        """WriteGateError raised when apply=False."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
            pytest.raises(WriteGateError, match="--apply"),
        ):
            await nextdns__profiles__delete_profile(
                "abc123", apply=False, delete_profile=True
            )

    async def test_delete_profile_flag_missing_raises(self, mock_client: AsyncMock):
        """WriteGateError raised when delete_profile=False."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
            pytest.raises(WriteGateError, match="--delete-profile"),
        ):
            await nextdns__profiles__delete_profile(
                "abc123", apply=True, delete_profile=False
            )


# ===========================================================================
# Task 236: Create profile
# ===========================================================================


class TestCreateProfile:
    """Tests for nextdns__profiles__create_profile()."""

    async def test_create_returns_profile_id_and_endpoint(self, mock_client: AsyncMock):
        """Successful creation returns id, name, DNS endpoint, and message."""
        mock_client.post = AsyncMock(return_value={"data": {"id": "xyz789"}})

        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__create_profile("My Network", apply=True)

        assert result["id"] == "xyz789"
        assert result["name"] == "My Network"
        assert result["dns_endpoint"] == "https://dns.nextdns.io/xyz789"
        assert "created successfully" in result["message"]

        mock_client.post.assert_awaited_once_with("/profiles", data={"name": "My Network"})

    async def test_create_handles_flat_response(self, mock_client: AsyncMock):
        """Handles response where id is at top level (no 'data' wrapper)."""
        mock_client.post = AsyncMock(return_value={"id": "flat01"})

        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__create_profile("Flat", apply=True)

        assert result["id"] == "flat01"


# ===========================================================================
# Task 237: Update profile
# ===========================================================================


class TestUpdateProfile:
    """Tests for nextdns__profiles__update_profile()."""

    async def test_update_sends_only_changed_fields(self, mock_client: AsyncMock):
        """Only non-None fields are sent in the PATCH request."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_profile(
                "abc123", name="Renamed", apply=True
            )

        assert result["profile_id"] == "abc123"
        assert result["updated_fields"] == ["name"]
        assert result["message"] == "Profile updated."

        mock_client.patch.assert_awaited_once_with(
            "/profiles/abc123", data={"name": "Renamed"}
        )

    async def test_update_with_no_fields(self, mock_client: AsyncMock):
        """Sending no changes still makes a PATCH with empty data."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_profile("abc123", apply=True)

        assert result["updated_fields"] == []
        mock_client.patch.assert_awaited_once_with("/profiles/abc123", data={})


# ===========================================================================
# Task 238: Delete profile
# ===========================================================================


class TestDeleteProfile:
    """Tests for nextdns__profiles__delete_profile()."""

    async def test_delete_success(self, mock_client: AsyncMock):
        """Successful deletion fetches profile name and confirms deletion."""
        mock_client.get_profile = AsyncMock(
            return_value={"data": {"id": "abc123", "name": "Old Profile"}}
        )
        mock_client.delete = AsyncMock(return_value={})

        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__delete_profile(
                "abc123", apply=True, delete_profile=True
            )

        assert result["profile_id"] == "abc123"
        assert result["profile_name"] == "Old Profile"
        assert "permanently deleted" in result["message"]
        mock_client.delete.assert_awaited_once_with("/profiles/abc123")

    async def test_delete_handles_missing_profile_name(self, mock_client: AsyncMock):
        """Falls back to 'Unknown' if profile lookup fails."""
        mock_client.get_profile = AsyncMock(side_effect=Exception("Not found"))
        mock_client.delete = AsyncMock(return_value={})

        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__delete_profile(
                "abc123", apply=True, delete_profile=True
            )

        assert result["profile_name"] == "Unknown"
        # Delete should still proceed even if profile lookup fails.
        mock_client.delete.assert_awaited_once_with("/profiles/abc123")


# ===========================================================================
# Task 239: Update security
# ===========================================================================


class TestUpdateSecurity:
    """Tests for nextdns__profiles__update_security()."""

    async def test_partial_update_only_sends_specified_fields(self, mock_client: AsyncMock):
        """Only non-None params are included in the PATCH payload."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_security(
                "abc123",
                csam=True,
                nrd=False,
                apply=True,
            )

        assert "csam" in result["updated_fields"]
        assert "nrd" in result["updated_fields"]
        assert len(result["updated_fields"]) == 2

        mock_client.patch_sub_resource.assert_awaited_once_with(
            "abc123", "security", {"csam": True, "nrd": False}
        )

    async def test_camelcase_conversion(self, mock_client: AsyncMock):
        """Python snake_case params are converted to camelCase API keys."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_security(
                "abc123",
                threat_intelligence_feeds=True,
                ai_threat_detection=False,
                google_safe_browsing=True,
                dns_rebinding=True,
                idn_homographs=False,
                apply=True,
            )

        call_args = mock_client.patch_sub_resource.call_args
        patch_data = call_args[0][2]  # Third positional arg is the data dict.

        assert "threatIntelligenceFeeds" in patch_data
        assert "aiThreatDetection" in patch_data
        assert "googleSafeBrowsing" in patch_data
        assert "dnsRebinding" in patch_data
        assert "idnHomographs" in patch_data
        assert patch_data["threatIntelligenceFeeds"] is True
        assert patch_data["aiThreatDetection"] is False

    async def test_all_twelve_fields(self, mock_client: AsyncMock):
        """All 12 security fields can be updated simultaneously."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_security(
                "abc123",
                threat_intelligence_feeds=True,
                ai_threat_detection=True,
                google_safe_browsing=True,
                cryptojacking=True,
                dns_rebinding=True,
                idn_homographs=True,
                typosquatting=True,
                dga=True,
                nrd=True,
                ddns=True,
                parking=True,
                csam=True,
                apply=True,
            )

        assert len(result["updated_fields"]) == 12


# ===========================================================================
# Task 240: Update privacy
# ===========================================================================


class TestUpdatePrivacy:
    """Tests for nextdns__profiles__update_privacy()."""

    async def test_blocklist_replacement_uses_put(self, mock_client: AsyncMock):
        """Blocklists are replaced via PUT to privacy.blocklists sub-resource."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_privacy(
                "abc123",
                blocklists=["oisd", "nextdns-recommended"],
                apply=True,
            )

        assert "blocklists" in result["updated_fields"]

        mock_client.put.assert_awaited_once_with(
            "/profiles/abc123/privacy/blocklists",
            data=[{"id": "oisd"}, {"id": "nextdns-recommended"}],
        )

    async def test_boolean_update_uses_patch(self, mock_client: AsyncMock):
        """Boolean fields (disguised_trackers, allow_affiliate) use PATCH."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_privacy(
                "abc123",
                disguised_trackers=True,
                allow_affiliate=False,
                apply=True,
            )

        assert "disguisedTrackers" in result["updated_fields"]
        assert "allowAffiliate" in result["updated_fields"]

        mock_client.patch_sub_resource.assert_awaited_once_with(
            "abc123", "privacy", {"disguisedTrackers": True, "allowAffiliate": False}
        )
        # No PUT should be called when blocklists are not specified.
        mock_client.put.assert_not_awaited()

    async def test_combined_blocklists_and_booleans(self, mock_client: AsyncMock):
        """Both blocklist replacement (PUT) and boolean update (PATCH) in one call."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_privacy(
                "abc123",
                blocklists=["oisd"],
                disguised_trackers=False,
                apply=True,
            )

        assert len(result["updated_fields"]) == 2
        mock_client.put.assert_awaited_once()
        mock_client.patch_sub_resource.assert_awaited_once()


# ===========================================================================
# Task 241: Update parental control
# ===========================================================================


class TestUpdateParentalControl:
    """Tests for nextdns__profiles__update_parental_control()."""

    async def test_services_list_uses_put(self, mock_client: AsyncMock):
        """Services list is replaced via PUT to parentalControl.services."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_parental_control(
                "abc123",
                services=["tiktok", "facebook", "instagram"],
                apply=True,
            )

        assert "services" in result["updated_fields"]

        mock_client.put.assert_awaited_once_with(
            "/profiles/abc123/parentalControl/services",
            data=[
                {"id": "tiktok", "active": True},
                {"id": "facebook", "active": True},
                {"id": "instagram", "active": True},
            ],
        )

    async def test_categories_list_uses_put(self, mock_client: AsyncMock):
        """Categories list is replaced via PUT to parentalControl.categories."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_parental_control(
                "abc123",
                categories=["porn", "gambling"],
                apply=True,
            )

        assert "categories" in result["updated_fields"]

        mock_client.put.assert_awaited_once_with(
            "/profiles/abc123/parentalControl/categories",
            data=[
                {"id": "porn", "active": True},
                {"id": "gambling", "active": True},
            ],
        )

    async def test_boolean_fields_use_patch(self, mock_client: AsyncMock):
        """Boolean fields (safe_search, etc.) are sent via PATCH."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_parental_control(
                "abc123",
                safe_search=True,
                youtube_restricted_mode=True,
                block_bypass=True,
                apply=True,
            )

        assert "safeSearch" in result["updated_fields"]
        assert "youtubeRestrictedMode" in result["updated_fields"]
        assert "blockBypass" in result["updated_fields"]

        mock_client.patch_sub_resource.assert_awaited_once_with(
            "abc123",
            "parentalControl",
            {
                "safeSearch": True,
                "youtubeRestrictedMode": True,
                "blockBypass": True,
            },
        )

    async def test_combined_lists_and_booleans(self, mock_client: AsyncMock):
        """Both list replacement (PUT) and boolean update (PATCH) in one call."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_parental_control(
                "abc123",
                services=["tiktok"],
                categories=["porn"],
                safe_search=True,
                apply=True,
            )

        assert len(result["updated_fields"]) == 3
        # Two PUT calls (services + categories) and one PATCH call.
        assert mock_client.put.await_count == 2
        mock_client.patch_sub_resource.assert_awaited_once()


# ===========================================================================
# Task 242: Add/remove denylist entries
# ===========================================================================


class TestDenylistEntries:
    """Tests for nextdns__profiles__add/remove_denylist_entry()."""

    async def test_add_denylist_entry(self, mock_client: AsyncMock):
        """Adds domain to denylist via add_to_array."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__add_denylist_entry(
                "abc123", "ads.example.com", apply=True
            )

        assert result["profile_id"] == "abc123"
        assert result["domain"] == "ads.example.com"
        assert result["action"] == "added_to_denylist"

        mock_client.add_to_array.assert_awaited_once_with(
            "abc123", "denylist", {"id": "ads.example.com", "active": True}
        )

    async def test_remove_denylist_entry(self, mock_client: AsyncMock):
        """Removes domain from denylist via delete_array_child."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__remove_denylist_entry(
                "abc123", "ads.example.com", apply=True
            )

        assert result["profile_id"] == "abc123"
        assert result["domain"] == "ads.example.com"
        assert result["action"] == "removed_from_denylist"

        mock_client.delete_array_child.assert_awaited_once_with(
            "abc123", "denylist", "ads.example.com"
        )


# ===========================================================================
# Task 243: Add/remove allowlist entries
# ===========================================================================


class TestAllowlistEntries:
    """Tests for nextdns__profiles__add/remove_allowlist_entry()."""

    async def test_add_allowlist_entry(self, mock_client: AsyncMock):
        """Adds domain to allowlist via add_to_array."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__add_allowlist_entry(
                "abc123", "safe.example.com", apply=True
            )

        assert result["profile_id"] == "abc123"
        assert result["domain"] == "safe.example.com"
        assert result["action"] == "added_to_allowlist"

        mock_client.add_to_array.assert_awaited_once_with(
            "abc123", "allowlist", {"id": "safe.example.com", "active": True}
        )

    async def test_remove_allowlist_entry(self, mock_client: AsyncMock):
        """Removes domain from allowlist via delete_array_child."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__remove_allowlist_entry(
                "abc123", "safe.example.com", apply=True
            )

        assert result["profile_id"] == "abc123"
        assert result["domain"] == "safe.example.com"
        assert result["action"] == "removed_from_allowlist"

        mock_client.delete_array_child.assert_awaited_once_with(
            "abc123", "allowlist", "safe.example.com"
        )


# ===========================================================================
# Task 244: Update settings
# ===========================================================================


class TestUpdateSettings:
    """Tests for nextdns__profiles__update_settings()."""

    async def test_logs_settings(self, mock_client: AsyncMock):
        """Logs settings are patched at settings.logs sub-resource."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_settings(
                "abc123",
                logs_enabled=False,
                logs_retention=7776000,
                apply=True,
            )

        assert "logs.enabled" in result["updated_fields"]
        assert "logs.retention" in result["updated_fields"]

        mock_client.patch_sub_resource.assert_any_await(
            "abc123", "settings.logs", {"enabled": False, "retention": 7776000}
        )

    async def test_block_page_settings(self, mock_client: AsyncMock):
        """Block page settings are patched at settings.blockPage."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_settings(
                "abc123",
                block_page_enabled=True,
                apply=True,
            )

        assert "blockPage.enabled" in result["updated_fields"]

        mock_client.patch_sub_resource.assert_awaited_once_with(
            "abc123", "settings.blockPage", {"enabled": True}
        )

    async def test_performance_settings(self, mock_client: AsyncMock):
        """Performance settings are batched into a single PATCH."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_settings(
                "abc123",
                ecs=True,
                cache_boost=True,
                cname_flattening=False,
                apply=True,
            )

        assert "performance.ecs" in result["updated_fields"]
        assert "performance.cacheBoost" in result["updated_fields"]
        assert "performance.cnameFlattening" in result["updated_fields"]

        mock_client.patch_sub_resource.assert_awaited_once_with(
            "abc123",
            "settings.performance",
            {"ecs": True, "cacheBoost": True, "cnameFlattening": False},
        )

    async def test_web3_setting(self, mock_client: AsyncMock):
        """Web3 is patched at the top-level settings sub-resource."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_settings(
                "abc123",
                web3=True,
                apply=True,
            )

        assert "web3" in result["updated_fields"]

        mock_client.patch_sub_resource.assert_awaited_once_with(
            "abc123", "settings", {"web3": True}
        )

    async def test_nested_settings_multiple_patches(self, mock_client: AsyncMock):
        """Updating fields across multiple sub-resources makes multiple PATCH calls."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__update_settings(
                "abc123",
                logs_enabled=True,
                block_page_enabled=False,
                ecs=True,
                web3=True,
                apply=True,
            )

        # Should make 4 PATCH calls: logs, blockPage, performance, web3.
        assert mock_client.patch_sub_resource.await_count == 4
        assert len(result["updated_fields"]) == 4


# ===========================================================================
# Task 246: Bulk template tool
# ===========================================================================


class TestApplyTemplate:
    """Tests for nextdns__profiles__apply_template()."""

    async def test_profiles_needing_changes(self, mock_client: AsyncMock):
        """Template detects differences and applies patches."""
        # Profile has ddns=False; template wants it True.
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__apply_template(
                profile_ids=["abc123"],
                template_security={"ddns": True},
                apply=True,
            )

        assert result["profiles_processed"] == 1
        assert result["profiles_updated"] == 1

        profile_result = result["results"][0]
        assert profile_result["status"] == "updated"
        assert any("ddns" in c for c in profile_result["changes"])

        mock_client.patch_sub_resource.assert_awaited_once_with(
            "abc123", "security", {"ddns": True}
        )

    async def test_profiles_already_matching(self, mock_client: AsyncMock):
        """Template detects no diff when profile already matches."""
        # Profile has csam=True; template also wants csam=True.
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__apply_template(
                profile_ids=["abc123"],
                template_security={"csam": True},
                apply=True,
            )

        assert result["profiles_updated"] == 0

        profile_result = result["results"][0]
        assert profile_result["status"] == "no_changes"
        assert "security.csam" in profile_result["already_matching"]

        # No PATCH should be made.
        mock_client.patch_sub_resource.assert_not_awaited()

    async def test_blocklist_diff(self, mock_client: AsyncMock):
        """Template detects blocklist differences and applies PUT."""
        # Profile has ["nextdns-recommended"]; template wants ["oisd", "nextdns-recommended"].
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__apply_template(
                profile_ids=["abc123"],
                template_privacy_blocklists=["oisd", "nextdns-recommended"],
                apply=True,
            )

        assert result["profiles_updated"] == 1
        profile_result = result["results"][0]
        assert any("blocklists added" in c for c in profile_result["changes"])

        mock_client.put.assert_awaited_once()

    async def test_blocklist_already_matching(self, mock_client: AsyncMock):
        """No PUT when blocklists already match template."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__apply_template(
                profile_ids=["abc123"],
                template_privacy_blocklists=["nextdns-recommended"],
                apply=True,
            )

        assert result["profiles_updated"] == 0
        profile_result = result["results"][0]
        assert "blocklists" in profile_result["already_matching"]

        mock_client.put.assert_not_awaited()

    async def test_disguised_trackers_diff(self, mock_client: AsyncMock):
        """Template detects disguisedTrackers difference and applies PATCH."""
        # Profile has disguisedTrackers=True; template wants False.
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__apply_template(
                profile_ids=["abc123"],
                template_privacy_disguised_trackers=False,
                apply=True,
            )

        assert result["profiles_updated"] == 1
        profile_result = result["results"][0]
        assert any("disguisedTrackers" in c for c in profile_result["changes"])

    async def test_multiple_profiles(self, mock_client: AsyncMock):
        """Template processes multiple profiles independently."""
        # Two profiles: abc123 and def456.
        profile_a = {
            "data": {
                "id": "abc123", "name": "Profile A",
                "security": {"ddns": False},
                "privacy": {"blocklists": [], "disguisedTrackers": False},
            }
        }
        profile_b = {
            "data": {
                "id": "def456", "name": "Profile B",
                "security": {"ddns": True},
                "privacy": {"blocklists": [], "disguisedTrackers": True},
            }
        }
        mock_client.get_profile = AsyncMock(side_effect=[profile_a, profile_b])

        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__apply_template(
                profile_ids=["abc123", "def456"],
                template_security={"ddns": True},
                apply=True,
            )

        assert result["profiles_processed"] == 2
        # Profile A needs ddns change; Profile B already has ddns=True.
        assert result["profiles_updated"] == 1

        assert result["results"][0]["status"] == "updated"
        assert result["results"][1]["status"] == "no_changes"

    async def test_error_handling_per_profile(self, mock_client: AsyncMock):
        """Error in one profile does not stop processing of others."""
        mock_client.get_profile = AsyncMock(
            side_effect=[
                Exception("API timeout"),
                {
                    "data": {
                        "id": "def456", "name": "Good Profile",
                        "security": {"ddns": False},
                        "privacy": {"blocklists": [], "disguisedTrackers": False},
                    }
                },
            ]
        )

        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__apply_template(
                profile_ids=["bad123", "def456"],
                template_security={"ddns": True},
                apply=True,
            )

        assert result["profiles_processed"] == 2
        assert result["results"][0]["status"] == "error"
        assert "API timeout" in result["results"][0]["error"]
        assert result["results"][1]["status"] == "updated"

    async def test_no_template_fields_produces_no_changes(self, mock_client: AsyncMock):
        """If no template fields are specified, no changes are applied."""
        with (
            patch("nextdns.tools.profile_writes.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__profiles__apply_template(
                profile_ids=["abc123"],
                apply=True,
            )

        assert result["profiles_updated"] == 0
        assert result["results"][0]["status"] == "no_changes"
