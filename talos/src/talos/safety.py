"""Write safety gate for the Talos plugin.

Implements steps 1 and 2 of the three-step write safety gate defined in
PRD Section 6.2:

    1. Env var gate -- ``TALOS_WRITE_ENABLED`` must be ``"true"``.
    2. Apply flag gate -- ``apply=True`` must be passed.
    3. Operator confirmation -- handled by the agent/command layer.

Additionally provides Talos-specific safety gates:

    - ``reset_gate`` -- Requires an extra ``reset_node=True`` flag for
      the destructive ``talosctl reset`` operation (TD9).
    - ``bootstrap_gate`` -- Blocks if etcd already has members, preventing
      the catastrophic mistake of bootstrapping twice (TD5).

Usage::

    from talos.safety import write_gate, reset_gate, bootstrap_gate

    @write_gate("TALOS")
    async def apply_config(node: str, config_file: str, *, apply: bool = False):
        ...

    @reset_gate
    @write_gate("TALOS")
    async def reset_node(node: str, *, apply: bool = False, reset_node: bool = False):
        ...
"""

from __future__ import annotations

import functools
import inspect
import os
from typing import TYPE_CHECKING, ParamSpec, TypeVar

from talos.errors import WriteGateError, WriteGateReason

if TYPE_CHECKING:
    from collections.abc import Callable

P = ParamSpec("P")
T = TypeVar("T")


def _env_var_name(plugin_name: str) -> str:
    """Return the write-enable environment variable name for a plugin."""
    return f"{plugin_name}_WRITE_ENABLED"


def check_write_enabled(plugin_name: str = "TALOS") -> bool:
    """Check if writes are enabled for the given plugin.

    Returns ``True`` if ``{plugin_name}_WRITE_ENABLED`` is ``"true"``
    (case-insensitive).
    """
    env_var = _env_var_name(plugin_name)
    return os.environ.get(env_var, "").lower() == "true"


def describe_write_status(plugin_name: str = "TALOS") -> str:
    """Return a human-readable description of the current write status."""
    env_var = _env_var_name(plugin_name)
    if check_write_enabled(plugin_name):
        return "Write operations are enabled. Use --apply flag to execute changes."
    return f"Write operations are disabled. Set {env_var}=true to enable."


def write_gate(plugin_name: str = "TALOS") -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator that enforces the write safety gate (steps 1 and 2).

    Checks two conditions before allowing execution:

    1. ``{plugin_name}_WRITE_ENABLED`` env var must be ``"true"``.
    2. ``apply=True`` must be passed as a keyword argument.

    Raises :class:`WriteGateError` if either check fails.
    """
    env_var = _env_var_name(plugin_name)

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
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

            return await func(*args, **kwargs)  # type: ignore[misc, no-any-return]

        return wrapper  # type: ignore[return-value]

    return decorator


def reset_gate(func: Callable[P, T]) -> Callable[P, T]:
    """Decorator that enforces the extra reset safety flag (TD9).

    ``talosctl reset`` wipes a node completely -- OS, data, and cluster
    membership. This decorator requires ``reset_node=True`` as an extra
    confirmation beyond the standard write gate.

    Must be applied **outside** (above) ``@write_gate`` so the reset flag
    check runs first::

        @reset_gate
        @write_gate("TALOS")
        async def reset(node: str, *, apply: bool = False, reset_node: bool = False):
            ...
    """
    sig = inspect.signature(func)
    reset_param = sig.parameters.get("reset_node")
    if reset_param is None or reset_param.kind != inspect.Parameter.KEYWORD_ONLY:
        raise TypeError(
            f"@reset_gate requires '{func.__name__}' to have "
            f"'reset_node' as a keyword-only parameter"
        )

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        reset_node = kwargs.get("reset_node", False)
        if not reset_node:
            raise WriteGateError(
                "Node reset requires the --reset-node flag. "
                "This operation wipes all data, OS state, and cluster membership. "
                "It is irreversible.",
                reason=WriteGateReason.RESET_FLAG_MISSING,
                plugin_name="TALOS",
                env_var="TALOS_WRITE_ENABLED",
            )

        return await func(*args, **kwargs)  # type: ignore[misc, no-any-return]

    return wrapper  # type: ignore[return-value]


def bootstrap_gate(func: Callable[P, T]) -> Callable[P, T]:
    """Decorator that blocks bootstrap if etcd already has members (TD5).

    ``talosctl bootstrap`` initializes etcd. Running it twice on an
    existing cluster corrupts etcd and destroys the cluster. This
    decorator checks a pre-flight ``etcd_members_count`` keyword
    argument and blocks if etcd members already exist.

    The caller is responsible for querying ``talosctl etcd members``
    beforehand and passing the result count::

        @bootstrap_gate
        @write_gate("TALOS")
        async def bootstrap(
            node: str,
            *,
            apply: bool = False,
            etcd_members_count: int = 0,
        ):
            ...
    """
    sig = inspect.signature(func)
    count_param = sig.parameters.get("etcd_members_count")
    if count_param is None or count_param.kind != inspect.Parameter.KEYWORD_ONLY:
        raise TypeError(
            f"@bootstrap_gate requires '{func.__name__}' to have "
            f"'etcd_members_count' as a keyword-only parameter"
        )

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        etcd_members_count = kwargs.get("etcd_members_count", 0)
        if etcd_members_count > 0:
            raise WriteGateError(
                f"etcd cluster already exists with {etcd_members_count} member(s). "
                "Bootstrap is a one-time operation. Running it again will corrupt "
                "the cluster and cause data loss.",
                reason=WriteGateReason.BOOTSTRAP_BLOCKED,
                plugin_name="TALOS",
                env_var="TALOS_WRITE_ENABLED",
            )

        return await func(*args, **kwargs)  # type: ignore[misc, no-any-return]

    return wrapper  # type: ignore[return-value]
