# SPDX-License-Identifier: MIT
"""Comprehensive tests for log tools and log investigation agents.

Covers all 4 log MCP tools:
- search (basic, with filters, with pagination, limit clamping)
- stream (collection, duration capping, polling note)
- download (URL return, warning without time range, no warning with time range)
- clear (write gate enforcement, successful deletion)

Also covers the log agents:
- investigate_device
- recent_blocks
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from nextdns.agents.logs import investigate_device, recent_blocks
from nextdns.errors import WriteGateError
from nextdns.tools.logs import (
    nextdns__logs__clear,
    nextdns__logs__download,
    nextdns__logs__search,
    nextdns__logs__stream,
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
def logs_search_fixture() -> dict[str, Any]:
    return _load_fixture("logs_search.json")


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
# search tests
# ---------------------------------------------------------------------------


class TestLogsSearch:
    """Tests for nextdns__logs__search()."""

    async def test_search_basic(self, mock_client, logs_search_fixture):
        """Returns parsed entries with stream_id from metadata."""
        mock_client.get = AsyncMock(return_value=logs_search_fixture)

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            result = await nextdns__logs__search("abc123")

        assert "entries" in result
        assert result["count"] == 4
        assert len(result["entries"]) == 4

        # First entry is the blocked doubleclick one.
        first = result["entries"][0]
        assert first["domain"] == "ads.doubleclick.net"
        assert first["status"] == "blocked"

        # stream_id should be extracted from meta.
        assert result["stream_id"] == "stream-abc123"

        # Cursor should be extracted from meta.pagination.
        assert result["next_cursor"] == "eyJ0IjoxNjE="

    async def test_search_with_filters(self, mock_client, logs_search_fixture):
        """Verifies domain, status, device params passed to the client."""
        mock_client.get = AsyncMock(return_value=logs_search_fixture)

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            await nextdns__logs__search(
                "abc123",
                domain="doubleclick",
                status="blocked",
                device="iPhone-13",
            )

        call_args = mock_client.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params")
        assert params["search"] == "doubleclick"
        assert params["status"] == "blocked"
        assert params["device"] == "iPhone-13"

    async def test_search_with_pagination(self, mock_client, logs_search_fixture):
        """Verifies cursor returned for multi-page results."""
        mock_client.get = AsyncMock(return_value=logs_search_fixture)

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            result = await nextdns__logs__search("abc123")

        # The fixture has a non-null cursor.
        assert "next_cursor" in result
        assert result["next_cursor"] == "eyJ0IjoxNjE="

    async def test_search_no_pagination_when_null_cursor(self, mock_client):
        """No next_cursor when pagination cursor is null."""
        data = {
            "data": [
                {"timestamp": "2026-03-28T10:00:00Z", "domain": "test.com", "status": "default"}
            ],
            "meta": {"pagination": {"cursor": None}, "stream": {}},
        }
        mock_client.get = AsyncMock(return_value=data)

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            result = await nextdns__logs__search("abc123")

        assert "next_cursor" not in result

    async def test_search_limit_clamped_low(self, mock_client):
        """Verifies limit is clamped to minimum of 10."""
        mock_client.get = AsyncMock(return_value={"data": [], "meta": {}})

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            await nextdns__logs__search("abc123", limit=1)

        call_args = mock_client.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params")
        assert params["limit"] == 10

    async def test_search_limit_clamped_high(self, mock_client):
        """Verifies limit is clamped to maximum of 1000."""
        mock_client.get = AsyncMock(return_value={"data": [], "meta": {}})

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            await nextdns__logs__search("abc123", limit=5000)

        call_args = mock_client.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params")
        assert params["limit"] == 1000


# ---------------------------------------------------------------------------
# stream tests
# ---------------------------------------------------------------------------


class TestLogsStream:
    """Tests for nextdns__logs__stream()."""

    async def test_stream_collects_entries(self, mock_client):
        """Collects unique entries from multiple polls with deduplication."""
        # Simulate two polls returning overlapping data.
        poll_1 = {
            "data": [
                {"timestamp": "2026-03-28T10:00:01Z", "domain": "a.com", "status": "default"},
                {"timestamp": "2026-03-28T10:00:02Z", "domain": "b.com", "status": "default"},
            ]
        }
        poll_2 = {
            "data": [
                {
                    "timestamp": "2026-03-28T10:00:02Z",
                    "domain": "b.com",
                    "status": "default",
                },  # duplicate
                {"timestamp": "2026-03-28T10:00:03Z", "domain": "c.com", "status": "blocked"},
            ]
        }
        mock_client.get = AsyncMock(side_effect=[poll_1, poll_2])

        # time.monotonic() call sites in the stream function:
        #   1. start = time.monotonic()
        #   2. while time.monotonic() - start < duration:  (loop check)
        #   3. remaining = duration - (time.monotonic() - start)  (sleep check)
        #   4. (repeat 2+3 for subsequent iterations)
        #   5. elapsed = round(time.monotonic() - start, 1)  (final)
        # Duration is clamped to min(max(30,5),120)=30 for default, but we pass 30.
        with (
            patch("nextdns.tools.logs.get_client", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(
                "time.monotonic",
                side_effect=[
                    0,  # 1: start
                    0,  # 2: first while check (0 < 30 -> enter loop)
                    1,  # 3: remaining = 30 - 1 = 29 > 5, so sleep
                    6,  # 2: second while check (6 < 30 -> enter loop)
                    8,  # 3: remaining = 30 - 8 = 22 > 5, so sleep
                    35,  # 2: third while check (35 < 30 -> false, exit loop)
                    35,  # 5: elapsed calculation
                ],
            ),
        ):
            result = await nextdns__logs__stream("abc123", duration_seconds=30)

        # Should have 3 unique entries (deduped by timestamp).
        assert result["count"] == 3
        assert len(result["entries"]) == 3
        # Entries should be sorted by timestamp descending.
        timestamps = [e["timestamp"] for e in result["entries"]]
        assert timestamps == sorted(timestamps, reverse=True)

    async def test_stream_duration_capped(self, mock_client):
        """Verifies max duration is 120 seconds."""
        mock_client.get = AsyncMock(return_value={"data": []})

        # Call sites: start, while-check, remaining-check, while-check, elapsed
        # After first poll (empty data), remaining = 120 - 1 = 119 > 5, so sleep.
        # Second while check: 125 >= 120, exit loop.
        with (
            patch("nextdns.tools.logs.get_client", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(
                "time.monotonic",
                side_effect=[
                    0,  # start
                    0,  # first while check (0 < 120 -> enter)
                    1,  # remaining = 120 - 1 = 119 > 5, sleep
                    125,  # second while check (125 < 120 -> false, exit)
                    125,  # elapsed
                ],
            ),
        ):
            result = await nextdns__logs__stream(
                "abc123",
                duration_seconds=300,  # requested 300s, capped to 120
            )

        assert result["count"] == 0
        # Duration should reflect actual elapsed, not requested.
        assert result["duration_seconds"] <= 125.0

    async def test_stream_includes_polling_note(self, mock_client):
        """Response includes a polling_note explaining SSE limitation."""
        mock_client.get = AsyncMock(return_value={"data": []})

        # Call sites: start, while-check, remaining-check, while-check, elapsed
        # remaining = 5 - 1 = 4, which is NOT > 5, so break after first poll.
        with (
            patch("nextdns.tools.logs.get_client", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(
                "time.monotonic",
                side_effect=[
                    0,  # start
                    0,  # first while check (0 < 5 -> enter)
                    1,  # remaining = 5 - 1 = 4, NOT > 5, break
                    1,  # elapsed
                ],
            ),
        ):
            result = await nextdns__logs__stream("abc123", duration_seconds=5)

        assert "polling_note" in result
        assert "SSE" in result["polling_note"]
        assert "polling" in result["polling_note"].lower()


# ---------------------------------------------------------------------------
# download tests
# ---------------------------------------------------------------------------


class TestLogsDownload:
    """Tests for nextdns__logs__download()."""

    async def test_download_returns_url(self, mock_client):
        """Returns download URL from API response."""
        mock_client.get = AsyncMock(
            return_value={"data": "https://api.nextdns.io/download/abc123/logs.csv"}
        )

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            result = await nextdns__logs__download("abc123")

        assert result["profile_id"] == "abc123"
        assert result["download_url"] == "https://api.nextdns.io/download/abc123/logs.csv"

    async def test_download_warns_no_time_range(self, mock_client):
        """Includes warning when no from/to time range specified."""
        mock_client.get = AsyncMock(return_value={"data": "https://example.com/logs.csv"})

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            result = await nextdns__logs__download("abc123")

        assert "warning" in result
        assert "ALL logs" in result["warning"]

    async def test_download_with_time_range(self, mock_client):
        """No warning when from/to time range is specified."""
        mock_client.get = AsyncMock(return_value={"data": "https://example.com/logs.csv"})

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            result = await nextdns__logs__download(
                "abc123", from_time="2026-03-01", to_time="2026-03-28"
            )

        assert "warning" not in result
        assert "time_range" in result
        assert result["time_range"]["from"] == "2026-03-01"
        assert result["time_range"]["to"] == "2026-03-28"

    async def test_download_url_field_fallback(self, mock_client):
        """Falls back to 'url' field if 'data' field is absent."""
        mock_client.get = AsyncMock(return_value={"url": "https://example.com/fallback.csv"})

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            result = await nextdns__logs__download("abc123")

        assert result["download_url"] == "https://example.com/fallback.csv"


# ---------------------------------------------------------------------------
# clear tests
# ---------------------------------------------------------------------------


class TestLogsClear:
    """Tests for nextdns__logs__clear()."""

    async def test_clear_requires_write_gate_env_var(self, mock_client):
        """Raises WriteGateError when env var is not set."""
        with (
            patch("nextdns.tools.logs.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": ""}, clear=False),
            pytest.raises(WriteGateError, match="disabled"),
        ):
            await nextdns__logs__clear("abc123", apply=True, clear_logs=True)

    async def test_clear_requires_apply_flag(self, mock_client):
        """Raises WriteGateError when apply=False."""
        with (
            patch("nextdns.tools.logs.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
            pytest.raises(WriteGateError, match="--apply"),
        ):
            await nextdns__logs__clear("abc123", apply=False, clear_logs=True)

    async def test_clear_requires_clear_logs_flag(self, mock_client):
        """Raises WriteGateError when clear_logs=False."""
        with (
            patch("nextdns.tools.logs.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
            pytest.raises(WriteGateError, match="--clear-logs"),
        ):
            await nextdns__logs__clear("abc123", apply=True, clear_logs=False)

    async def test_clear_success(self, mock_client):
        """Successful clear makes DELETE request and returns confirmation."""
        mock_client.delete = AsyncMock(return_value=None)

        with (
            patch("nextdns.tools.logs.get_client", return_value=mock_client),
            patch.dict("os.environ", {"NEXTDNS_WRITE_ENABLED": "true"}, clear=False),
        ):
            result = await nextdns__logs__clear("abc123", apply=True, clear_logs=True)

        assert result["profile_id"] == "abc123"
        assert result["status"] == "cleared"
        assert "permanently deleted" in result["message"]
        mock_client.delete.assert_awaited_once_with("/profiles/abc123/logs")


# ---------------------------------------------------------------------------
# Agent tests -- investigate_device
# ---------------------------------------------------------------------------


class TestInvestigateDevice:
    """Tests for the investigate_device agent."""

    async def test_investigate_device(self, mock_client, logs_search_fixture):
        """Produces formatted investigation report from log entries."""
        mock_client.get = AsyncMock(return_value=logs_search_fixture)

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            output = await investigate_device("abc123", "iPhone-13")

        assert "Device Investigation" in output
        assert "iPhone-13" in output
        # Should show total queries and blocked count.
        assert "Total queries" in output or "queries" in output.lower()
        assert "Blocked" in output

    async def test_investigate_device_no_entries(self, mock_client):
        """Returns no-data message when device has no queries."""
        mock_client.get = AsyncMock(return_value={"data": [], "meta": {}})

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            output = await investigate_device("abc123", "ghost-device")

        assert "ghost-device" in output
        assert "No DNS queries found" in output

    async def test_investigate_device_has_top_domains(self, mock_client, logs_search_fixture):
        """Investigation report includes top queried domains table."""
        mock_client.get = AsyncMock(return_value=logs_search_fixture)

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            output = await investigate_device("abc123", "iPhone-13")

        assert "Top Queried Domains" in output


# ---------------------------------------------------------------------------
# Agent tests -- recent_blocks
# ---------------------------------------------------------------------------


class TestRecentBlocks:
    """Tests for the recent_blocks agent."""

    async def test_recent_blocks(self, mock_client, logs_search_fixture):
        """Returns formatted blocked query report with reasons."""
        mock_client.get = AsyncMock(return_value=logs_search_fixture)

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            output = await recent_blocks("abc123")

        assert "Recent Blocked Queries" in output
        # Should include block reason breakdown.
        assert "Block Reasons" in output or "Reason" in output

    async def test_recent_blocks_empty(self, mock_client):
        """Returns no-data message when no blocked queries exist."""
        mock_client.get = AsyncMock(return_value={"data": [], "meta": {}})

        with patch("nextdns.tools.logs.get_client", return_value=mock_client):
            output = await recent_blocks("abc123")

        assert "No blocked queries found" in output
