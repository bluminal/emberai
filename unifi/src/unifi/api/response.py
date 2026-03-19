# SPDX-License-Identifier: MIT
"""Response normalization for the UniFi Local Gateway API.

The UniFi Local Gateway wraps all successful responses in a standard
envelope::

    {"data": [...], "meta": {"rc": "ok"}}

Error responses use the same envelope with a different ``rc`` value::

    {"data": [], "meta": {"rc": "error", "msg": "api.err.Invalid"}}

Some endpoints also include ``count`` and ``totalCount`` fields for
pagination support.

This module provides functions to unwrap these envelopes into clean,
typed data structures, raising structured errors when the API signals
a failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from unifi.errors import APIError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NormalizedResponse:
    """Unwrapped response from the UniFi Local Gateway API.

    Attributes
    ----------
    data:
        The unwrapped data array from the API envelope.
    count:
        Number of items in this response page.
    total_count:
        Total number of items available across all pages (for pagination).
        ``None`` when the API does not provide pagination metadata.
    meta:
        The original ``meta`` block from the API envelope, preserved
        for callers that need access to it (e.g., for debugging).
    """

    data: list[dict[str, Any]]
    count: int
    total_count: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def normalize_response(raw: dict[str, Any]) -> NormalizedResponse:
    """Unwrap the UniFi API envelope into clean data.

    Handles the following response shapes:

    - **Standard envelope**: ``{"data": [...], "meta": {"rc": "ok"}}``
    - **Error envelope**: ``{"data": [], "meta": {"rc": "error", "msg": "..."}}``
    - **Count fields**: ``{"data": [...], "count": N, "totalCount": M}``
    - **Flat responses** (no envelope): returned as-is in a single-item list

    Parameters
    ----------
    raw:
        The raw JSON response dictionary from the API.

    Returns
    -------
    NormalizedResponse
        The unwrapped and normalized response.

    Raises
    ------
    APIError
        If ``meta.rc`` is ``"error"``.
    """
    meta = raw.get("meta", {})

    # Check for API-level error signalled via the meta block.
    if isinstance(meta, dict) and meta.get("rc") == "error":
        msg = meta.get("msg", "Unknown API error")
        logger.error("UniFi API error in response envelope: %s", msg)
        raise APIError(
            f"UniFi API error: {msg}",
            status_code=200,  # HTTP was 200, but API signalled an error
            details={"meta": meta},
        )

    # Standard envelope: has "data" key with a list value.
    if "data" in raw and isinstance(raw["data"], list):
        data = raw["data"]
        count = raw.get("count", len(data))
        total_count = raw.get("totalCount")

        return NormalizedResponse(
            data=data,
            count=count,
            total_count=total_count,
            meta=meta if isinstance(meta, dict) else {},
        )

    # Flat response (no envelope): wrap the entire dict in a single-item list.
    logger.debug("Response has no 'data' envelope; wrapping as single-item list")
    return NormalizedResponse(
        data=[raw],
        count=1,
        total_count=None,
        meta={},
    )


def normalize_single(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize and return the first item from the data array.

    Convenience function for endpoints that are expected to return
    exactly one item (e.g., fetching a single device by MAC address).

    Parameters
    ----------
    raw:
        The raw JSON response dictionary from the API.

    Returns
    -------
    dict
        The first item from the ``data`` array.

    Raises
    ------
    APIError
        If ``meta.rc`` is ``"error"`` (delegated to :func:`normalize_response`),
        or if the ``data`` array is empty.
    """
    normalized = normalize_response(raw)

    if not normalized.data:
        raise APIError(
            "Expected a single item in response but data array is empty",
            status_code=200,
            details={"meta": normalized.meta},
        )

    return normalized.data[0]
