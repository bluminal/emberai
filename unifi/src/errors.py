"""Error hierarchy for the UniFi plugin.

Stub module providing WriteGateError for the safety module.
The full error hierarchy (NetexError -> AuthenticationError, RateLimitError,
NetworkError, APIError, ValidationError, WriteGateError) is implemented in
Task 6 and will replace this stub when branches are merged.
"""

from __future__ import annotations


class NetexError(Exception):
    """Base error for all Netex plugin errors."""

    def __init__(self, message: str, **context: object) -> None:
        self.message = message
        self.context = context
        super().__init__(message)


class WriteGateError(NetexError):
    """Raised when a write operation is blocked by the safety gate.

    Carries structured context including the block reason, plugin name,
    and the environment variable that controls write access.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        plugin_name: str,
        env_var: str,
    ) -> None:
        super().__init__(
            message,
            reason=reason,
            plugin_name=plugin_name,
            env_var=env_var,
        )
        self.reason = reason
        self.plugin_name = plugin_name
        self.env_var = env_var
