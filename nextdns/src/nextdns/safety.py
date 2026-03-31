"""Write safety gate for the NextDNS plugin.

Implements steps 1 and 2 of the three-step write safety gate defined in
PRD Section 6.2:

    1. Env var gate -- The environment variable ``{PLUGIN}_WRITE_ENABLED``
       must be explicitly set to ``"true"`` (case-insensitive).
    2. Apply flag gate -- The command/tool call must include ``apply=True``
       as a keyword argument.
    3. Operator confirmation -- The operator must confirm the presented
       change plan in the Claude conversation.  **This step is NOT handled
       here.**  It is the responsibility of the agent/command layer
       (see ``nextdns.ask`` and the orchestrator).

All write operations across all Netex plugins (unifi, opnsense, nextdns, netex)
follow this same gate pattern.  Each plugin implements its own copy of this
module (no shared code between plugins -- see Decision D5/D8 in the
implementation plan).

In addition to the standard write gate, the NextDNS plugin adds two
extra safety decorators for destructive DNS operations (Decision D18):

- ``delete_profile_gate`` -- requires ``--delete-profile`` flag for profile
  deletion, protecting against accidental removal of entire DNS profiles.
- ``clear_logs_gate`` -- requires ``--clear-logs`` flag for log clearing,
  protecting against accidental loss of DNS query history.

Usage::

    from nextdns.safety import write_gate, delete_profile_gate, clear_logs_gate

    @write_gate("NEXTDNS")
    async def update_profile(profile_id: str, *, apply: bool = False) -> dict:
        ...  # write logic here

    @delete_profile_gate
    async def delete_profile(profile_id: str, *, apply: bool = False,
                             delete_profile: bool = False) -> dict:
        ...  # deletion logic here

    @clear_logs_gate
    async def clear_logs(profile_id: str, *, apply: bool = False,
                         clear_logs: bool = False) -> dict:
        ...  # log clearing logic here
"""

from __future__ import annotations

import functools
import inspect
import os
from enum import StrEnum
from typing import TYPE_CHECKING, ParamSpec, TypeVar

from nextdns.errors import WriteGateError, WriteGateReason

if TYPE_CHECKING:
    from collections.abc import Callable

P = ParamSpec("P")
T = TypeVar("T")


class WriteBlockReason(StrEnum):
    """Machine-readable reasons why a write operation was blocked."""

    ENV_VAR_DISABLED = "env_var_disabled"
    APPLY_FLAG_MISSING = "apply_flag_missing"
    DELETE_FLAG_MISSING = "delete_flag_missing"
    CLEAR_LOGS_FLAG_MISSING = "clear_logs_flag_missing"


def _env_var_name(plugin_name: str) -> str:
    """Return the write-enable environment variable name for a plugin."""
    return f"{plugin_name}_WRITE_ENABLED"


def check_write_enabled(plugin_name: str = "NEXTDNS") -> bool:
    """Check if writes are enabled for the given plugin.

    Returns ``True`` if the environment variable ``{plugin_name}_WRITE_ENABLED``
    is set to ``"true"`` (case-insensitive).  Returns ``False`` otherwise.

    This is a non-throwing convenience check for use in plan-only code paths
    that need to know whether writes *could* proceed without actually
    attempting one.

    Args:
        plugin_name: The uppercase plugin name (e.g. ``"NEXTDNS"``).

    Returns:
        Whether writes are enabled for the plugin.
    """
    env_var = _env_var_name(plugin_name)
    return os.environ.get(env_var, "").lower() == "true"


def describe_write_status(plugin_name: str = "NEXTDNS") -> str:
    """Return a human-readable description of the current write status.

    Used in plan-only mode to explain to the operator why writes are
    disabled and what they need to do to enable them.

    Args:
        plugin_name: The uppercase plugin name (e.g. ``"NEXTDNS"``).

    Returns:
        A human-readable status message.
    """
    env_var = _env_var_name(plugin_name)
    if check_write_enabled(plugin_name):
        return "Write operations are enabled. Use --apply flag to execute changes."
    return f"Write operations are disabled. Set {env_var}=true to enable."


def write_gate(plugin_name: str = "NEXTDNS") -> Callable[[Callable[P, T]], Callable[P, T]]:
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
            environment variable name (e.g. ``"NEXTDNS"`` ->
            ``NEXTDNS_WRITE_ENABLED``).

    Returns:
        A decorator that enforces the write safety gate.

    Raises:
        WriteGateError: If either the env var or apply flag check fails.

    Usage::

        @write_gate("NEXTDNS")
        async def update_profile(profile_id: str, *, apply: bool = False):
            ...

        # Calling without apply raises WriteGateError:
        await update_profile("abc123")

        # Calling with apply=True but env var disabled raises WriteGateError:
        await update_profile("abc123", apply=True)

        # Both checks pass -- function executes:
        # (with NEXTDNS_WRITE_ENABLED=true in environment)
        await update_profile("abc123", apply=True)
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


def delete_profile_gate[**P, T](func: Callable[P, T]) -> Callable[P, T]:
    """Decorator that enforces the delete-profile safety gate (Decision D18).

    Wraps an async function and enforces all three conditions:

    1. **Standard write gate** -- env var + apply flag (delegated to
       ``write_gate("NEXTDNS")``).
    2. **Delete profile flag** -- The decorated function must be called with
       ``delete_profile=True`` as a keyword argument.

    The standard write gate checks run first. If those pass, the
    ``delete_profile`` flag is checked. This ensures the operator must
    explicitly confirm profile deletion beyond the normal write gate.

    The decorated function must have both ``apply`` and ``delete_profile``
    as keyword-only parameters.

    Raises:
        WriteGateError: If any of the three checks fail.
        TypeError: If the decorated function lacks required parameters.

    Usage::

        @delete_profile_gate
        async def delete_profile(profile_id: str, *, apply: bool = False,
                                 delete_profile: bool = False) -> dict:
            ...
    """
    # Validate the function signature at decoration time.
    sig = inspect.signature(func)
    delete_param = sig.parameters.get("delete_profile")
    if delete_param is None or delete_param.kind != inspect.Parameter.KEYWORD_ONLY:
        raise TypeError(
            f"@delete_profile_gate requires '{func.__name__}' to have "
            f"'delete_profile' as a keyword-only parameter"
        )

    # Apply the standard write gate first.
    write_gate("NEXTDNS")(func)

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        # Step 1 & 2: Standard write gate (env var + apply) -- delegated
        # to the inner gated_func. If it raises, we propagate.

        # Step 3: Check --delete-profile flag BEFORE calling gated_func,
        # but after verifying we would pass the write gate. We check the
        # write gate first by calling the gated function's checks inline.
        # Actually, we call gated_func which already does steps 1 & 2,
        # but we need to check delete_profile AFTER those pass. So we
        # check delete_profile first (since it's cheaper) and then
        # delegate to gated_func. Wait -- the spec says standard write
        # gate runs first. Let's run gated_func's checks by checking
        # env var and apply manually, then check delete_profile.

        env_var = _env_var_name("NEXTDNS")

        # Step 1: Check environment variable
        if not check_write_enabled("NEXTDNS"):
            raise WriteGateError(
                f"Write operations are disabled for NEXTDNS. Set {env_var}=true to enable.",
                reason=WriteGateReason.ENV_VAR_DISABLED,
                plugin_name="NEXTDNS",
                env_var=env_var,
            )

        # Step 2: Check --apply flag
        apply = kwargs.get("apply", False)
        if not apply:
            raise WriteGateError(
                "Write operations require the --apply flag. "
                "Without --apply, this command runs in plan-only mode.",
                reason=WriteGateReason.APPLY_FLAG_MISSING,
                plugin_name="NEXTDNS",
                env_var=env_var,
            )

        # Step 3: Check --delete-profile flag
        delete_profile = kwargs.get("delete_profile", False)
        if not delete_profile:
            raise WriteGateError(
                "Profile deletion requires the --delete-profile flag for safety.",
                reason=WriteGateReason.APPLY_FLAG_MISSING,
                plugin_name="NEXTDNS",
                env_var=env_var,
                details={"missing_flag": "delete_profile"},
            )

        # All gates passed -- execute the wrapped function directly
        return await func(*args, **kwargs)  # type: ignore[misc, no-any-return]

    return wrapper  # type: ignore[return-value]


def clear_logs_gate[**P, T](func: Callable[P, T]) -> Callable[P, T]:
    """Decorator that enforces the clear-logs safety gate (Decision D18).

    Wraps an async function and enforces all three conditions:

    1. **Standard write gate** -- env var + apply flag (delegated to
       ``write_gate("NEXTDNS")``).
    2. **Clear logs flag** -- The decorated function must be called with
       ``clear_logs=True`` as a keyword argument.

    The standard write gate checks run first. If those pass, the
    ``clear_logs`` flag is checked. This ensures the operator must
    explicitly confirm log clearing beyond the normal write gate.

    The decorated function must have both ``apply`` and ``clear_logs``
    as keyword-only parameters.

    Raises:
        WriteGateError: If any of the three checks fail.
        TypeError: If the decorated function lacks required parameters.

    Usage::

        @clear_logs_gate
        async def clear_logs(profile_id: str, *, apply: bool = False,
                             clear_logs: bool = False) -> dict:
            ...
    """
    # Validate the function signature at decoration time.
    sig = inspect.signature(func)
    clear_param = sig.parameters.get("clear_logs")
    if clear_param is None or clear_param.kind != inspect.Parameter.KEYWORD_ONLY:
        raise TypeError(
            f"@clear_logs_gate requires '{func.__name__}' to have "
            f"'clear_logs' as a keyword-only parameter"
        )

    # Validate that 'apply' is also present (required by write gate).
    apply_param = sig.parameters.get("apply")
    if apply_param is None or apply_param.kind != inspect.Parameter.KEYWORD_ONLY:
        raise TypeError(
            f"@clear_logs_gate requires '{func.__name__}' to have "
            f"'apply' as a keyword-only parameter"
        )

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        env_var = _env_var_name("NEXTDNS")

        # Step 1: Check environment variable
        if not check_write_enabled("NEXTDNS"):
            raise WriteGateError(
                f"Write operations are disabled for NEXTDNS. Set {env_var}=true to enable.",
                reason=WriteGateReason.ENV_VAR_DISABLED,
                plugin_name="NEXTDNS",
                env_var=env_var,
            )

        # Step 2: Check --apply flag
        apply = kwargs.get("apply", False)
        if not apply:
            raise WriteGateError(
                "Write operations require the --apply flag. "
                "Without --apply, this command runs in plan-only mode.",
                reason=WriteGateReason.APPLY_FLAG_MISSING,
                plugin_name="NEXTDNS",
                env_var=env_var,
            )

        # Step 3: Check --clear-logs flag
        clear_logs = kwargs.get("clear_logs", False)
        if not clear_logs:
            raise WriteGateError(
                "Log clearing requires the --clear-logs flag for safety.",
                reason=WriteGateReason.APPLY_FLAG_MISSING,
                plugin_name="NEXTDNS",
                env_var=env_var,
                details={"missing_flag": "clear_logs"},
            )

        # All gates passed -- execute the wrapped function directly
        return await func(*args, **kwargs)  # type: ignore[misc, no-any-return]

    return wrapper  # type: ignore[return-value]
