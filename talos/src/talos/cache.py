"""Async-safe TTL cache with LRU eviction and stampede protection.

Provides an in-memory cache designed for single-instance MCP servers. Each entry
carries its own TTL, enabling per-data-type expiration suited to Talos cluster
response freshness requirements:

    - Node list:          5 minutes (300 s) -- cluster membership changes rarely
    - Cluster health:     1 minute  (60 s)  -- health can change quickly
    - etcd status:        30 seconds (30 s) -- etcd is latency-sensitive
    - Service status:     1 minute  (60 s)  -- service state changes moderately
    - Resource queries:   2 minutes (120 s) -- Talos resources are relatively stable
    - Config generation:  no cache  (0 s)   -- must always reflect current input

Concurrent requests for the same key are coalesced via a single-flight pattern:
only one fetch executes while other callers await its result.

Typical usage with the TalosCtl client::

    cache = TTLCache(max_size=500, default_ttl=120.0)

    nodes = await cache.get_or_fetch(
        "nodes:all",
        fetcher=lambda: talosctl.run(["get", "members"]),
        ttl=CacheTTL.NODE_LIST,
    )

The cache is not persistent across process restarts.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


# ---------------------------------------------------------------------------
# Default TTLs for Talos data types
# ---------------------------------------------------------------------------


class CacheTTL:
    """Default TTL values (in seconds) for Talos cluster data types.

    These values reflect how frequently each data type changes in typical
    Kubernetes cluster deployments. Use these constants when calling
    ``get_or_fetch`` to ensure consistent caching behaviour across the plugin.
    """

    NODE_LIST: float = 300.0  # 5 minutes -- cluster membership changes rarely
    CLUSTER_HEALTH: float = 60.0  # 1 minute -- health can change quickly
    ETCD_STATUS: float = 30.0  # 30 seconds -- etcd is latency-sensitive
    SERVICE_STATUS: float = 60.0  # 1 minute -- service state changes moderately
    RESOURCE_QUERY: float = 120.0  # 2 minutes -- Talos resources are stable
    VERSION_INFO: float = 600.0  # 10 minutes -- versions don't change
    CONFIG_GENERATION: float = 0.0  # never cache -- must reflect current input


class _CacheEntry:
    """Internal container for a cached value and its expiration timestamp."""

    __slots__ = ("expires_at", "value")

    def __init__(self, value: Any, expires_at: float) -> None:
        self.value = value
        self.expires_at = expires_at

    def is_expired(self) -> bool:
        return time.monotonic() >= self.expires_at


class TTLCache:
    """Async-safe in-memory TTL cache with LRU eviction and stampede protection.

    Args:
        max_size: Maximum number of entries before LRU eviction kicks in.
        default_ttl: Default time-to-live in seconds for entries that don't
            specify a custom TTL.
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 120.0) -> None:
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got {max_size}")
        if default_ttl <= 0:
            raise ValueError(f"default_ttl must be positive, got {default_ttl}")

        self._max_size = max_size
        self._default_ttl = default_ttl
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Future[Any]] = {}
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

        **Stampede protection:** If multiple concurrent callers request the
        same key while a fetch is in progress, only the first caller invokes
        *fetcher*. The rest await the same result.
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
        """Flush all keys whose name starts with *prefix*.

        Useful for post-write cache invalidation, e.g.
        ``await cache.flush_by_prefix("nodes:")`` after a node operation.
        """
        async with self._lock:
            keys_to_remove = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._store[k]

    @property
    def stats(self) -> dict[str, int]:
        """Return cache statistics (hits, misses, size, evictions)."""
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
