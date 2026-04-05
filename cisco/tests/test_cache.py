"""Tests for the async TTL cache with LRU eviction and stampede protection.

Covers Cisco-specific default TTLs (CacheTTL) and the full cache
implementation: get/set, TTL expiration, LRU eviction, flush,
get_or_fetch with stampede protection, concurrency safety, and stats.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from cisco.cache import CacheTTL, TTLCache

# ---------------------------------------------------------------------------
# CacheTTL constants
# ---------------------------------------------------------------------------


class TestCacheTTL:
    """Verify Cisco-specific default TTL constants."""

    def test_vlans_ttl(self) -> None:
        assert CacheTTL.VLANS == 300.0  # 5 minutes

    def test_interfaces_ttl(self) -> None:
        assert CacheTTL.INTERFACES == 120.0  # 2 minutes

    def test_mac_table_ttl(self) -> None:
        assert CacheTTL.MAC_TABLE == 30.0  # 30 seconds

    def test_lldp_neighbors_ttl(self) -> None:
        assert CacheTTL.LLDP_NEIGHBORS == 300.0  # 5 minutes

    def test_running_config_ttl(self) -> None:
        assert CacheTTL.RUNNING_CONFIG == 600.0  # 10 minutes

    def test_system_info_ttl(self) -> None:
        assert CacheTTL.SYSTEM_INFO == 600.0  # 10 minutes

    def test_interface_counters_ttl(self) -> None:
        assert CacheTTL.INTERFACE_COUNTERS == 60.0  # 1 minute

    def test_spanning_tree_ttl(self) -> None:
        assert CacheTTL.SPANNING_TREE == 120.0  # 2 minutes


# ---------------------------------------------------------------------------
# Construction & validation
# ---------------------------------------------------------------------------


class TestConstruction:
    """Tests for TTLCache.__init__ parameter validation."""

    def test_default_parameters(self) -> None:
        cache = TTLCache()
        assert cache._max_size == 1000
        assert cache._default_ttl == 120.0

    def test_custom_parameters(self) -> None:
        cache = TTLCache(max_size=50, default_ttl=10.0)
        assert cache._max_size == 50
        assert cache._default_ttl == 10.0

    def test_zero_max_size_raises(self) -> None:
        with pytest.raises(ValueError, match="max_size must be positive"):
            TTLCache(max_size=0)

    def test_negative_max_size_raises(self) -> None:
        with pytest.raises(ValueError, match="max_size must be positive"):
            TTLCache(max_size=-1)

    def test_zero_ttl_raises(self) -> None:
        with pytest.raises(ValueError, match="default_ttl must be positive"):
            TTLCache(default_ttl=0)

    def test_negative_ttl_raises(self) -> None:
        with pytest.raises(ValueError, match="default_ttl must be positive"):
            TTLCache(default_ttl=-5.0)


# ---------------------------------------------------------------------------
# Basic get / set -- cache hit
# ---------------------------------------------------------------------------


class TestCacheHit:
    """Test cache_hit -- set and get before TTL expires."""

    @pytest.mark.asyncio
    async def test_set_and_get_round_trip(self) -> None:
        cache = TTLCache()
        await cache.set("key1", {"data": 42})
        result = await cache.get("key1")
        assert result == {"data": 42}

    @pytest.mark.asyncio
    async def test_set_various_value_types(self) -> None:
        cache = TTLCache()
        await cache.set("str", "hello")
        await cache.set("int", 42)
        await cache.set("list", [1, 2, 3])
        await cache.set("none", None)

        assert await cache.get("str") == "hello"
        assert await cache.get("int") == 42
        assert await cache.get("list") == [1, 2, 3]
        assert await cache.get("none") is None

    @pytest.mark.asyncio
    async def test_hit_tracking(self) -> None:
        cache = TTLCache()
        await cache.set("key", "value")
        await cache.get("key")
        await cache.get("key")
        assert cache.stats["hits"] == 2

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self) -> None:
        cache = TTLCache()
        result = await cache.get("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# TTL expiration -- cache miss after TTL
# ---------------------------------------------------------------------------


class TestCacheMissAfterTTL:
    """Test cache_miss_after_ttl -- set, wait, get returns None."""

    @pytest.mark.asyncio
    async def test_expired_entry_returns_none(self) -> None:
        cache = TTLCache(default_ttl=0.05)
        await cache.set("key", "value")
        await asyncio.sleep(0.06)
        assert await cache.get("key") is None

    @pytest.mark.asyncio
    async def test_expired_entry_is_removed_from_store(self) -> None:
        cache = TTLCache(default_ttl=0.05)
        await cache.set("key", "value")
        await asyncio.sleep(0.06)
        await cache.get("key")  # Triggers lazy removal
        assert cache.stats["size"] == 0

    @pytest.mark.asyncio
    async def test_per_key_ttl_independence(self) -> None:
        cache = TTLCache(default_ttl=300.0)
        await cache.set("short", "short-lived", ttl=0.05)
        await cache.set("long", "long-lived", ttl=5.0)

        await asyncio.sleep(0.06)

        assert await cache.get("short") is None
        assert await cache.get("long") == "long-lived"

    @pytest.mark.asyncio
    async def test_miss_tracking(self) -> None:
        cache = TTLCache()
        await cache.get("missing")
        assert cache.stats["misses"] == 1


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------


class TestCacheLRUEviction:
    """Test cache_lru_eviction -- fill cache beyond max_size."""

    @pytest.mark.asyncio
    async def test_evicts_lru_when_full(self) -> None:
        cache = TTLCache(max_size=3, default_ttl=300.0)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)

        # Cache is full. Adding a 4th entry should evict "a" (LRU).
        await cache.set("d", 4)

        assert await cache.get("a") is None  # Evicted
        assert await cache.get("b") == 2
        assert await cache.get("c") == 3
        assert await cache.get("d") == 4
        assert cache.stats["evictions"] == 1

    @pytest.mark.asyncio
    async def test_get_promotes_to_mru(self) -> None:
        """Accessing a key promotes it, so it won't be evicted next."""
        cache = TTLCache(max_size=3, default_ttl=300.0)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)

        # Access "a" to promote it to MRU
        await cache.get("a")

        # Now "b" is the LRU. Adding "d" should evict "b".
        await cache.set("d", 4)

        assert await cache.get("a") == 1  # Promoted, not evicted
        assert await cache.get("b") is None  # Evicted

    @pytest.mark.asyncio
    async def test_eviction_count_accumulates(self) -> None:
        cache = TTLCache(max_size=2, default_ttl=300.0)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)  # Evicts "a"
        await cache.set("d", 4)  # Evicts "b"

        assert cache.stats["evictions"] == 2


# ---------------------------------------------------------------------------
# get_or_fetch
# ---------------------------------------------------------------------------


class TestGetOrFetch:
    """Test get_or_fetch -- fetcher called on miss, not on hit."""

    @pytest.mark.asyncio
    async def test_fetcher_called_on_miss(self) -> None:
        cache = TTLCache()
        fetcher = AsyncMock(return_value={"vlans": [1, 10, 20]})

        result = await cache.get_or_fetch("key", fetcher)

        assert result == {"vlans": [1, 10, 20]}
        fetcher.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetcher_not_called_on_hit(self) -> None:
        cache = TTLCache()
        await cache.set("key", "cached-value")
        fetcher = AsyncMock(return_value="fresh-value")

        result = await cache.get_or_fetch("key", fetcher)

        assert result == "cached-value"
        fetcher.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_custom_ttl_on_get_or_fetch(self) -> None:
        cache = TTLCache(default_ttl=300.0)
        fetcher = AsyncMock(return_value="value")

        await cache.get_or_fetch("key", fetcher, ttl=CacheTTL.MAC_TABLE)
        assert await cache.get("key") == "value"

    @pytest.mark.asyncio
    async def test_fetcher_exception_propagates(self) -> None:
        cache = TTLCache()

        async def failing_fetcher() -> None:
            raise ConnectionError("SSH connection lost")

        with pytest.raises(ConnectionError, match="SSH connection lost"):
            await cache.get_or_fetch("key", failing_fetcher)

        # Key should NOT be cached after a failed fetch
        assert await cache.get("key") is None


# ---------------------------------------------------------------------------
# Flush
# ---------------------------------------------------------------------------


class TestFlush:
    """Test flush -- by key, flush all, flush by prefix."""

    @pytest.mark.asyncio
    async def test_flush_single_key(self) -> None:
        cache = TTLCache()
        await cache.set("a", 1)
        await cache.set("b", 2)

        await cache.flush("a")

        assert await cache.get("a") is None
        assert await cache.get("b") == 2

    @pytest.mark.asyncio
    async def test_flush_all(self) -> None:
        cache = TTLCache()
        await cache.set("a", 1)
        await cache.set("b", 2)

        await cache.flush()

        assert cache.stats["size"] == 0

    @pytest.mark.asyncio
    async def test_flush_by_prefix(self) -> None:
        cache = TTLCache()
        await cache.set("vlans:all", [1, 10])
        await cache.set("vlans:10", {"name": "Admin"})
        await cache.set("interfaces:list", ["gi1", "gi2"])

        await cache.flush_by_prefix("vlans:")

        assert await cache.get("vlans:all") is None
        assert await cache.get("vlans:10") is None
        assert await cache.get("interfaces:list") == ["gi1", "gi2"]


# ---------------------------------------------------------------------------
# Stampede protection
# ---------------------------------------------------------------------------


class TestStampedeProtection:
    """Test stampede_protection -- concurrent calls trigger one fetch."""

    @pytest.mark.asyncio
    async def test_concurrent_callers_single_fetch(self) -> None:
        """Multiple concurrent get_or_fetch calls for the same key should
        result in only one invocation of the fetcher."""
        cache = TTLCache()
        call_count = 0

        async def slow_fetcher() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)
            return "result"

        tasks = [
            asyncio.create_task(cache.get_or_fetch("key", slow_fetcher))
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks)

        assert all(r == "result" for r in results)
        assert call_count == 1, f"Fetcher was called {call_count} times, expected 1"

    @pytest.mark.asyncio
    async def test_stampede_fetcher_error_propagates_to_all(self) -> None:
        """When the fetcher fails, all waiting callers should receive the
        exception."""
        cache = TTLCache()

        async def failing_fetcher() -> None:
            await asyncio.sleep(0.05)
            raise ValueError("SSH down")

        tasks = [
            asyncio.create_task(cache.get_or_fetch("key", failing_fetcher))
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert all(isinstance(r, ValueError) for r in results)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestStats:
    """Cache statistics tracking."""

    @pytest.mark.asyncio
    async def test_initial_stats(self) -> None:
        cache = TTLCache()
        assert cache.stats == {
            "hits": 0,
            "misses": 0,
            "size": 0,
            "evictions": 0,
        }
