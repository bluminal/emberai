"""Tests for the async TTL cache with LRU eviction and stampede protection.

Covers OPNsense-specific default TTLs (CacheTTL) and the full cache
implementation: get/set, TTL expiration, LRU eviction, flush,
get_or_fetch with stampede protection, concurrency safety, and stats.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from opnsense.cache import CacheTTL, TTLCache


# ---------------------------------------------------------------------------
# CacheTTL constants
# ---------------------------------------------------------------------------


class TestCacheTTL:
    """Verify OPNsense-specific default TTL constants."""

    def test_interface_ttl(self) -> None:
        assert CacheTTL.INTERFACES == 300.0  # 5 minutes

    def test_firewall_rules_ttl(self) -> None:
        assert CacheTTL.FIREWALL_RULES == 120.0  # 2 minutes

    def test_dhcp_leases_ttl(self) -> None:
        assert CacheTTL.DHCP_LEASES == 60.0  # 1 minute

    def test_vpn_sessions_ttl(self) -> None:
        assert CacheTTL.VPN_SESSIONS == 60.0  # 1 minute

    def test_firmware_ttl(self) -> None:
        assert CacheTTL.FIRMWARE == 600.0  # 10 minutes

    def test_ids_alerts_ttl(self) -> None:
        assert CacheTTL.IDS_ALERTS == 30.0  # 30 seconds

    def test_routes_ttl(self) -> None:
        assert CacheTTL.ROUTES == 120.0  # 2 minutes

    def test_certificates_ttl(self) -> None:
        assert CacheTTL.CERTIFICATES == 300.0  # 5 minutes


# ---------------------------------------------------------------------------
# Construction & validation
# ---------------------------------------------------------------------------


class TestConstruction:
    """Tests for TTLCache.__init__ parameter validation."""

    def test_default_parameters(self) -> None:
        cache = TTLCache()
        assert cache._max_size == 1000
        assert cache._default_ttl == 120.0  # OPNsense default: 2 minutes

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
# Basic get / set
# ---------------------------------------------------------------------------


class TestGetSet:
    """Tests for basic get and set operations."""

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self) -> None:
        cache = TTLCache()
        result = await cache.get("nonexistent")
        assert result is None

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
    async def test_set_overwrites_existing_key(self) -> None:
        cache = TTLCache()
        await cache.set("key", "first")
        await cache.set("key", "second")
        assert await cache.get("key") == "second"

    @pytest.mark.asyncio
    async def test_set_with_custom_ttl(self) -> None:
        cache = TTLCache(default_ttl=300.0)
        await cache.set("key", "value", ttl=0.05)

        # Value should be available immediately.
        assert await cache.get("key") == "value"

        # Wait for expiry.
        await asyncio.sleep(0.06)
        assert await cache.get("key") is None


# ---------------------------------------------------------------------------
# TTL expiration
# ---------------------------------------------------------------------------


class TestTTLExpiration:
    """Tests for TTL-based entry expiration."""

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
        await cache.get("key")  # Triggers lazy removal.
        assert cache.stats["size"] == 0

    @pytest.mark.asyncio
    async def test_per_key_ttl_independence(self) -> None:
        """Different keys can have different TTLs."""
        cache = TTLCache(default_ttl=300.0)
        await cache.set("short", "short-lived", ttl=0.05)
        await cache.set("long", "long-lived", ttl=5.0)

        await asyncio.sleep(0.06)

        assert await cache.get("short") is None  # Expired.
        assert await cache.get("long") == "long-lived"  # Still alive.


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------


class TestLRUEviction:
    """Tests for max_size enforcement and LRU eviction policy."""

    @pytest.mark.asyncio
    async def test_evicts_lru_when_full(self) -> None:
        cache = TTLCache(max_size=3, default_ttl=300.0)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)

        # Cache is full. Adding a 4th entry should evict "a" (LRU).
        await cache.set("d", 4)

        assert await cache.get("a") is None  # Evicted.
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

        # Access "a" to promote it to MRU.
        await cache.get("a")

        # Now "b" is the LRU. Adding "d" should evict "b".
        await cache.set("d", 4)

        assert await cache.get("a") == 1  # Promoted, not evicted.
        assert await cache.get("b") is None  # Evicted.

    @pytest.mark.asyncio
    async def test_eviction_count_accumulates(self) -> None:
        cache = TTLCache(max_size=2, default_ttl=300.0)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)  # Evicts "a"
        await cache.set("d", 4)  # Evicts "b"

        assert cache.stats["evictions"] == 2


# ---------------------------------------------------------------------------
# Flush
# ---------------------------------------------------------------------------


class TestFlush:
    """Tests for flush and flush_by_prefix."""

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
        await cache.set("firewall:rules", [1, 2])
        await cache.set("firewall:aliases", [3, 4])
        await cache.set("interfaces:list", [5, 6])

        await cache.flush_by_prefix("firewall:")

        assert await cache.get("firewall:rules") is None
        assert await cache.get("firewall:aliases") is None
        assert await cache.get("interfaces:list") == [5, 6]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestStats:
    """Tests for cache hit/miss/eviction statistics."""

    @pytest.mark.asyncio
    async def test_initial_stats(self) -> None:
        cache = TTLCache()
        assert cache.stats == {
            "hits": 0,
            "misses": 0,
            "size": 0,
            "evictions": 0,
        }

    @pytest.mark.asyncio
    async def test_hit_tracking(self) -> None:
        cache = TTLCache()
        await cache.set("key", "value")
        await cache.get("key")
        await cache.get("key")
        assert cache.stats["hits"] == 2

    @pytest.mark.asyncio
    async def test_miss_tracking(self) -> None:
        cache = TTLCache()
        await cache.get("missing")
        assert cache.stats["misses"] == 1


# ---------------------------------------------------------------------------
# get_or_fetch
# ---------------------------------------------------------------------------


class TestGetOrFetch:
    """Tests for get_or_fetch caching and fetcher invocation."""

    @pytest.mark.asyncio
    async def test_fetcher_called_on_miss(self) -> None:
        cache = TTLCache()
        fetcher = AsyncMock(return_value={"rules": [1, 2, 3]})

        result = await cache.get_or_fetch("key", fetcher)

        assert result == {"rules": [1, 2, 3]}
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

        await cache.get_or_fetch("key", fetcher, ttl=CacheTTL.IDS_ALERTS)
        assert await cache.get("key") == "value"

    @pytest.mark.asyncio
    async def test_fetcher_exception_propagates(self) -> None:
        cache = TTLCache()

        async def failing_fetcher() -> None:
            raise ConnectionError("OPNsense API unreachable")

        with pytest.raises(ConnectionError, match="OPNsense API unreachable"):
            await cache.get_or_fetch("key", failing_fetcher)

        # Key should NOT be cached after a failed fetch.
        assert await cache.get("key") is None


# ---------------------------------------------------------------------------
# Stampede protection
# ---------------------------------------------------------------------------


class TestStampedeProtection:
    """Tests for the single-flight pattern in get_or_fetch."""

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

        # Launch 10 concurrent requests for the same key.
        tasks = [
            asyncio.create_task(cache.get_or_fetch("key", slow_fetcher))
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks)

        assert all(r == "result" for r in results)
        assert call_count == 1, (
            f"Fetcher was called {call_count} times, expected 1"
        )

    @pytest.mark.asyncio
    async def test_stampede_fetcher_error_propagates_to_all(self) -> None:
        """When the fetcher fails, all waiting callers should receive the
        exception."""
        cache = TTLCache()

        async def failing_fetcher() -> None:
            await asyncio.sleep(0.05)
            raise ValueError("API down")

        tasks = [
            asyncio.create_task(cache.get_or_fetch("key", failing_fetcher))
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert all(isinstance(r, ValueError) for r in results)


# ---------------------------------------------------------------------------
# Concurrent access safety
# ---------------------------------------------------------------------------


class TestConcurrency:
    """Tests for asyncio.Lock correctness under concurrent access."""

    @pytest.mark.asyncio
    async def test_concurrent_sets_no_corruption(self) -> None:
        """Many concurrent set operations should not corrupt the store."""
        cache = TTLCache(max_size=1000, default_ttl=300.0)

        async def setter(i: int) -> None:
            await cache.set(f"key-{i}", i)

        await asyncio.gather(*[setter(i) for i in range(200)])

        assert cache.stats["size"] == 200
        for i in range(200):
            assert await cache.get(f"key-{i}") == i
