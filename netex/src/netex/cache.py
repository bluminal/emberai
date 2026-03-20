"""Async-safe TTL cache with LRU eviction and stampede protection.

Provides an in-memory cache designed for single-instance MCP servers. Each entry
carries its own TTL, enabling per-data-type expiration. Concurrent requests for
the same key are coalesced via a single-flight pattern: only one fetch executes
while other callers await its result.

Typical usage::

    cache = TTLCache(max_size=500, default_ttl=300.0)

    plugins = await cache.get_or_fetch(
        "plugins:all",
        fetcher=lambda: registry.list_plugins(),
        ttl=60.0,
    )
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable


class _CacheEntry:
    """Internal container for a cached value and its expiration timestamp."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, expires_at: float) -> None:
        self.value = value
        self.expires_at = expires_at

    def is_expired(self) -> bool:
        return time.monotonic() >= self.expires_at


class TTLCache:
    """Async-safe in-memory TTL cache with LRU eviction and stampede protection.

    Args:
        max_size: Maximum number of entries before LRU eviction kicks in.
            Must be a positive integer.
        default_ttl: Default time-to-live in seconds for entries that don't
            specify a custom TTL. Must be a positive number.

    Raises:
        ValueError: If ``max_size`` is not positive or ``default_ttl`` is
            not positive.
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 300.0) -> None:
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got {max_size}")
        if default_ttl <= 0:
            raise ValueError(f"default_ttl must be positive, got {default_ttl}")

        self._max_size = max_size
        self._default_ttl = default_ttl

        # OrderedDict gives us O(1) move-to-end for LRU tracking.
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()

        # Global lock protects _store mutations and _inflight bookkeeping.
        self._lock = asyncio.Lock()

        # In-flight fetches for stampede protection.
        self._inflight: dict[str, asyncio.Future[Any]] = {}

        # Stats counters.
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Any | None:
        """Return a cached value, or ``None`` if the key is missing or expired."""
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired():
                del self._store[key]
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return entry.value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store a value under *key* with an optional per-key *ttl*."""
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.monotonic() + effective_ttl

        async with self._lock:
            if key in self._store:
                self._store[key] = _CacheEntry(value, expires_at)
                self._store.move_to_end(key)
            else:
                self._evict_if_full()
                self._store[key] = _CacheEntry(value, expires_at)

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], Awaitable[Any]],
        ttl: float | None = None,
    ) -> Any:
        """Return a cached value or call *fetcher* to populate the cache.

        Stampede protection: concurrent callers for the same key share
        a single fetch.
        """
        while True:
            is_owner = False

            async with self._lock:
                entry = self._store.get(key)
                if entry is not None and not entry.is_expired():
                    self._store.move_to_end(key)
                    self._hits += 1
                    return entry.value

                if entry is not None:
                    del self._store[key]

                self._misses += 1

                shared_future = self._inflight.get(key)
                if shared_future is None:
                    loop = asyncio.get_running_loop()
                    shared_future = loop.create_future()
                    self._inflight[key] = shared_future
                    is_owner = True

            if not is_owner:
                try:
                    return await asyncio.shield(shared_future)
                except Exception:
                    continue

            try:
                value = await fetcher()
            except BaseException as exc:
                async with self._lock:
                    self._inflight.pop(key, None)
                shared_future.set_exception(exc)
                raise

            effective_ttl = ttl if ttl is not None else self._default_ttl
            expires_at = time.monotonic() + effective_ttl

            async with self._lock:
                self._inflight.pop(key, None)
                self._evict_if_full()
                self._store[key] = _CacheEntry(value, expires_at)

            shared_future.set_result(value)
            return value

    async def flush(self, key: str | None = None) -> None:
        """Flush a specific key or all entries."""
        async with self._lock:
            if key is not None:
                self._store.pop(key, None)
            else:
                self._store.clear()

    async def flush_by_prefix(self, prefix: str) -> None:
        """Flush all keys whose name starts with *prefix*."""
        async with self._lock:
            keys_to_remove = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._store[k]

    @property
    def stats(self) -> dict[str, int]:
        """Return cache statistics."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._store),
            "evictions": self._evictions,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_if_full(self) -> None:
        """Evict the least-recently-used entry if at capacity."""
        while len(self._store) >= self._max_size:
            self._store.popitem(last=False)
            self._evictions += 1
