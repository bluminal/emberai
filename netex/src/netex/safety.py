"""Write safety gate for the netex umbrella plugin.

Implements steps 1 and 2 of the three-step write safety gate defined in
PRD Section 6.2:

    1. Env var gate -- The environment variable ``{PLUGIN}_WRITE_ENABLED``
       must be explicitly set to ``"true"`` (case-insensitive).
    2. Apply flag gate -- The command/tool call must include ``apply=True``
       as a keyword argument.
    3. Operator confirmation -- Handled by the agent/command layer.

Usage::

    from netex.safety import write_gate

    @write_gate("NETEX")
    async def provision_vlan(name: str, *, apply: bool = False) -> dict:
        ...  # write logic here
"""

from __future__ import annotations

import functools
import os
from enum import StrEnum
from typing import TYPE_CHECKING, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

from netex.errors import WriteGateError

P = ParamSpec("P")
T = TypeVar("T")


class WriteBlockReason(StrEnum):
    """Machine-readable reasons why a write operation was blocked."""

    ENV_VAR_DISABLED = "env_var_disabled"
    APPLY_FLAG_MISSING = "apply_flag_missing"


def _env_var_name(plugin_name: str) -> str:
    """Return the write-enable environment variable name for a plugin."""
    return f"{plugin_name}_WRITE_ENABLED"


def check_write_enabled(plugin_name: str = "NETEX") -> bool:
    """Check if writes are enabled for the given plugin.

    Returns ``True`` if the environment variable ``{plugin_name}_WRITE_ENABLED``
    is set to ``"true"`` (case-insensitive).  Returns ``False`` otherwise.
    """
    env_var = _env_var_name(plugin_name)
    return os.environ.get(env_var, "").lower() == "true"


def describe_write_status(plugin_name: str = "NETEX") -> str:
    """Return a human-readable description of the current write status."""
    env_var = _env_var_name(plugin_name)
    if check_write_enabled(plugin_name):
        return "Write operations are enabled. Use --apply flag to execute changes."
    return f"Write operations are disabled. Set {env_var}=true to enable."


def write_gate(plugin_name: str = "NETEX") -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator that enforces the write safety gate (steps 1 and 2).

    Wraps an async function and checks two conditions before allowing
    execution:

    1. ``{plugin_name}_WRITE_ENABLED`` must be set to ``"true"``.
    2. The decorated function must be called with ``apply=True``.

    If either check fails, raises :class:`WriteGateError`.
    """
    env_var = _env_var_name(plugin_name)

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:  # type: ignore[misc]
            # Step 1: Check environment variable
            if not check_write_enabled(plugin_name):
                raise WriteGateError(
                    f"Write operations are disabled for {plugin_name}. "
                    f"Set {env_var}=true to enable.",
                    reason=WriteBlockReason.ENV_VAR_DISABLED,
                    plugin_name=plugin_name,
                    env_var=env_var,
                )

            # Step 2: Check --apply flag
            apply = kwargs.get("apply", False)
            if not apply:
                raise WriteGateError(
                    "Write operations require the --apply flag. "
                    "Without --apply, this command runs in plan-only mode.",
                    reason=WriteBlockReason.APPLY_FLAG_MISSING,
                    plugin_name=plugin_name,
                    env_var=env_var,
                )

            # Both gates passed -- execute the wrapped function
            return await func(*args, **kwargs)  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
