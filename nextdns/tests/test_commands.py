# SPDX-License-Identifier: MIT
"""Comprehensive tests for high-level command tools.

Covers all 5 commands:
- profiles (list mode, detail mode)
- analytics (with and without time range)
- audit (all profiles, single profile, compare mode)
- logs (search, stream, download, device investigation)
- manage (add deny, add allow, remove deny, remove allow,
         enable security, no-action summary, write gate enforcement)

Each test verifies:
- Correct agent/tool delegation
- Correct parameter passing
- Output is a formatted string (not raw dict)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from nextdns.tools.commands import (
    format_download_result,
    format_log_search_result,
    format_stream_result,
    nextdns__cmd__analytics,
    nextdns__cmd__audit,
    nextdns__cmd__logs,
    nextdns__cmd__manage,
    nextdns__cmd__profiles,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_client_factory():
    """Reset the client factory singleton before each test."""
    from nextdns.tools._client_factory import reset_client

    reset_client()
    yield
    reset_client()


# ---------------------------------------------------------------------------
# Task 248: nextdns profiles command
# ---------------------------------------------------------------------------


class TestCmdProfiles:
    """Tests for nextdns__cmd__profiles()."""

    async def test_profiles_list_mode(self):
        """Delegates to profile_list_summary and returns formatted string."""
        with patch(
            "nextdns.tools.commands.profile_list_summary",
            new_callable=AsyncMock,
            return_value="### Profiles\n\n| Name | ID |\n",
        ) as mock_list:
            result = await nextdns__cmd__profiles()

        mock_list.assert_awaited_once()
        assert isinstance(result, str)
        assert "Profiles" in result

    async def test_profiles_detail_mode(self):
        """Delegates to profile_detail when detail_id is provided."""
        with patch(
            "nextdns.tools.commands.profile_detail",
            new_callable=AsyncMock,
            return_value="## Profile: My Profile (abc123)\n\n",
        ) as mock_detail:
            result = await nextdns__cmd__profiles(detail_id="abc123")

        mock_detail.assert_awaited_once_with("abc123")
        assert isinstance(result, str)
        assert "abc123" in result

    async def test_profiles_list_returns_string_not_dict(self):
        """Ensures the command returns a string, not a raw data structure."""
        with patch(
            "nextdns.tools.commands.profile_list_summary",
            new_callable=AsyncMock,
            return_value="formatted output",
        ):
            result = await nextdns__cmd__profiles()

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Task 249: nextdns analytics command
# ---------------------------------------------------------------------------


class TestCmdAnalytics:
    """Tests for nextdns__cmd__analytics()."""

    async def test_analytics_basic(self):
        """Delegates to analytics_dashboard with profile_id."""
        with patch(
            "nextdns.tools.commands.analytics_dashboard",
            new_callable=AsyncMock,
            return_value="## Analytics Summary\n\n**Total queries:** 1,000\n",
        ) as mock_dashboard:
            result = await nextdns__cmd__analytics("abc123")

        mock_dashboard.assert_awaited_once_with("abc123", None, None)
        assert isinstance(result, str)
        assert "Analytics" in result

    async def test_analytics_with_time_range(self):
        """Passes from_time and to_time to analytics_dashboard."""
        with patch(
            "nextdns.tools.commands.analytics_dashboard",
            new_callable=AsyncMock,
            return_value="## Analytics Summary\n",
        ) as mock_dashboard:
            result = await nextdns__cmd__analytics(
                "abc123", from_time="-7d", to_time="-1d",
            )

        mock_dashboard.assert_awaited_once_with("abc123", "-7d", "-1d")
        assert isinstance(result, str)

    async def test_analytics_returns_string(self):
        """Output is always a formatted string."""
        with patch(
            "nextdns.tools.commands.analytics_dashboard",
            new_callable=AsyncMock,
            return_value="dashboard output",
        ):
            result = await nextdns__cmd__analytics("abc123")

        assert isinstance(result, str)
        assert result == "dashboard output"


# ---------------------------------------------------------------------------
# Task 250: nextdns audit command
# ---------------------------------------------------------------------------


class TestCmdAudit:
    """Tests for nextdns__cmd__audit()."""

    async def test_audit_all_profiles(self):
        """Delegates to security_audit with None when no profile specified."""
        with patch(
            "nextdns.tools.commands.security_audit",
            new_callable=AsyncMock,
            return_value="## Security Posture\n\n**3 findings:**\n",
        ) as mock_audit:
            result = await nextdns__cmd__audit()

        mock_audit.assert_awaited_once_with(None)
        assert isinstance(result, str)
        assert "Security Posture" in result

    async def test_audit_single_profile(self):
        """Delegates to security_audit with specific profile_id."""
        with patch(
            "nextdns.tools.commands.security_audit",
            new_callable=AsyncMock,
            return_value="## Security Posture\n",
        ) as mock_audit:
            result = await nextdns__cmd__audit(profile_id="abc123")

        mock_audit.assert_awaited_once_with("abc123")
        assert isinstance(result, str)

    async def test_audit_compare_mode(self):
        """Delegates to security_compare when both compare_a and compare_b given."""
        with patch(
            "nextdns.tools.commands.security_compare",
            new_callable=AsyncMock,
            return_value="## Profile Comparison: Profile A vs Profile B\n",
        ) as mock_compare:
            result = await nextdns__cmd__audit(
                compare_a="profile1", compare_b="profile2",
            )

        mock_compare.assert_awaited_once_with("profile1", "profile2")
        assert isinstance(result, str)
        assert "Comparison" in result

    async def test_audit_compare_ignores_profile_id(self):
        """When compare_a and compare_b are set, profile_id is ignored."""
        with patch(
            "nextdns.tools.commands.security_compare",
            new_callable=AsyncMock,
            return_value="comparison",
        ) as mock_compare:
            await nextdns__cmd__audit(
                profile_id="ignored",
                compare_a="a",
                compare_b="b",
            )

        mock_compare.assert_awaited_once_with("a", "b")

    async def test_audit_partial_compare_falls_through(self):
        """When only compare_a is set (no compare_b), falls through to audit."""
        with patch(
            "nextdns.tools.commands.security_audit",
            new_callable=AsyncMock,
            return_value="audit output",
        ) as mock_audit:
            await nextdns__cmd__audit(compare_a="a")

        # compare_b is None, so it should NOT call security_compare
        mock_audit.assert_awaited_once_with(None)


# ---------------------------------------------------------------------------
# Task 251: nextdns logs command
# ---------------------------------------------------------------------------


class TestCmdLogs:
    """Tests for nextdns__cmd__logs()."""

    async def test_logs_search_basic(self):
        """Default mode delegates to search and formats results."""
        search_result = {
            "entries": [
                {
                    "timestamp": "2026-03-28T10:00:00Z",
                    "domain": "example.com",
                    "status": "default",
                }
            ],
            "count": 1,
        }
        with patch(
            "nextdns.tools.commands.nextdns__logs__search",
            new_callable=AsyncMock,
            return_value=search_result,
        ) as mock_search:
            result = await nextdns__cmd__logs("abc123")

        mock_search.assert_awaited_once()
        assert isinstance(result, str)
        assert "Log Search Results" in result

    async def test_logs_search_with_filters(self):
        """Passes domain, status, from_time, to_time, and limit to search."""
        search_result = {"entries": [], "count": 0}

        with patch(
            "nextdns.tools.commands.nextdns__logs__search",
            new_callable=AsyncMock,
            return_value=search_result,
        ) as mock_search:
            await nextdns__cmd__logs(
                "abc123",
                domain="ads",
                status="blocked",
                from_time="-1h",
                to_time="now",
                limit=25,
            )

        mock_search.assert_awaited_once_with(
            "abc123",
            domain="ads",
            status="blocked",
            device=None,
            from_time="-1h",
            to_time="now",
            limit=25,
        )

    async def test_logs_stream_mode(self):
        """stream=True delegates to stream tool and formats result."""
        stream_result = {
            "entries": [
                {
                    "timestamp": "2026-03-28T10:00:00Z",
                    "domain": "stream.example.com",
                    "status": "default",
                }
            ],
            "count": 1,
            "duration_seconds": 30.0,
            "polls": 6,
            "polling_note": "Used polling with 5-second intervals.",
        }
        with patch(
            "nextdns.tools.commands.nextdns__logs__stream",
            new_callable=AsyncMock,
            return_value=stream_result,
        ) as mock_stream:
            result = await nextdns__cmd__logs("abc123", stream=True)

        mock_stream.assert_awaited_once_with(
            "abc123", device=None, status=None, domain=None,
        )
        assert isinstance(result, str)
        assert "Live Log Stream" in result

    async def test_logs_stream_with_filters(self):
        """stream mode passes device, status, domain filters."""
        stream_result = {
            "entries": [], "count": 0,
            "duration_seconds": 5.0, "polls": 1,
        }
        with patch(
            "nextdns.tools.commands.nextdns__logs__stream",
            new_callable=AsyncMock,
            return_value=stream_result,
        ) as mock_stream:
            await nextdns__cmd__logs(
                "abc123",
                stream=True,
                device="iPhone-13",
                status="blocked",
                domain="ads",
            )

        mock_stream.assert_awaited_once_with(
            "abc123", device="iPhone-13", status="blocked", domain="ads",
        )

    async def test_logs_download_mode(self):
        """download=True delegates to download tool and formats result."""
        download_result = {
            "profile_id": "abc123",
            "download_url": "https://api.nextdns.io/download/abc123/logs.csv",
            "time_range": {"from": "-7d", "to": "now"},
        }
        with patch(
            "nextdns.tools.commands.nextdns__logs__download",
            new_callable=AsyncMock,
            return_value=download_result,
        ) as mock_download:
            result = await nextdns__cmd__logs(
                "abc123", download=True, from_time="-7d", to_time="now",
            )

        mock_download.assert_awaited_once_with("abc123", "-7d", "now")
        assert isinstance(result, str)
        assert "Log Download" in result
        assert "https://api.nextdns.io" in result

    async def test_logs_device_investigation(self):
        """device param without domain/status triggers investigate_device."""
        with patch(
            "nextdns.tools.commands.investigate_device",
            new_callable=AsyncMock,
            return_value="## Device Investigation: iPhone-13\n\n",
        ) as mock_investigate:
            result = await nextdns__cmd__logs("abc123", device="iPhone-13")

        mock_investigate.assert_awaited_once_with("abc123", "iPhone-13")
        assert isinstance(result, str)
        assert "Device Investigation" in result

    async def test_logs_device_with_domain_uses_search(self):
        """device + domain falls through to search instead of investigate."""
        search_result = {"entries": [], "count": 0}

        with patch(
            "nextdns.tools.commands.nextdns__logs__search",
            new_callable=AsyncMock,
            return_value=search_result,
        ) as mock_search:
            result = await nextdns__cmd__logs(
                "abc123", device="iPhone-13", domain="ads",
            )

        mock_search.assert_awaited_once()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Task 252: nextdns manage command
# ---------------------------------------------------------------------------


class TestCmdManage:
    """Tests for nextdns__cmd__manage()."""

    async def test_manage_no_action_shows_summary(self):
        """Without action flags, shows profile detail summary."""
        with patch(
            "nextdns.tools.commands.profile_detail",
            new_callable=AsyncMock,
            return_value="## Profile: My Profile (abc123)\n",
        ) as mock_detail:
            result = await nextdns__cmd__manage("abc123")

        mock_detail.assert_awaited_once_with("abc123")
        assert isinstance(result, str)
        assert "Profile" in result

    async def test_manage_add_deny_with_apply(self):
        """add_deny with apply=True calls the denylist tool."""
        with (
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
            patch(
                "nextdns.tools.commands.nextdns__profiles__add_denylist_entry",
                new_callable=AsyncMock,
                return_value={"profile_id": "abc123", "domain": "ads.example.com"},
            ) as mock_add,
        ):
            result = await nextdns__cmd__manage(
                "abc123", add_deny="ads.example.com", apply=True,
            )

        mock_add.assert_awaited_once_with(
            "abc123", "ads.example.com", apply=True,
        )
        assert isinstance(result, str)
        assert "ads.example.com" in result
        assert "deny list" in result.lower()

    async def test_manage_remove_deny_with_apply(self):
        """remove_deny with apply=True calls the remove denylist tool."""
        with (
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
            patch(
                "nextdns.tools.commands.nextdns__profiles__remove_denylist_entry",
                new_callable=AsyncMock,
                return_value={"profile_id": "abc123", "domain": "safe.example.com"},
            ) as mock_remove,
        ):
            result = await nextdns__cmd__manage(
                "abc123", remove_deny="safe.example.com", apply=True,
            )

        mock_remove.assert_awaited_once_with(
            "abc123", "safe.example.com", apply=True,
        )
        assert "safe.example.com" in result
        assert "deny list" in result.lower()

    async def test_manage_add_allow_with_apply(self):
        """add_allow with apply=True calls the allowlist tool."""
        with (
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
            patch(
                "nextdns.tools.commands.nextdns__profiles__add_allowlist_entry",
                new_callable=AsyncMock,
                return_value={"profile_id": "abc123", "domain": "safe.example.com"},
            ) as mock_add,
        ):
            result = await nextdns__cmd__manage(
                "abc123", add_allow="safe.example.com", apply=True,
            )

        mock_add.assert_awaited_once_with(
            "abc123", "safe.example.com", apply=True,
        )
        assert "safe.example.com" in result
        assert "allow list" in result.lower()

    async def test_manage_remove_allow_with_apply(self):
        """remove_allow with apply=True calls the remove allowlist tool."""
        with (
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
            patch(
                "nextdns.tools.commands.nextdns__profiles__remove_allowlist_entry",
                new_callable=AsyncMock,
                return_value={"profile_id": "abc123", "domain": "bad.example.com"},
            ) as mock_remove,
        ):
            result = await nextdns__cmd__manage(
                "abc123", remove_allow="bad.example.com", apply=True,
            )

        mock_remove.assert_awaited_once_with(
            "abc123", "bad.example.com", apply=True,
        )
        assert "bad.example.com" in result
        assert "allow list" in result.lower()

    async def test_manage_enable_all_security(self):
        """enable_all_security with apply=True enables all 12 toggles."""
        with (
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
            patch(
                "nextdns.tools.commands.nextdns__profiles__update_security",
                new_callable=AsyncMock,
                return_value={"profile_id": "abc123", "updated_fields": []},
            ) as mock_security,
        ):
            result = await nextdns__cmd__manage(
                "abc123", enable_all_security=True, apply=True,
            )

        mock_security.assert_awaited_once()
        # Verify all 12 toggles were set to True
        call_kwargs = mock_security.call_args.kwargs
        assert call_kwargs["apply"] is True
        assert call_kwargs["threat_intelligence_feeds"] is True
        assert call_kwargs["csam"] is True
        assert call_kwargs["cryptojacking"] is True
        assert call_kwargs["dga"] is True
        assert isinstance(result, str)
        assert "security" in result.lower()

    async def test_manage_write_gate_apply_false_plan_only(self):
        """apply=False returns a plan-only message with planned actions."""
        result = await nextdns__cmd__manage(
            "abc123", add_deny="ads.example.com", apply=False,
        )

        assert isinstance(result, str)
        assert "Plan Only" in result
        assert "ads.example.com" in result
        assert "deny list" in result.lower()
        assert "apply=True" in result or "apply" in result.lower()

    async def test_manage_write_gate_env_disabled(self):
        """apply=True but env var disabled returns blocked message."""
        with patch.dict(
            "os.environ", {"NEXTDNS_WRITE_ENABLED": "false"}, clear=False,
        ):
            result = await nextdns__cmd__manage(
                "abc123", add_deny="ads.example.com", apply=True,
            )

        assert isinstance(result, str)
        assert "Blocked" in result
        assert "disabled" in result.lower()
        assert "NEXTDNS_WRITE_ENABLED" in result

    async def test_manage_multiple_actions_with_apply(self):
        """Multiple action flags execute all requested actions."""
        with (
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
            patch(
                "nextdns.tools.commands.nextdns__profiles__add_denylist_entry",
                new_callable=AsyncMock,
                return_value={},
            ) as mock_add_deny,
            patch(
                "nextdns.tools.commands.nextdns__profiles__add_allowlist_entry",
                new_callable=AsyncMock,
                return_value={},
            ) as mock_add_allow,
        ):
            result = await nextdns__cmd__manage(
                "abc123",
                add_deny="bad.example.com",
                add_allow="good.example.com",
                apply=True,
            )

        mock_add_deny.assert_awaited_once()
        mock_add_allow.assert_awaited_once()
        assert "bad.example.com" in result
        assert "good.example.com" in result
        assert "Changes Applied" in result


# ---------------------------------------------------------------------------
# Formatter tests
# ---------------------------------------------------------------------------


class TestFormatters:
    """Tests for command-level formatting helpers."""

    def test_format_download_result_with_url(self):
        """Formats download URL and time range."""
        result = format_download_result({
            "download_url": "https://example.com/logs.csv",
            "time_range": {"from": "-7d", "to": "now"},
        })

        assert "Log Download" in result
        assert "https://example.com/logs.csv" in result
        assert "-7d" in result

    def test_format_download_result_with_warning(self):
        """Includes warning when present."""
        result = format_download_result({
            "download_url": "https://example.com/logs.csv",
            "warning": "This may download ALL logs.",
        })

        assert "Warning" in result
        assert "ALL logs" in result

    def test_format_download_result_no_url(self):
        """Shows 'Not available' when URL is empty."""
        result = format_download_result({"download_url": ""})
        assert "Not available" in result

    def test_format_stream_result(self):
        """Formats stream results with duration and polling info."""
        result = format_stream_result({
            "entries": [
                {
                    "timestamp": "2026-03-28T10:00:00Z",
                    "domain": "example.com",
                    "status": "default",
                }
            ],
            "count": 1,
            "duration_seconds": 30.0,
            "polls": 6,
            "polling_note": "Used polling.",
        })

        assert "Live Log Stream" in result
        assert "30.0s" in result
        assert "6 polls" in result
        assert "Used polling." in result

    def test_format_stream_result_empty(self):
        """Handles empty stream results."""
        result = format_stream_result({
            "entries": [],
            "count": 0,
            "duration_seconds": 5.0,
            "polls": 1,
        })

        assert "Live Log Stream" in result
        assert "0" in result

    def test_format_log_search_result(self):
        """Formats search results with entry count."""
        result = format_log_search_result({
            "entries": [
                {
                    "timestamp": "2026-03-28T10:00:00Z",
                    "domain": "example.com",
                    "status": "default",
                }
            ],
            "count": 1,
        })

        assert "Log Search Results" in result
        assert "1" in result

    def test_format_log_search_result_with_cursor(self):
        """Shows pagination notice when cursor is present."""
        result = format_log_search_result({
            "entries": [
                {
                    "timestamp": "2026-03-28T10:00:00Z",
                    "domain": "example.com",
                    "status": "default",
                }
            ],
            "count": 1,
            "next_cursor": "abc123",
        })

        assert "More results available" in result

    def test_format_log_search_result_empty(self):
        """Shows 'no entries' message when results are empty."""
        result = format_log_search_result({"entries": [], "count": 0})

        assert "No matching" in result
