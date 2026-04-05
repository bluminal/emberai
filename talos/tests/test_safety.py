"""Tests for the Talos plugin write safety gate.

Covers:
- write_gate decorator: env var enabled/disabled, --apply present/missing
- reset_gate decorator: --reset-node flag present/missing
- bootstrap_gate decorator: etcd members exist/empty
- check_write_enabled: non-throwing boolean check
- describe_write_status: human-readable messages
- Error structure: reason, plugin_name, env_var fields
- Decorator preserves function metadata (functools.wraps)
- Decorator requires keyword-only parameters
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from talos.errors import WriteGateError, WriteGateReason
from talos.safety import (
    bootstrap_gate,
    check_write_enabled,
    describe_write_status,
    reset_gate,
    write_gate,
)

# ---------------------------------------------------------------------------
# Fixtures -- sample decorated functions
# ---------------------------------------------------------------------------


@write_gate("TALOS")
async def sample_write_tool(name: str, *, apply: bool = False) -> dict[str, str]:
    """A sample write tool for testing the write gate."""
    return {"applied": name}


@write_gate("TALOS")
async def sample_tool_no_args(*, apply: bool = False) -> str:
    """A sample write tool with no positional arguments."""
    return "done"


@reset_gate
@write_gate("TALOS")
async def sample_reset_tool(
    node: str, *, apply: bool = False, reset_node: bool = False
) -> str:
    """A sample reset tool for testing the reset gate."""
    return f"reset {node}"


@bootstrap_gate
@write_gate("TALOS")
async def sample_bootstrap_tool(
    node: str, *, apply: bool = False, etcd_members_count: int = 0
) -> str:
    """A sample bootstrap tool for testing the bootstrap gate."""
    return f"bootstrapped {node}"


# ---------------------------------------------------------------------------
# check_write_enabled
# ---------------------------------------------------------------------------


class TestCheckWriteEnabled:
    """Non-throwing check for write-enabled status."""

    def test_returns_true_when_enabled(self) -> None:
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            assert check_write_enabled("TALOS") is True

    def test_returns_true_case_insensitive(self) -> None:
        for value in ("true", "True", "TRUE", "tRuE"):
            with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": value}):
                assert check_write_enabled("TALOS") is True, f"Failed for value: {value}"

    def test_returns_false_when_disabled(self) -> None:
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "false"}):
            assert check_write_enabled("TALOS") is False

    def test_returns_false_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert check_write_enabled("TALOS") is False

    def test_returns_false_when_empty(self) -> None:
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": ""}):
            assert check_write_enabled("TALOS") is False

    def test_returns_false_for_non_true_values(self) -> None:
        for value in ("1", "yes", "on", "enabled", "truee", " true"):
            with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": value}):
                assert check_write_enabled("TALOS") is False, (
                    f"Should be False for value: {value!r}"
                )

    def test_default_plugin_name_is_talos(self) -> None:
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            assert check_write_enabled() is True


# ---------------------------------------------------------------------------
# describe_write_status
# ---------------------------------------------------------------------------


class TestDescribeWriteStatus:
    """Human-readable write status messages."""

    def test_disabled_message(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            msg = describe_write_status("TALOS")
            assert "disabled" in msg.lower()
            assert "TALOS_WRITE_ENABLED" in msg

    def test_enabled_message(self) -> None:
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            msg = describe_write_status("TALOS")
            assert "enabled" in msg.lower()
            assert "--apply" in msg

    def test_default_plugin_name_is_talos(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            msg = describe_write_status()
            assert "TALOS_WRITE_ENABLED" in msg


# ---------------------------------------------------------------------------
# write_gate decorator -- env var check (step 1)
# ---------------------------------------------------------------------------


class TestWriteGateEnvVar:
    """Step 1: environment variable gate."""

    @pytest.mark.asyncio
    async def test_write_gate_blocks_when_env_disabled(self) -> None:
        """TALOS_WRITE_ENABLED not set -> WriteGateError with ENV_VAR_DISABLED."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED
            assert exc_info.value.plugin_name == "TALOS"
            assert exc_info.value.env_var == "TALOS_WRITE_ENABLED"

    @pytest.mark.asyncio
    async def test_raises_when_env_var_false(self) -> None:
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "false"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_raises_when_env_var_empty(self) -> None:
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": ""}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_error_message_includes_env_var_name(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError, match="TALOS_WRITE_ENABLED"),
        ):
            await sample_write_tool("test", apply=True)

    @pytest.mark.asyncio
    async def test_env_var_takes_priority_over_apply_flag(self) -> None:
        """When env var is disabled, error is ENV_VAR_DISABLED even if apply=False."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=False)
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED


# ---------------------------------------------------------------------------
# write_gate decorator -- apply flag check (step 2)
# ---------------------------------------------------------------------------


class TestWriteGateApplyFlag:
    """Step 2: --apply flag gate."""

    @pytest.mark.asyncio
    async def test_write_gate_blocks_when_apply_missing(self) -> None:
        """Env set but apply=False -> WriteGateError with APPLY_FLAG_MISSING."""
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=False)
            assert exc_info.value.reason == WriteGateReason.APPLY_FLAG_MISSING
            assert exc_info.value.plugin_name == "TALOS"

    @pytest.mark.asyncio
    async def test_raises_when_apply_not_provided(self) -> None:
        """apply defaults to False, so omitting it should block."""
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test")
            assert exc_info.value.reason == WriteGateReason.APPLY_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_error_message_mentions_apply(self) -> None:
        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            pytest.raises(WriteGateError, match="--apply"),
        ):
            await sample_write_tool("test")


# ---------------------------------------------------------------------------
# write_gate decorator -- both gates pass
# ---------------------------------------------------------------------------


class TestWriteGateSuccess:
    """Both gates pass -- the wrapped function executes."""

    @pytest.mark.asyncio
    async def test_write_gate_passes(self) -> None:
        """Both env and apply=True -> function executes."""
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            result = await sample_write_tool("my-config", apply=True)
            assert result == {"applied": "my-config"}

    @pytest.mark.asyncio
    async def test_env_var_case_insensitive(self) -> None:
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "True"}):
            result = await sample_write_tool("test", apply=True)
            assert result == {"applied": "test"}

    @pytest.mark.asyncio
    async def test_no_positional_args(self) -> None:
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            result = await sample_tool_no_args(apply=True)
            assert result == "done"


# ---------------------------------------------------------------------------
# write_gate decorator -- requires keyword-only apply parameter
# ---------------------------------------------------------------------------


class TestWriteGateRequiresApply:
    """Decorator fails at decoration time on bad function signature."""

    def test_write_gate_requires_keyword_only_apply(self) -> None:
        """Decorating a function without keyword-only ``apply`` raises TypeError."""
        with pytest.raises(TypeError, match="apply"):

            @write_gate("TALOS")
            async def bad_tool(name: str) -> str:
                return name

    def test_positional_apply_rejected(self) -> None:
        """apply as a positional argument (not keyword-only) is rejected."""
        with pytest.raises(TypeError, match="apply"):

            @write_gate("TALOS")
            async def bad_tool(apply: bool = False) -> str:
                return "x"


# ---------------------------------------------------------------------------
# write_gate decorator -- metadata preservation
# ---------------------------------------------------------------------------


class TestWriteGateMetadata:
    """The decorator preserves function metadata via functools.wraps."""

    def test_preserves_function_name(self) -> None:
        assert sample_write_tool.__name__ == "sample_write_tool"

    def test_preserves_docstring(self) -> None:
        assert sample_write_tool.__doc__ is not None
        assert "sample write tool" in sample_write_tool.__doc__.lower()

    def test_preserves_module(self) -> None:
        assert sample_write_tool.__module__ == __name__


# ---------------------------------------------------------------------------
# reset_gate -- reset-node flag check
# ---------------------------------------------------------------------------


class TestResetGate:
    """Reset gate: requires --reset-node flag for destructive operations."""

    @pytest.mark.asyncio
    async def test_blocks_when_reset_node_missing(self) -> None:
        """reset_node=False -> WriteGateError with RESET_FLAG_MISSING."""
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_reset_tool("192.168.30.11", apply=True, reset_node=False)
            assert exc_info.value.reason == WriteGateReason.RESET_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_blocks_when_reset_node_not_provided(self) -> None:
        """reset_node defaults to False, so omitting it should block."""
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_reset_tool("192.168.30.11", apply=True)
            assert exc_info.value.reason == WriteGateReason.RESET_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_passes_when_reset_node_true(self) -> None:
        """reset_node=True -> function executes."""
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            result = await sample_reset_tool(
                "192.168.30.11", apply=True, reset_node=True
            )
            assert result == "reset 192.168.30.11"

    @pytest.mark.asyncio
    async def test_error_message_mentions_reset_node(self) -> None:
        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            pytest.raises(WriteGateError, match="--reset-node"),
        ):
            await sample_reset_tool("192.168.30.11", apply=True, reset_node=False)

    @pytest.mark.asyncio
    async def test_error_message_mentions_irreversible(self) -> None:
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_reset_tool("192.168.30.11", apply=True, reset_node=False)
            assert "irreversible" in str(exc_info.value.message).lower()

    def test_requires_keyword_only_reset_node(self) -> None:
        """Decorating a function without keyword-only reset_node raises TypeError."""
        with pytest.raises(TypeError, match="reset_node"):

            @reset_gate
            async def bad_tool(reset_node: bool = False) -> str:
                return "x"


# ---------------------------------------------------------------------------
# bootstrap_gate -- etcd existence check
# ---------------------------------------------------------------------------


class TestBootstrapGate:
    """Bootstrap gate: blocks if etcd members already exist."""

    @pytest.mark.asyncio
    async def test_blocks_when_etcd_members_exist(self) -> None:
        """etcd_members_count > 0 -> WriteGateError with BOOTSTRAP_BLOCKED."""
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_bootstrap_tool(
                    "192.168.30.11", apply=True, etcd_members_count=3
                )
            assert exc_info.value.reason == WriteGateReason.BOOTSTRAP_BLOCKED

    @pytest.mark.asyncio
    async def test_blocks_with_single_member(self) -> None:
        """Even a single etcd member should block bootstrap."""
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_bootstrap_tool(
                    "192.168.30.11", apply=True, etcd_members_count=1
                )
            assert exc_info.value.reason == WriteGateReason.BOOTSTRAP_BLOCKED

    @pytest.mark.asyncio
    async def test_passes_when_no_etcd_members(self) -> None:
        """etcd_members_count=0 -> function executes."""
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            result = await sample_bootstrap_tool(
                "192.168.30.11", apply=True, etcd_members_count=0
            )
            assert result == "bootstrapped 192.168.30.11"

    @pytest.mark.asyncio
    async def test_passes_when_etcd_members_count_not_provided(self) -> None:
        """Default is 0, so omitting etcd_members_count should proceed."""
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            result = await sample_bootstrap_tool("192.168.30.11", apply=True)
            assert result == "bootstrapped 192.168.30.11"

    @pytest.mark.asyncio
    async def test_error_message_mentions_bootstrap(self) -> None:
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_bootstrap_tool(
                    "192.168.30.11", apply=True, etcd_members_count=3
                )
            assert "bootstrap" in str(exc_info.value.message).lower()

    @pytest.mark.asyncio
    async def test_error_message_includes_member_count(self) -> None:
        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_bootstrap_tool(
                    "192.168.30.11", apply=True, etcd_members_count=3
                )
            assert "3" in str(exc_info.value.message)

    def test_requires_keyword_only_etcd_members_count(self) -> None:
        """Decorating without keyword-only etcd_members_count raises TypeError."""
        with pytest.raises(TypeError, match="etcd_members_count"):

            @bootstrap_gate
            async def bad_tool(etcd_members_count: int = 0) -> str:
                return "x"
