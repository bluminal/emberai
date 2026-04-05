"""Tests for the Cisco plugin write safety gate.

Covers:
- write_gate decorator: env var enabled/disabled, --apply present/missing
- check_write_enabled: non-throwing boolean check
- describe_write_status: human-readable messages
- Edge cases: case sensitivity, empty env var, unset env var
- Error structure: reason, plugin_name, env_var fields
- Decorator preserves function metadata (functools.wraps)
- Decorator requires keyword-only apply parameter
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from cisco.errors import WriteGateError, WriteGateReason
from cisco.safety import (
    WriteBlockReason,
    check_write_enabled,
    describe_write_status,
    write_gate,
)

# ---------------------------------------------------------------------------
# Fixtures -- sample decorated functions
# ---------------------------------------------------------------------------


@write_gate("CISCO")
async def sample_write_tool(name: str, *, apply: bool = False) -> dict[str, str]:
    """A sample write tool for testing the decorator."""
    return {"created": name}


@write_gate("CISCO")
async def sample_tool_no_args(*, apply: bool = False) -> str:
    """A sample write tool with no positional arguments."""
    return "done"


# ---------------------------------------------------------------------------
# WriteBlockReason enum
# ---------------------------------------------------------------------------


class TestWriteBlockReason:
    """Verify WriteBlockReason enum values are stable strings."""

    def test_env_var_disabled_value(self) -> None:
        assert WriteBlockReason.ENV_VAR_DISABLED == "env_var_disabled"

    def test_apply_flag_missing_value(self) -> None:
        assert WriteBlockReason.APPLY_FLAG_MISSING == "apply_flag_missing"

    def test_is_str_enum(self) -> None:
        reason: str = WriteBlockReason.ENV_VAR_DISABLED
        assert isinstance(reason, str)


# ---------------------------------------------------------------------------
# check_write_enabled
# ---------------------------------------------------------------------------


class TestCheckWriteEnabled:
    """Non-throwing check for write-enabled status."""

    def test_returns_true_when_enabled(self) -> None:
        with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": "true"}):
            assert check_write_enabled("CISCO") is True

    def test_returns_true_case_insensitive(self) -> None:
        for value in ("true", "True", "TRUE", "tRuE"):
            with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": value}):
                assert check_write_enabled("CISCO") is True, f"Failed for value: {value}"

    def test_returns_false_when_disabled(self) -> None:
        with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": "false"}):
            assert check_write_enabled("CISCO") is False

    def test_returns_false_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert check_write_enabled("CISCO") is False

    def test_returns_false_when_empty(self) -> None:
        with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": ""}):
            assert check_write_enabled("CISCO") is False

    def test_returns_false_for_non_true_values(self) -> None:
        for value in ("1", "yes", "on", "enabled", "truee", " true"):
            with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": value}):
                assert check_write_enabled("CISCO") is False, (
                    f"Should be False for value: {value!r}"
                )

    def test_default_plugin_name_is_cisco(self) -> None:
        with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": "true"}):
            assert check_write_enabled() is True


# ---------------------------------------------------------------------------
# describe_write_status
# ---------------------------------------------------------------------------


class TestDescribeWriteStatus:
    """Human-readable write status messages."""

    def test_disabled_message(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            msg = describe_write_status("CISCO")
            assert "disabled" in msg.lower()
            assert "CISCO_WRITE_ENABLED" in msg

    def test_enabled_message(self) -> None:
        with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": "true"}):
            msg = describe_write_status("CISCO")
            assert "enabled" in msg.lower()
            assert "--apply" in msg

    def test_default_plugin_name_is_cisco(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            msg = describe_write_status()
            assert "CISCO_WRITE_ENABLED" in msg


# ---------------------------------------------------------------------------
# write_gate decorator -- env var check (step 1)
# ---------------------------------------------------------------------------


class TestWriteGateEnvVar:
    """Step 1: environment variable gate."""

    @pytest.mark.asyncio
    async def test_write_gate_blocks_when_env_disabled(self) -> None:
        """CISCO_WRITE_ENABLED not set -> WriteGateError with ENV_VAR_DISABLED."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED
            assert exc_info.value.plugin_name == "CISCO"
            assert exc_info.value.env_var == "CISCO_WRITE_ENABLED"

    @pytest.mark.asyncio
    async def test_raises_when_env_var_false(self) -> None:
        with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": "false"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_raises_when_env_var_empty(self) -> None:
        with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": ""}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_error_message_includes_env_var_name(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError, match="CISCO_WRITE_ENABLED"),
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
        with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=False)
            assert exc_info.value.reason == WriteGateReason.APPLY_FLAG_MISSING
            assert exc_info.value.plugin_name == "CISCO"

    @pytest.mark.asyncio
    async def test_raises_when_apply_not_provided(self) -> None:
        """apply defaults to False, so omitting it should block."""
        with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test")
            assert exc_info.value.reason == WriteGateReason.APPLY_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_error_message_mentions_apply(self) -> None:
        with (
            patch.dict(os.environ, {"CISCO_WRITE_ENABLED": "true"}),
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
        with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": "true"}):
            result = await sample_write_tool("my-rule", apply=True)
            assert result == {"created": "my-rule"}

    @pytest.mark.asyncio
    async def test_env_var_case_insensitive(self) -> None:
        with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": "True"}):
            result = await sample_write_tool("test", apply=True)
            assert result == {"created": "test"}

    @pytest.mark.asyncio
    async def test_no_positional_args(self) -> None:
        with patch.dict(os.environ, {"CISCO_WRITE_ENABLED": "true"}):
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

            @write_gate("CISCO")
            async def bad_tool(name: str) -> str:
                return name

    def test_positional_apply_rejected(self) -> None:
        """apply as a positional argument (not keyword-only) is rejected."""
        with pytest.raises(TypeError, match="apply"):

            @write_gate("CISCO")
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
