# SPDX-License-Identifier: MIT
"""Caching wrapper around LocalGatewayClient.

Transparently caches GET responses using a TTL cache, with per-endpoint
TTL values derived from PRD Section 6.3. POST requests are never cached;
after a successful POST the cache is flushed for the affected endpoint
prefix to prevent stale reads.

Typical usage::

    from unifi.api.local_gateway_client import LocalGatewayClient
    from unifi.cache import TTLCache

    cache = TTLCache(max_size=500, default_ttl=300.0)
    raw_client = LocalGatewayClient(host="192.168.1.1", api_key="...")

    client = CachedGatewayClient(raw_client, cache)
    devices = await client.get("/api/s/default/stat/device")
    # Second call returns cached data (no API request).
    devices_again = await client.get("/api/s/default/stat/device")

Cache keys encode both the endpoint and sorted query parameters so that
identical logical requests always hit the same cache entry.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from unifi.api.local_gateway_client import LocalGatewayClient
    from unifi.cache import TTLCache

logger = logging.getLogger(__name__)


class CachedGatewayClient:
    """Wraps LocalGatewayClient with TTL caching for GET requests.

    POST requests are never cached. After a POST (write), the cache
    is flushed for the affected endpoint prefix.

    Parameters
    ----------
    client:
        The underlying ``LocalGatewayClient`` to delegate HTTP requests to.
    cache:
        A ``TTLCache`` instance used for caching GET responses.
    """

    # TTL per endpoint category (PRD Section 6.3).
    # Keys are suffix patterns matched against the request endpoint.
    ENDPOINT_TTLS: ClassVar[dict[str, int]] = {
        "stat/device": 300,       # Device list: 5 min
        "stat/health": 120,       # Site health: 2 min
        "stat/sta": 30,           # Client list: 30 sec
        "stat/event": 0,          # Events: no cache (always fresh)
        "rest/networkconf": 300,  # VLAN config: 5 min
        "rest/wlanconf": 300,     # WLAN config: 5 min
    }
    DEFAULT_TTL: int = 300  # 5 min default

    def __init__(self, client: LocalGatewayClient, cache: TTLCache) -> None:
        self._client = client
        self._cache = cache

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Cached GET. Uses endpoint to determine TTL.

        If the resolved TTL is 0, the cache is bypassed entirely and the
        request is forwarded directly to the underlying client.

        Parameters
        ----------
        endpoint:
            API path relative to ``/proxy/network/``
            (e.g. ``"/api/s/default/stat/device"``).
        params:
            Optional query parameters.

        Returns
        -------
        dict
            The raw JSON response (envelope included).
        """
        ttl = self._resolve_ttl(endpoint)

        # TTL of 0 means "never cache" -- bypass completely.
        if ttl == 0:
            logger.debug("Cache bypass (TTL=0) for %s", endpoint)
            return await self._client.get(endpoint, params=params)

        cache_key = self._build_cache_key(endpoint, params)

        result: dict[str, Any] = await self._cache.get_or_fetch(
            cache_key,
            fetcher=lambda: self._client.get(endpoint, params=params),
            ttl=float(ttl),
        )
        return result

    async def post(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Uncached POST. Flushes cache for the endpoint prefix after success.

        Parameters
        ----------
        endpoint:
            API path relative to ``/proxy/network/``.
        data:
            Optional JSON body.

        Returns
        -------
        dict
            The raw JSON response (envelope included).
        """
        result = await self._client.post(endpoint, data=data)

        # After a successful write, invalidate cached entries whose keys
        # share the same endpoint prefix so subsequent GETs fetch fresh data.
        prefix = self._extract_endpoint_prefix(endpoint)
        logger.debug("POST succeeded for %s; flushing cache prefix '%s'", endpoint, prefix)
        await self._cache.flush_by_prefix(prefix)

        return result

    async def flush(self, endpoint: str | None = None) -> None:
        """Manually flush cache for a specific endpoint prefix or all entries.

        Parameters
        ----------
        endpoint:
            If provided, flush all cache entries whose key starts with this
            endpoint string. If ``None``, flush the entire cache.
        """
        if endpoint is not None:
            prefix = self._extract_endpoint_prefix(endpoint)
            await self._cache.flush_by_prefix(prefix)
        else:
            await self._cache.flush()

    @property
    def cache_stats(self) -> dict[str, int]:
        """Return cache hit/miss/eviction stats.

        Returns
        -------
        dict
            A dict with keys ``hits``, ``misses``, ``size``, ``evictions``.
        """
        return self._cache.stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_ttl(self, endpoint: str) -> int:
        """Determine the TTL for a given endpoint using prefix matching.

        Iterates through ``ENDPOINT_TTLS`` and returns the TTL for the
        first key that appears as a substring in the endpoint. Falls back
        to ``DEFAULT_TTL`` if no match is found.

        The matching is deliberately substring-based rather than strict
        prefix-based, because UniFi endpoints include site-specific
        prefixes (e.g. ``/api/s/default/stat/device``).
        """
        for pattern, ttl in self.ENDPOINT_TTLS.items():
            if pattern in endpoint:
                return ttl
        return self.DEFAULT_TTL

    @staticmethod
    def _build_cache_key(endpoint: str, params: dict[str, Any] | None = None) -> str:
        """Build a deterministic cache key from endpoint and parameters.

        Format: ``{endpoint}:{sorted_params_json}``

        Parameters are sorted by key to ensure deterministic ordering
        regardless of dict insertion order. Values are converted to strings
        for consistent serialisation.
        """
        if params:
            sorted_params = json.dumps(
                {k: str(v) for k, v in sorted(params.items())},
                separators=(",", ":"),
            )
        else:
            sorted_params = "{}"
        return f"{endpoint}:{sorted_params}"

    @staticmethod
    def _extract_endpoint_prefix(endpoint: str) -> str:
        """Extract the cache key prefix for flush operations.

        For an endpoint like ``/api/s/default/stat/device``, the prefix
        used for cache key matching is the full endpoint path (without
        trailing slashes), so that ``flush_by_prefix`` invalidates all
        cached entries for that endpoint regardless of their query parameters.
        """
        return endpoint.rstrip("/")
