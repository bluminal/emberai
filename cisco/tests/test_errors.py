"""Tests for the Cisco plugin error hierarchy.

Covers:
- NetexError base class has all structured fields
- Each subclass sets proper default values
- SSHCommandError carries command and output
- CLIParseError carries raw_output
- WriteGateError carries reason enum
- __str__ and __repr__ formatting
"""

from __future__ import annotations

import pytest

from cisco.errors import (
    AuthenticationError,
    CLIParseError,
    NetexError,
    NetworkError,
    SSHCommandError,
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
            endpoint="show vlan",
            retry_hint="retry in 5s",
            details={"key": "value"},
        )
        assert err.status_code == 500
        assert err.endpoint == "show vlan"
        assert err.retry_hint == "retry in 5s"
        assert err.details == {"key": "value"}

    def test_str_includes_endpoint(self) -> None:
        err = NetexError("test", endpoint="show vlan")
        result = str(err)
        assert "show vlan" in result

    def test_str_includes_status_code(self) -> None:
        err = NetexError("test", status_code=404)
        result = str(err)
        assert "404" in result

    def test_str_includes_retry_hint(self) -> None:
        err = NetexError("test", retry_hint="check network")
        result = str(err)
        assert "check network" in result

    def test_repr_format(self) -> None:
        err = NetexError("test error", endpoint="show vlan")
        result = repr(err)
        assert "NetexError" in result
        assert "test error" in result
        assert "show vlan" in result

    def test_is_exception(self) -> None:
        err = NetexError("test")
        assert isinstance(err, Exception)

    def test_inherits_from_exception(self) -> None:
        with pytest.raises(NetexError):
            raise NetexError("test")


# ---------------------------------------------------------------------------
# AuthenticationError
# ---------------------------------------------------------------------------


class TestAuthenticationError:
    """SSH authentication failure error."""

    def test_basic_creation(self) -> None:
        err = AuthenticationError("bad password")
        assert err.message == "bad password"
        assert err.env_var is None

    def test_with_env_var(self) -> None:
        err = AuthenticationError("bad password", env_var="CISCO_SSH_PASSWORD")
        assert err.env_var == "CISCO_SSH_PASSWORD"
        assert "CISCO_SSH_PASSWORD" in err.details.get("env_var", "")

    def test_retry_hint_set_from_env_var(self) -> None:
        err = AuthenticationError("bad", env_var="CISCO_SSH_USERNAME")
        assert err.retry_hint is not None
        assert "CISCO_SSH_USERNAME" in err.retry_hint

    def test_retry_hint_none_without_env_var(self) -> None:
        err = AuthenticationError("bad")
        assert err.retry_hint is None

    def test_str_includes_env_var(self) -> None:
        err = AuthenticationError("bad", env_var="CISCO_SSH_PASSWORD")
        assert "CISCO_SSH_PASSWORD" in str(err)

    def test_is_netex_error(self) -> None:
        err = AuthenticationError("bad")
        assert isinstance(err, NetexError)

    def test_status_code_always_none(self) -> None:
        err = AuthenticationError("bad", env_var="X")
        assert err.status_code is None


# ---------------------------------------------------------------------------
# NetworkError
# ---------------------------------------------------------------------------


class TestNetworkError:
    """SSH transport-level failure error."""

    def test_basic_creation(self) -> None:
        err = NetworkError("connection refused")
        assert err.message == "connection refused"
        assert err.status_code is None

    def test_default_retry_hint(self) -> None:
        err = NetworkError("timeout")
        assert err.retry_hint is not None
        assert "network" in err.retry_hint.lower() or "retry" in err.retry_hint.lower()

    def test_custom_retry_hint(self) -> None:
        err = NetworkError("timeout", retry_hint="wait 30 seconds")
        assert err.retry_hint == "wait 30 seconds"

    def test_with_endpoint(self) -> None:
        err = NetworkError("timeout", endpoint="192.168.1.2")
        assert err.endpoint == "192.168.1.2"

    def test_is_netex_error(self) -> None:
        assert isinstance(NetworkError("x"), NetexError)


# ---------------------------------------------------------------------------
# SSHCommandError
# ---------------------------------------------------------------------------


class TestSSHCommandError:
    """CLI command error carries command and output."""

    def test_basic_creation(self) -> None:
        err = SSHCommandError("command failed")
        assert err.message == "command failed"
        assert err.command is None
        assert err.output is None

    def test_with_command(self) -> None:
        err = SSHCommandError("failed", command="show vlan")
        assert err.command == "show vlan"
        assert "command" in err.details

    def test_with_command_and_endpoint(self) -> None:
        err = SSHCommandError("failed", command="show vlan", endpoint="192.168.1.2")
        assert err.command == "show vlan"
        assert err.endpoint == "192.168.1.2"

    def test_with_output(self) -> None:
        err = SSHCommandError(
            "failed",
            command="show vlan",
            output="% Invalid input detected",
        )
        assert err.output == "% Invalid input detected"
        assert err.details["output"] == "% Invalid input detected"

    def test_with_extra_details(self) -> None:
        err = SSHCommandError(
            "failed",
            command="show vlan",
            details={"extra": "info"},
        )
        assert err.details["command"] == "show vlan"
        assert err.details["extra"] == "info"

    def test_is_netex_error(self) -> None:
        assert isinstance(SSHCommandError("x"), NetexError)


# ---------------------------------------------------------------------------
# CLIParseError
# ---------------------------------------------------------------------------


class TestCLIParseError:
    """CLI parse error carries raw_output."""

    def test_basic_creation(self) -> None:
        err = CLIParseError("unexpected format")
        assert err.message == "unexpected format"
        assert err.command is None
        assert err.raw_output is None

    def test_with_raw_output(self) -> None:
        raw = "garbled output here"
        err = CLIParseError("parse failed", raw_output=raw)
        assert err.raw_output == raw
        assert err.details["raw_output"] == raw

    def test_with_command(self) -> None:
        err = CLIParseError("parse failed", command="show vlan")
        assert err.command == "show vlan"
        assert err.endpoint == "show vlan"

    def test_retry_hint_mentions_firmware(self) -> None:
        err = CLIParseError("parse failed")
        assert err.retry_hint is not None
        assert "firmware" in err.retry_hint.lower()

    def test_is_netex_error(self) -> None:
        assert isinstance(CLIParseError("x"), NetexError)


# ---------------------------------------------------------------------------
# ValidationError
# ---------------------------------------------------------------------------


class TestValidationError:
    """Input validation error."""

    def test_basic_creation(self) -> None:
        err = ValidationError("invalid VLAN ID")
        assert err.message == "invalid VLAN ID"
        assert err.status_code is None
        assert err.retry_hint is None

    def test_is_netex_error(self) -> None:
        assert isinstance(ValidationError("x"), NetexError)

    def test_with_details(self) -> None:
        err = ValidationError("bad input", details={"field": "vlan_id"})
        assert err.details == {"field": "vlan_id"}


# ---------------------------------------------------------------------------
# WriteGateError
# ---------------------------------------------------------------------------


class TestWriteGateError:
    """Write gate error carries reason enum."""

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

    def test_plugin_name_field(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.ENV_VAR_DISABLED,
            plugin_name="CISCO",
        )
        assert err.plugin_name == "CISCO"
        assert err.details["plugin_name"] == "CISCO"

    def test_env_var_field(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.ENV_VAR_DISABLED,
            env_var="CISCO_WRITE_ENABLED",
        )
        assert err.env_var == "CISCO_WRITE_ENABLED"
        assert err.details["env_var"] == "CISCO_WRITE_ENABLED"

    def test_retry_hint_for_env_var(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.ENV_VAR_DISABLED,
        )
        assert err.retry_hint is not None
        assert "CISCO_WRITE_ENABLED" in err.retry_hint

    def test_retry_hint_for_apply_flag(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.APPLY_FLAG_MISSING,
        )
        assert err.retry_hint is not None
        assert "--apply" in err.retry_hint

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
        """Line 359: extra_details.update(details) branch."""
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.ENV_VAR_DISABLED,
            details={"extra_key": "extra_value"},
        )
        assert err.details["extra_key"] == "extra_value"
        assert err.details["reason"] == "env_var_disabled"


# ---------------------------------------------------------------------------
# AuthenticationError.__str__ without env_var (line 153)
# ---------------------------------------------------------------------------


class TestAuthenticationErrorStrWithoutEnvVar:
    """AuthenticationError.__str__ when env_var is None."""

    def test_str_without_env_var(self) -> None:
        err = AuthenticationError("bad password")
        result = str(err)
        assert result == "bad password"
        assert "Env var" not in result


# ---------------------------------------------------------------------------
# SSHCommandError.__str__ (lines 230-235)
# ---------------------------------------------------------------------------


class TestSSHCommandErrorStr:
    """SSHCommandError __str__ formatting."""

    def test_str_message_only(self) -> None:
        err = SSHCommandError("command failed")
        assert str(err) == "command failed"

    def test_str_with_command(self) -> None:
        err = SSHCommandError("failed", command="show vlan")
        result = str(err)
        assert "failed" in result
        assert "Command: show vlan" in result

    def test_str_with_command_and_endpoint(self) -> None:
        err = SSHCommandError("failed", command="show vlan", endpoint="192.168.1.2")
        result = str(err)
        assert "Command: show vlan" in result
        assert "Endpoint: 192.168.1.2" in result

    def test_str_with_endpoint_only(self) -> None:
        err = SSHCommandError("failed", endpoint="192.168.1.2")
        result = str(err)
        assert "Endpoint: 192.168.1.2" in result


# ---------------------------------------------------------------------------
# CLIParseError with extra details (line 274)
# ---------------------------------------------------------------------------


class TestCLIParseErrorWithDetails:
    """CLIParseError with extra details dict."""

    def test_with_extra_details(self) -> None:
        err = CLIParseError(
            "parse failed",
            command="show vlan",
            details={"extra": "context"},
        )
        assert err.details["command"] == "show vlan"
        assert err.details["extra"] == "context"
