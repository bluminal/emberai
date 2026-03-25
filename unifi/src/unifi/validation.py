# SPDX-License-Identifier: MIT
"""Path parameter validation utilities for the unifi plugin.

Prevents path traversal attacks by validating that user-supplied values
are safe for interpolation into API URL paths.  Any value containing
``/``, ``..``, or disallowed characters is rejected with a
:class:`~unifi.errors.ValidationError`.
"""

from __future__ import annotations

import re

from unifi.errors import ValidationError

# Match alphanumeric strings with hyphens, underscores, and dots (max 128 chars).
_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_.\-]{1,128}$")

# Standard UUID format: 8-4-4-4-12 hex digits.
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# MAC address: six hex pairs with optional colon or dash separators.
_MAC_PATTERN = re.compile(
    r"^[0-9a-fA-F]{2}([:\-]?)[0-9a-fA-F]{2}"
    r"(\1[0-9a-fA-F]{2}){4}$"
)


def validate_path_param(value: str, param_name: str) -> str:
    """Validate that a value is safe for URL path interpolation.

    Strips leading/trailing whitespace, then checks for path traversal
    characters (``/`` and ``..``) and ensures the value matches either
    a UUID pattern or a safe alphanumeric pattern.

    Parameters
    ----------
    value:
        The raw user-supplied value to validate.
    param_name:
        Name of the parameter (used in error messages).

    Returns
    -------
    str
        The cleaned (stripped) value, guaranteed safe for path interpolation.

    Raises
    ------
    ValidationError
        If the value is empty, contains path traversal characters, or
        contains disallowed characters.
    """
    cleaned = value.strip()

    if not cleaned:
        raise ValidationError(
            f"{param_name} must not be empty.",
            details={"field": param_name},
        )

    if "/" in cleaned or ".." in cleaned:
        raise ValidationError(
            f"Invalid {param_name}: path traversal characters detected.",
            details={"field": param_name},
        )

    if (
        not _SAFE_ID_PATTERN.match(cleaned)
        and not _UUID_PATTERN.match(cleaned)
        and not _MAC_PATTERN.match(cleaned)
    ):
        raise ValidationError(
            f"Invalid {param_name}: contains disallowed characters.",
            details={"field": param_name},
        )

    return cleaned
