# SPDX-License-Identifier: MIT
"""Tests for the structured error hierarchy in netex.errors."""

from __future__ import annotations

import pytest

from netex.errors import (
    ContractViolationError,
    NetexError,
    PluginNotFoundError,
    ValidationError,
    WorkflowError,
    WriteGateError,
    WriteGateReason,
)

# ---------------------------------------------------------------------------
# NetexError (base)
# ---------------------------------------------------------------------------


class TestNetexError:
    def test_minimal_construction(self) -> None:
        err = NetexError("something went wrong")
        assert str(err) == "something went wrong"
        assert err.message == "something went wrong"
        assert err.status_code is None
        assert err.endpoint is None
        assert err.retry_hint is None
        assert err.details == {}

    def test_full_construction(self) -> None:
        err = NetexError(
            "full context",
            status_code=500,
            endpoint="/api/test",
            retry_hint="Try again",
            details={"key": "value"},
        )
        assert err.status_code == 500
        assert err.endpoint == "/api/test"
        assert err.retry_hint == "Try again"
        assert err.details == {"key": "value"}

    def test_str_includes_all_parts(self) -> None:
        err = NetexError(
            "failure",
            status_code=502,
            endpoint="/api/test",
            retry_hint="Retry later",
        )
        result = str(err)
        assert "failure" in result
        assert "Endpoint: /api/test" in result
        assert "Status: 502" in result
        assert "Hint: Retry later" in result

    def test_str_omits_none_parts(self) -> None:
        err = NetexError("just a message")
        assert str(err) == "just a message"

    def test_repr_shows_class_and_fields(self) -> None:
        err = NetexError("msg", status_code=404)
        r = repr(err)
        assert r.startswith("NetexError(")
        assert "message='msg'" in r
        assert "status_code=404" in r

    def test_is_exception(self) -> None:
        err = NetexError("test")
        assert isinstance(err, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(NetexError, match="boom"):
            raise NetexError("boom")

    def test_details_default_is_empty_dict(self) -> None:
        err = NetexError("test")
        assert err.details == {}
        err.details["key"] = "value"
        err2 = NetexError("test2")
        assert err2.details == {}


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


class TestInheritance:
    @pytest.mark.parametrize(
        "error_class, kwargs",
        [
            (PluginNotFoundError, {"message": "missing"}),
            (ContractViolationError, {"message": "invalid"}),
            (WorkflowError, {"message": "bad transition"}),
            (ValidationError, {"message": "bad input"}),
            (WriteGateError, {"message": "blocked", "reason": WriteGateReason.ENV_VAR_DISABLED}),
        ],
    )
    def test_subclass_is_netex_error(
        self,
        error_class: type[NetexError],
        kwargs: dict[str, object],
    ) -> None:
        err = error_class(**kwargs)  # type: ignore[arg-type]
        assert isinstance(err, NetexError)
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# PluginNotFoundError
# ---------------------------------------------------------------------------


class TestPluginNotFoundError:
    def test_basic(self) -> None:
        err = PluginNotFoundError("opnsense not installed")
        assert err.status_code is None
        assert err.retry_hint is not None

    def test_with_plugin_name(self) -> None:
        err = PluginNotFoundError("missing", plugin_name="opnsense")
        assert err.plugin_name == "opnsense"
        assert err.details["plugin_name"] == "opnsense"

    def test_with_role(self) -> None:
        err = PluginNotFoundError("no gateway", required_role="gateway")
        assert err.required_role == "gateway"
        assert err.details["required_role"] == "gateway"

    def test_with_skill(self) -> None:
        err = PluginNotFoundError("no firewall", required_skill="firewall")
        assert err.required_skill == "firewall"
        assert err.details["required_skill"] == "firewall"


# ---------------------------------------------------------------------------
# ContractViolationError
# ---------------------------------------------------------------------------


class TestContractViolationError:
    def test_basic(self) -> None:
        err = ContractViolationError("bad plugin")
        assert err.plugin_name is None
        assert err.violations == []

    def test_with_violations(self) -> None:
        violations = ["missing name", "invalid version"]
        err = ContractViolationError(
            "validation failed",
            plugin_name="bad-plugin",
            violations=violations,
        )
        assert err.plugin_name == "bad-plugin"
        assert err.violations == violations
        assert err.details["violations"] == violations

    def test_retry_hint(self) -> None:
        err = ContractViolationError("failed")
        assert err.retry_hint is not None
        assert "contract" in err.retry_hint.lower()


# ---------------------------------------------------------------------------
# WorkflowError
# ---------------------------------------------------------------------------


class TestWorkflowError:
    def test_basic(self) -> None:
        err = WorkflowError("bad transition")
        assert err.workflow_id is None
        assert err.current_state is None
        assert err.attempted_state is None

    def test_with_states(self) -> None:
        err = WorkflowError(
            "invalid transition",
            workflow_id="wf-123",
            current_state="created",
            attempted_state="completed",
        )
        assert err.workflow_id == "wf-123"
        assert err.current_state == "created"
        assert err.attempted_state == "completed"
        assert err.details["workflow_id"] == "wf-123"


# ---------------------------------------------------------------------------
# WriteGateError
# ---------------------------------------------------------------------------


class TestWriteGateError:
    def test_env_var_disabled(self) -> None:
        err = WriteGateError(
            "Write operations are disabled",
            reason=WriteGateReason.ENV_VAR_DISABLED,
        )
        assert err.reason == WriteGateReason.ENV_VAR_DISABLED
        assert err.details["reason"] == "env_var_disabled"

    def test_apply_flag_missing(self) -> None:
        err = WriteGateError(
            "Missing --apply",
            reason=WriteGateReason.APPLY_FLAG_MISSING,
        )
        assert err.reason == WriteGateReason.APPLY_FLAG_MISSING

    def test_retry_hint_for_env_var(self) -> None:
        err = WriteGateError("blocked", reason=WriteGateReason.ENV_VAR_DISABLED)
        assert err.retry_hint is not None
        assert "NETEX_WRITE_ENABLED" in err.retry_hint

    def test_retry_hint_for_apply_flag(self) -> None:
        err = WriteGateError("blocked", reason=WriteGateReason.APPLY_FLAG_MISSING)
        assert err.retry_hint is not None
        assert "--apply" in err.retry_hint

    def test_str_includes_reason(self) -> None:
        err = WriteGateError(
            "Write blocked",
            reason=WriteGateReason.ENV_VAR_DISABLED,
        )
        result = str(err)
        assert "Reason: env_var_disabled" in result

    def test_custom_details_merged(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.APPLY_FLAG_MISSING,
            details={"command": "vlan configure"},
        )
        assert err.details["reason"] == "apply_flag_missing"
        assert err.details["command"] == "vlan configure"


# ---------------------------------------------------------------------------
# WriteGateReason enum
# ---------------------------------------------------------------------------


class TestWriteGateReason:
    def test_is_str_enum(self) -> None:
        assert isinstance(WriteGateReason.ENV_VAR_DISABLED, str)
        assert isinstance(WriteGateReason.APPLY_FLAG_MISSING, str)

    def test_values(self) -> None:
        assert WriteGateReason.ENV_VAR_DISABLED == "env_var_disabled"
        assert WriteGateReason.APPLY_FLAG_MISSING == "apply_flag_missing"

    def test_from_string(self) -> None:
        assert WriteGateReason("env_var_disabled") == WriteGateReason.ENV_VAR_DISABLED

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            WriteGateReason("invalid_reason")
