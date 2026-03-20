# SPDX-License-Identifier: MIT
"""Async HTTP client for the UniFi Local Gateway API.

Communicates with a UniFi gateway (UDM, UDM-Pro, UDR, etc.) over its
local REST API at ``https://{host}/proxy/network/``.  Authentication is
via an ``X-API-KEY`` header.

Typical usage::

    async with LocalGatewayClient(host="192.168.1.1", api_key="...") as client:
        response = await client.get("/api/s/default/stat/device")
        devices = response["data"]

SSL verification is **off** by default because UniFi gateways ship with
self-signed certificates.  A warning is logged when verification is
disabled so operators are aware.

Error responses are translated to the structured error hierarchy defined
in :mod:`unifi.errors`.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from types import TracebackType

from unifi.api.response import NormalizedResponse, normalize_response, normalize_single
from unifi.errors import APIError, AuthenticationError, NetworkError, RateLimitError

logger = logging.getLogger(__name__)

# Threshold in seconds above which a successful request triggers a warning.
_SLOW_REQUEST_THRESHOLD = 5.0


class LocalGatewayClient:
    """Async HTTP client for the UniFi Local Gateway REST API.

    Parameters
    ----------
    host:
        IP address or hostname of the UniFi gateway (without scheme or path).
        Example: ``"192.168.1.1"`` or ``"unifi.local"``.
    api_key:
        API key used for ``X-API-KEY`` authentication.
    verify_ssl:
        Whether to verify the gateway's TLS certificate.  Defaults to
        ``False`` because UniFi gateways typically use self-signed certs.
    timeout:
        Request timeout in seconds (applies to connect + read).
    """

    def __init__(
        self,
        host: str,
        api_key: str,
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self._host = host
        self._api_key = api_key
        self._verify_ssl = verify_ssl
        self._timeout = timeout

        # Normalise base URL: strip trailing slashes from host, ensure scheme.
        clean_host = host.rstrip("/")
        if not clean_host.startswith(("http://", "https://")):
            clean_host = f"https://{clean_host}"
        self._base_url = f"{clean_host}/proxy/network"

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "X-API-KEY": self._api_key,
                "Accept": "application/json",
            },
            verify=self._verify_ssl,
            timeout=httpx.Timeout(timeout),
        )

        if not self._verify_ssl:
            logger.warning(
                "SSL verification is disabled for %s. "
                "This is expected for UniFi gateways with self-signed certificates, "
                "but should not be used in environments where certificate validation "
                "is required.",
                self._base_url,
            )

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> LocalGatewayClient:
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

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request to the local gateway API.

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

        Raises
        ------
        AuthenticationError
            On 401 or 403 responses.
        RateLimitError
            On 429 responses.
        APIError
            On other 4xx/5xx responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        return await self._request("GET", endpoint, params=params)

    async def post(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a POST request to the local gateway API.

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

        Raises
        ------
        AuthenticationError
            On 401 or 403 responses.
        RateLimitError
            On 429 responses.
        APIError
            On other 4xx/5xx responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        return await self._request("POST", endpoint, json_data=data)

    async def put(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a PUT request to the local gateway API.

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

        Raises
        ------
        AuthenticationError
            On 401 or 403 responses.
        RateLimitError
            On 429 responses.
        APIError
            On other 4xx/5xx responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        return await self._request("PUT", endpoint, json_data=data)

    async def get_normalized(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> NormalizedResponse:
        """Make a GET request and return the normalized (unwrapped) response.

        This is the preferred method for most callers.  It unwraps the
        UniFi API envelope and returns a :class:`NormalizedResponse` with
        the ``data`` array, item count, and optional pagination metadata.

        Parameters
        ----------
        endpoint:
            API path relative to ``/proxy/network/``.
        params:
            Optional query parameters.

        Returns
        -------
        NormalizedResponse
            The unwrapped response data.

        Raises
        ------
        APIError
            If the API envelope signals an error (``meta.rc == "error"``),
            or on HTTP 4xx/5xx responses.
        AuthenticationError
            On 401 or 403 responses.
        RateLimitError
            On 429 responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        raw = await self.get(endpoint, params=params)
        return normalize_response(raw)

    async def get_single(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a GET request and return the first item from the data array.

        Convenience method for endpoints expected to return a single item
        (e.g., fetching a specific device by MAC address).

        Parameters
        ----------
        endpoint:
            API path relative to ``/proxy/network/``.
        params:
            Optional query parameters.

        Returns
        -------
        dict
            The first item from the ``data`` array.

        Raises
        ------
        APIError
            If the data array is empty, or the API envelope signals an error.
        AuthenticationError
            On 401 or 403 responses.
        RateLimitError
            On 429 responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        raw = await self.get(endpoint, params=params)
        return normalize_single(raw)

    async def get_all(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        page_size: int = 100,
    ) -> NormalizedResponse:
        """Fetch all pages of a paginated endpoint and combine the results.

        Makes successive GET requests with ``offset`` and ``limit`` query
        parameters, collecting results until all items have been fetched
        (i.e., ``count >= totalCount``).

        If the first response has no ``totalCount`` (i.e., the endpoint does
        not support pagination), returns that single response as-is.

        Parameters
        ----------
        endpoint:
            API path relative to ``/proxy/network/``.
        params:
            Optional base query parameters (``offset`` and ``limit`` will be
            added/overridden by the pagination logic).
        page_size:
            Number of items to request per page (default: 100).

        Returns
        -------
        NormalizedResponse
            Combined response with all pages of data merged into a single
            ``data`` list.  ``count`` reflects the total number of items
            returned, and ``total_count`` reflects the API's ``totalCount``.

        Raises
        ------
        APIError
            If any page returns an API-level error.
        AuthenticationError
            On 401 or 403 responses.
        RateLimitError
            On 429 responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        base_params = dict(params) if params else {}
        all_data: list[dict[str, Any]] = []
        offset = 0
        total_count: int | None = None
        last_meta: dict[str, Any] = {}

        while True:
            page_params = {**base_params, "offset": offset, "limit": page_size}
            raw = await self.get(endpoint, params=page_params)
            page = normalize_response(raw)

            all_data.extend(page.data)
            last_meta = page.meta

            # If no totalCount is reported, the endpoint does not paginate.
            if page.total_count is None:
                logger.debug(
                    "Endpoint %s does not report totalCount; returning single page",
                    endpoint,
                )
                return page

            total_count = page.total_count

            # If we have fetched all available items, stop.
            if len(all_data) >= total_count:
                break

            # If the page returned no data, stop to avoid infinite loops.
            if not page.data:
                logger.warning(
                    "Endpoint %s returned empty page at offset %d; stopping pagination",
                    endpoint,
                    offset,
                )
                break

            offset += len(page.data)

        return NormalizedResponse(
            data=all_data,
            count=len(all_data),
            total_count=total_count,
            meta=last_meta,
        )

    async def close(self) -> None:
        """Close the underlying httpx client and release resources."""
        await self._client.aclose()
        logger.debug("Closed LocalGatewayClient for %s", self._base_url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request with logging and error translation.

        All public methods delegate here so that logging, timing, and error
        mapping are applied consistently.
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
            # Check for SSL-specific errors in the exception chain.
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
                    retry_hint="Check UNIFI_LOCAL_HOST or SSL settings",
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
            # Catch-all for other httpx transport errors (DNS failures, etc.).
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
                "Verify that UNIFI_LOCAL_KEY is set correctly.",
                env_var="UNIFI_LOCAL_KEY",
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
                env_var="UNIFI_LOCAL_KEY",
                endpoint=endpoint,
                details={"hint": "Check API key permissions in UniFi settings"},
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
