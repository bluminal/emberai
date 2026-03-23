# SPDX-License-Identifier: MIT
"""Structured error hierarchy for the unifi plugin.

All errors carry structured context beyond a plain message string, enabling
programmatic inspection by callers (retry logic, user-facing formatting,
logging) without parsing message text.

Hierarchy
---------
::

    NetexError (base)
    ├── AuthenticationError    # 401 — missing or invalid API key
    ├── RateLimitError         # 429 — quota exceeded (carries retry_after_seconds)
    ├── NetworkError           # Connection timeout, DNS failure, SSL errors
    ├── APIError               # 4xx / 5xx API responses
    ├── ValidationError        # Invalid input or schema mismatch
    └── WriteGateError         # Write operation blocked by safety gate

Every error inherits the following structured fields from ``NetexError``:

* ``status_code``   — HTTP status code when applicable.
* ``endpoint``      — The API endpoint that produced the error.
* ``retry_hint``    — Operator-friendly retry guidance (e.g. "Retry after 30 s").
* ``details``       — Arbitrary additional context as a dict.

Subclasses add domain-specific fields (see each class's docstring).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, ClassVar

# ---------------------------------------------------------------------------
# WriteGateReason enum
# ---------------------------------------------------------------------------


class WriteGateReason(StrEnum):
    """Reason a write operation was blocked by the safety gate."""

    ENV_VAR_DISABLED = "env_var_disabled"
    APPLY_FLAG_MISSING = "apply_flag_missing"


# ---------------------------------------------------------------------------
# Base error
# ---------------------------------------------------------------------------


class NetexError(Exception):
    """Base exception for all Netex / unifi plugin errors.

    Parameters
    ----------
    message:
        Human-readable description of what went wrong.
    status_code:
        HTTP status code, if the error originated from an HTTP response.
    endpoint:
        API endpoint path (e.g. ``/api/s/default/stat/device``).
    retry_hint:
        Operator-facing guidance on whether / when to retry.
    details:
        Arbitrary structured context (logged, never displayed raw to operator).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        endpoint: str | None = None,
        retry_hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.endpoint = endpoint
        self.retry_hint = retry_hint
        self.details = details or {}

    def __str__(self) -> str:
        parts: list[str] = [self.message]
        if self.endpoint:
            parts.append(f"Endpoint: {self.endpoint}")
        if self.status_code is not None:
            parts.append(f"Status: {self.status_code}")
        if self.retry_hint:
            parts.append(f"Hint: {self.retry_hint}")
        return " | ".join(parts)

    def __repr__(self) -> str:
        fields = ", ".join(
            f"{k}={v!r}"
            for k, v in {
                "message": self.message,
                "status_code": self.status_code,
                "endpoint": self.endpoint,
                "retry_hint": self.retry_hint,
                "details": self.details if self.details else None,
            }.items()
            if v is not None
        )
        return f"{type(self).__name__}({fields})"


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class AuthenticationError(NetexError):
    """Raised when authentication fails (HTTP 401 or missing credentials).

    Parameters
    ----------
    message:
        Human-readable description.
    env_var:
        Name of the environment variable that is missing or invalid
        (e.g. ``UNIFI_LOCAL_KEY``).
    """

    def __init__(
        self,
        message: str,
        *,
        env_var: str | None = None,
        endpoint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra_details: dict[str, Any] = {}
        if env_var is not None:
            extra_details["env_var"] = env_var
        if details:
            extra_details.update(details)

        super().__init__(
            message,
            status_code=401,
            endpoint=endpoint,
            retry_hint=f"Set or correct the {env_var} environment variable" if env_var else None,
            details=extra_details or None,
        )
        self.env_var = env_var

    def __str__(self) -> str:
        base = super().__str__()
        if self.env_var:
            return f"{base} | Env var: {self.env_var}"
        return base


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class RateLimitError(NetexError):
    """Raised when the API returns HTTP 429 (quota exceeded).

    Parameters
    ----------
    message:
        Human-readable description.
    retry_after_seconds:
        Number of seconds the caller should wait before retrying.  Derived
        from the ``Retry-After`` response header when available.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
        endpoint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        retry_hint: str | None = None
        if retry_after_seconds is not None:
            retry_hint = f"Retry after {retry_after_seconds:.0f} seconds"

        extra_details: dict[str, Any] = {}
        if retry_after_seconds is not None:
            extra_details["retry_after_seconds"] = retry_after_seconds
        if details:
            extra_details.update(details)

        super().__init__(
            message,
            status_code=429,
            endpoint=endpoint,
            retry_hint=retry_hint,
            details=extra_details or None,
        )
        self.retry_after_seconds = retry_after_seconds


# ---------------------------------------------------------------------------
# Network / connectivity
# ---------------------------------------------------------------------------


class NetworkError(NetexError):
    """Raised for transport-level failures (timeout, DNS, SSL, connection refused).

    No HTTP status code is set because the request never received a response.
    """

    def __init__(
        self,
        message: str,
        *,
        endpoint: str | None = None,
        retry_hint: str | None = "Check network connectivity and retry",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=None,
            endpoint=endpoint,
            retry_hint=retry_hint,
            details=details,
        )


# ---------------------------------------------------------------------------
# API response errors (4xx / 5xx)
# ---------------------------------------------------------------------------


class APIError(NetexError):
    """Raised for non-401/429 HTTP error responses from the API.

    Parameters
    ----------
    message:
        Human-readable description.
    status_code:
        HTTP status code (e.g. 400, 403, 404, 500, 502, 503).
    endpoint:
        The API endpoint that returned the error.
    response_body:
        Raw response body text, useful for debugging opaque API errors.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        endpoint: str | None = None,
        response_body: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra_details: dict[str, Any] = {}
        if response_body is not None:
            extra_details["response_body"] = response_body
        if details:
            extra_details.update(details)

        retry_hint: str | None = None
        if status_code >= 500:
            retry_hint = "Server error — retry after a short delay"

        super().__init__(
            message,
            status_code=status_code,
            endpoint=endpoint,
            retry_hint=retry_hint,
            details=extra_details or None,
        )
        self.response_body = response_body


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationError(NetexError):
    """Raised when input validation or schema conformance fails.

    This is a *client-side* validation error (bad input from the caller),
    not an API-returned validation error (which would be ``APIError`` with
    status 422).
    """

    def __init__(
        self,
        message: str,
        *,
        endpoint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=None,
            endpoint=endpoint,
            retry_hint=None,
            details=details,
        )


# ---------------------------------------------------------------------------
# Write gate
# ---------------------------------------------------------------------------


class WriteGateError(NetexError):
    """Raised when a write operation is blocked by the safety gate.

    The safety gate (see ``unifi/safety.py``) enforces two preconditions
    before any write can proceed:

    1. The ``{PLUGIN}_WRITE_ENABLED`` environment variable must be ``"true"``.
    2. The ``--apply`` flag must be present in the command invocation.

    Parameters
    ----------
    message:
        Human-readable description.
    reason:
        Why the write was blocked — either the env var is disabled or the
        ``--apply`` flag is missing.
    """

    _REASON_MESSAGES: ClassVar[dict[WriteGateReason, str]] = {
        WriteGateReason.ENV_VAR_DISABLED: (
            "Set UNIFI_WRITE_ENABLED=true to allow write operations"
        ),
        WriteGateReason.APPLY_FLAG_MISSING: ("Add the --apply flag to execute write operations"),
    }

    def __init__(
        self,
        message: str,
        *,
        reason: WriteGateReason,
        plugin_name: str | None = None,
        env_var: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra_details: dict[str, Any] = {"reason": reason.value}
        if plugin_name is not None:
            extra_details["plugin_name"] = plugin_name
        if env_var is not None:
            extra_details["env_var"] = env_var
        if details:
            extra_details.update(details)

        super().__init__(
            message,
            status_code=None,
            endpoint=None,
            retry_hint=self._REASON_MESSAGES.get(reason),
            details=extra_details,
        )
        self.reason = reason
        self.plugin_name = plugin_name
        self.env_var = env_var

    def __str__(self) -> str:
        parts: list[str] = [self.message, f"Reason: {self.reason.value}"]
        if self.retry_hint:
            parts.append(f"Hint: {self.retry_hint}")
        return " | ".join(parts)
