# SPDX-License-Identifier: MIT
"""Async HTTP client for the OPNsense REST API.

Communicates with an OPNsense firewall over its REST API at
``{host}/api/{module}/{controller}/{command}``.  Authentication uses
HTTP Basic Auth with ``api_key`` as the username and ``api_secret``
as the password.

Typical usage::

    async with OPNsenseClient(
        host="https://192.168.1.1",
        api_key="...",
        api_secret="...",
        verify_ssl=False,
    ) as client:
        rules = await client.get("firewall", "filter", "searchRule")

OPNsense write operations follow a two-step pattern:

1. **write()** -- saves configuration but does NOT apply to the live system.
2. **reconfigure()** -- pushes saved configuration to the live system.

Both steps are protected by safety gates (see :mod:`opnsense.safety`).
After a successful reconfigure, the cache is automatically flushed for
the affected module to ensure stale data is not served.

SSL verification defaults to **True** but can be disabled for OPNsense
instances using self-signed certificates (common in home and lab
environments).  A warning is logged when verification is disabled.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from types import TracebackType

from opnsense.api.response import NormalizedResponse, normalize_response
from opnsense.cache import TTLCache
from opnsense.errors import APIError, AuthenticationError, NetworkError

logger = logging.getLogger(__name__)

# Threshold in seconds above which a successful request triggers a warning.
_SLOW_REQUEST_THRESHOLD = 5.0


class OPNsenseClient:
    """Async HTTP client for the OPNsense REST API.

    Parameters
    ----------
    host:
        The OPNsense instance URL (including scheme).
        Example: ``"https://192.168.1.1"`` or ``"https://opnsense.local"``.
    api_key:
        API key (used as Basic Auth username).  Created in OPNsense
        under System > Access > Users > API keys.
    api_secret:
        API secret (used as Basic Auth password).
    verify_ssl:
        Whether to verify the server's TLS certificate.  Defaults to
        ``True``.  Set to ``False`` for self-signed certificates.
    timeout:
        Request timeout in seconds (applies to connect + read).
    cache:
        Optional :class:`TTLCache` instance for response caching.
        If ``None``, a default cache is created.
    """

    def __init__(
        self,
        host: str,
        api_key: str,
        api_secret: str,
        *,
        verify_ssl: bool = True,
        timeout: float = 30.0,
        cache: TTLCache | None = None,
    ) -> None:
        self._host = host
        self._api_key = api_key
        self._api_secret = api_secret
        self._verify_ssl = verify_ssl
        self._timeout = timeout

        # Normalise base URL: strip trailing slashes, ensure scheme.
        clean_host = host.rstrip("/")
        if not clean_host.startswith(("http://", "https://")):
            clean_host = f"https://{clean_host}"
        self._base_url = clean_host

        # Build Basic Auth header: base64(api_key:api_secret)
        credentials = f"{api_key}:{api_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        self._auth_header = f"Basic {encoded}"

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": self._auth_header,
                "Accept": "application/json",
                # Note: Content-Type is NOT set here because OPNsense 26.x
                # returns 400 on GET requests that include Content-Type.
                # POST/PUT methods pass Content-Type via the json= parameter
                # which httpx sets automatically.
            },
            verify=self._verify_ssl,
            timeout=httpx.Timeout(timeout),
        )

        # Cache for GET responses.
        self._cache = cache if cache is not None else TTLCache()

        if not self._verify_ssl:
            logger.warning(
                "SSL verification is disabled for %s. "
                "This is common for OPNsense with self-signed certificates, "
                "but should not be used in production environments where "
                "certificate validation is required.",
                self._base_url,
            )

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> OPNsenseClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Public API — Read operations
    # ------------------------------------------------------------------

    def build_url(self, module: str, controller: str, command: str) -> str:
        """Build the full API URL path.

        OPNsense API URL pattern: ``/api/{module}/{controller}/{command}``

        Parameters
        ----------
        module:
            The API module (e.g. ``"firewall"``, ``"interfaces"``).
        controller:
            The controller within the module (e.g. ``"filter"``, ``"overview"``).
        command:
            The command/action (e.g. ``"searchRule"``, ``"export"``).

        Returns
        -------
        str
            The URL path (e.g. ``"/api/firewall/filter/searchRule"``).
        """
        return f"/api/{module}/{controller}/{command}"

    async def get(
        self,
        module: str,
        controller: str,
        command: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET request for read operations.

        Parameters
        ----------
        module:
            The API module (e.g. ``"firewall"``).
        controller:
            The controller within the module (e.g. ``"filter"``).
        command:
            The command (e.g. ``"searchRule"``).
        params:
            Optional query parameters.

        Returns
        -------
        dict
            The raw JSON response.

        Raises
        ------
        AuthenticationError
            On 401 or 403 responses.
        APIError
            On other 4xx/5xx responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        endpoint = self.build_url(module, controller, command)
        return await self._request("GET", endpoint, params=params)

    async def get_normalized(
        self,
        module: str,
        controller: str,
        command: str,
        params: dict[str, Any] | None = None,
    ) -> NormalizedResponse:
        """GET request returning a normalized (unwrapped) response.

        This is the preferred method for most callers. It normalizes
        the OPNsense response envelope (search-style or action-style)
        into a consistent :class:`NormalizedResponse`.

        Parameters
        ----------
        module:
            The API module.
        controller:
            The controller within the module.
        command:
            The command.
        params:
            Optional query parameters.

        Returns
        -------
        NormalizedResponse
            The normalized response.
        """
        raw = await self.get(module, controller, command, params=params)
        return normalize_response(raw)

    async def get_cached(
        self,
        module: str,
        controller: str,
        command: str,
        *,
        cache_key: str,
        ttl: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET request with TTL cache integration.

        Returns a cached response if available and not expired.  Otherwise,
        fetches from the API and caches the result.

        Uses the cache's stampede protection: concurrent requests for the
        same key result in only one actual API call.

        Parameters
        ----------
        module:
            The API module.
        controller:
            The controller.
        command:
            The command.
        cache_key:
            The cache key to use (e.g. ``"firewall:rules"``).
        ttl:
            Time-to-live in seconds.  Falls back to the cache's default TTL.
        params:
            Optional query parameters.

        Returns
        -------
        dict
            The raw JSON response (from cache or API).
        """
        return await self._cache.get_or_fetch(
            cache_key,
            fetcher=lambda: self.get(module, controller, command, params=params),
            ttl=ttl,
        )

    async def post(
        self,
        module: str,
        controller: str,
        command: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST request for write/action operations.

        Parameters
        ----------
        module:
            The API module.
        controller:
            The controller.
        command:
            The command.
        data:
            Optional JSON body.

        Returns
        -------
        dict
            The raw JSON response.

        Raises
        ------
        AuthenticationError
            On 401 or 403 responses.
        APIError
            On other 4xx/5xx responses.
        NetworkError
            On connection failures, timeouts, or SSL errors.
        """
        endpoint = self.build_url(module, controller, command)
        return await self._request("POST", endpoint, json_data=data)

    # ------------------------------------------------------------------
    # Public API — Write + Reconfigure pattern (Task 82)
    # ------------------------------------------------------------------

    async def write(
        self,
        module: str,
        controller: str,
        command: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write (save config). Does NOT apply to live system.

        This method saves configuration via a POST request but does NOT
        activate it on the live system.  To apply the saved configuration,
        call :meth:`reconfigure` separately.

        The write/reconfigure separation is fundamental to OPNsense's
        architecture.  Writes are reversible (they only modify the
        staging config); reconfigures are the point of no return.

        **Safety gates are enforced by the calling tool layer** (see
        :mod:`opnsense.safety`), not by this method.  This client is
        a transport layer; policy is enforced above it.

        Parameters
        ----------
        module:
            The API module (e.g. ``"firewall"``).
        controller:
            The controller (e.g. ``"filter"``).
        command:
            The write command (e.g. ``"addRule"``, ``"setRule"``).
        data:
            The configuration data to save.

        Returns
        -------
        dict
            The raw JSON response (typically ``{"result": "saved", ...}``).
        """
        endpoint = self.build_url(module, controller, command)
        return await self._request("POST", endpoint, json_data=data)

    async def reconfigure(
        self,
        module: str,
        controller: str,
    ) -> dict[str, Any]:
        """Apply saved config to the live system.

        This is the "point of no return" in OPNsense workflows.  After
        reconfigure completes, the saved configuration is active on the
        live firewall.

        Post-reconfigure, the cache is automatically flushed for the
        affected module to prevent serving stale data.

        **Safety gates are enforced by the calling tool layer** (see
        :mod:`opnsense.safety`), not by this method.

        Parameters
        ----------
        module:
            The API module (e.g. ``"firewall"``).
        controller:
            The controller (e.g. ``"filter"``).

        Returns
        -------
        dict
            The raw JSON response (typically ``{"status": "ok"}``).
        """
        endpoint = self.build_url(module, controller, "reconfigure")
        result = await self._request("POST", endpoint)

        # Flush cache for the affected module so subsequent reads
        # pick up the newly applied configuration.
        await self._cache.flush_by_prefix(f"{module}:")
        logger.info(
            "Reconfigure completed for %s/%s; cache flushed for prefix '%s:'",
            module,
            controller,
            module,
        )

        return result

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    @property
    def cache(self) -> TTLCache:
        """Access the underlying TTL cache instance.

        Exposed for direct cache operations (e.g., manual flush,
        stats inspection) by higher-level code.
        """
        return self._cache

    async def flush_cache(self, module: str | None = None) -> None:
        """Flush cached responses.

        Parameters
        ----------
        module:
            If provided, flush only cache keys for this module
            (keys matching the ``{module}:`` prefix).  If ``None``,
            flush the entire cache.
        """
        if module is not None:
            await self._cache.flush_by_prefix(f"{module}:")
            logger.debug("Flushed cache for module: %s", module)
        else:
            await self._cache.flush()
            logger.debug("Flushed entire cache")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying httpx client and release resources."""
        await self._client.aclose()
        logger.debug("Closed OPNsenseClient for %s", self._base_url)

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
        logger.debug(
            "Request: %s %s%s",
            method,
            self._base_url,
            endpoint,
        )

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
                "Connection timeout: %s %s%s after %.2fs -- %s",
                method,
                self._base_url,
                endpoint,
                elapsed,
                exc,
            )
            raise NetworkError(
                f"Connection timed out after {elapsed:.1f}s: {self._base_url}{endpoint}",
                endpoint=endpoint,
                retry_hint="Check network connectivity and OPNsense availability",
            ) from exc
        except httpx.ConnectError as exc:
            elapsed = time.monotonic() - start
            exc_str = str(exc).lower()
            if "ssl" in exc_str or "certificate" in exc_str:
                logger.error(
                    "SSL error connecting to %s%s -- %s",
                    self._base_url,
                    endpoint,
                    exc,
                )
                raise NetworkError(
                    f"SSL error connecting to {self._base_url}{endpoint}: {exc}",
                    endpoint=endpoint,
                    retry_hint="Set OPNSENSE_VERIFY_SSL=false for self-signed certs",
                ) from exc
            logger.error(
                "Connection refused: %s%s after %.2fs -- %s",
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
                "HTTP transport error: %s %s%s after %.2fs -- %s",
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
        """Translate HTTP error responses to the structured error hierarchy.

        Error mapping follows D14 from the implementation plan:
        - 401 -> AuthenticationError(env_var="OPNSENSE_API_KEY")
        - 403 -> AuthenticationError with privilege hint
        - 5xx -> APIError with retry hint
        - Timeout -> NetworkError (handled in _request)
        - SSL -> NetworkError with VERIFY_SSL hint (handled in _request)
        """
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
                "Verify that OPNSENSE_API_KEY and OPNSENSE_API_SECRET are set correctly.",
                env_var="OPNSENSE_API_KEY",
                endpoint=endpoint,
            )

        if status == 403:
            logger.error(
                "Forbidden (403) for %s%s -- API key may lack required privileges",
                self._base_url,
                endpoint,
            )
            raise AuthenticationError(
                f"Insufficient privileges (403) for {endpoint}. "
                "Check System > Access > Users > Effective Privileges "
                "in the OPNsense web UI.",
                env_var="OPNSENSE_API_KEY",
                endpoint=endpoint,
                details={
                    "hint": (
                        "Insufficient privileges. Check System > Access > Users > "
                        "Effective Privileges"
                    ),
                },
            )

        if status == 429:
            raise APIError(
                f"Rate limited (429) for {endpoint}.",
                status_code=429,
                endpoint=endpoint,
                response_body=body_text,
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
