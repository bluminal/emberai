# SPDX-License-Identifier: MIT
"""Client factory for NextDNS API access in tool functions.

Provides a module-level singleton :class:`CachedNextDNSClient` backed by a
shared :class:`TTLCache`. Tool functions call :func:`get_client` to obtain
the client without managing lifecycle or credentials directly.

The client is lazily initialised on first call and reused for the lifetime
of the process. The ``NEXTDNS_API_KEY`` environment variable must be set
before any tool invocation.
"""

from __future__ import annotations

import os

from nextdns.api.nextdns_client import CachedNextDNSClient
from nextdns.cache import TTLCache
from nextdns.errors import AuthenticationError

_AUTH_DOCS = "https://bluminal.github.io/emberai/getting-started/authentication/"

_cache = TTLCache(max_size=500, default_ttl=300.0)
_client: CachedNextDNSClient | None = None


def get_client() -> CachedNextDNSClient:
    """Return a shared :class:`CachedNextDNSClient` instance.

    The client is created lazily on first call using the
    ``NEXTDNS_API_KEY`` environment variable.

    Raises
    ------
    AuthenticationError
        If ``NEXTDNS_API_KEY`` is not set or empty.
    """
    global _client
    if _client is None:
        api_key = os.environ.get("NEXTDNS_API_KEY", "").strip()
        if not api_key:
            raise AuthenticationError(
                "NEXTDNS_API_KEY is not configured. "
                "Set this environment variable to use NextDNS API features. "
                f"See: {_AUTH_DOCS}",
                env_var="NEXTDNS_API_KEY",
            )
        _client = CachedNextDNSClient(api_key=api_key, cache=_cache)
    return _client


def reset_client() -> None:
    """Reset the singleton client (for testing only)."""
    global _client
    _client = None
