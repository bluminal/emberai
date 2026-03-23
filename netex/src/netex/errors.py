# SPDX-License-Identifier: MIT
"""Structured error hierarchy for the netex umbrella plugin.

All errors carry structured context beyond a plain message string, enabling
programmatic inspection by callers (retry logic, user-facing formatting,
logging) without parsing message text.

Hierarchy
---------
::

    NetexError (base)
    +-- PluginNotFoundError    # Required vendor plugin is not installed
    +-- ContractViolationError # Plugin fails contract validation
    +-- WorkflowError          # Workflow state machine violation
    +-- ValidationError        # Invalid input or schema mismatch
    +-- WriteGateError         # Write operation blocked by safety gate

Every error inherits the following structured fields from ``NetexError``:

* ``status_code``   -- HTTP status code when applicable.
* ``endpoint``      -- The API endpoint that produced the error.
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


# ---------------------------------------------------------------------------
# Base error
# ---------------------------------------------------------------------------

class NetexError(Exception):
    """Base exception for all netex umbrella plugin errors.

    Parameters
    ----------
    message:
        Human-readable description of what went wrong.
    status_code:
        HTTP status code, if the error originated from an HTTP response.
    endpoint:
        API endpoint path.
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
# Plugin not found
# ---------------------------------------------------------------------------

class PluginNotFoundError(NetexError):
    """Raised when a required vendor plugin is not installed.

    Parameters
    ----------
    message:
        Human-readable description.
    plugin_name:
        Name of the missing plugin (e.g. ``"opnsense"``).
    required_role:
        The role that was being queried (e.g. ``"gateway"``).
    required_skill:
        The skill that was being queried (e.g. ``"firewall"``).
    """

    def __init__(
        self,
        message: str,
        *,
        plugin_name: str | None = None,
        required_role: str | None = None,
        required_skill: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra_details: dict[str, Any] = {}
        if plugin_name is not None:
            extra_details["plugin_name"] = plugin_name
        if required_role is not None:
            extra_details["required_role"] = required_role
        if required_skill is not None:
            extra_details["required_skill"] = required_skill
        if details:
            extra_details.update(details)

        super().__init__(
            message,
            status_code=None,
            endpoint=None,
            retry_hint="Install the missing plugin and restart netex",
            details=extra_details or None,
        )
        self.plugin_name = plugin_name
        self.required_role = required_role
        self.required_skill = required_skill


# ---------------------------------------------------------------------------
# Contract violation
# ---------------------------------------------------------------------------

class ContractViolationError(NetexError):
    """Raised when a plugin fails Vendor Plugin Contract validation.

    Parameters
    ----------
    message:
        Human-readable description.
    plugin_name:
        Name of the plugin that violates the contract.
    violations:
        List of specific contract violations found.
    """

    def __init__(
        self,
        message: str,
        *,
        plugin_name: str | None = None,
        violations: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra_details: dict[str, Any] = {}
        if plugin_name is not None:
            extra_details["plugin_name"] = plugin_name
        if violations is not None:
            extra_details["violations"] = violations
        if details:
            extra_details.update(details)

        super().__init__(
            message,
            status_code=None,
            endpoint=None,
            retry_hint="Fix the contract violations and reinstall the plugin",
            details=extra_details or None,
        )
        self.plugin_name = plugin_name
        self.violations = violations or []


# ---------------------------------------------------------------------------
# Workflow error
# ---------------------------------------------------------------------------

class WorkflowError(NetexError):
    """Raised when a workflow state machine transition is invalid.

    Parameters
    ----------
    message:
        Human-readable description.
    workflow_id:
        Identifier of the workflow instance.
    current_state:
        The state the workflow was in when the error occurred.
    attempted_state:
        The state that was attempted but is not a valid transition.
    """

    def __init__(
        self,
        message: str,
        *,
        workflow_id: str | None = None,
        current_state: str | None = None,
        attempted_state: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra_details: dict[str, Any] = {}
        if workflow_id is not None:
            extra_details["workflow_id"] = workflow_id
        if current_state is not None:
            extra_details["current_state"] = current_state
        if attempted_state is not None:
            extra_details["attempted_state"] = attempted_state
        if details:
            extra_details.update(details)

        super().__init__(
            message,
            status_code=None,
            endpoint=None,
            retry_hint=None,
            details=extra_details or None,
        )
        self.workflow_id = workflow_id
        self.current_state = current_state
        self.attempted_state = attempted_state


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationError(NetexError):
    """Raised when input validation or schema conformance fails.

    This is a *client-side* validation error (bad input from the caller),
    not an API-returned validation error.
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

    Parameters
    ----------
    message:
        Human-readable description.
    reason:
        Why the write was blocked.
    """

    _REASON_MESSAGES: ClassVar[dict[WriteGateReason, str]] = {
        WriteGateReason.ENV_VAR_DISABLED: (
            "Set NETEX_WRITE_ENABLED=true to allow write operations"
        ),
        WriteGateReason.APPLY_FLAG_MISSING: (
            "Add the --apply flag to execute write operations"
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
