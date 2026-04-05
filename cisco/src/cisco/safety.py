"""Write safety gate for the Cisco plugin.

Implements steps 1 and 2 of the three-step write safety gate defined in
PRD Section 6.2:

    1. Env var gate -- The environment variable ``CISCO_WRITE_ENABLED``
       must be explicitly set to ``"true"`` (case-insensitive).
    2. Apply flag gate -- The command/tool call must include ``apply=True``
       as a keyword argument.
    3. Operator confirmation -- The operator must confirm the presented
       change plan in the Claude conversation.  **This step is NOT handled
       here.**  It is the responsibility of the agent/command layer.

Unlike OPNsense, the Cisco SG-300 applies configuration changes immediately
when commands are issued via CLI, so there is no separate ``reconfigure_gate``.
The write gate is the single safety boundary.

Usage::

    from cisco.safety import write_gate

    @write_gate("CISCO")
    async def set_port_vlan(port: str, vlan_id: int, *, apply: bool = False) -> dict:
        ...  # configures port VLAN assignment via SSH
"""

from __future__ import annotations

import functools
import inspect
import os
from enum import StrEnum
from typing import TYPE_CHECKING, ParamSpec, TypeVar

from cisco.errors import WriteGateError, WriteGateReason

if TYPE_CHECKING:
    from collections.abc import Callable

P = ParamSpec("P")
T = TypeVar("T")


class WriteBlockReason(StrEnum):
    """Machine-readable reasons why a write operation was blocked."""

    ENV_VAR_DISABLED = "env_var_disabled"
    APPLY_FLAG_MISSING = "apply_flag_missing"


def _env_var_name(plugin_name: str) -> str:
    """Return the write-enable environment variable name for a plugin."""
    return f"{plugin_name}_WRITE_ENABLED"


def check_write_enabled(plugin_name: str = "CISCO") -> bool:
    """Check if writes are enabled for the given plugin.

    Returns ``True`` if the environment variable ``{plugin_name}_WRITE_ENABLED``
    is set to ``"true"`` (case-insensitive).  Returns ``False`` otherwise.

    This is a non-throwing convenience check for use in plan-only code paths
    that need to know whether writes *could* proceed without actually
    attempting one.

    Args:
        plugin_name: The uppercase plugin name (e.g. ``"CISCO"``).

    Returns:
        Whether writes are enabled for the plugin.
    """
    env_var = _env_var_name(plugin_name)
    return os.environ.get(env_var, "").lower() == "true"


def describe_write_status(plugin_name: str = "CISCO") -> str:
    """Return a human-readable description of the current write status.

    Used in plan-only mode to explain to the operator why writes are
    disabled and what they need to do to enable them.

    Args:
        plugin_name: The uppercase plugin name (e.g. ``"CISCO"``).

    Returns:
        A human-readable status message.
    """
    env_var = _env_var_name(plugin_name)
    if check_write_enabled(plugin_name):
        return "Write operations are enabled. Use --apply flag to execute changes."
    return f"Write operations are disabled. Set {env_var}=true to enable."


def write_gate(plugin_name: str = "CISCO") -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator that enforces the write safety gate (steps 1 and 2).

    Wraps an async function and checks two conditions before allowing
    execution:

    1. **Env var gate** -- ``{plugin_name}_WRITE_ENABLED`` must be set to
       ``"true"`` in the environment (case-insensitive).
    2. **Apply flag gate** -- The decorated function must be called with
       ``apply=True`` as a keyword argument.

    If either check fails, raises :class:`WriteGateError` with a structured
    ``reason`` field (a :class:`WriteBlockReason` value) so callers can
    programmatically distinguish the failure mode.

    Step 3 (operator confirmation) is **not** enforced here -- that is the
    responsibility of the agent/command layer.

    The checks are evaluated in order: env var first, then apply flag.
    This means if the env var is disabled, the error will always report
    ``ENV_VAR_DISABLED`` regardless of the apply flag value.

    Args:
        plugin_name: The uppercase plugin name used to construct the
            environment variable name (e.g. ``"CISCO"`` ->
            ``CISCO_WRITE_ENABLED``).

    Returns:
        A decorator that enforces the write safety gate.

    Raises:
        WriteGateError: If either the env var or apply flag check fails.

    Usage::

        @write_gate("CISCO")
        async def set_port_vlan(port: str, vlan_id: int, *, apply: bool = False):
            ...

        # Calling without apply raises WriteGateError:
        await set_port_vlan("gi1", 100)

        # Calling with apply=True but env var disabled raises WriteGateError:
        await set_port_vlan("gi1", 100, apply=True)

        # Both checks pass -- function executes:
        # (with CISCO_WRITE_ENABLED=true in environment)
        await set_port_vlan("gi1", 100, apply=True)
    """
    env_var = _env_var_name(plugin_name)

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        # Fail fast at decoration time if the decorated function
        # doesn't have 'apply' as a keyword-only parameter.
        sig = inspect.signature(func)
        apply_param = sig.parameters.get("apply")
        if apply_param is None or apply_param.kind != inspect.Parameter.KEYWORD_ONLY:
            raise TypeError(
                f"@write_gate requires '{func.__name__}' to have "
                f"'apply' as a keyword-only parameter"
            )

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Step 1: Check environment variable
            if not check_write_enabled(plugin_name):
                raise WriteGateError(
                    f"Write operations are disabled for {plugin_name}. "
                    f"Set {env_var}=true to enable.",
                    reason=WriteGateReason.ENV_VAR_DISABLED,
                    plugin_name=plugin_name,
                    env_var=env_var,
                )

            # Step 2: Check --apply flag
            apply = kwargs.get("apply", False)
            if not apply:
                raise WriteGateError(
                    "Write operations require the --apply flag. "
                    "Without --apply, this command runs in plan-only mode.",
                    reason=WriteGateReason.APPLY_FLAG_MISSING,
                    plugin_name=plugin_name,
                    env_var=env_var,
                )

            # Both gates passed -- execute the wrapped function
            return await func(*args, **kwargs)  # type: ignore[misc, no-any-return]

        return wrapper  # type: ignore[return-value]

    return decorator
