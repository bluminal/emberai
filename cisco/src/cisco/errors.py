# SPDX-License-Identifier: MIT
"""Structured error hierarchy for the cisco plugin.

All errors carry structured context beyond a plain message string, enabling
programmatic inspection by callers (retry logic, user-facing formatting,
logging) without parsing message text.

Hierarchy
---------
::

    NetexError (base)
    +-- AuthenticationError    # SSH authentication failure or missing credentials
    +-- NetworkError           # Connection timeout, DNS failure, SSH transport errors
    +-- SSHCommandError        # CLI command execution failures
    +-- ValidationError        # Invalid input or schema mismatch
    +-- WriteGateError         # Write operation blocked by safety gate

Every error inherits the following structured fields from ``NetexError``:

* ``status_code``   -- HTTP status code when applicable (rarely used for SSH).
* ``endpoint``      -- The SSH host or target that produced the error.
* ``retry_hint``    -- Operator-friendly retry guidance.
* ``details``       -- Arbitrary additional context as a dict.

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
    """Base exception for all Netex / cisco plugin errors.

    Parameters
    ----------
    message:
        Human-readable description of what went wrong.
    status_code:
        HTTP status code, if the error originated from an HTTP response.
    endpoint:
        SSH host or API endpoint that produced the error.
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
    """Raised when SSH authentication fails or credentials are missing.

    Parameters
    ----------
    message:
        Human-readable description.
    env_var:
        Name of the environment variable that is missing or invalid
        (e.g. ``CISCO_SSH_PASSWORD``).
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
            status_code=None,
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
# Network / connectivity
# ---------------------------------------------------------------------------


class NetworkError(NetexError):
    """Raised for transport-level failures (SSH timeout, DNS, connection refused).

    No HTTP status code is set because these are SSH transport errors.
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
# SSH command execution errors
# ---------------------------------------------------------------------------


class SSHCommandError(NetexError):
    """Raised when a CLI command fails to execute or returns unexpected output.

    Parameters
    ----------
    message:
        Human-readable description.
    command:
        The CLI command that was executed.
    output:
        Raw output returned by the switch, if any.
    """

    def __init__(
        self,
        message: str,
        *,
        command: str | None = None,
        output: str | None = None,
        endpoint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra_details: dict[str, Any] = {}
        if command is not None:
            extra_details["command"] = command
        if output is not None:
            extra_details["output"] = output
        if details:
            extra_details.update(details)

        super().__init__(
            message,
            status_code=None,
            endpoint=endpoint,
            retry_hint=None,
            details=extra_details or None,
        )
        self.command = command
        self.output = output

    def __str__(self) -> str:
        parts: list[str] = [self.message]
        if self.command:
            parts.append(f"Command: {self.command}")
        if self.endpoint:
            parts.append(f"Endpoint: {self.endpoint}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# CLI parse errors
# ---------------------------------------------------------------------------


class CLIParseError(NetexError):
    """Raised when CLI output cannot be parsed into the expected structure.

    This indicates the switch returned output in an unexpected format,
    possibly due to firmware version differences or incomplete command
    output.

    Parameters
    ----------
    message:
        Human-readable description.
    command:
        The CLI command whose output could not be parsed.
    raw_output:
        The raw CLI output that failed to parse.
    """

    def __init__(
        self,
        message: str,
        *,
        command: str | None = None,
        raw_output: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra_details: dict[str, Any] = {}
        if command is not None:
            extra_details["command"] = command
        if raw_output is not None:
            extra_details["raw_output"] = raw_output
        if details:
            extra_details.update(details)

        super().__init__(
            message,
            status_code=None,
            endpoint=command,
            retry_hint="Check switch firmware version compatibility",
            details=extra_details or None,
        )
        self.command = command
        self.raw_output = raw_output


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationError(NetexError):
    """Raised when input validation or schema conformance fails.

    This is a *client-side* validation error (bad input from the caller),
    not an error returned by the switch CLI.
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

    The safety gate enforces two preconditions before any write can proceed:

    1. The ``CISCO_WRITE_ENABLED`` environment variable must be ``"true"``.
    2. The ``--apply`` flag must be present in the command invocation.

    Parameters
    ----------
    message:
        Human-readable description.
    reason:
        Why the write was blocked -- either the env var is disabled or the
        ``--apply`` flag is missing.
    """

    _REASON_MESSAGES: ClassVar[dict[WriteGateReason, str]] = {
        WriteGateReason.ENV_VAR_DISABLED: (
            "Set CISCO_WRITE_ENABLED=true to allow write operations"
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
