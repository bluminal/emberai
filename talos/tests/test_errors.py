"""Tests for the Talos plugin error hierarchy.

Covers:
- NetexError base class has all structured fields
- Each subclass sets proper default values and extra attributes
- TalosCtlError carries command, stderr, and exit_code
- TalosCtlNotFoundError has installation hint
- ConfigParseError carries raw_output
- WriteGateError carries reason enum with Talos-specific reasons
- Error hierarchy: all errors are instances of NetexError
- __str__ and __repr__ formatting
"""

from __future__ import annotations

import pytest

from talos.errors import (
    AuthenticationError,
    ConfigParseError,
    NetexError,
    NetworkError,
    TalosCtlError,
    TalosCtlNotFoundError,
    ValidationError,
    WriteGateError,
    WriteGateReason,
)

# ---------------------------------------------------------------------------
# WriteGateReason enum
# ---------------------------------------------------------------------------


class TestWriteGateReason:
    """Verify WriteGateReason enum values are stable strings."""

    def test_env_var_disabled_value(self) -> None:
        assert WriteGateReason.ENV_VAR_DISABLED == "env_var_disabled"

    def test_apply_flag_missing_value(self) -> None:
        assert WriteGateReason.APPLY_FLAG_MISSING == "apply_flag_missing"

    def test_reset_flag_missing_value(self) -> None:
        assert WriteGateReason.RESET_FLAG_MISSING == "reset_flag_missing"

    def test_bootstrap_blocked_value(self) -> None:
        assert WriteGateReason.BOOTSTRAP_BLOCKED == "bootstrap_blocked"

    def test_is_str_enum(self) -> None:
        """WriteGateReason values can be used as plain strings."""
        reason: str = WriteGateReason.ENV_VAR_DISABLED
        assert isinstance(reason, str)
        assert reason == "env_var_disabled"


# ---------------------------------------------------------------------------
# NetexError (base)
# ---------------------------------------------------------------------------


class TestNetexError:
    """Base error class carries structured fields."""

    def test_message_field(self) -> None:
        err = NetexError("something failed")
        assert err.message == "something failed"
        assert str(err) == "something failed"

    def test_all_fields_default_to_none_or_empty(self) -> None:
        err = NetexError("test")
        assert err.status_code is None
        assert err.endpoint is None
        assert err.retry_hint is None
        assert err.details == {}

    def test_custom_fields(self) -> None:
        err = NetexError(
            "test",
            status_code=500,
            endpoint="192.168.30.11:50000",
            retry_hint="retry in 5s",
            details={"key": "value"},
        )
        assert err.status_code == 500
        assert err.endpoint == "192.168.30.11:50000"
        assert err.retry_hint == "retry in 5s"
        assert err.details == {"key": "value"}

    def test_str_includes_endpoint(self) -> None:
        err = NetexError("test", endpoint="192.168.30.11")
        result = str(err)
        assert "192.168.30.11" in result

    def test_str_includes_status_code(self) -> None:
        err = NetexError("test", status_code=404)
        result = str(err)
        assert "404" in result

    def test_str_includes_retry_hint(self) -> None:
        err = NetexError("test", retry_hint="check network")
        result = str(err)
        assert "check network" in result

    def test_repr_format(self) -> None:
        err = NetexError("test error", endpoint="192.168.30.11")
        result = repr(err)
        assert "NetexError" in result
        assert "test error" in result
        assert "192.168.30.11" in result

    def test_repr_omits_none_fields(self) -> None:
        err = NetexError("test")
        result = repr(err)
        assert "status_code" not in result
        assert "endpoint" not in result

    def test_is_exception(self) -> None:
        err = NetexError("test")
        assert isinstance(err, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(NetexError):
            raise NetexError("test")


# ---------------------------------------------------------------------------
# AuthenticationError
# ---------------------------------------------------------------------------


class TestAuthenticationError:
    """Talosconfig / mTLS authentication failure error."""

    def test_basic_creation(self) -> None:
        err = AuthenticationError("certificate expired")
        assert err.message == "certificate expired"
        assert err.config_path is None
        assert err.context is None

    def test_with_config_path(self) -> None:
        err = AuthenticationError(
            "bad cert", config_path="/home/user/.talos/config"
        )
        assert err.config_path == "/home/user/.talos/config"
        assert "config_path" in err.details

    def test_with_context(self) -> None:
        err = AuthenticationError("bad context", context="homelab")
        assert err.context == "homelab"
        assert err.details["context"] == "homelab"

    def test_retry_hint_mentions_talosconfig(self) -> None:
        err = AuthenticationError("auth failed")
        assert err.retry_hint is not None
        assert "talosconfig" in err.retry_hint.lower()

    def test_is_netex_error(self) -> None:
        assert isinstance(AuthenticationError("bad"), NetexError)

    def test_status_code_always_none(self) -> None:
        err = AuthenticationError("bad", config_path="/x")
        assert err.status_code is None

    def test_with_extra_details(self) -> None:
        err = AuthenticationError(
            "bad", details={"extra": "info"}
        )
        assert err.details["extra"] == "info"


# ---------------------------------------------------------------------------
# NetworkError
# ---------------------------------------------------------------------------


class TestNetworkError:
    """Transport-level failure error (node unreachable, timeout)."""

    def test_basic_creation(self) -> None:
        err = NetworkError("connection refused")
        assert err.message == "connection refused"
        assert err.status_code is None

    def test_default_retry_hint(self) -> None:
        err = NetworkError("timeout")
        assert err.retry_hint is not None
        assert "network" in err.retry_hint.lower() or "connectivity" in err.retry_hint.lower()

    def test_custom_retry_hint(self) -> None:
        err = NetworkError("timeout", retry_hint="wait 30 seconds")
        assert err.retry_hint == "wait 30 seconds"

    def test_with_endpoint(self) -> None:
        err = NetworkError("timeout", endpoint="192.168.30.11")
        assert err.endpoint == "192.168.30.11"

    def test_is_netex_error(self) -> None:
        assert isinstance(NetworkError("x"), NetexError)


# ---------------------------------------------------------------------------
# TalosCtlError
# ---------------------------------------------------------------------------


class TestTalosCtlError:
    """talosctl subprocess error carries command, stderr, and exit_code."""

    def test_basic_creation(self) -> None:
        err = TalosCtlError("command failed")
        assert err.message == "command failed"
        assert err.command is None
        assert err.stderr is None
        assert err.exit_code is None

    def test_with_command(self) -> None:
        err = TalosCtlError(
            "failed",
            command=["talosctl", "health", "--nodes", "192.168.30.11"],
        )
        assert err.command == ["talosctl", "health", "--nodes", "192.168.30.11"]
        assert "command" in err.details

    def test_with_stderr(self) -> None:
        stderr_text = "rpc error: code = Unavailable desc = connection refused"
        err = TalosCtlError("failed", stderr=stderr_text)
        assert err.stderr == stderr_text
        assert err.details["stderr"] == stderr_text

    def test_with_exit_code(self) -> None:
        err = TalosCtlError("failed", exit_code=1)
        assert err.exit_code == 1
        assert err.details["exit_code"] == 1

    def test_with_all_fields(self) -> None:
        err = TalosCtlError(
            "failed",
            command=["talosctl", "version"],
            stderr="error: dial timeout",
            exit_code=1,
            endpoint="192.168.30.11",
        )
        assert err.command == ["talosctl", "version"]
        assert err.stderr == "error: dial timeout"
        assert err.exit_code == 1
        assert err.endpoint == "192.168.30.11"

    def test_str_includes_command(self) -> None:
        err = TalosCtlError(
            "failed",
            command=["talosctl", "health"],
        )
        result = str(err)
        assert "talosctl health" in result

    def test_str_includes_exit_code(self) -> None:
        err = TalosCtlError("failed", exit_code=1)
        result = str(err)
        assert "1" in result

    def test_with_extra_details(self) -> None:
        err = TalosCtlError(
            "failed",
            command=["talosctl", "version"],
            details={"extra": "info"},
        )
        assert err.details["extra"] == "info"
        assert "command" in err.details

    def test_is_netex_error(self) -> None:
        assert isinstance(TalosCtlError("x"), NetexError)


# ---------------------------------------------------------------------------
# TalosCtlNotFoundError
# ---------------------------------------------------------------------------


class TestTalosCtlNotFoundError:
    """talosctl binary not found -- includes installation hint."""

    def test_default_message(self) -> None:
        err = TalosCtlNotFoundError()
        assert "talosctl" in err.message.lower()
        assert "not found" in err.message.lower()

    def test_custom_message(self) -> None:
        err = TalosCtlNotFoundError("custom message")
        assert err.message == "custom message"

    def test_install_hint_in_retry_hint(self) -> None:
        err = TalosCtlNotFoundError()
        assert err.retry_hint is not None
        assert "talosctl" in err.retry_hint.lower()
        assert "install" in err.retry_hint.lower()

    def test_install_hint_class_var(self) -> None:
        assert "talosctl" in TalosCtlNotFoundError.INSTALL_HINT.lower()
        assert "talos.dev" in TalosCtlNotFoundError.INSTALL_HINT

    def test_is_netex_error(self) -> None:
        assert isinstance(TalosCtlNotFoundError(), NetexError)

    def test_endpoint_is_none(self) -> None:
        err = TalosCtlNotFoundError()
        assert err.endpoint is None


# ---------------------------------------------------------------------------
# ConfigParseError
# ---------------------------------------------------------------------------


class TestConfigParseError:
    """Output parse error carries raw_output."""

    def test_basic_creation(self) -> None:
        err = ConfigParseError("unexpected format")
        assert err.message == "unexpected format"
        assert err.command is None
        assert err.raw_output is None

    def test_with_raw_output(self) -> None:
        raw = '{"invalid json'
        err = ConfigParseError("parse failed", raw_output=raw)
        assert err.raw_output == raw
        assert err.details["raw_output"] == raw

    def test_with_command(self) -> None:
        err = ConfigParseError("parse failed", command="talosctl version -o json")
        assert err.command == "talosctl version -o json"
        assert err.details["command"] == "talosctl version -o json"

    def test_retry_hint_mentions_version(self) -> None:
        err = ConfigParseError("parse failed")
        assert err.retry_hint is not None
        assert "version" in err.retry_hint.lower() or "compatibility" in err.retry_hint.lower()

    def test_with_extra_details(self) -> None:
        err = ConfigParseError(
            "parse failed",
            command="talosctl version",
            details={"extra": "context"},
        )
        assert err.details["command"] == "talosctl version"
        assert err.details["extra"] == "context"

    def test_is_netex_error(self) -> None:
        assert isinstance(ConfigParseError("x"), NetexError)


# ---------------------------------------------------------------------------
# ValidationError
# ---------------------------------------------------------------------------


class TestValidationError:
    """Input validation error."""

    def test_basic_creation(self) -> None:
        err = ValidationError("invalid node IP")
        assert err.message == "invalid node IP"
        assert err.status_code is None
        assert err.retry_hint is None

    def test_is_netex_error(self) -> None:
        assert isinstance(ValidationError("x"), NetexError)

    def test_with_details(self) -> None:
        err = ValidationError("bad input", details={"field": "node_ip"})
        assert err.details == {"field": "node_ip"}

    def test_with_endpoint(self) -> None:
        err = ValidationError("bad input", endpoint="192.168.30.11")
        assert err.endpoint == "192.168.30.11"


# ---------------------------------------------------------------------------
# WriteGateError
# ---------------------------------------------------------------------------


class TestWriteGateError:
    """Write gate error carries reason enum with Talos-specific reasons."""

    def test_env_var_disabled_reason(self) -> None:
        err = WriteGateError(
            "writes disabled",
            reason=WriteGateReason.ENV_VAR_DISABLED,
        )
        assert err.reason == WriteGateReason.ENV_VAR_DISABLED
        assert err.details["reason"] == "env_var_disabled"

    def test_apply_flag_missing_reason(self) -> None:
        err = WriteGateError(
            "need --apply",
            reason=WriteGateReason.APPLY_FLAG_MISSING,
        )
        assert err.reason == WriteGateReason.APPLY_FLAG_MISSING
        assert err.details["reason"] == "apply_flag_missing"

    def test_reset_flag_missing_reason(self) -> None:
        err = WriteGateError(
            "need --reset-node",
            reason=WriteGateReason.RESET_FLAG_MISSING,
        )
        assert err.reason == WriteGateReason.RESET_FLAG_MISSING
        assert err.details["reason"] == "reset_flag_missing"

    def test_bootstrap_blocked_reason(self) -> None:
        err = WriteGateError(
            "etcd exists",
            reason=WriteGateReason.BOOTSTRAP_BLOCKED,
        )
        assert err.reason == WriteGateReason.BOOTSTRAP_BLOCKED
        assert err.details["reason"] == "bootstrap_blocked"

    def test_plugin_name_field(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.ENV_VAR_DISABLED,
            plugin_name="TALOS",
        )
        assert err.plugin_name == "TALOS"
        assert err.details["plugin_name"] == "TALOS"

    def test_env_var_field(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.ENV_VAR_DISABLED,
            env_var="TALOS_WRITE_ENABLED",
        )
        assert err.env_var == "TALOS_WRITE_ENABLED"
        assert err.details["env_var"] == "TALOS_WRITE_ENABLED"

    def test_retry_hint_for_env_var(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.ENV_VAR_DISABLED,
        )
        assert err.retry_hint is not None
        assert "WRITE_ENABLED" in err.retry_hint.upper() or "true" in err.retry_hint

    def test_retry_hint_for_apply_flag(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.APPLY_FLAG_MISSING,
        )
        assert err.retry_hint is not None
        assert "--apply" in err.retry_hint

    def test_retry_hint_for_reset_flag(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.RESET_FLAG_MISSING,
        )
        assert err.retry_hint is not None
        assert "--reset-node" in err.retry_hint

    def test_retry_hint_for_bootstrap(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.BOOTSTRAP_BLOCKED,
        )
        assert err.retry_hint is not None
        assert "bootstrap" in err.retry_hint.lower()

    def test_str_includes_reason(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.ENV_VAR_DISABLED,
        )
        assert "env_var_disabled" in str(err)

    def test_is_netex_error(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.ENV_VAR_DISABLED,
        )
        assert isinstance(err, NetexError)

    def test_with_extra_details(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.ENV_VAR_DISABLED,
            details={"extra_key": "extra_value"},
        )
        assert err.details["extra_key"] == "extra_value"
        assert err.details["reason"] == "env_var_disabled"


# ---------------------------------------------------------------------------
# Error hierarchy -- all are NetexError subclasses
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    """All error types are instances of NetexError."""

    @pytest.mark.parametrize(
        "error",
        [
            NetexError("base"),
            AuthenticationError("auth"),
            NetworkError("network"),
            TalosCtlError("talosctl"),
            TalosCtlNotFoundError(),
            ConfigParseError("parse"),
            ValidationError("validation"),
            WriteGateError("gate", reason=WriteGateReason.ENV_VAR_DISABLED),
        ],
        ids=[
            "NetexError",
            "AuthenticationError",
            "NetworkError",
            "TalosCtlError",
            "TalosCtlNotFoundError",
            "ConfigParseError",
            "ValidationError",
            "WriteGateError",
        ],
    )
    def test_all_are_netex_error(self, error: Exception) -> None:
        assert isinstance(error, NetexError)
        assert isinstance(error, Exception)
