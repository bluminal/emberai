# SPDX-License-Identifier: MIT
"""Async HTTP client for the NextDNS API.

Communicates with the NextDNS cloud API at ``https://api.nextdns.io``.
Authentication is via an ``X-Api-Key`` header with an API key from the
``NEXTDNS_API_KEY`` environment variable.

Typical usage::

    async with NextDNSClient(api_key="...") as client:
        profiles = await client.get("/profiles")
        security = await client.get_sub_resource("abc123", "security")

The client includes:

- **Rate limiting**: Conservative 100 ms throttle between requests, plus
  exponential backoff with jitter on HTTP 429 responses.
- **Cursor-based pagination**: :meth:`get_paginated` and :meth:`iter_pages`
  for endpoints that return paginated results.
- **Sub-resource helpers**: Convenience methods for the nested profile
  resource pattern used throughout the NextDNS API.

Error responses are translated to the structured error hierarchy defined
in :mod:`nextdns.errors`.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING, Any, ClassVar

import httpx

from nextdns.api.url_builder import array_child_url, profile_url, sub_resource_url
from nextdns.errors import APIError, AuthenticationError, NetworkError, RateLimitError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from types import TracebackType

logger = logging.getLogger(__name__)

# Threshold in seconds above which a successful request triggers a warning.
_SLOW_REQUEST_THRESHOLD = 5.0

# 429 retry defaults.
_MAX_429_RETRIES = 3
_INITIAL_BACKOFF = 1.0
_MAX_BACKOFF = 60.0
_BACKOFF_FACTOR = 2.0


class NextDNSClient:
    """Async HTTP client for the NextDNS REST API.

    Parameters
    ----------
    api_key:
        API key for ``X-Api-Key`` authentication.  Obtain from the
        NextDNS account settings page.
    timeout:
        Request timeout in seconds (applies to connect + read).
    """

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._base_url = "https://api.nextdns.io"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
            timeout=httpx.Timeout(timeout),
        )
        # Conservative throttle: minimum 100 ms between requests.
        self._min_request_interval = 0.1
        self._last_request_time = 0.0

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> NextDNSClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Core HTTP methods
    # ------------------------------------------------------------------

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request to the NextDNS API.

        Parameters
        ----------
        endpoint:
            API path (e.g. ``"/profiles"``).
        params:
            Optional query parameters.

        Returns
        -------
        dict
            The parsed JSON response.

        Raises
        ------
        AuthenticationError
            On 401 responses.
        RateLimitError
            On 429 responses (after retry exhaustion).
        APIError
            On other 4xx/5xx responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        return await self._request("GET", endpoint, params=params)

    async def post(
        self, endpoint: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a POST request to the NextDNS API.

        Parameters
        ----------
        endpoint:
            API path.
        data:
            Optional JSON body.

        Returns
        -------
        dict
            The parsed JSON response.

        Raises
        ------
        AuthenticationError
            On 401 responses.
        RateLimitError
            On 429 responses (after retry exhaustion).
        APIError
            On other 4xx/5xx responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        return await self._request("POST", endpoint, json_data=data)

    async def put(
        self, endpoint: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a PUT request to the NextDNS API.

        Parameters
        ----------
        endpoint:
            API path.
        data:
            Optional JSON body.

        Returns
        -------
        dict
            The parsed JSON response.

        Raises
        ------
        AuthenticationError
            On 401 responses.
        RateLimitError
            On 429 responses (after retry exhaustion).
        APIError
            On other 4xx/5xx responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        return await self._request("PUT", endpoint, json_data=data)

    async def patch(
        self, endpoint: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a PATCH request to the NextDNS API.

        Parameters
        ----------
        endpoint:
            API path.
        data:
            Optional JSON body.

        Returns
        -------
        dict
            The parsed JSON response.

        Raises
        ------
        AuthenticationError
            On 401 responses.
        RateLimitError
            On 429 responses (after retry exhaustion).
        APIError
            On other 4xx/5xx responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        return await self._request("PATCH", endpoint, json_data=data)

    async def delete(self, endpoint: str) -> dict[str, Any]:
        """Make a DELETE request to the NextDNS API.

        Parameters
        ----------
        endpoint:
            API path.

        Returns
        -------
        dict
            The parsed JSON response.

        Raises
        ------
        AuthenticationError
            On 401 responses.
        RateLimitError
            On 429 responses (after retry exhaustion).
        APIError
            On other 4xx/5xx responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        return await self._request("DELETE", endpoint)

    # ------------------------------------------------------------------
    # Cursor-based pagination
    # ------------------------------------------------------------------

    async def get_paginated(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        limit: int | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch all pages using cursor-based pagination.

        Makes successive GET requests, following cursor values in the
        response metadata until all items have been collected (or the
        optional *limit* is reached).

        Args:
            endpoint: API path (e.g. ``"/profiles"``).
            params: Base query parameters.
            limit: Maximum total items to return (``None`` = all).
            page_size: Items per page (max 500, default 100).

        Returns:
            Combined list of all items from all pages.
        """
        all_items: list[dict[str, Any]] = []

        async for page in self.iter_pages(endpoint, params=params, page_size=page_size):
            all_items.extend(page)
            if limit is not None and len(all_items) >= limit:
                all_items = all_items[:limit]
                break

        return all_items

    async def iter_pages(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield pages of results using cursor-based pagination.

        Each yielded value is the ``data`` array from one API response.
        Iteration stops when the cursor is ``null`` or the page is empty.

        Args:
            endpoint: API path (e.g. ``"/profiles"``).
            params: Base query parameters.
            page_size: Items per page (max 500, default 100).

        Yields:
            A list of items for each page.
        """
        base_params = dict(params) if params else {}
        cursor: str | None = None
        page_num = 0

        while True:
            page_params = {**base_params, "limit": page_size}
            if cursor is not None:
                page_params["cursor"] = cursor

            response = await self.get(endpoint, params=page_params)

            data = response.get("data", [])
            if not data:
                logger.debug(
                    "Pagination stopped: empty data on page %d for %s",
                    page_num,
                    endpoint,
                )
                break

            yield data
            page_num += 1

            # Extract cursor for the next page.
            meta = response.get("meta", {})
            pagination = meta.get("pagination", {})
            cursor = pagination.get("cursor") if pagination else None

            if cursor is None:
                logger.debug(
                    "Pagination complete: %d page(s) fetched for %s",
                    page_num,
                    endpoint,
                )
                break

    # ------------------------------------------------------------------
    # Sub-resource convenience methods
    # ------------------------------------------------------------------

    async def get_profile(self, profile_id: str) -> dict[str, Any]:
        """GET /profiles/{id}

        Fetch a single profile by its identifier.
        """
        return await self.get(profile_url(profile_id))

    async def get_sub_resource(self, profile_id: str, path: str) -> dict[str, Any]:
        """GET a sub-resource (security, privacy, etc.).

        Args:
            profile_id: Profile identifier.
            path: Dotted path to the sub-resource (e.g. ``"security"``).
        """
        return await self.get(sub_resource_url(profile_id, path))

    async def patch_sub_resource(
        self, profile_id: str, path: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """PATCH an object sub-resource.

        Args:
            profile_id: Profile identifier.
            path: Dotted path to the sub-resource.
            data: Fields to update.
        """
        return await self.patch(sub_resource_url(profile_id, path), data=data)

    async def get_array(self, profile_id: str, path: str) -> list[dict[str, Any]]:
        """GET an array sub-resource (denylist, blocklists, etc.).

        Args:
            profile_id: Profile identifier.
            path: Dotted path to the array sub-resource.

        Returns:
            The ``data`` array from the response.
        """
        response = await self.get(sub_resource_url(profile_id, path))
        return response.get("data", [])

    async def add_to_array(
        self, profile_id: str, path: str, item: dict[str, Any]
    ) -> dict[str, Any]:
        """POST a new item to an array sub-resource.

        Args:
            profile_id: Profile identifier.
            path: Dotted path to the array sub-resource.
            item: The item to add.
        """
        return await self.post(sub_resource_url(profile_id, path), data=item)

    async def update_array_child(
        self,
        profile_id: str,
        path: str,
        item_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """PATCH a specific array item.

        Args:
            profile_id: Profile identifier.
            path: Dotted path to the array sub-resource.
            item_id: Identifier of the item to update.
            data: Fields to update.
        """
        return await self.patch(array_child_url(profile_id, path, item_id), data=data)

    async def delete_array_child(
        self, profile_id: str, path: str, item_id: str
    ) -> dict[str, Any]:
        """DELETE a specific array item.

        Args:
            profile_id: Profile identifier.
            path: Dotted path to the array sub-resource.
            item_id: Identifier of the item to remove.
        """
        return await self.delete(array_child_url(profile_id, path, item_id))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying httpx client and release resources."""
        await self._client.aclose()
        logger.debug("Closed NextDNSClient")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _throttle(self) -> None:
        """Enforce the minimum inter-request interval.

        Sleeps if needed to ensure at least :attr:`_min_request_interval`
        seconds have elapsed since the last request.
        """
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._min_request_interval:
            sleep_time = self._min_request_interval - elapsed
            logger.debug("Throttling: sleeping %.3fs before next request", sleep_time)
            await asyncio.sleep(sleep_time)

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request with logging, throttling, and error translation.

        All public methods delegate here so that logging, timing, rate limiting,
        and error mapping are applied consistently.

        Implements automatic retry with exponential backoff on 429 responses.
        """
        redacted_headers = {
            k: ("***" if k.lower() == "x-api-key" else v)
            for k, v in self._client.headers.items()
        }
        logger.debug(
            "Request: %s %s%s | headers=%s",
            method,
            self._base_url,
            endpoint,
            redacted_headers,
        )

        retries = 0
        backoff = _INITIAL_BACKOFF

        while True:
            # Apply conservative throttle.
            await self._throttle()

            start = time.monotonic()

            try:
                response = await self._client.request(
                    method,
                    endpoint,
                    params=params,
                    json=json_data,
                )
            except httpx.TimeoutException as exc:
                elapsed = time.monotonic() - start
                logger.error(
                    "Connection timeout: %s %s%s after %.2fs — %s",
                    method,
                    self._base_url,
                    endpoint,
                    elapsed,
                    exc,
                )
                raise NetworkError(
                    f"Connection timed out after {elapsed:.1f}s: {self._base_url}{endpoint}",
                    endpoint=endpoint,
                ) from exc
            except httpx.ConnectError as exc:
                elapsed = time.monotonic() - start
                exc_str = str(exc).lower()
                if "ssl" in exc_str or "certificate" in exc_str:
                    logger.error(
                        "SSL error connecting to %s%s — %s",
                        self._base_url,
                        endpoint,
                        exc,
                    )
                    raise NetworkError(
                        f"SSL error connecting to {self._base_url}{endpoint}: {exc}",
                        endpoint=endpoint,
                        retry_hint="Check network connectivity or SSL configuration",
                    ) from exc
                logger.error(
                    "Connection refused: %s%s after %.2fs — %s",
                    self._base_url,
                    endpoint,
                    elapsed,
                    exc,
                )
                raise NetworkError(
                    f"Connection refused: {self._base_url}{endpoint}",
                    endpoint=endpoint,
                ) from exc
            except httpx.HTTPError as exc:
                elapsed = time.monotonic() - start
                logger.error(
                    "HTTP transport error: %s %s%s after %.2fs — %s",
                    method,
                    self._base_url,
                    endpoint,
                    elapsed,
                    exc,
                )
                raise NetworkError(
                    f"HTTP transport error for {self._base_url}{endpoint}: {exc}",
                    endpoint=endpoint,
                ) from exc

            elapsed = time.monotonic() - start
            self._last_request_time = time.monotonic()

            # --- Handle 429 with retry ---
            if response.status_code == 429:
                retries += 1
                logger.warning(
                    "Rate limited (429) on %s %s%s — attempt %d/%d",
                    method,
                    self._base_url,
                    endpoint,
                    retries,
                    _MAX_429_RETRIES,
                )
                if retries > _MAX_429_RETRIES:
                    retry_after = self._parse_retry_after(response)
                    raise RateLimitError(
                        f"Rate limited (429) for {endpoint} after {_MAX_429_RETRIES} retries.",
                        retry_after_seconds=retry_after,
                        endpoint=endpoint,
                    )
                # Exponential backoff with jitter.
                jitter = random.uniform(0, backoff * 0.5)
                sleep_time = min(backoff + jitter, _MAX_BACKOFF)
                logger.info(
                    "Backing off %.2fs before retry %d for %s",
                    sleep_time,
                    retries,
                    endpoint,
                )
                await asyncio.sleep(sleep_time)
                backoff *= _BACKOFF_FACTOR
                continue

            # --- Logging ---
            if response.is_success:
                logger.info(
                    "%s %s%s -> %d (%.2fs)",
                    method,
                    self._base_url,
                    endpoint,
                    response.status_code,
                    elapsed,
                )
                if elapsed > _SLOW_REQUEST_THRESHOLD:
                    logger.warning(
                        "Slow request: %s %s%s took %.2fs (threshold: %.1fs)",
                        method,
                        self._base_url,
                        endpoint,
                        elapsed,
                        _SLOW_REQUEST_THRESHOLD,
                    )
            else:
                logger.warning(
                    "Non-200 response: %s %s%s -> %d (%.2fs)",
                    method,
                    self._base_url,
                    endpoint,
                    response.status_code,
                    elapsed,
                )

            # --- Error mapping ---
            self._raise_for_status(response, endpoint)

            # --- Parse JSON ---
            return response.json()  # type: ignore[no-any-return]

    def _raise_for_status(self, response: httpx.Response, endpoint: str) -> None:
        """Translate HTTP error responses to the structured error hierarchy."""
        status = response.status_code
        if 200 <= status < 300:
            return

        body_text = response.text

        if status == 401:
            logger.error(
                "Authentication failed (401) for %s%s",
                self._base_url,
                endpoint,
            )
            raise AuthenticationError(
                f"Authentication failed (401) for {endpoint}. "
                "Verify that NEXTDNS_API_KEY is set correctly.",
                env_var="NEXTDNS_API_KEY",
                endpoint=endpoint,
            )

        if status == 404:
            raise APIError(
                f"Not found (404): {endpoint}",
                status_code=404,
                endpoint=endpoint,
                response_body=body_text,
            )

        if status >= 500:
            raise APIError(
                f"Server error ({status}) for {endpoint}",
                status_code=status,
                endpoint=endpoint,
                response_body=body_text,
            )

        # Other 4xx errors.
        raise APIError(
            f"API error ({status}) for {endpoint}",
            status_code=status,
            endpoint=endpoint,
            response_body=body_text,
        )

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float | None:
        """Extract Retry-After value from response headers.

        Returns the value as a float (seconds), or ``None`` if the header
        is absent or unparseable.
        """
        header = response.headers.get("retry-after")
        if header is None:
            return None
        try:
            return float(header)
        except (ValueError, TypeError):
            return None


class CachedNextDNSClient(NextDNSClient):
    """NextDNS client with TTL caching on GET requests.

    Wraps :class:`NextDNSClient` to transparently cache GET responses
    with pattern-based TTL values tuned to data volatility:

    - ``/profiles`` list: 5 min (300 s)
    - Single profiles and sub-resources: 2 min (120 s, default)
    - Analytics endpoints: 30 s
    - Log endpoints: never cached

    Write operations (PATCH, POST, PUT, DELETE) automatically flush
    cached data for the affected profile.

    Parameters
    ----------
    api_key:
        API key for authentication.
    cache:
        A :class:`~nextdns.cache.TTLCache` instance for storing responses.
    """

    # TTL mapping by endpoint pattern.
    _CACHE_TTLS: ClassVar[dict[str, float]] = {
        "/profiles": 300.0,  # 5 min for profile list
        "analytics": 30.0,  # 30 sec for analytics
        "logs": 0.0,  # never cache logs
        "default": 120.0,  # 2 min for profiles and sub-resources
    }

    def __init__(self, api_key: str, cache: Any, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self._cache = cache

    def _cache_ttl_for(self, endpoint: str) -> float:
        """Determine the cache TTL for an endpoint based on pattern matching.

        Args:
            endpoint: The API endpoint path.

        Returns:
            TTL in seconds. Returns 0.0 for endpoints that should not be cached.
        """
        # Exact match for profile list.
        if endpoint == "/profiles":
            return self._CACHE_TTLS["/profiles"]

        # Check for log endpoints — never cache.
        if "/logs" in endpoint:
            return self._CACHE_TTLS["logs"]

        # Check for analytics endpoints — short TTL.
        if "/analytics" in endpoint:
            return self._CACHE_TTLS["analytics"]

        # Default TTL for everything else (single profiles, sub-resources).
        return self._CACHE_TTLS["default"]

    def _cache_key(self, endpoint: str, params: dict[str, Any] | None = None) -> str:
        """Build a deterministic cache key from endpoint and params.

        Args:
            endpoint: The API endpoint path.
            params: Optional query parameters.

        Returns:
            A string key combining endpoint and sorted params.
        """
        if params:
            sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            return f"{endpoint}?{sorted_params}"
        return endpoint

    @staticmethod
    def _profile_id_from_endpoint(endpoint: str) -> str | None:
        """Extract the profile ID from an endpoint path, if present.

        Returns ``None`` if the endpoint is not profile-scoped.
        """
        # Pattern: /profiles/{id} or /profiles/{id}/...
        parts = endpoint.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "profiles":
            return parts[1]
        return None

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET with caching.

        Returns cached data if available and not expired. Otherwise
        fetches from the API and caches the result.
        """
        ttl = self._cache_ttl_for(endpoint)

        # Never cache if TTL is 0.
        if ttl <= 0:
            return await super().get(endpoint, params=params)

        key = self._cache_key(endpoint, params)
        cached = await self._cache.get(key)
        if cached is not None:
            logger.debug("Cache hit: %s", key)
            return cached

        logger.debug("Cache miss: %s", key)
        result = await super().get(endpoint, params=params)
        await self._cache.set(key, result, ttl=ttl)
        return result

    async def post(
        self, endpoint: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """POST with post-write cache flush."""
        result = await super().post(endpoint, data=data)
        await self._flush_affected_profile(endpoint)
        return result

    async def put(
        self, endpoint: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """PUT with post-write cache flush."""
        result = await super().put(endpoint, data=data)
        await self._flush_affected_profile(endpoint)
        return result

    async def patch(
        self, endpoint: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """PATCH with post-write cache flush."""
        result = await super().patch(endpoint, data=data)
        await self._flush_affected_profile(endpoint)
        return result

    async def delete(self, endpoint: str) -> dict[str, Any]:
        """DELETE with post-write cache flush."""
        result = await super().delete(endpoint)
        await self._flush_affected_profile(endpoint)
        return result

    async def _flush_affected_profile(self, endpoint: str) -> None:
        """Flush all cached data for the profile affected by a write operation."""
        profile_id = self._profile_id_from_endpoint(endpoint)
        if profile_id:
            await self.flush_profile(profile_id)
        else:
            # If the write is not profile-scoped (e.g. /profiles), flush all.
            await self._cache.flush()
            logger.debug("Flushed entire cache after write to %s", endpoint)

    async def flush_profile(self, profile_id: str) -> None:
        """Manually invalidate all cached data for a specific profile.

        Flushes:
        - The profile list (``/profiles``)
        - The individual profile (``/profiles/{id}``)
        - All sub-resources (``/profiles/{id}/...``)

        Args:
            profile_id: The NextDNS profile identifier.
        """
        # Flush the profile list.
        await self._cache.flush("/profiles")
        # Flush the individual profile and all sub-resources by prefix.
        await self._cache.flush_by_prefix(f"/profiles/{profile_id}")
        logger.debug("Flushed cache for profile %s", profile_id)
