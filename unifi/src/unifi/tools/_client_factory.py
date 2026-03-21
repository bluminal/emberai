# SPDX-License-Identifier: MIT
"""Shared client factory for UniFi MCP tools.

Provides ``get_local_client()`` and ``get_cloud_client()`` with credential
validation and helpful error messages when env vars are not configured.
"""

from __future__ import annotations

import os

from unifi.api.cloud_v1_client import CloudV1Client
from unifi.api.local_gateway_client import LocalGatewayClient
from unifi.errors import APIError, AuthenticationError

_AUTH_DOCS = "https://bluminal.github.io/emberai/getting-started/authentication/"


def get_local_client() -> LocalGatewayClient:
    """Create a :class:`LocalGatewayClient` from environment variables.

    Raises
    ------
    APIError
        If ``UNIFI_LOCAL_HOST`` or ``UNIFI_LOCAL_KEY`` is not set.
    """
    host = os.environ.get("UNIFI_LOCAL_HOST", "").strip()
    key = os.environ.get("UNIFI_LOCAL_KEY", "").strip()
    if not host or not key:
        missing = []
        if not host:
            missing.append("UNIFI_LOCAL_HOST")
        if not key:
            missing.append("UNIFI_LOCAL_KEY")
        raise APIError(
            f"UniFi credentials not configured: {', '.join(missing)}. "
            "Set these environment variables to connect to your UniFi gateway. "
            f"See: {_AUTH_DOCS}",
            status_code=500,
            details={"missing_vars": missing},
        )
    return LocalGatewayClient(host=host, api_key=key)


def get_cloud_client() -> CloudV1Client:
    """Create a :class:`CloudV1Client` from ``UNIFI_API_KEY``.

    Raises
    ------
    AuthenticationError
        If ``UNIFI_API_KEY`` is not set.
    """
    api_key = os.environ.get("UNIFI_API_KEY", "").strip()
    if not api_key:
        raise AuthenticationError(
            "UNIFI_API_KEY is not configured. "
            "Set this environment variable to use Cloud V1 API features. "
            f"See: {_AUTH_DOCS}",
            env_var="UNIFI_API_KEY",
        )
    return CloudV1Client(api_key=api_key)
