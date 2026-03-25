"""Async-safe TTL cache with LRU eviction and stampede protection.

Provides an in-memory cache designed for single-instance MCP servers. Each entry
carries its own TTL, enabling per-data-type expiration suited to OPNsense
response freshness requirements:

    - Interface list:     5 minutes (300 s) -- changes rarely
    - Firewall rules:     2 minutes (120 s) -- may change during sessions
    - DHCP leases:        1 minute  (60 s)  -- dynamic, changes frequently
    - VPN sessions:       1 minute  (60 s)  -- status changes frequently
    - Firmware status:    10 minutes (600 s) -- very stable data
    - Routing table:      2 minutes (120 s)  -- may change during sessions
    - IDS alerts:         30 seconds (30 s)  -- real-time relevance

Concurrent requests for the same key are coalesced via a single-flight pattern:
only one fetch executes while other callers await its result.

Typical usage with the OPNsense API client::

    cache = TTLCache(max_size=500, default_ttl=120.0)

    rules = await cache.get_or_fetch(
        "firewall:rules",
        fetcher=lambda: api.list_rules(),
        ttl=CacheTTL.FIREWALL_RULES,
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
# Default TTLs for OPNsense data types
# ---------------------------------------------------------------------------


class CacheTTL:
    """Default TTL values (in seconds) for OPNsense data types.

    These values reflect how frequently each data type changes in typical
    OPNsense deployments. Use these constants when calling ``get_or_fetch``
    to ensure consistent caching behaviour across the plugin.
    """

    INTERFACES: float = 300.0  # 5 minutes -- interfaces change rarely
    VLAN_INTERFACES: float = 300.0  # 5 minutes -- VLAN definitions are stable
    FIREWALL_RULES: float = 120.0  # 2 minutes -- may change during sessions
    FIREWALL_ALIASES: float = 120.0  # 2 minutes -- alias definitions
    NAT_RULES: float = 120.0  # 2 minutes -- NAT configuration
    DHCP_LEASES: float = 60.0  # 1 minute -- dynamic lease data
    DNS_OVERRIDES: float = 120.0  # 2 minutes -- DNS host overrides
    ROUTES: float = 120.0  # 2 minutes -- routing table
    GATEWAYS: float = 120.0  # 2 minutes -- gateway status
    GATEWAY_GROUPS: float = 120.0  # 2 minutes -- gateway group config
    VPN_SESSIONS: float = 60.0  # 1 minute -- VPN tunnel status changes
    IDS_ALERTS: float = 30.0  # 30 seconds -- real-time security data
    CERTIFICATES: float = 300.0  # 5 minutes -- certificate inventory
    FIRMWARE: float = 600.0  # 10 minutes -- very stable data


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
            Must be a positive integer.
        default_ttl: Default time-to-live in seconds for entries that don't
            specify a custom TTL. Must be a positive number.

    Raises:
        ValueError: If ``max_size`` is not positive or ``default_ttl`` is
            not positive.
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 120.0) -> None:
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

        # In-flight fetches for stampede protection. Maps a cache key to a
        # Future so concurrent callers can await the first fetch instead of
        # issuing duplicates.
        self._inflight: dict[str, asyncio.Future[Any]] = {}

        # Stats counters.
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Any | None:
        """Return a cached value, or ``None`` if the key is missing or expired.

        Accessing a live entry promotes it to most-recently-used.
        """
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired():
                del self._store[key]
                self._misses += 1
                return None
            # Promote to most-recently-used.
            self._store.move_to_end(key)
            self._hits += 1
            return entry.value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store a value under *key* with an optional per-key *ttl*.

        If the key already exists, its value and TTL are replaced. When the
        cache is at capacity, the least-recently-used entry is evicted first.

        Args:
            key: Cache key string.
            value: The value to cache (any type).
            ttl: Time-to-live in seconds. Falls back to ``default_ttl``.
        """
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.monotonic() + effective_ttl

        async with self._lock:
            if key in self._store:
                # Replace existing entry and promote to most-recently-used.
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
        same key while a fetch is already in progress, only the first caller
        invokes *fetcher*. The remaining callers await the same result without
        issuing duplicate requests.

        If *fetcher* raises an exception, the exception propagates to **all**
        waiting callers and the key is not cached.

        Args:
            key: Cache key string.
            fetcher: An async callable that produces the value to cache.
            ttl: Time-to-live in seconds. Falls back to ``default_ttl``.

        Returns:
            The cached or freshly-fetched value.
        """
        # This loop handles the case where a waiter's in-flight fetch fails
        # and the waiter needs to retry (potentially becoming the new owner).
        while True:
            is_owner = False

            async with self._lock:
                # Check for a live cached value.
                entry = self._store.get(key)
                if entry is not None and not entry.is_expired():
                    self._store.move_to_end(key)
                    self._hits += 1
                    return entry.value

                # Clean up expired entry.
                if entry is not None:
                    del self._store[key]

                self._misses += 1

                # Check for an in-flight fetch (stampede protection).
                shared_future = self._inflight.get(key)
                if shared_future is None:
                    # We are the first caller -- create a Future and register
                    # ourselves as the owner of this fetch.
                    loop = asyncio.get_running_loop()
                    shared_future = loop.create_future()
                    self._inflight[key] = shared_future
                    is_owner = True

            # --- Outside the lock ---

            if not is_owner:
                # We are a waiter. Await the shared future. If the fetch
                # fails, loop back and retry (we may become the new owner).
                try:
                    return await asyncio.shield(shared_future)
                except Exception:
                    # Owner's fetch failed; _inflight was cleaned up by the
                    # owner. Loop back to potentially become the new owner.
                    continue

            # We are the owner -- perform the actual fetch.
            try:
                value = await fetcher()
            except BaseException as exc:
                # Clean up the in-flight registration and propagate the
                # exception to all waiters.
                async with self._lock:
                    self._inflight.pop(key, None)
                shared_future.set_exception(exc)
                raise

            # Cache the fetched value and notify waiters.
            effective_ttl = ttl if ttl is not None else self._default_ttl
            expires_at = time.monotonic() + effective_ttl

            async with self._lock:
                self._inflight.pop(key, None)
                self._evict_if_full()
                self._store[key] = _CacheEntry(value, expires_at)

            shared_future.set_result(value)
            return value

    async def flush(self, key: str | None = None) -> None:
        """Flush a specific key or all entries.

        Args:
            key: If provided, flush only this key. If ``None``, flush all.
        """
        async with self._lock:
            if key is not None:
                self._store.pop(key, None)
            else:
                self._store.clear()

    async def flush_by_prefix(self, prefix: str) -> None:
        """Flush all keys whose name starts with *prefix*.

        Useful for post-write cache invalidation, e.g.
        ``await cache.flush_by_prefix("firewall:")`` after a rule update.

        Args:
            prefix: The key prefix to match against.
        """
        async with self._lock:
            keys_to_remove = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._store[k]

    @property
    def stats(self) -> dict[str, int]:
        """Return cache statistics.

        Returns:
            A dict with keys ``hits``, ``misses``, ``size``, ``evictions``.
            All values are integers. ``size`` is the current number of entries
            (including any that may have expired but have not yet been evicted
            lazily).
        """
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
        """Evict the least-recently-used entry if at capacity.

        Must be called while ``_lock`` is held.
        """
        while len(self._store) >= self._max_size:
            self._store.popitem(last=False)
            self._evictions += 1
