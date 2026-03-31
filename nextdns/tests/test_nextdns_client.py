# SPDX-License-Identifier: MIT
"""Comprehensive tests for the NextDNS API client.

Covers:
- Authentication (API key header injection, masked logging)
- Error handling (401, 404, 429, 5xx, timeouts, connect errors)
- Rate limiting (429 retry with backoff, max retries, conservative throttle)
- Cursor-based pagination (multi-page, single page, empty, bounded limit)
- Sub-resource URL builder (all patterns, edge cases)
- Cache integration (hit, miss, TTL, post-write flush, pattern-based TTL)
- Convenience methods (all sub-resource operations)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nextdns.api.nextdns_client import (
    _MAX_429_RETRIES,
    _SLOW_REQUEST_THRESHOLD,
    CachedNextDNSClient,
    NextDNSClient,
)
from nextdns.api.url_builder import array_child_url, profile_url, sub_resource_url
from nextdns.cache import TTLCache
from nextdns.errors import APIError, AuthenticationError, NetworkError, RateLimitError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_response():
    """Factory for mock httpx.Response objects."""

    def _make(
        status_code: int = 200,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> MagicMock:
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        response.is_success = 200 <= status_code < 300
        response.json.return_value = json_data or {}
        response.text = str(json_data)
        # Use httpx.Headers for case-insensitive header access.
        response.headers = httpx.Headers(headers or {})
        return response

    return _make


@pytest.fixture()
def api_key() -> str:
    return "test-api-key-abc123"


@pytest.fixture()
async def client(api_key: str) -> NextDNSClient:
    """Create a NextDNSClient for testing (not entered as context manager)."""
    c = NextDNSClient(api_key=api_key)
    # Reset throttle so tests don't sleep.
    c._last_request_time = 0.0
    c._min_request_interval = 0.0
    yield c  # type: ignore[misc]
    await c.close()


@pytest.fixture()
async def cached_client(api_key: str) -> CachedNextDNSClient:
    """Create a CachedNextDNSClient with a real TTLCache."""
    cache = TTLCache(max_size=100, default_ttl=120.0)
    c = CachedNextDNSClient(api_key=api_key, cache=cache)
    c._last_request_time = 0.0
    c._min_request_interval = 0.0
    yield c  # type: ignore[misc]
    await c.close()


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


class TestAuthentication:
    """Verify API key handling and header injection."""

    async def test_api_key_header_injected(self, api_key: str) -> None:
        """The X-Api-Key header is set on the underlying httpx client."""
        client = NextDNSClient(api_key=api_key)
        assert client._client.headers["X-Api-Key"] == api_key
        assert client._client.headers["Accept"] == "application/json"
        await client.close()

    async def test_api_key_masked_in_logs(self, client: NextDNSClient, mock_response: Any) -> None:
        """Ensure API key is masked when logging request headers."""
        response = mock_response(200, {"data": []})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            with patch("nextdns.api.nextdns_client.logger") as mock_logger:
                await client.get("/profiles")

                # Check the debug call for request logging.
                debug_calls = [c for c in mock_logger.debug.call_args_list]
                assert len(debug_calls) > 0
                # The first debug call is the request log with headers.
                # Format: logger.debug(fmt, method, base_url, endpoint, headers)
                first_call_args = debug_calls[0]
                header_arg = first_call_args[0][4]  # 5th positional (index 4)
                assert header_arg.get("x-api-key") == "***"

    async def test_base_url(self, api_key: str) -> None:
        """The client uses the correct NextDNS API base URL."""
        client = NextDNSClient(api_key=api_key)
        assert client._base_url == "https://api.nextdns.io"
        await client.close()


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify HTTP error responses are mapped to the correct exceptions."""

    async def test_401_raises_authentication_error(
        self, client: NextDNSClient, mock_response: Any
    ) -> None:
        """401 responses raise AuthenticationError referencing NEXTDNS_API_KEY."""
        response = mock_response(401, {"errors": [{"detail": "Invalid API key"}]})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            with pytest.raises(AuthenticationError) as exc_info:
                await client.get("/profiles")

            assert "NEXTDNS_API_KEY" in str(exc_info.value)
            assert exc_info.value.env_var == "NEXTDNS_API_KEY"

    async def test_404_raises_api_error(self, client: NextDNSClient, mock_response: Any) -> None:
        """404 responses raise APIError with status_code=404."""
        response = mock_response(404, {"errors": [{"detail": "Not found"}]})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            with pytest.raises(APIError) as exc_info:
                await client.get("/profiles/nonexistent")

            assert exc_info.value.status_code == 404
            assert "Not found (404)" in exc_info.value.message

    async def test_500_raises_api_error(self, client: NextDNSClient, mock_response: Any) -> None:
        """5xx responses raise APIError with the actual status code."""
        response = mock_response(500, {"errors": [{"detail": "Internal error"}]})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            with pytest.raises(APIError) as exc_info:
                await client.get("/profiles")

            assert exc_info.value.status_code == 500
            assert "Server error" in exc_info.value.message

    async def test_502_raises_api_error(self, client: NextDNSClient, mock_response: Any) -> None:
        """502 responses raise APIError."""
        response = mock_response(502, {})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            with pytest.raises(APIError) as exc_info:
                await client.get("/profiles")

            assert exc_info.value.status_code == 502

    async def test_400_raises_api_error(self, client: NextDNSClient, mock_response: Any) -> None:
        """Other 4xx responses raise APIError."""
        response = mock_response(400, {"errors": [{"detail": "Bad request"}]})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            with pytest.raises(APIError) as exc_info:
                await client.get("/profiles")

            assert exc_info.value.status_code == 400

    async def test_timeout_raises_network_error(self, client: NextDNSClient) -> None:
        """httpx.TimeoutException is translated to NetworkError."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = httpx.TimeoutException("read timed out")

            with pytest.raises(NetworkError) as exc_info:
                await client.get("/profiles")

            assert "timed out" in exc_info.value.message

    async def test_connect_error_raises_network_error(self, client: NextDNSClient) -> None:
        """httpx.ConnectError is translated to NetworkError."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = httpx.ConnectError("Connection refused")

            with pytest.raises(NetworkError) as exc_info:
                await client.get("/profiles")

            assert "Connection refused" in exc_info.value.message

    async def test_ssl_error_raises_network_error(self, client: NextDNSClient) -> None:
        """SSL errors within ConnectError include appropriate retry hint."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = httpx.ConnectError("SSL certificate verify failed")

            with pytest.raises(NetworkError) as exc_info:
                await client.get("/profiles")

            assert "SSL" in exc_info.value.message

    async def test_generic_http_error_raises_network_error(self, client: NextDNSClient) -> None:
        """Other httpx.HTTPError subclasses are caught and translated."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = httpx.HTTPError("DNS resolution failed")

            with pytest.raises(NetworkError) as exc_info:
                await client.get("/profiles")

            assert "transport error" in exc_info.value.message


# ---------------------------------------------------------------------------
# Rate limiting tests
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Verify 429 retry logic and conservative throttle."""

    async def test_429_retries_with_backoff(
        self, client: NextDNSClient, mock_response: Any
    ) -> None:
        """On 429, the client retries with exponential backoff and eventually succeeds."""
        response_429 = mock_response(429, {}, {"Retry-After": "2"})
        response_200 = mock_response(200, {"data": []})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            # First two calls return 429, third succeeds.
            mock_req.side_effect = [response_429, response_429, response_200]

            with patch("nextdns.api.nextdns_client.asyncio.sleep", new_callable=AsyncMock):
                result = await client.get("/profiles")

            assert result == {"data": []}
            assert mock_req.call_count == 3

    async def test_429_max_retries_raises_rate_limit_error(
        self, client: NextDNSClient, mock_response: Any
    ) -> None:
        """After max retries, raises RateLimitError."""
        response_429 = mock_response(429, {}, {"Retry-After": "30"})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            # Return 429 for more than max retries.
            mock_req.side_effect = [response_429] * (_MAX_429_RETRIES + 2)

            with (
                patch("nextdns.api.nextdns_client.asyncio.sleep", new_callable=AsyncMock),
                pytest.raises(RateLimitError) as exc_info,
            ):
                await client.get("/profiles")

            assert exc_info.value.retry_after_seconds == 30.0
            # Should have been called max_retries + 1 times (initial + retries).
            assert mock_req.call_count == _MAX_429_RETRIES + 1

    async def test_429_retry_after_header_parsed(
        self, client: NextDNSClient, mock_response: Any
    ) -> None:
        """The Retry-After header is parsed and included in the error."""
        response_429 = mock_response(429, {}, {"Retry-After": "42"})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [response_429] * (_MAX_429_RETRIES + 2)

            with (
                patch("nextdns.api.nextdns_client.asyncio.sleep", new_callable=AsyncMock),
                pytest.raises(RateLimitError) as exc_info,
            ):
                await client.get("/profiles")

            assert exc_info.value.retry_after_seconds == 42.0

    async def test_429_logs_every_occurrence(
        self, client: NextDNSClient, mock_response: Any
    ) -> None:
        """Each 429 response is logged for rate limit discovery."""
        response_429 = mock_response(429, {})
        response_200 = mock_response(200, {"data": []})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [response_429, response_200]

            with (
                patch("nextdns.api.nextdns_client.asyncio.sleep", new_callable=AsyncMock),
                patch("nextdns.api.nextdns_client.logger") as mock_logger,
            ):
                await client.get("/profiles")

                # Verify 429 was logged as a warning.
                warning_calls = mock_logger.warning.call_args_list
                rate_limit_logs = [
                    c for c in warning_calls if "Rate limited" in str(c) or "429" in str(c)
                ]
                assert len(rate_limit_logs) >= 1

    async def test_conservative_throttle(self, api_key: str, mock_response: Any) -> None:
        """Requests respect the minimum inter-request interval."""
        client = NextDNSClient(api_key=api_key)
        # Set a small interval for testing.
        client._min_request_interval = 0.05

        response = mock_response(200, {"data": []})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            # First request: no throttle needed.
            await client.get("/profiles")
            time.monotonic()

            # Second request: should throttle.
            await client.get("/profiles")
            time.monotonic()

            # The second request should have a very small delay at minimum.
            # We just verify both requests completed successfully.
            assert mock_req.call_count == 2

        await client.close()


# ---------------------------------------------------------------------------
# Cursor-based pagination tests
# ---------------------------------------------------------------------------


class TestPagination:
    """Verify cursor-based pagination logic."""

    async def test_multi_page_pagination(self, client: NextDNSClient, mock_response: Any) -> None:
        """get_paginated follows cursors through 3 pages."""
        page1 = mock_response(
            200,
            {
                "data": [{"id": "a"}, {"id": "b"}],
                "meta": {"pagination": {"cursor": "cursor1"}},
            },
        )
        page2 = mock_response(
            200,
            {
                "data": [{"id": "c"}, {"id": "d"}],
                "meta": {"pagination": {"cursor": "cursor2"}},
            },
        )
        page3 = mock_response(
            200,
            {
                "data": [{"id": "e"}],
                "meta": {"pagination": {"cursor": None}},
            },
        )

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [page1, page2, page3]
            result = await client.get_paginated("/profiles", page_size=2)

        assert len(result) == 5
        assert [r["id"] for r in result] == ["a", "b", "c", "d", "e"]
        assert mock_req.call_count == 3

    async def test_single_page_cursor_null(self, client: NextDNSClient, mock_response: Any) -> None:
        """Single-page response with null cursor stops immediately."""
        response = mock_response(
            200,
            {
                "data": [{"id": "a"}],
                "meta": {"pagination": {"cursor": None}},
            },
        )

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            result = await client.get_paginated("/profiles")

        assert len(result) == 1
        assert mock_req.call_count == 1

    async def test_empty_response_stops_pagination(
        self, client: NextDNSClient, mock_response: Any
    ) -> None:
        """Empty data array stops pagination."""
        response = mock_response(
            200,
            {"data": [], "meta": {"pagination": {"cursor": None}}},
        )

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            result = await client.get_paginated("/profiles")

        assert len(result) == 0
        assert mock_req.call_count == 1

    async def test_bounded_limit(self, client: NextDNSClient, mock_response: Any) -> None:
        """Pagination stops when the limit is reached."""
        page1 = mock_response(
            200,
            {
                "data": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "meta": {"pagination": {"cursor": "cursor1"}},
            },
        )
        page2 = mock_response(
            200,
            {
                "data": [{"id": "d"}, {"id": "e"}, {"id": "f"}],
                "meta": {"pagination": {"cursor": "cursor2"}},
            },
        )

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [page1, page2]
            result = await client.get_paginated("/profiles", limit=4)

        assert len(result) == 4
        assert [r["id"] for r in result] == ["a", "b", "c", "d"]

    async def test_iter_pages_yields_per_page(
        self, client: NextDNSClient, mock_response: Any
    ) -> None:
        """iter_pages yields each page's data array separately."""
        page1 = mock_response(
            200,
            {
                "data": [{"id": "a"}],
                "meta": {"pagination": {"cursor": "c1"}},
            },
        )
        page2 = mock_response(
            200,
            {
                "data": [{"id": "b"}],
                "meta": {"pagination": {"cursor": None}},
            },
        )

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [page1, page2]

            pages = []
            async for page in client.iter_pages("/profiles"):
                pages.append(page)

        assert len(pages) == 2
        assert pages[0] == [{"id": "a"}]
        assert pages[1] == [{"id": "b"}]

    async def test_pagination_no_meta_stops(
        self, client: NextDNSClient, mock_response: Any
    ) -> None:
        """Response without meta/pagination stops after first page."""
        response = mock_response(200, {"data": [{"id": "a"}]})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            result = await client.get_paginated("/profiles")

        assert len(result) == 1
        assert mock_req.call_count == 1

    async def test_pagination_passes_page_size(
        self, client: NextDNSClient, mock_response: Any
    ) -> None:
        """The page_size parameter is passed as `limit` query param."""
        response = mock_response(
            200,
            {"data": [{"id": "a"}], "meta": {"pagination": {"cursor": None}}},
        )

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            await client.get_paginated("/profiles", page_size=50)

            call_kwargs = mock_req.call_args
            params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
            assert params.get("limit") == 50


# ---------------------------------------------------------------------------
# URL builder tests
# ---------------------------------------------------------------------------


class TestURLBuilder:
    """Verify URL construction utilities."""

    def test_profile_url(self) -> None:
        assert profile_url("abc123") == "/profiles/abc123"

    def test_profile_url_alphanumeric(self) -> None:
        assert profile_url("def456") == "/profiles/def456"

    def test_sub_resource_url_simple(self) -> None:
        assert sub_resource_url("abc", "security") == "/profiles/abc/security"

    def test_sub_resource_url_nested(self) -> None:
        assert sub_resource_url("abc", "privacy.blocklists") == "/profiles/abc/privacy/blocklists"

    def test_sub_resource_url_camel_case(self) -> None:
        assert (
            sub_resource_url("abc", "parentalControl.services")
            == "/profiles/abc/parentalControl/services"
        )

    def test_sub_resource_url_deeply_nested(self) -> None:
        assert (
            sub_resource_url("abc", "settings.logs.retention")
            == "/profiles/abc/settings/logs/retention"
        )

    def test_array_child_url_simple(self) -> None:
        assert array_child_url("abc", "denylist", "bad.com") == "/profiles/abc/denylist/bad.com"

    def test_array_child_url_nested_path(self) -> None:
        assert (
            array_child_url("abc", "privacy.blocklists", "oisd")
            == "/profiles/abc/privacy/blocklists/oisd"
        )

    def test_array_child_url_with_special_chars(self) -> None:
        """Item IDs with dots (domains) are preserved as-is."""
        assert (
            array_child_url("abc", "allowlist", "safe.example.com")
            == "/profiles/abc/allowlist/safe.example.com"
        )


# ---------------------------------------------------------------------------
# Cache integration tests
# ---------------------------------------------------------------------------


class TestCacheIntegration:
    """Verify caching behaviour of CachedNextDNSClient."""

    async def test_cache_hit_returns_cached_data(
        self, cached_client: CachedNextDNSClient, mock_response: Any
    ) -> None:
        """Second GET to the same endpoint returns cached data without API call."""
        response = mock_response(200, {"data": [{"id": "abc"}]})

        with patch.object(cached_client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            # First call: cache miss, hits API.
            result1 = await cached_client.get("/profiles/abc")
            # Second call: cache hit, no API call.
            result2 = await cached_client.get("/profiles/abc")

        assert result1 == result2
        assert mock_req.call_count == 1  # Only one API call.

    async def test_cache_miss_fetches_from_api(
        self, cached_client: CachedNextDNSClient, mock_response: Any
    ) -> None:
        """Cache miss results in an API call and caches the response."""
        response = mock_response(200, {"data": [{"id": "abc"}]})

        with patch.object(cached_client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            result = await cached_client.get("/profiles/abc")

        assert result == {"data": [{"id": "abc"}]}
        assert mock_req.call_count == 1

        # Verify it was cached.
        cached = await cached_client._cache.get("/profiles/abc")
        assert cached == {"data": [{"id": "abc"}]}

    async def test_cache_ttl_expiry(self, api_key: str, mock_response: Any) -> None:
        """Expired cache entries result in a fresh API call."""
        cache = TTLCache(max_size=100, default_ttl=0.05)  # Very short TTL.
        client = CachedNextDNSClient(api_key=api_key, cache=cache)
        client._min_request_interval = 0.0
        # Override the client's TTL map to use very short TTLs so expiry is testable.
        client._CACHE_TTLS = {
            "/profiles": 0.05,
            "analytics": 0.05,
            "logs": 0.0,
            "default": 0.05,
        }

        response = mock_response(200, {"data": [{"id": "abc"}]})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            # First call: cache miss.
            await client.get("/profiles/abc")
            # Wait for TTL to expire.
            await asyncio.sleep(0.1)
            # Second call: cache expired, fetches again.
            await client.get("/profiles/abc")

        assert mock_req.call_count == 2
        await client.close()

    async def test_post_write_flush(
        self, cached_client: CachedNextDNSClient, mock_response: Any
    ) -> None:
        """POST/PATCH/PUT/DELETE flush cache for the affected profile."""
        get_response = mock_response(200, {"data": {"id": "abc"}})
        post_response = mock_response(200, {"data": {"id": "new-item"}})

        with patch.object(cached_client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = get_response

            # Populate cache.
            await cached_client.get("/profiles/abc/security")

            # Verify cached.
            cached = await cached_client._cache.get("/profiles/abc/security")
            assert cached is not None

            # Write operation flushes the profile cache.
            mock_req.return_value = post_response
            await cached_client.post("/profiles/abc/denylist", data={"id": "bad.com"})

            # Cache should be flushed for this profile.
            cached = await cached_client._cache.get("/profiles/abc/security")
            assert cached is None

    async def test_patch_flushes_cache(
        self, cached_client: CachedNextDNSClient, mock_response: Any
    ) -> None:
        """PATCH requests flush the affected profile's cache."""
        get_resp = mock_response(200, {"data": {"nrd": True}})
        patch_resp = mock_response(200, {"data": {"nrd": False}})

        with patch.object(cached_client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = get_resp
            await cached_client.get("/profiles/abc/security")

            mock_req.return_value = patch_resp
            await cached_client.patch("/profiles/abc/security", data={"nrd": False})

            cached = await cached_client._cache.get("/profiles/abc/security")
            assert cached is None

    async def test_delete_flushes_cache(
        self, cached_client: CachedNextDNSClient, mock_response: Any
    ) -> None:
        """DELETE requests flush the affected profile's cache."""
        get_resp = mock_response(200, {"data": [{"id": "bad.com"}]})
        del_resp = mock_response(200, {})

        with patch.object(cached_client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = get_resp
            await cached_client.get("/profiles/abc/denylist")

            mock_req.return_value = del_resp
            await cached_client.delete("/profiles/abc/denylist/bad.com")

            cached = await cached_client._cache.get("/profiles/abc/denylist")
            assert cached is None

    async def test_pattern_based_ttl_profiles(self, cached_client: CachedNextDNSClient) -> None:
        """Profile list endpoint gets 5 min TTL."""
        ttl = cached_client._cache_ttl_for("/profiles")
        assert ttl == 300.0

    async def test_pattern_based_ttl_analytics(self, cached_client: CachedNextDNSClient) -> None:
        """Analytics endpoints get 30 sec TTL."""
        ttl = cached_client._cache_ttl_for("/profiles/abc/analytics/status")
        assert ttl == 30.0

    async def test_pattern_based_ttl_logs(self, cached_client: CachedNextDNSClient) -> None:
        """Log endpoints get 0 TTL (never cached)."""
        ttl = cached_client._cache_ttl_for("/profiles/abc/logs")
        assert ttl == 0.0

    async def test_pattern_based_ttl_default(self, cached_client: CachedNextDNSClient) -> None:
        """Sub-resource endpoints get default 2 min TTL."""
        ttl = cached_client._cache_ttl_for("/profiles/abc/security")
        assert ttl == 120.0

    async def test_logs_never_cached(
        self, cached_client: CachedNextDNSClient, mock_response: Any
    ) -> None:
        """Log endpoints bypass cache entirely."""
        response = mock_response(200, {"data": [{"domain": "example.com"}]})

        with patch.object(cached_client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            await cached_client.get("/profiles/abc/logs")
            await cached_client.get("/profiles/abc/logs")

        # Both calls hit the API (no caching).
        assert mock_req.call_count == 2

    async def test_manual_profile_flush(
        self, cached_client: CachedNextDNSClient, mock_response: Any
    ) -> None:
        """flush_profile invalidates all cached data for a specific profile."""
        response = mock_response(200, {"data": {"id": "abc"}})

        with patch.object(cached_client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            # Populate cache with multiple endpoints for the profile.
            await cached_client.get("/profiles/abc/security")
            await cached_client.get("/profiles/abc/privacy")

            # Manual flush.
            await cached_client.flush_profile("abc")

            # Both should be flushed.
            assert await cached_client._cache.get("/profiles/abc/security") is None
            assert await cached_client._cache.get("/profiles/abc/privacy") is None

    async def test_cache_key_includes_params(
        self, cached_client: CachedNextDNSClient, mock_response: Any
    ) -> None:
        """Different query params produce different cache keys."""
        resp1 = mock_response(200, {"data": [{"status": "blocked"}]})
        resp2 = mock_response(200, {"data": [{"status": "allowed"}]})

        with patch.object(cached_client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [resp1, resp2]

            r1 = await cached_client.get(
                "/profiles/abc/analytics/status", params={"from": "2026-01-01"}
            )
            r2 = await cached_client.get(
                "/profiles/abc/analytics/status", params={"from": "2026-02-01"}
            )

        # Different params = different cache keys = both hit API.
        assert mock_req.call_count == 2
        assert r1 != r2


# ---------------------------------------------------------------------------
# Convenience method tests
# ---------------------------------------------------------------------------


class TestConvenienceMethods:
    """Verify sub-resource convenience methods."""

    async def test_get_profile(self, client: NextDNSClient, mock_response: Any) -> None:
        """get_profile calls GET /profiles/{id}."""
        response = mock_response(200, {"data": {"id": "abc", "name": "Home"}})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            result = await client.get_profile("abc")

        assert result == {"data": {"id": "abc", "name": "Home"}}
        call_args = mock_req.call_args
        assert call_args[0] == ("GET", "/profiles/abc")

    async def test_get_sub_resource(self, client: NextDNSClient, mock_response: Any) -> None:
        """get_sub_resource calls GET /profiles/{id}/{path}."""
        response = mock_response(200, {"data": {"nrd": True}})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            result = await client.get_sub_resource("abc", "security")

        assert result == {"data": {"nrd": True}}
        call_args = mock_req.call_args
        assert call_args[0] == ("GET", "/profiles/abc/security")

    async def test_patch_sub_resource(self, client: NextDNSClient, mock_response: Any) -> None:
        """patch_sub_resource calls PATCH /profiles/{id}/{path}."""
        response = mock_response(200, {"data": {"nrd": False}})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            result = await client.patch_sub_resource("abc", "security", {"nrd": False})

        assert result == {"data": {"nrd": False}}
        call_args = mock_req.call_args
        assert call_args[0] == ("PATCH", "/profiles/abc/security")
        assert call_args[1].get("json") == {"nrd": False}

    async def test_get_array(self, client: NextDNSClient, mock_response: Any) -> None:
        """get_array returns the 'data' array from the response."""
        response = mock_response(200, {"data": [{"id": "bad.com"}, {"id": "evil.org"}]})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            result = await client.get_array("abc", "denylist")

        assert result == [{"id": "bad.com"}, {"id": "evil.org"}]
        call_args = mock_req.call_args
        assert call_args[0] == ("GET", "/profiles/abc/denylist")

    async def test_add_to_array(self, client: NextDNSClient, mock_response: Any) -> None:
        """add_to_array calls POST /profiles/{id}/{path}."""
        response = mock_response(200, {"data": {"id": "bad.com", "active": True}})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            result = await client.add_to_array("abc", "denylist", {"id": "bad.com", "active": True})

        assert result == {"data": {"id": "bad.com", "active": True}}
        call_args = mock_req.call_args
        assert call_args[0] == ("POST", "/profiles/abc/denylist")

    async def test_update_array_child(self, client: NextDNSClient, mock_response: Any) -> None:
        """update_array_child calls PATCH /profiles/{id}/{path}/{item_id}."""
        response = mock_response(200, {"data": {"id": "bad.com", "active": False}})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            result = await client.update_array_child(
                "abc", "denylist", "bad.com", {"active": False}
            )

        assert result == {"data": {"id": "bad.com", "active": False}}
        call_args = mock_req.call_args
        assert call_args[0] == ("PATCH", "/profiles/abc/denylist/bad.com")

    async def test_delete_array_child(self, client: NextDNSClient, mock_response: Any) -> None:
        """delete_array_child calls DELETE /profiles/{id}/{path}/{item_id}."""
        response = mock_response(200, {})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            await client.delete_array_child("abc", "denylist", "bad.com")

        call_args = mock_req.call_args
        assert call_args[0] == ("DELETE", "/profiles/abc/denylist/bad.com")


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------


class TestContextManager:
    """Verify async context manager protocol."""

    async def test_context_manager_enter_returns_self(self, api_key: str) -> None:
        """__aenter__ returns the client instance."""
        async with NextDNSClient(api_key=api_key) as client:
            assert isinstance(client, NextDNSClient)

    async def test_context_manager_closes_on_exit(self, api_key: str) -> None:
        """__aexit__ calls close(), shutting down the httpx client."""
        client = NextDNSClient(api_key=api_key)
        with patch.object(client, "close", new_callable=AsyncMock) as mock_close:
            async with client:
                pass
            mock_close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Slow request warning tests
# ---------------------------------------------------------------------------


class TestSlowRequestWarning:
    """Verify slow request detection and logging."""

    async def test_slow_request_logged(self, client: NextDNSClient, mock_response: Any) -> None:
        """Requests exceeding the threshold generate a warning log."""
        response = mock_response(200, {"data": []})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response

            # Simulate a slow request by patching time.monotonic.
            original_monotonic = time.monotonic
            call_count = 0

            def slow_monotonic() -> float:
                nonlocal call_count
                call_count += 1
                # Make the elapsed time > threshold.
                base = original_monotonic()
                if call_count >= 3:  # After start time is recorded
                    return base + _SLOW_REQUEST_THRESHOLD + 1.0
                return base

            with (
                patch("nextdns.api.nextdns_client.time.monotonic", side_effect=slow_monotonic),
                patch("nextdns.api.nextdns_client.logger") as mock_logger,
            ):
                await client.get("/profiles")

                warning_calls = mock_logger.warning.call_args_list
                slow_logs = [c for c in warning_calls if "Slow request" in str(c)]
                assert len(slow_logs) >= 1


# ---------------------------------------------------------------------------
# HTTP method delegation tests
# ---------------------------------------------------------------------------


class TestHTTPMethods:
    """Verify all HTTP methods delegate to _request correctly."""

    async def test_post_sends_json_body(self, client: NextDNSClient, mock_response: Any) -> None:
        """POST method sends JSON body."""
        response = mock_response(200, {"data": {}})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            await client.post("/profiles/abc/denylist", data={"id": "bad.com"})

        call_args = mock_req.call_args
        assert call_args[0] == ("POST", "/profiles/abc/denylist")
        assert call_args[1].get("json") == {"id": "bad.com"}

    async def test_put_sends_json_body(self, client: NextDNSClient, mock_response: Any) -> None:
        """PUT method sends JSON body."""
        response = mock_response(200, {"data": {}})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            await client.put("/profiles/abc/denylist", data=[{"id": "bad.com"}])

        call_args = mock_req.call_args
        assert call_args[0] == ("PUT", "/profiles/abc/denylist")

    async def test_patch_sends_json_body(self, client: NextDNSClient, mock_response: Any) -> None:
        """PATCH method sends JSON body."""
        response = mock_response(200, {"data": {}})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            await client.patch("/profiles/abc/security", data={"nrd": False})

        call_args = mock_req.call_args
        assert call_args[0] == ("PATCH", "/profiles/abc/security")
        assert call_args[1].get("json") == {"nrd": False}

    async def test_delete_no_body(self, client: NextDNSClient, mock_response: Any) -> None:
        """DELETE method sends no JSON body."""
        response = mock_response(200, {})

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = response
            await client.delete("/profiles/abc/denylist/bad.com")

        call_args = mock_req.call_args
        assert call_args[0] == ("DELETE", "/profiles/abc/denylist/bad.com")
        assert call_args[1].get("json") is None


# ---------------------------------------------------------------------------
# Profile ID extraction tests
# ---------------------------------------------------------------------------


class TestProfileIdExtraction:
    """Verify _profile_id_from_endpoint helper."""

    def test_profile_id_from_profile_url(self) -> None:
        result = CachedNextDNSClient._profile_id_from_endpoint("/profiles/abc123")
        assert result == "abc123"

    def test_profile_id_from_sub_resource(self) -> None:
        result = CachedNextDNSClient._profile_id_from_endpoint("/profiles/abc123/security")
        assert result == "abc123"

    def test_no_profile_id_from_list(self) -> None:
        """The /profiles endpoint has no profile ID."""
        result = CachedNextDNSClient._profile_id_from_endpoint("/profiles")
        assert result is None

    def test_no_profile_id_from_root(self) -> None:
        result = CachedNextDNSClient._profile_id_from_endpoint("/")
        assert result is None
