"""Tests for the write safety gate and reconfigure gate modules.

Covers:
- WriteBlockReason enum values
- write_gate decorator: env var enabled/disabled, --apply present/missing
- reconfigure_gate decorator: same gates + reconfigure-specific behavior
- check_write_enabled: non-throwing boolean check
- describe_write_status: human-readable messages
- Edge cases: case sensitivity, empty env var, unset env var
- Error structure: reason, plugin_name, env_var fields
- Multiple plugin names (OPNSENSE, UNIFI, NETEX)
- Decorator preserves function metadata (functools.wraps)
- Reconfigure gate carries is_reconfigure detail
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from opnsense.errors import WriteGateError
from opnsense.safety import (
    WriteBlockReason,
    check_write_enabled,
    describe_write_status,
    reconfigure_gate,
    write_gate,
)

# ---------------------------------------------------------------------------
# Fixtures — sample decorated functions
# ---------------------------------------------------------------------------


@write_gate("OPNSENSE")
async def sample_write_tool(name: str, *, apply: bool = False) -> dict[str, str]:
    """A sample write tool for testing the decorator."""
    return {"created": name}


@write_gate("UNIFI")
async def sample_unifi_tool(*, apply: bool = False) -> str:
    """A sample unifi write tool for testing multi-plugin support."""
    return "unifi_result"


@write_gate("NETEX")
async def sample_netex_tool(data: list[int], *, apply: bool = False) -> int:
    """A sample netex write tool for testing the umbrella plugin."""
    return sum(data)


@reconfigure_gate("OPNSENSE")
async def sample_reconfigure_tool(*, apply: bool = False) -> str:
    """A sample reconfigure tool for testing the reconfigure gate."""
    return "reconfigured"


@reconfigure_gate("OPNSENSE")
async def sample_firewall_apply(*, apply: bool = False) -> dict[str, str]:
    """Simulates POST /api/firewall/filter/apply."""
    return {"status": "applied"}


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
        """WriteBlockReason values can be used as plain strings."""
        reason: str = WriteBlockReason.ENV_VAR_DISABLED
        assert isinstance(reason, str)
        assert reason == "env_var_disabled"


# ---------------------------------------------------------------------------
# check_write_enabled
# ---------------------------------------------------------------------------


class TestCheckWriteEnabled:
    """Non-throwing check for write-enabled status."""

    def test_returns_true_when_enabled(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            assert check_write_enabled("OPNSENSE") is True

    def test_returns_true_case_insensitive(self) -> None:
        for value in ("true", "True", "TRUE", "tRuE"):
            with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": value}):
                assert check_write_enabled("OPNSENSE") is True, f"Failed for value: {value}"

    def test_returns_false_when_disabled(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "false"}):
            assert check_write_enabled("OPNSENSE") is False

    def test_returns_false_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert check_write_enabled("OPNSENSE") is False

    def test_returns_false_when_empty(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": ""}):
            assert check_write_enabled("OPNSENSE") is False

    def test_returns_false_for_non_true_values(self) -> None:
        for value in ("1", "yes", "on", "enabled", "truee", " true"):
            with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": value}):
                assert check_write_enabled("OPNSENSE") is False, (
                    f"Should be False for value: {value!r}"
                )

    def test_uses_plugin_name_for_env_var(self) -> None:
        env = {"UNIFI_WRITE_ENABLED": "true"}
        with patch.dict(os.environ, env, clear=True):
            assert check_write_enabled("UNIFI") is True
            assert check_write_enabled("OPNSENSE") is False

    def test_default_plugin_name_is_opnsense(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            assert check_write_enabled() is True


# ---------------------------------------------------------------------------
# describe_write_status
# ---------------------------------------------------------------------------


class TestDescribeWriteStatus:
    """Human-readable write status messages."""

    def test_disabled_message(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            msg = describe_write_status("OPNSENSE")
            assert "disabled" in msg.lower()
            assert "OPNSENSE_WRITE_ENABLED=true" in msg

    def test_enabled_message(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            msg = describe_write_status("OPNSENSE")
            assert "enabled" in msg.lower()
            assert "--apply" in msg

    def test_unifi_disabled_message(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            msg = describe_write_status("UNIFI")
            assert "UNIFI_WRITE_ENABLED=true" in msg

    def test_netex_disabled_message(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            msg = describe_write_status("NETEX")
            assert "NETEX_WRITE_ENABLED=true" in msg

    def test_default_plugin_name_is_opnsense(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            msg = describe_write_status()
            assert "OPNSENSE_WRITE_ENABLED" in msg


# ---------------------------------------------------------------------------
# write_gate decorator — env var check (step 1)
# ---------------------------------------------------------------------------


class TestWriteGateEnvVar:
    """Step 1: environment variable gate."""

    @pytest.mark.asyncio
    async def test_raises_when_env_var_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED
            assert exc_info.value.plugin_name == "OPNSENSE"
            assert exc_info.value.env_var == "OPNSENSE_WRITE_ENABLED"

    @pytest.mark.asyncio
    async def test_raises_when_env_var_false(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "false"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_raises_when_env_var_empty(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": ""}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_error_message_includes_env_var_name(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError, match="OPNSENSE_WRITE_ENABLED"),
        ):
            await sample_write_tool("test", apply=True)

    @pytest.mark.asyncio
    async def test_env_var_takes_priority_over_apply_flag(self) -> None:
        """When env var is disabled, error is ENV_VAR_DISABLED even if apply=False."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=False)
            # Should report env var issue, not apply flag issue
            assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED


# ---------------------------------------------------------------------------
# write_gate decorator — apply flag check (step 2)
# ---------------------------------------------------------------------------


class TestWriteGateApplyFlag:
    """Step 2: --apply flag gate."""

    @pytest.mark.asyncio
    async def test_raises_when_apply_false(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=False)
            assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING
            assert exc_info.value.plugin_name == "OPNSENSE"

    @pytest.mark.asyncio
    async def test_raises_when_apply_not_provided(self) -> None:
        """apply defaults to False, so omitting it should block."""
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test")
            assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_error_message_mentions_apply(self) -> None:
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            pytest.raises(WriteGateError, match="--apply"),
        ):
            await sample_write_tool("test")


# ---------------------------------------------------------------------------
# write_gate decorator — both gates pass
# ---------------------------------------------------------------------------


class TestWriteGateSuccess:
    """Both gates pass -- the wrapped function executes."""

    @pytest.mark.asyncio
    async def test_executes_when_both_gates_pass(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            result = await sample_write_tool("my-rule", apply=True)
            assert result == {"created": "my-rule"}

    @pytest.mark.asyncio
    async def test_passes_all_arguments_through(self) -> None:
        with patch.dict(os.environ, {"NETEX_WRITE_ENABLED": "true"}):
            result = await sample_netex_tool([1, 2, 3], apply=True)
            assert result == 6

    @pytest.mark.asyncio
    async def test_env_var_case_insensitive(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "True"}):
            result = await sample_write_tool("test", apply=True)
            assert result == {"created": "test"}


# ---------------------------------------------------------------------------
# write_gate decorator — multi-plugin support
# ---------------------------------------------------------------------------


class TestWriteGateMultiPlugin:
    """Each plugin has its own independent env var."""

    @pytest.mark.asyncio
    async def test_unifi_plugin_uses_own_env_var(self) -> None:
        with patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}):
            result = await sample_unifi_tool(apply=True)
            assert result == "unifi_result"

    @pytest.mark.asyncio
    async def test_unifi_blocked_by_own_env_var(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_unifi_tool(apply=True)
            assert exc_info.value.env_var == "UNIFI_WRITE_ENABLED"

    @pytest.mark.asyncio
    async def test_plugins_are_independent(self) -> None:
        """Enabling one plugin does not enable another."""
        with patch.dict(
            os.environ,
            {"OPNSENSE_WRITE_ENABLED": "true"},
            clear=True,
        ):
            # OPNSENSE should work
            result = await sample_write_tool("test", apply=True)
            assert result == {"created": "test"}

            # UNIFI should be blocked
            with pytest.raises(WriteGateError) as exc_info:
                await sample_unifi_tool(apply=True)
            assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED


# ---------------------------------------------------------------------------
# write_gate decorator — metadata preservation
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
# reconfigure_gate decorator — env var check
# ---------------------------------------------------------------------------


class TestReconfigureGateEnvVar:
    """Reconfigure gate step 1: environment variable gate."""

    @pytest.mark.asyncio
    async def test_raises_when_env_var_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_reconfigure_tool(apply=True)
            assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED
            assert exc_info.value.plugin_name == "OPNSENSE"

    @pytest.mark.asyncio
    async def test_error_message_says_reconfigure(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError, match=r"[Rr]econfigure"),
        ):
            await sample_reconfigure_tool(apply=True)

    @pytest.mark.asyncio
    async def test_error_carries_is_reconfigure_detail(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_reconfigure_tool(apply=True)
            assert exc_info.value.details.get("is_reconfigure") is True


# ---------------------------------------------------------------------------
# reconfigure_gate decorator — apply flag check
# ---------------------------------------------------------------------------


class TestReconfigureGateApplyFlag:
    """Reconfigure gate step 2: --apply flag gate."""

    @pytest.mark.asyncio
    async def test_raises_when_apply_false(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_reconfigure_tool(apply=False)
            assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_error_message_mentions_reconfigure(self) -> None:
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            pytest.raises(WriteGateError, match=r"[Rr]econfigure"),
        ):
            await sample_reconfigure_tool()

    @pytest.mark.asyncio
    async def test_error_carries_is_reconfigure_detail(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_reconfigure_tool()
            assert exc_info.value.details.get("is_reconfigure") is True


# ---------------------------------------------------------------------------
# reconfigure_gate decorator — success
# ---------------------------------------------------------------------------


class TestReconfigureGateSuccess:
    """Reconfigure gate -- both gates pass."""

    @pytest.mark.asyncio
    async def test_executes_when_both_gates_pass(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            result = await sample_reconfigure_tool(apply=True)
            assert result == "reconfigured"

    @pytest.mark.asyncio
    async def test_firewall_apply_executes(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            result = await sample_firewall_apply(apply=True)
            assert result == {"status": "applied"}


# ---------------------------------------------------------------------------
# reconfigure_gate decorator — metadata and marker
# ---------------------------------------------------------------------------


class TestReconfigureGateMetadata:
    """Reconfigure gate preserves metadata and adds reconfigure marker."""

    def test_preserves_function_name(self) -> None:
        assert sample_reconfigure_tool.__name__ == "sample_reconfigure_tool"

    def test_preserves_docstring(self) -> None:
        assert sample_reconfigure_tool.__doc__ is not None
        assert "reconfigure" in sample_reconfigure_tool.__doc__.lower()

    def test_has_is_reconfigure_marker(self) -> None:
        assert hasattr(sample_reconfigure_tool, "_is_reconfigure")
        assert sample_reconfigure_tool._is_reconfigure is True  # type: ignore[attr-defined]

    def test_write_gate_does_not_have_reconfigure_marker(self) -> None:
        assert not hasattr(sample_write_tool, "_is_reconfigure")


# ---------------------------------------------------------------------------
# WriteGateError structure
# ---------------------------------------------------------------------------


class TestWriteGateErrorStructure:
    """Verify error objects carry structured context."""

    @pytest.mark.asyncio
    async def test_error_has_reason_field(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            err = exc_info.value
            assert hasattr(err, "reason")
            assert err.reason in (
                WriteBlockReason.ENV_VAR_DISABLED,
                WriteBlockReason.APPLY_FLAG_MISSING,
            )

    @pytest.mark.asyncio
    async def test_error_has_plugin_name_field(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            assert exc_info.value.plugin_name == "OPNSENSE"

    @pytest.mark.asyncio
    async def test_error_has_env_var_field(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            assert exc_info.value.env_var == "OPNSENSE_WRITE_ENABLED"

    @pytest.mark.asyncio
    async def test_error_is_exception(self) -> None:
        with patch.dict(os.environ, {}, clear=True), pytest.raises(WriteGateError):
            await sample_write_tool("test", apply=True)

    @pytest.mark.asyncio
    async def test_error_message_is_str(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await sample_write_tool("test", apply=True)
            assert isinstance(str(exc_info.value), str)
            assert len(str(exc_info.value)) > 0
