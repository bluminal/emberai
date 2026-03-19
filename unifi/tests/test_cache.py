"""Tests for the async TTL cache with LRU eviction and stampede protection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from unifi.cache import TTLCache


# ---------------------------------------------------------------------------
# Construction & validation
# ---------------------------------------------------------------------------


class TestConstruction:
    """Tests for TTLCache.__init__ parameter validation."""

    def test_default_parameters(self) -> None:
        cache = TTLCache()
        assert cache._max_size == 1000
        assert cache._default_ttl == 300.0

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
        # None is a valid cached value -- distinct from "key not found".
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

    @pytest.mark.asyncio
    async def test_overwrite_resets_ttl(self) -> None:
        cache = TTLCache(default_ttl=0.05)
        await cache.set("key", "v1")
        await asyncio.sleep(0.03)
        # Overwrite with a fresh TTL.
        await cache.set("key", "v2", ttl=5.0)
        await asyncio.sleep(0.03)
        # Original TTL would have expired, but the overwrite gave us more time.
        assert await cache.get("key") == "v2"


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
        assert await cache.get("c") == 3
        assert await cache.get("d") == 4

    @pytest.mark.asyncio
    async def test_set_existing_key_does_not_evict(self) -> None:
        """Overwriting an existing key should not trigger eviction."""
        cache = TTLCache(max_size=3, default_ttl=300.0)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)

        # Overwrite "b" -- should NOT evict anything.
        await cache.set("b", 20)

        assert await cache.get("a") == 1
        assert await cache.get("b") == 20
        assert await cache.get("c") == 3
        assert cache.stats["evictions"] == 0

    @pytest.mark.asyncio
    async def test_max_size_one(self) -> None:
        """Edge case: cache with max_size=1."""
        cache = TTLCache(max_size=1, default_ttl=300.0)
        await cache.set("a", 1)
        await cache.set("b", 2)

        assert await cache.get("a") is None
        assert await cache.get("b") == 2
        assert cache.stats["evictions"] == 1

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
    async def test_flush_nonexistent_key_is_noop(self) -> None:
        cache = TTLCache()
        await cache.flush("nonexistent")  # Should not raise.

    @pytest.mark.asyncio
    async def test_flush_all(self) -> None:
        cache = TTLCache()
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)

        await cache.flush()

        assert await cache.get("a") is None
        assert await cache.get("b") is None
        assert await cache.get("c") is None
        assert cache.stats["size"] == 0

    @pytest.mark.asyncio
    async def test_flush_by_prefix(self) -> None:
        cache = TTLCache()
        await cache.set("devices:site1", [1, 2])
        await cache.set("devices:site2", [3, 4])
        await cache.set("clients:site1", [5, 6])

        await cache.flush_by_prefix("devices:")

        assert await cache.get("devices:site1") is None
        assert await cache.get("devices:site2") is None
        assert await cache.get("clients:site1") == [5, 6]

    @pytest.mark.asyncio
    async def test_flush_by_prefix_no_matches(self) -> None:
        cache = TTLCache()
        await cache.set("a", 1)
        await cache.flush_by_prefix("zzz")  # No keys match.
        assert await cache.get("a") == 1

    @pytest.mark.asyncio
    async def test_flush_by_prefix_empty_prefix_flushes_all(self) -> None:
        cache = TTLCache()
        await cache.set("a", 1)
        await cache.set("b", 2)

        await cache.flush_by_prefix("")  # Every key starts with "".

        assert cache.stats["size"] == 0


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
    async def test_miss_tracking_absent_key(self) -> None:
        cache = TTLCache()
        await cache.get("missing")
        assert cache.stats["misses"] == 1

    @pytest.mark.asyncio
    async def test_miss_tracking_expired_key(self) -> None:
        cache = TTLCache(default_ttl=0.05)
        await cache.set("key", "value")
        await asyncio.sleep(0.06)
        await cache.get("key")
        assert cache.stats["misses"] == 1

    @pytest.mark.asyncio
    async def test_size_reflects_live_entries(self) -> None:
        cache = TTLCache()
        await cache.set("a", 1)
        await cache.set("b", 2)
        assert cache.stats["size"] == 2

        await cache.flush("a")
        assert cache.stats["size"] == 1


# ---------------------------------------------------------------------------
# get_or_fetch — basic behaviour
# ---------------------------------------------------------------------------


class TestGetOrFetch:
    """Tests for get_or_fetch caching and fetcher invocation."""

    @pytest.mark.asyncio
    async def test_fetcher_called_on_miss(self) -> None:
        cache = TTLCache()
        fetcher = AsyncMock(return_value={"devices": [1, 2, 3]})

        result = await cache.get_or_fetch("key", fetcher)

        assert result == {"devices": [1, 2, 3]}
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
    async def test_fetched_value_is_cached(self) -> None:
        cache = TTLCache()
        call_count = 0

        async def counting_fetcher() -> str:
            nonlocal call_count
            call_count += 1
            return "fetched"

        # First call: fetches.
        r1 = await cache.get_or_fetch("key", counting_fetcher)
        # Second call: cache hit.
        r2 = await cache.get_or_fetch("key", counting_fetcher)

        assert r1 == "fetched"
        assert r2 == "fetched"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_custom_ttl_on_get_or_fetch(self) -> None:
        cache = TTLCache(default_ttl=300.0)
        fetcher = AsyncMock(return_value="value")

        await cache.get_or_fetch("key", fetcher, ttl=0.05)
        assert await cache.get("key") == "value"

        await asyncio.sleep(0.06)
        assert await cache.get("key") is None

    @pytest.mark.asyncio
    async def test_get_or_fetch_after_expiry_re_fetches(self) -> None:
        cache = TTLCache(default_ttl=0.05)
        call_count = 0

        async def counting_fetcher() -> str:
            nonlocal call_count
            call_count += 1
            return f"v{call_count}"

        r1 = await cache.get_or_fetch("key", counting_fetcher)
        assert r1 == "v1"

        await asyncio.sleep(0.06)

        r2 = await cache.get_or_fetch("key", counting_fetcher)
        assert r2 == "v2"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_fetcher_exception_propagates(self) -> None:
        cache = TTLCache()

        async def failing_fetcher() -> None:
            raise ConnectionError("API unreachable")

        with pytest.raises(ConnectionError, match="API unreachable"):
            await cache.get_or_fetch("key", failing_fetcher)

        # Key should NOT be cached after a failed fetch.
        assert await cache.get("key") is None

    @pytest.mark.asyncio
    async def test_get_or_fetch_tracks_stats(self) -> None:
        cache = TTLCache()
        fetcher = AsyncMock(return_value="value")

        await cache.get_or_fetch("key", fetcher)  # Miss + fetch.
        await cache.get_or_fetch("key", fetcher)  # Hit.

        assert cache.stats["misses"] == 1
        assert cache.stats["hits"] == 1


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
    async def test_stampede_different_keys_independent(self) -> None:
        """Concurrent requests for different keys should each invoke their
        own fetcher independently."""
        cache = TTLCache()
        call_counts: dict[str, int] = {}

        async def keyed_fetcher(key: str) -> str:
            call_counts[key] = call_counts.get(key, 0) + 1
            await asyncio.sleep(0.05)
            return f"result-{key}"

        tasks = [
            asyncio.create_task(
                cache.get_or_fetch(f"key-{i}", lambda i=i: keyed_fetcher(f"key-{i}"))
            )
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks)

        assert len(results) == 5
        for key, count in call_counts.items():
            assert count == 1, f"{key} was fetched {count} times"

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
        assert all(str(r) == "API down" for r in results)

    @pytest.mark.asyncio
    async def test_after_failed_fetch_new_attempt_succeeds(self) -> None:
        """After a failed fetch, a subsequent request should attempt a new
        fetch and succeed."""
        cache = TTLCache()
        attempt = 0

        async def eventually_succeeds() -> str:
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise ConnectionError("first try fails")
            return "success"

        # First attempt fails.
        with pytest.raises(ConnectionError):
            await cache.get_or_fetch("key", eventually_succeeds)

        # Second attempt should succeed with a new fetch.
        result = await cache.get_or_fetch("key", eventually_succeeds)
        assert result == "success"
        assert attempt == 2

    @pytest.mark.asyncio
    async def test_stampede_waiters_retry_after_failure(self) -> None:
        """When waiters' in-flight fetch fails, they should be able to
        retry and get a fresh successful result."""
        cache = TTLCache()
        attempt = 0

        async def fetcher_fails_then_succeeds() -> str:
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                await asyncio.sleep(0.05)
                raise RuntimeError("transient failure")
            return "recovered"

        async def waiter_task() -> str:
            # Wait a tiny bit to ensure we are a waiter, not the owner.
            await asyncio.sleep(0.01)
            return await cache.get_or_fetch("key", fetcher_fails_then_succeeds)

        # Owner task.
        owner_task = asyncio.create_task(
            cache.get_or_fetch("key", fetcher_fails_then_succeeds)
        )
        waiter = asyncio.create_task(waiter_task())

        # Owner should fail.
        with pytest.raises(RuntimeError, match="transient failure"):
            await owner_task

        # Waiter should retry and get a fresh fetch.
        result = await waiter
        assert result == "recovered"


# ---------------------------------------------------------------------------
# LRU eviction during get_or_fetch
# ---------------------------------------------------------------------------


class TestGetOrFetchEviction:
    """Tests that get_or_fetch respects max_size and triggers LRU eviction."""

    @pytest.mark.asyncio
    async def test_get_or_fetch_evicts_when_full(self) -> None:
        cache = TTLCache(max_size=2, default_ttl=300.0)
        await cache.set("a", 1)
        await cache.set("b", 2)

        fetcher = AsyncMock(return_value=3)
        await cache.get_or_fetch("c", fetcher)  # Should evict "a".

        assert await cache.get("a") is None
        assert await cache.get("b") == 2
        assert await cache.get("c") == 3


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

    @pytest.mark.asyncio
    async def test_concurrent_gets_no_corruption(self) -> None:
        """Many concurrent get operations should return correct values."""
        cache = TTLCache()
        await cache.set("shared", 42)

        async def getter() -> int | None:
            return await cache.get("shared")

        results = await asyncio.gather(*[getter() for _ in range(100)])
        assert all(r == 42 for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_flush_and_set(self) -> None:
        """Flush and set operations running concurrently should not raise."""
        cache = TTLCache()

        async def set_loop() -> None:
            for i in range(50):
                await cache.set(f"k{i}", i)

        async def flush_loop() -> None:
            for _ in range(10):
                await cache.flush()
                await asyncio.sleep(0.001)

        # Should complete without deadlock or exception.
        await asyncio.gather(set_loop(), flush_loop())


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case and regression tests."""

    @pytest.mark.asyncio
    async def test_none_value_is_cacheable(self) -> None:
        """None should be a valid cached value (distinct from cache miss).

        Note: with the current API, get() returns None for both a cached None
        and a miss. Callers who need to distinguish should use get_or_fetch().
        """
        cache = TTLCache()
        fetcher_calls = 0

        async def fetcher() -> None:
            nonlocal fetcher_calls
            fetcher_calls += 1
            return None

        r1 = await cache.get_or_fetch("key", fetcher)
        r2 = await cache.get_or_fetch("key", fetcher)

        assert r1 is None
        assert r2 is None
        # Fetcher should only be called once -- None is cached.
        assert fetcher_calls == 1

    @pytest.mark.asyncio
    async def test_empty_string_key(self) -> None:
        cache = TTLCache()
        await cache.set("", "empty-key-value")
        assert await cache.get("") == "empty-key-value"

    @pytest.mark.asyncio
    async def test_large_value(self) -> None:
        cache = TTLCache()
        big_list = list(range(100_000))
        await cache.set("big", big_list)
        assert await cache.get("big") == big_list

    @pytest.mark.asyncio
    async def test_stats_property_returns_new_dict(self) -> None:
        """Stats dict should be a snapshot, not a live reference."""
        cache = TTLCache()
        stats1 = cache.stats
        await cache.set("key", "value")
        stats2 = cache.stats

        assert stats1["size"] == 0
        assert stats2["size"] == 1
        # Mutating stats1 should not affect cache internals.
        stats1["hits"] = 999
        assert cache.stats["hits"] == 0
