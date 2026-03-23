"""Tests for the CachedGatewayClient — caching wrapper around LocalGatewayClient."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from unifi.api.cached_client import CachedGatewayClient
from unifi.cache import TTLCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    *,
    max_size: int = 500,
    default_ttl: float = 300.0,
) -> tuple[CachedGatewayClient, AsyncMock, TTLCache]:
    """Create a CachedGatewayClient with a mocked underlying client.

    Returns:
        A tuple of (cached_client, mock_raw_client, cache).
    """
    mock_raw = AsyncMock()
    cache = TTLCache(max_size=max_size, default_ttl=default_ttl)
    cached = CachedGatewayClient(mock_raw, cache)
    return cached, mock_raw, cache


# ---------------------------------------------------------------------------
# Cache hit / miss
# ---------------------------------------------------------------------------


class TestCacheHitMiss:
    """Tests for basic cache hit and miss behaviour."""

    @pytest.mark.asyncio
    async def test_first_get_calls_underlying_client(self) -> None:
        """First GET for an endpoint should call the underlying client."""
        client, mock_raw, _cache = _make_client()
        mock_raw.get.return_value = {"data": [{"mac": "aa:bb:cc"}]}

        result = await client.get("/api/s/default/stat/device")

        assert result == {"data": [{"mac": "aa:bb:cc"}]}
        mock_raw.get.assert_awaited_once_with("/api/s/default/stat/device", params=None)

    @pytest.mark.asyncio
    async def test_second_get_returns_cached_data(self) -> None:
        """Second GET for the same endpoint should return cached data
        without calling the underlying client again."""
        client, mock_raw, _cache = _make_client()
        mock_raw.get.return_value = {"data": [{"mac": "aa:bb:cc"}]}

        result1 = await client.get("/api/s/default/stat/device")
        result2 = await client.get("/api/s/default/stat/device")

        assert result1 == result2
        # Underlying client called only once.
        assert mock_raw.get.await_count == 1

    @pytest.mark.asyncio
    async def test_different_endpoints_cached_independently(self) -> None:
        """GETs to different endpoints should be cached independently."""
        client, mock_raw, _cache = _make_client()
        mock_raw.get.side_effect = [
            {"data": "devices"},
            {"data": "clients"},
        ]

        r1 = await client.get("/api/s/default/stat/device")
        r2 = await client.get("/api/s/default/stat/sta")

        assert r1 == {"data": "devices"}
        assert r2 == {"data": "clients"}
        assert mock_raw.get.await_count == 2

    @pytest.mark.asyncio
    async def test_different_params_cached_independently(self) -> None:
        """GETs to the same endpoint with different params should be
        cached independently."""
        client, mock_raw, _cache = _make_client()
        mock_raw.get.side_effect = [
            {"data": "vlan10"},
            {"data": "vlan20"},
        ]

        r1 = await client.get("/api/s/default/stat/sta", params={"vlan_id": "10"})
        r2 = await client.get("/api/s/default/stat/sta", params={"vlan_id": "20"})

        assert r1 == {"data": "vlan10"}
        assert r2 == {"data": "vlan20"}
        assert mock_raw.get.await_count == 2

    @pytest.mark.asyncio
    async def test_same_params_different_order_is_cache_hit(self) -> None:
        """Params in different dict order should produce the same cache key."""
        client, mock_raw, _cache = _make_client()
        mock_raw.get.return_value = {"data": "result"}

        # Two dicts with same keys/values but different insertion order.
        await client.get("/api/s/default/stat/sta", params={"b": "2", "a": "1"})
        await client.get("/api/s/default/stat/sta", params={"a": "1", "b": "2"})

        # Should only call underlying client once (cache hit on second call).
        assert mock_raw.get.await_count == 1

    @pytest.mark.asyncio
    async def test_get_passes_params_to_underlying_client(self) -> None:
        """Query parameters should be forwarded to the underlying client."""
        client, mock_raw, _cache = _make_client()
        mock_raw.get.return_value = {"data": []}
        params: dict[str, Any] = {"type": "all", "within": "3600"}

        await client.get("/api/s/default/stat/sta", params=params)

        mock_raw.get.assert_awaited_once_with("/api/s/default/stat/sta", params=params)


# ---------------------------------------------------------------------------
# TTL selection per endpoint
# ---------------------------------------------------------------------------


class TestTTLSelection:
    """Tests for per-endpoint TTL resolution."""

    def test_stat_device_ttl(self) -> None:
        client, _, _ = _make_client()
        assert client._resolve_ttl("/api/s/default/stat/device") == 300

    def test_stat_health_ttl(self) -> None:
        client, _, _ = _make_client()
        assert client._resolve_ttl("/api/s/default/stat/health") == 120

    def test_stat_sta_ttl(self) -> None:
        client, _, _ = _make_client()
        assert client._resolve_ttl("/api/s/default/stat/sta") == 30

    def test_stat_event_ttl_is_zero(self) -> None:
        client, _, _ = _make_client()
        assert client._resolve_ttl("/api/s/default/stat/event") == 0

    def test_rest_networkconf_ttl(self) -> None:
        client, _, _ = _make_client()
        assert client._resolve_ttl("/api/s/default/rest/networkconf") == 300

    def test_rest_wlanconf_ttl(self) -> None:
        client, _, _ = _make_client()
        assert client._resolve_ttl("/api/s/default/rest/wlanconf") == 300

    def test_unknown_endpoint_uses_default_ttl(self) -> None:
        client, _, _ = _make_client()
        assert client._resolve_ttl("/api/s/default/some/unknown/endpoint") == 300

    def test_endpoint_with_subpath_still_matches(self) -> None:
        """Endpoint like stat/device/abc123 should still match stat/device."""
        client, _, _ = _make_client()
        assert client._resolve_ttl("/api/s/default/stat/device/abc123") == 300


# ---------------------------------------------------------------------------
# Events endpoint (TTL=0) is never cached
# ---------------------------------------------------------------------------


class TestNoCacheEndpoints:
    """Tests that endpoints with TTL=0 bypass the cache entirely."""

    @pytest.mark.asyncio
    async def test_events_always_calls_underlying_client(self) -> None:
        """stat/event has TTL=0, so every GET should hit the API."""
        client, mock_raw, _cache = _make_client()
        mock_raw.get.side_effect = [
            {"data": [{"event": "1"}]},
            {"data": [{"event": "2"}]},
        ]

        r1 = await client.get("/api/s/default/stat/event")
        r2 = await client.get("/api/s/default/stat/event")

        # Both calls should hit the underlying client.
        assert r1 == {"data": [{"event": "1"}]}
        assert r2 == {"data": [{"event": "2"}]}
        assert mock_raw.get.await_count == 2

    @pytest.mark.asyncio
    async def test_events_not_stored_in_cache(self) -> None:
        """TTL=0 endpoints should not add entries to the cache."""
        client, mock_raw, cache = _make_client()
        mock_raw.get.return_value = {"data": []}

        await client.get("/api/s/default/stat/event")

        assert cache.stats["size"] == 0


# ---------------------------------------------------------------------------
# POST flushes related cache entries
# ---------------------------------------------------------------------------


class TestPostFlush:
    """Tests that POST requests flush related cache entries."""

    @pytest.mark.asyncio
    async def test_post_calls_underlying_client(self) -> None:
        """POST should always call the underlying client."""
        client, mock_raw, _cache = _make_client()
        mock_raw.post.return_value = {"meta": {"rc": "ok"}}

        result = await client.post("/api/s/default/cmd/devmgr", data={"cmd": "restart"})

        assert result == {"meta": {"rc": "ok"}}
        mock_raw.post.assert_awaited_once_with("/api/s/default/cmd/devmgr", data={"cmd": "restart"})

    @pytest.mark.asyncio
    async def test_post_flushes_cache_for_endpoint_prefix(self) -> None:
        """After a successful POST, cached GETs for the same endpoint
        prefix should be invalidated."""
        client, mock_raw, _cache = _make_client()
        mock_raw.get.side_effect = [
            {"data": "first"},
            {"data": "second"},
        ]
        mock_raw.post.return_value = {"meta": {"rc": "ok"}}

        # Populate cache.
        r1 = await client.get("/api/s/default/stat/device")
        assert r1 == {"data": "first"}
        assert mock_raw.get.await_count == 1

        # POST to the same endpoint family.
        await client.post("/api/s/default/stat/device", data={"action": "update"})

        # Subsequent GET should re-fetch (cache was flushed).
        r2 = await client.get("/api/s/default/stat/device")
        assert r2 == {"data": "second"}
        assert mock_raw.get.await_count == 2

    @pytest.mark.asyncio
    async def test_post_flushes_only_matching_prefix(self) -> None:
        """POST should only flush cache entries for the affected endpoint,
        not unrelated endpoints."""
        client, mock_raw, _cache = _make_client()
        mock_raw.get.side_effect = [
            {"data": "devices"},
            {"data": "clients"},
        ]
        mock_raw.post.return_value = {"meta": {"rc": "ok"}}

        # Populate cache for two different endpoints.
        await client.get("/api/s/default/stat/device")
        await client.get("/api/s/default/stat/sta")

        # POST to stat/device — should flush device cache only.
        await client.post("/api/s/default/stat/device", data={"action": "update"})

        # stat/sta should still be cached (no additional get call needed).
        r = await client.get("/api/s/default/stat/sta")
        assert r == {"data": "clients"}
        # Only 2 get calls total: one for device, one for sta. The third
        # get for sta should have been a cache hit.
        assert mock_raw.get.await_count == 2

    @pytest.mark.asyncio
    async def test_post_flushes_all_params_variants(self) -> None:
        """POST should flush all cached entries for the endpoint, regardless
        of the query params used in the cached GETs."""
        client, mock_raw, _cache = _make_client()
        mock_raw.get.side_effect = [
            {"data": "vlan10"},
            {"data": "vlan20"},
            {"data": "vlan10_fresh"},
            {"data": "vlan20_fresh"},
        ]
        mock_raw.post.return_value = {"meta": {"rc": "ok"}}

        # Cache two GETs with different params.
        await client.get("/api/s/default/stat/sta", params={"vlan_id": "10"})
        await client.get("/api/s/default/stat/sta", params={"vlan_id": "20"})
        assert mock_raw.get.await_count == 2

        # POST to stat/sta — should flush both cached entries.
        await client.post("/api/s/default/stat/sta", data={"action": "kick"})

        # Both GETs should now re-fetch.
        await client.get("/api/s/default/stat/sta", params={"vlan_id": "10"})
        await client.get("/api/s/default/stat/sta", params={"vlan_id": "20"})
        assert mock_raw.get.await_count == 4

    @pytest.mark.asyncio
    async def test_post_with_trailing_slash_flushes_correctly(self) -> None:
        """POST to an endpoint with a trailing slash should still flush
        the cached entries for the base endpoint."""
        client, mock_raw, _cache = _make_client()
        mock_raw.get.side_effect = [
            {"data": "first"},
            {"data": "second"},
        ]
        mock_raw.post.return_value = {"meta": {"rc": "ok"}}

        await client.get("/api/s/default/stat/device")
        assert mock_raw.get.await_count == 1

        # POST with trailing slash.
        await client.post("/api/s/default/stat/device/", data={"action": "update"})

        # Should have flushed; next GET re-fetches.
        await client.get("/api/s/default/stat/device")
        assert mock_raw.get.await_count == 2


# ---------------------------------------------------------------------------
# Cache stats tracking
# ---------------------------------------------------------------------------


class TestCacheStats:
    """Tests for the cache_stats property."""

    @pytest.mark.asyncio
    async def test_initial_stats(self) -> None:
        client, _, _ = _make_client()
        assert client.cache_stats == {
            "hits": 0,
            "misses": 0,
            "size": 0,
            "evictions": 0,
        }

    @pytest.mark.asyncio
    async def test_stats_after_miss_and_hit(self) -> None:
        """Cache stats should reflect a miss on first GET and a hit on second."""
        client, mock_raw, _ = _make_client()
        mock_raw.get.return_value = {"data": []}

        await client.get("/api/s/default/stat/device")  # Miss.
        await client.get("/api/s/default/stat/device")  # Hit.

        stats = client.cache_stats
        assert stats["misses"] == 1
        assert stats["hits"] == 1
        assert stats["size"] == 1

    @pytest.mark.asyncio
    async def test_stats_not_affected_by_zero_ttl_endpoints(self) -> None:
        """Requests to TTL=0 endpoints should not appear in cache stats
        as entries (though they may appear as misses in the underlying
        cache if get_or_fetch were used — but TTL=0 bypasses entirely)."""
        client, mock_raw, _ = _make_client()
        mock_raw.get.return_value = {"data": []}

        await client.get("/api/s/default/stat/event")
        await client.get("/api/s/default/stat/event")

        stats = client.cache_stats
        # TTL=0 bypasses the cache entirely, so no hits/misses/size changes.
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0


# ---------------------------------------------------------------------------
# Manual flush
# ---------------------------------------------------------------------------


class TestManualFlush:
    """Tests for the flush() method."""

    @pytest.mark.asyncio
    async def test_flush_all(self) -> None:
        """flush() with no args should clear the entire cache."""
        client, mock_raw, _ = _make_client()
        mock_raw.get.return_value = {"data": []}

        await client.get("/api/s/default/stat/device")
        await client.get("/api/s/default/stat/sta")
        assert client.cache_stats["size"] == 2

        await client.flush()
        assert client.cache_stats["size"] == 0

    @pytest.mark.asyncio
    async def test_flush_specific_endpoint(self) -> None:
        """flush(endpoint) should clear only entries for that endpoint."""
        client, mock_raw, _ = _make_client()
        mock_raw.get.side_effect = [
            {"data": "devices"},
            {"data": "clients"},
            {"data": "devices_fresh"},
        ]

        await client.get("/api/s/default/stat/device")
        await client.get("/api/s/default/stat/sta")
        assert client.cache_stats["size"] == 2

        await client.flush("/api/s/default/stat/device")

        # stat/device should be flushed.
        r = await client.get("/api/s/default/stat/device")
        assert r == {"data": "devices_fresh"}
        assert mock_raw.get.await_count == 3  # Re-fetched device.

    @pytest.mark.asyncio
    async def test_flush_specific_endpoint_preserves_others(self) -> None:
        """Flushing one endpoint should not affect other endpoints."""
        client, mock_raw, _ = _make_client()
        mock_raw.get.side_effect = [
            {"data": "devices"},
            {"data": "clients"},
        ]

        await client.get("/api/s/default/stat/device")
        await client.get("/api/s/default/stat/sta")

        await client.flush("/api/s/default/stat/device")

        # stat/sta should still be cached.
        r = await client.get("/api/s/default/stat/sta")
        assert r == {"data": "clients"}
        assert mock_raw.get.await_count == 2  # No additional calls.

    @pytest.mark.asyncio
    async def test_flush_nonexistent_endpoint_is_noop(self) -> None:
        """Flushing an endpoint with no cached entries should not raise."""
        client, _, _ = _make_client()
        await client.flush("/api/s/default/nonexistent")  # Should not raise.


# ---------------------------------------------------------------------------
# Cache key construction
# ---------------------------------------------------------------------------


class TestCacheKey:
    """Tests for the _build_cache_key static method."""

    def test_key_with_no_params(self) -> None:
        key = CachedGatewayClient._build_cache_key("/api/s/default/stat/device")
        assert key == "/api/s/default/stat/device:{}"

    def test_key_with_params(self) -> None:
        key = CachedGatewayClient._build_cache_key(
            "/api/s/default/stat/sta",
            params={"vlan_id": "10"},
        )
        assert key == '/api/s/default/stat/sta:{"vlan_id":"10"}'

    def test_key_with_multiple_params_sorted(self) -> None:
        key = CachedGatewayClient._build_cache_key(
            "/api/s/default/stat/sta",
            params={"z_param": "3", "a_param": "1", "m_param": "2"},
        )
        assert key == '/api/s/default/stat/sta:{"a_param":"1","m_param":"2","z_param":"3"}'

    def test_key_with_none_params(self) -> None:
        key = CachedGatewayClient._build_cache_key("/api/s/default/stat/device", params=None)
        assert key == "/api/s/default/stat/device:{}"

    def test_key_with_empty_params(self) -> None:
        key = CachedGatewayClient._build_cache_key("/api/s/default/stat/device", params={})
        assert key == "/api/s/default/stat/device:{}"

    def test_numeric_param_values_converted_to_string(self) -> None:
        key = CachedGatewayClient._build_cache_key(
            "/api/s/default/stat/sta",
            params={"limit": 100},
        )
        assert key == '/api/s/default/stat/sta:{"limit":"100"}'


# ---------------------------------------------------------------------------
# Endpoint prefix extraction
# ---------------------------------------------------------------------------


class TestEndpointPrefix:
    """Tests for the _extract_endpoint_prefix static method."""

    def test_basic_endpoint(self) -> None:
        prefix = CachedGatewayClient._extract_endpoint_prefix("/api/s/default/stat/device")
        assert prefix == "/api/s/default/stat/device"

    def test_endpoint_with_trailing_slash(self) -> None:
        prefix = CachedGatewayClient._extract_endpoint_prefix("/api/s/default/stat/device/")
        assert prefix == "/api/s/default/stat/device"

    def test_endpoint_with_multiple_trailing_slashes(self) -> None:
        prefix = CachedGatewayClient._extract_endpoint_prefix("/api/s/default/stat/device///")
        assert prefix == "/api/s/default/stat/device"


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    """Tests that errors from the underlying client propagate correctly."""

    @pytest.mark.asyncio
    async def test_get_error_propagates_and_is_not_cached(self) -> None:
        """If the underlying GET raises, the error should propagate and
        nothing should be cached."""
        client, mock_raw, _ = _make_client()
        mock_raw.get.side_effect = ConnectionError("API unreachable")

        with pytest.raises(ConnectionError, match="API unreachable"):
            await client.get("/api/s/default/stat/device")

        assert client.cache_stats["size"] == 0

    @pytest.mark.asyncio
    async def test_post_error_propagates_without_flush(self) -> None:
        """If the underlying POST raises, the error should propagate and
        the cache should NOT be flushed (only flush on success)."""
        client, mock_raw, cache = _make_client()

        # Pre-populate cache.
        mock_raw.get.return_value = {"data": "cached"}
        await client.get("/api/s/default/stat/device")
        assert cache.stats["size"] == 1

        # POST fails.
        mock_raw.post.side_effect = ConnectionError("API unreachable")
        with pytest.raises(ConnectionError, match="API unreachable"):
            await client.post("/api/s/default/stat/device", data={"cmd": "restart"})

        # Cache should still have the entry (not flushed on failure).
        assert cache.stats["size"] == 1
