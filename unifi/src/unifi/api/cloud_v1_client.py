# SPDX-License-Identifier: MIT
"""Async HTTP client for the UniFi Cloud V1 API.

Communicates with the Ubiquiti cloud API at ``https://api.ui.com/v1/``.
Authentication is via an ``X-API-KEY`` header sourced from the
``UNIFI_API_KEY`` environment variable.

The Cloud V1 API wraps responses in a different envelope than the local
gateway API::

    {"data": ..., "httpStatusCode": 200, "traceId": "abc-123"}

This module provides :func:`normalize_cloud_v1_response` to unwrap this
envelope into the shared :class:`~unifi.api.response.NormalizedResponse`
format used throughout the codebase.

Rate limiting
-------------

The Cloud V1 API enforces a quota of 10,000 requests per minute.  The
client tracks the remaining quota via the ``X-RateLimit-Remaining``
response header and logs a WARNING when the remaining quota drops below
20% (i.e., fewer than 2,000 requests remaining).

When a 429 response is received the client automatically retries with
exponential backoff (initial delay 1 s, max delay 60 s, with jitter).

Typical usage::

    async with CloudV1Client(api_key="...") as client:
        response = await client.get("sites")
        sites = response["data"]

"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from types import TracebackType

from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, AuthenticationError, NetworkError, RateLimitError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://api.ui.com/v1/"

# Threshold in seconds above which a successful request triggers a warning.
_SLOW_REQUEST_THRESHOLD = 5.0

# Rate-limit quota tracking.
_RATE_LIMIT_TOTAL = 10_000
_RATE_LIMIT_LOW_THRESHOLD = 2_000  # warn when remaining drops below this

# Exponential backoff for 429 retries.
_BACKOFF_INITIAL = 1.0  # seconds
_BACKOFF_MAX = 60.0  # seconds
_BACKOFF_MAX_RETRIES = 5
_BACKOFF_JITTER_FACTOR = 0.5  # +-50% jitter


# ---------------------------------------------------------------------------
# Cloud V1 response normalization
# ---------------------------------------------------------------------------


def normalize_cloud_v1_response(raw: dict[str, Any]) -> NormalizedResponse:
    """Unwrap the Cloud V1 API envelope into a :class:`NormalizedResponse`.

    The Cloud V1 envelope has the shape::

        {"data": <object-or-list>, "httpStatusCode": 200, "traceId": "..."}

    Where ``data`` may be:

    * A **list** of items (collection endpoints).
    * A **dict** (single-resource endpoints).
    * ``None`` / absent (e.g. 204-style responses).

    Parameters
    ----------
    raw:
        The raw JSON response dictionary from the Cloud V1 API.

    Returns
    -------
    NormalizedResponse
        The unwrapped response with a consistent ``data`` list.

    Raises
    ------
    APIError
        If the envelope indicates an error via ``httpStatusCode``.
    """
    status_code = raw.get("httpStatusCode")
    trace_id = raw.get("traceId", "")

    meta: dict[str, Any] = {
        "httpStatusCode": status_code,
        "traceId": trace_id,
    }

    # Check for error signalled within the envelope itself.
    if isinstance(status_code, int) and status_code >= 400:
        error_msg = raw.get("message", raw.get("error", f"Cloud V1 error (status {status_code})"))
        logger.error(
            "Cloud V1 API error in response envelope: %s (traceId=%s)",
            error_msg,
            trace_id,
        )
        raise APIError(
            f"Cloud V1 API error: {error_msg}",
            status_code=status_code,
            details=meta,
        )

    data = raw.get("data")

    # Normalise into a list.
    if data is None:
        data_list: list[dict[str, Any]] = []
    elif isinstance(data, list):
        data_list = data
    elif isinstance(data, dict):
        data_list = [data]
    else:
        # Unexpected data type — wrap in a list for safety.
        data_list = [{"value": data}]

    return NormalizedResponse(
        data=data_list,
        count=len(data_list),
        total_count=None,  # Cloud V1 does not use pagination metadata in the envelope
        meta=meta,
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class CloudV1Client:
    """Async HTTP client for the UniFi Cloud V1 REST API.

    Parameters
    ----------
    api_key:
        API key used for ``X-API-KEY`` authentication.  Typically sourced
        from the ``UNIFI_API_KEY`` environment variable.
    base_url:
        Override the base URL (useful for testing).  Defaults to
        ``https://api.ui.com/v1/``.
    timeout:
        Request timeout in seconds (applies to connect + read).
    max_retries:
        Maximum number of retries on 429 responses before giving up.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _BASE_URL,
        timeout: float = 30.0,
        max_retries: int = _BACKOFF_MAX_RETRIES,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout = timeout
        self._max_retries = max_retries

        # Track rate-limit quota from response headers.
        self._rate_limit_remaining: int | None = None

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "X-API-KEY": self._api_key,
                "Accept": "application/json",
            },
            verify=True,  # Public API — always verify SSL
            timeout=httpx.Timeout(timeout),
        )

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> CloudV1Client:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def rate_limit_remaining(self) -> int | None:
        """Most recently observed rate-limit remaining quota, or ``None``."""
        return self._rate_limit_remaining

    async def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a GET request to the Cloud V1 API.

        Parameters
        ----------
        endpoint:
            API path relative to the base URL (e.g. ``"sites"``).
        params:
            Optional query parameters.

        Returns
        -------
        dict
            The raw JSON response (envelope included).

        Raises
        ------
        AuthenticationError
            On 401 or 403 responses.
        RateLimitError
            On 429 responses after exhausting retries.
        APIError
            On other 4xx/5xx responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        return await self._request_with_retry("GET", endpoint, params=params)

    async def get_normalized(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> NormalizedResponse:
        """Make a GET request and return the normalized (unwrapped) response.

        This is the preferred method for most callers.  It unwraps the
        Cloud V1 API envelope and returns a :class:`NormalizedResponse`
        with the ``data`` array, item count, and trace metadata.

        Parameters
        ----------
        endpoint:
            API path relative to the base URL (e.g. ``"sites"``).
        params:
            Optional query parameters.

        Returns
        -------
        NormalizedResponse
            The unwrapped response data.

        Raises
        ------
        AuthenticationError
            On 401 or 403 responses.
        RateLimitError
            On 429 responses after exhausting retries.
        APIError
            On other 4xx/5xx responses or envelope-level errors.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        raw = await self.get(endpoint, params=params)
        return normalize_cloud_v1_response(raw)

    async def close(self) -> None:
        """Close the underlying httpx client and release resources."""
        await self._client.aclose()
        logger.debug("Closed CloudV1Client for %s", self._base_url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a request with exponential backoff on 429 responses.

        On a 429, the client waits with exponential backoff (jittered)
        and retries up to ``max_retries`` times.  If the server provides
        a ``Retry-After`` header, that value is used as the delay floor.

        If retries are exhausted, :class:`~unifi.errors.RateLimitError`
        is raised.
        """
        delay = _BACKOFF_INITIAL

        for attempt in range(self._max_retries + 1):
            try:
                return await self._request(method, endpoint, params=params)
            except RateLimitError as exc:
                if attempt >= self._max_retries:
                    logger.error(
                        "Rate limit retries exhausted after %d attempts for %s %s",
                        attempt + 1,
                        method,
                        endpoint,
                    )
                    raise

                # Use Retry-After from the server if available and larger.
                if exc.retry_after_seconds is not None:
                    delay = max(delay, exc.retry_after_seconds)

                # Apply jitter: delay * (1 +/- jitter_factor * random)
                jitter = _BACKOFF_JITTER_FACTOR * (2.0 * random.random() - 1.0)
                jittered_delay = delay * (1.0 + jitter)
                jittered_delay = min(jittered_delay, _BACKOFF_MAX)

                logger.warning(
                    "Rate limited (429) on attempt %d/%d for %s %s. "
                    "Retrying in %.2f seconds.",
                    attempt + 1,
                    self._max_retries + 1,
                    method,
                    endpoint,
                    jittered_delay,
                )

                await asyncio.sleep(jittered_delay)

                # Exponential increase for next attempt.
                delay = min(delay * 2.0, _BACKOFF_MAX)

        # Should not be reachable, but satisfy the type checker.
        raise RateLimitError(  # pragma: no cover
            f"Rate limit retries exhausted for {endpoint}.",
            endpoint=endpoint,
        )

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a single HTTP request with logging and error translation.

        All public methods ultimately delegate here so that logging,
        timing, rate-limit tracking, and error mapping are applied
        consistently.
        """
        url = endpoint
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

        start = time.monotonic()

        try:
            response = await self._client.request(
                method,
                url,
                params=params,
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

        # --- Rate-limit tracking ---
        self._track_rate_limit(response)

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

    def _track_rate_limit(self, response: httpx.Response) -> None:
        """Update rate-limit quota from response headers and log warnings."""
        remaining_header = response.headers.get("x-ratelimit-remaining")
        if remaining_header is None:
            return

        try:
            remaining = int(remaining_header)
        except (ValueError, TypeError):
            logger.debug(
                "Could not parse X-RateLimit-Remaining header: %r",
                remaining_header,
            )
            return

        self._rate_limit_remaining = remaining

        if remaining < _RATE_LIMIT_LOW_THRESHOLD:
            logger.warning(
                "Cloud V1 API rate-limit quota low: %d/%d remaining "
                "(threshold: %d). Consider reducing request frequency.",
                remaining,
                _RATE_LIMIT_TOTAL,
                _RATE_LIMIT_LOW_THRESHOLD,
            )

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
                "Verify that UNIFI_API_KEY is set correctly.",
                env_var="UNIFI_API_KEY",
                endpoint=endpoint,
            )

        if status == 403:
            logger.error(
                "Forbidden (403) for %s%s — API key may lack required permissions",
                self._base_url,
                endpoint,
            )
            raise AuthenticationError(
                f"Forbidden (403) for {endpoint}. "
                "The API key may lack the required permissions for this endpoint.",
                env_var="UNIFI_API_KEY",
                endpoint=endpoint,
                details={"hint": "Check API key permissions in UniFi Cloud settings"},
            )

        if status == 429:
            retry_after = self._parse_retry_after(response)
            logger.error(
                "Rate limited (429) for %s%s — retry after %s seconds",
                self._base_url,
                endpoint,
                retry_after,
            )
            raise RateLimitError(
                f"Rate limited (429) for {endpoint}.",
                retry_after_seconds=retry_after,
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
