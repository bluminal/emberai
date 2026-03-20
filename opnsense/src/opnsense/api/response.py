# SPDX-License-Identifier: MIT
"""Response normalization for the OPNsense REST API.

OPNsense returns two distinct response shapes:

**Search endpoints** (paginated listings)::

    {
        "rows": [...],
        "rowCount": 5,
        "total": 42,
        "current": 1
    }

**Action endpoints** (mutations, status checks)::

    {"result": "saved", "changed": true}

    # or flat dictionaries:
    {"items": [...]}

    # or simple status:
    {"status": "ok"}

This module normalizes both shapes into a consistent :class:`NormalizedResponse`
dataclass, making downstream code agnostic to envelope format.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NormalizedResponse:
    """Normalized response from the OPNsense REST API.

    Attributes
    ----------
    data:
        The unwrapped data array.  For search endpoints, this is the
        ``rows`` array.  For action endpoints, the raw response dict
        is wrapped in a single-item list.
    count:
        Number of items in this response page (``rowCount`` for search
        endpoints, 1 for action endpoints).
    total:
        Total number of items across all pages.  ``None`` when the
        response does not include pagination metadata.
    current_page:
        The current page number (``current`` field from search endpoints).
        ``None`` for non-paginated responses.
    raw:
        The original unmodified response dictionary, preserved for
        callers that need access to action-specific fields like
        ``result`` or ``changed``.
    """

    data: list[dict[str, Any]]
    count: int
    total: int | None = None
    current_page: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def normalize_response(raw: dict[str, Any]) -> NormalizedResponse:
    """Normalize an OPNsense API response into a consistent structure.

    Handles both search-style (``rows``/``rowCount``/``total``/``current``)
    and action-style (flat JSON) responses.

    Parameters
    ----------
    raw:
        The raw JSON response dictionary from the API.

    Returns
    -------
    NormalizedResponse
        The normalized response.
    """
    # Search-style response: has "rows" key with a list value.
    if "rows" in raw and isinstance(raw["rows"], list):
        rows = raw["rows"]
        row_count = raw.get("rowCount", len(rows))
        total = raw.get("total")
        current = raw.get("current")

        logger.debug(
            "Normalized search response: %d rows, total=%s, page=%s",
            row_count,
            total,
            current,
        )

        return NormalizedResponse(
            data=rows,
            count=row_count,
            total=total,
            current_page=current,
            raw=raw,
        )

    # Action/flat response: wrap in a single-item list for uniform access.
    logger.debug("Normalized action/flat response: %s", list(raw.keys()))
    return NormalizedResponse(
        data=[raw],
        count=1,
        total=None,
        current_page=None,
        raw=raw,
    )


def is_search_response(raw: dict[str, Any]) -> bool:
    """Check whether a response dict is a search-style paginated response.

    Parameters
    ----------
    raw:
        The raw JSON response dictionary.

    Returns
    -------
    bool
        ``True`` if the response has a ``rows`` key containing a list.
    """
    return "rows" in raw and isinstance(raw["rows"], list)


def is_action_success(raw: dict[str, Any]) -> bool:
    """Check whether an action response indicates success.

    OPNsense action endpoints typically return one of:
    - ``{"result": "saved"}`` -- config was saved
    - ``{"status": "ok"}``   -- reconfigure completed
    - ``{"changed": true}``  -- config was modified

    Parameters
    ----------
    raw:
        The raw JSON response dictionary.

    Returns
    -------
    bool
        ``True`` if any of the known success indicators are present.
    """
    result = raw.get("result", "")
    status = raw.get("status", "")

    if isinstance(result, str) and result.lower() in ("saved", "done"):
        return True
    if isinstance(status, str) and status.lower() in ("ok", "done"):
        return True

    return False
