"""Structured error hierarchy for the talos plugin.

All errors carry structured context beyond a plain message string, enabling
programmatic inspection by callers (retry logic, user-facing formatting,
logging) without parsing message text.

Hierarchy
---------
::

    NetexError (base)
    +-- AuthenticationError    # talosconfig auth or mTLS certificate failures
    +-- NetworkError           # Connection timeout, node unreachable
    +-- TalosCtlError          # Non-zero exit code from talosctl subprocess
    +-- TalosCtlNotFoundError  # talosctl binary not found on PATH
    +-- ConfigParseError       # Unparseable talosctl output (JSON parse failure)
    +-- ValidationError        # Invalid input or schema mismatch
    +-- WriteGateError         # Write operation blocked by safety gate

Every error inherits the following structured fields from ``NetexError``:

* ``status_code``   -- HTTP status code when applicable (rarely used for CLI).
* ``endpoint``      -- The talosctl target node that produced the error.
* ``retry_hint``    -- Operator-friendly retry guidance.
* ``details``       -- Arbitrary additional context as a dict.
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
    RESET_FLAG_MISSING = "reset_flag_missing"
    BOOTSTRAP_BLOCKED = "bootstrap_blocked"


# ---------------------------------------------------------------------------
# Base error
# ---------------------------------------------------------------------------


class NetexError(Exception):
    """Base exception for all Netex / talos plugin errors.

    Parameters
    ----------
    message:
        Human-readable description of what went wrong.
    status_code:
        HTTP status code, if the error originated from an HTTP response.
    endpoint:
        Target node IP or talosctl endpoint that produced the error.
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
    """Raised when talosconfig authentication fails or credentials are missing.

    This covers mTLS certificate issues, missing talosconfig, invalid
    context, or expired certificates.

    Parameters
    ----------
    message:
        Human-readable description.
    config_path:
        Path to the talosconfig file that caused the error.
    context:
        Named context within the talosconfig that failed.
    """

    def __init__(
        self,
        message: str,
        *,
        config_path: str | None = None,
        context: str | None = None,
        endpoint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra_details: dict[str, Any] = {}
        if config_path is not None:
            extra_details["config_path"] = config_path
        if context is not None:
            extra_details["context"] = context
        if details:
            extra_details.update(details)

        super().__init__(
            message,
            status_code=None,
            endpoint=endpoint,
            retry_hint="Check talosconfig path and context in TALOS_CONFIG / TALOS_CONTEXT",
            details=extra_details or None,
        )
        self.config_path = config_path
        self.context = context


# ---------------------------------------------------------------------------
# Network / connectivity
# ---------------------------------------------------------------------------


class NetworkError(NetexError):
    """Raised for transport-level failures (node unreachable, timeout, DNS).

    Talos nodes communicate over gRPC + mTLS on port 50000. This error
    indicates the node could not be reached at the transport level.
    """

    def __init__(
        self,
        message: str,
        *,
        endpoint: str | None = None,
        retry_hint: str | None = "Check network connectivity and node status",
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
# talosctl subprocess errors
# ---------------------------------------------------------------------------


class TalosCtlError(NetexError):
    """Raised when talosctl exits with a non-zero exit code.

    Captures the full command, stderr output, and exit code for
    programmatic inspection and operator-friendly error reporting.

    Parameters
    ----------
    message:
        Human-readable description.
    command:
        The full talosctl command as a list of arguments.
    stderr:
        Standard error output from the subprocess.
    exit_code:
        Process exit code.
    """

    def __init__(
        self,
        message: str,
        *,
        command: list[str] | None = None,
        stderr: str | None = None,
        exit_code: int | None = None,
        endpoint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra_details: dict[str, Any] = {}
        if command is not None:
            extra_details["command"] = command
        if stderr is not None:
            extra_details["stderr"] = stderr
        if exit_code is not None:
            extra_details["exit_code"] = exit_code
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
        self.stderr = stderr
        self.exit_code = exit_code

    def __str__(self) -> str:
        parts: list[str] = [self.message]
        if self.command:
            parts.append(f"Command: {' '.join(self.command)}")
        if self.exit_code is not None:
            parts.append(f"Exit code: {self.exit_code}")
        if self.endpoint:
            parts.append(f"Endpoint: {self.endpoint}")
        return " | ".join(parts)


class TalosCtlNotFoundError(NetexError):
    """Raised when the talosctl binary is not found on PATH.

    Provides installation instructions so the operator can resolve
    the issue without searching documentation.
    """

    INSTALL_HINT: ClassVar[str] = (
        "Install talosctl: brew install siderolabs/tap/talosctl "
        "or see https://www.talos.dev/latest/talos-guides/install/talosctl/"
    )

    def __init__(
        self,
        message: str = "talosctl binary not found on PATH",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=None,
            endpoint=None,
            retry_hint=self.INSTALL_HINT,
            details=details,
        )


# ---------------------------------------------------------------------------
# Output parse errors
# ---------------------------------------------------------------------------


class ConfigParseError(NetexError):
    """Raised when talosctl output cannot be parsed into the expected structure.

    This typically means the JSON output mode returned invalid JSON, or a
    text-mode command returned output in an unexpected format (possibly
    due to version differences).

    Parameters
    ----------
    message:
        Human-readable description.
    command:
        The talosctl command whose output could not be parsed.
    raw_output:
        The raw output that failed to parse.
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
            endpoint=None,
            retry_hint="Check talosctl version compatibility (TQ3)",
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
    not an error returned by talosctl.
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

    The safety gate enforces preconditions before any write can proceed:

    1. The ``TALOS_WRITE_ENABLED`` env var must be ``"true"``.
    2. The ``--apply`` flag must be present in the command invocation.
    3. For reset: the ``--reset-node`` flag must be present (TD9).
    4. For bootstrap: etcd must not already have members (TD5).

    Parameters
    ----------
    message:
        Human-readable description.
    reason:
        Why the write was blocked.
    """

    _REASON_MESSAGES: ClassVar[dict[WriteGateReason, str]] = {
        WriteGateReason.ENV_VAR_DISABLED: (
            "Set TALOS_WRITE_ENABLED=true to allow write operations"
        ),
        WriteGateReason.APPLY_FLAG_MISSING: (
            "Add the --apply flag to execute write operations"
        ),
        WriteGateReason.RESET_FLAG_MISSING: (
            "Add the --reset-node flag to confirm node reset (this is destructive)"
        ),
        WriteGateReason.BOOTSTRAP_BLOCKED: (
            "etcd cluster already exists — bootstrap is a one-time operation"
        ),
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
