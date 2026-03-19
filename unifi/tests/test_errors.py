# SPDX-License-Identifier: MIT
"""Tests for the structured error hierarchy in unifi.src.errors."""

from __future__ import annotations

import pytest

from unifi.src.errors import (
    APIError,
    AuthenticationError,
    NetexError,
    NetworkError,
    RateLimitError,
    ValidationError,
    WriteGateError,
    WriteGateReason,
)


# ---------------------------------------------------------------------------
# NetexError (base)
# ---------------------------------------------------------------------------

class TestNetexError:
    """Tests for the base NetexError class."""

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
            endpoint="/api/s/default/stat/device",
            retry_hint="Try again in 10 seconds",
            details={"request_id": "abc123"},
        )
        assert err.status_code == 500
        assert err.endpoint == "/api/s/default/stat/device"
        assert err.retry_hint == "Try again in 10 seconds"
        assert err.details == {"request_id": "abc123"}

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

    def test_repr_omits_none_and_empty_details(self) -> None:
        err = NetexError("msg")
        r = repr(err)
        assert "endpoint" not in r
        assert "details" not in r

    def test_is_exception(self) -> None:
        err = NetexError("test")
        assert isinstance(err, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(NetexError, match="boom"):
            raise NetexError("boom")

    def test_details_default_is_empty_dict(self) -> None:
        err = NetexError("test")
        assert err.details == {}
        # Verify it's a new dict instance, not a shared mutable default
        err.details["key"] = "value"
        err2 = NetexError("test2")
        assert err2.details == {}


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------

class TestInheritance:
    """All error subclasses should be catchable as NetexError."""

    @pytest.mark.parametrize(
        "error_class, kwargs",
        [
            (AuthenticationError, {"message": "auth fail"}),
            (RateLimitError, {"message": "rate limited"}),
            (NetworkError, {"message": "timeout"}),
            (APIError, {"message": "bad request", "status_code": 400}),
            (ValidationError, {"message": "invalid input"}),
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

    def test_catch_all_subclasses_as_base(self) -> None:
        """Verify the catch-all pattern works in a try/except."""
        errors: list[NetexError] = [
            AuthenticationError("a"),
            RateLimitError("b"),
            NetworkError("c"),
            APIError("d", status_code=500),
            ValidationError("e"),
            WriteGateError("f", reason=WriteGateReason.APPLY_FLAG_MISSING),
        ]
        for err in errors:
            with pytest.raises(NetexError):
                raise err


# ---------------------------------------------------------------------------
# AuthenticationError
# ---------------------------------------------------------------------------

class TestAuthenticationError:
    """Tests for AuthenticationError."""

    def test_status_code_is_401(self) -> None:
        err = AuthenticationError("invalid key")
        assert err.status_code == 401

    def test_env_var_stored(self) -> None:
        err = AuthenticationError("missing key", env_var="UNIFI_LOCAL_KEY")
        assert err.env_var == "UNIFI_LOCAL_KEY"
        assert err.details["env_var"] == "UNIFI_LOCAL_KEY"

    def test_retry_hint_includes_env_var(self) -> None:
        err = AuthenticationError("bad key", env_var="UNIFI_API_KEY")
        assert err.retry_hint is not None
        assert "UNIFI_API_KEY" in err.retry_hint

    def test_str_includes_env_var(self) -> None:
        err = AuthenticationError("no auth", env_var="UNIFI_LOCAL_KEY")
        result = str(err)
        assert "Env var: UNIFI_LOCAL_KEY" in result

    def test_without_env_var(self) -> None:
        err = AuthenticationError("unknown auth failure")
        assert err.env_var is None
        assert err.retry_hint is None

    def test_str_without_env_var(self) -> None:
        err = AuthenticationError("unknown auth failure")
        result = str(err)
        assert "unknown auth failure" in result
        assert "Env var:" not in result

    def test_with_endpoint(self) -> None:
        err = AuthenticationError(
            "401 from API",
            env_var="UNIFI_LOCAL_KEY",
            endpoint="/api/s/default/stat/device",
        )
        assert err.endpoint == "/api/s/default/stat/device"

    def test_custom_details_merged(self) -> None:
        err = AuthenticationError(
            "auth fail",
            env_var="UNIFI_LOCAL_KEY",
            details={"response": "Unauthorized"},
        )
        assert err.details["env_var"] == "UNIFI_LOCAL_KEY"
        assert err.details["response"] == "Unauthorized"


# ---------------------------------------------------------------------------
# RateLimitError
# ---------------------------------------------------------------------------

class TestRateLimitError:
    """Tests for RateLimitError."""

    def test_status_code_is_429(self) -> None:
        err = RateLimitError("too many requests")
        assert err.status_code == 429

    def test_retry_after_seconds(self) -> None:
        err = RateLimitError("rate limited", retry_after_seconds=30)
        assert err.retry_after_seconds == 30
        assert err.details["retry_after_seconds"] == 30

    def test_retry_hint_generated(self) -> None:
        err = RateLimitError("quota exceeded", retry_after_seconds=60)
        assert err.retry_hint is not None
        assert "60" in err.retry_hint

    def test_without_retry_after(self) -> None:
        err = RateLimitError("rate limited")
        assert err.retry_after_seconds is None
        assert err.retry_hint is None

    def test_float_retry_after(self) -> None:
        err = RateLimitError("throttled", retry_after_seconds=30.5)
        assert err.retry_after_seconds == 30.5
        # Hint should show rounded value
        assert "30" in str(err)

    def test_with_endpoint(self) -> None:
        err = RateLimitError(
            "rate limited",
            retry_after_seconds=10,
            endpoint="/v1/sites",
        )
        assert err.endpoint == "/v1/sites"

    def test_custom_details_merged(self) -> None:
        err = RateLimitError(
            "rate limited",
            retry_after_seconds=30,
            details={"quota_remaining": 0},
        )
        assert err.details["retry_after_seconds"] == 30
        assert err.details["quota_remaining"] == 0


# ---------------------------------------------------------------------------
# NetworkError
# ---------------------------------------------------------------------------

class TestNetworkError:
    """Tests for NetworkError."""

    def test_no_status_code(self) -> None:
        err = NetworkError("connection timeout")
        assert err.status_code is None

    def test_default_retry_hint(self) -> None:
        err = NetworkError("DNS resolution failed")
        assert err.retry_hint is not None
        assert "connectivity" in err.retry_hint.lower()

    def test_custom_retry_hint(self) -> None:
        err = NetworkError(
            "SSL handshake failed",
            retry_hint="Verify SSL certificate configuration",
        )
        assert err.retry_hint == "Verify SSL certificate configuration"

    def test_with_endpoint(self) -> None:
        err = NetworkError(
            "timeout after 30s",
            endpoint="https://192.168.1.1/api/s/default/stat/device",
        )
        assert err.endpoint is not None

    def test_with_details(self) -> None:
        err = NetworkError(
            "connection refused",
            details={"host": "192.168.1.1", "port": 443},
        )
        assert err.details["host"] == "192.168.1.1"
        assert err.details["port"] == 443


# ---------------------------------------------------------------------------
# APIError
# ---------------------------------------------------------------------------

class TestAPIError:
    """Tests for APIError."""

    def test_requires_status_code(self) -> None:
        err = APIError("bad request", status_code=400)
        assert err.status_code == 400

    def test_response_body_stored(self) -> None:
        err = APIError(
            "server error",
            status_code=500,
            response_body='{"error": "internal"}',
        )
        assert err.response_body == '{"error": "internal"}'
        assert err.details["response_body"] == '{"error": "internal"}'

    def test_5xx_gets_retry_hint(self) -> None:
        err = APIError("gateway timeout", status_code=504)
        assert err.retry_hint is not None
        assert "retry" in err.retry_hint.lower()

    def test_4xx_no_retry_hint(self) -> None:
        err = APIError("not found", status_code=404)
        assert err.retry_hint is None

    def test_with_endpoint(self) -> None:
        err = APIError(
            "forbidden",
            status_code=403,
            endpoint="/api/s/default/cmd/sitemgr",
        )
        assert err.endpoint == "/api/s/default/cmd/sitemgr"

    def test_without_response_body(self) -> None:
        err = APIError("error", status_code=500)
        assert err.response_body is None

    def test_custom_details_merged_with_response_body(self) -> None:
        err = APIError(
            "error",
            status_code=500,
            response_body="oops",
            details={"trace_id": "xyz"},
        )
        assert err.details["response_body"] == "oops"
        assert err.details["trace_id"] == "xyz"


# ---------------------------------------------------------------------------
# ValidationError
# ---------------------------------------------------------------------------

class TestValidationError:
    """Tests for ValidationError."""

    def test_no_status_code(self) -> None:
        err = ValidationError("invalid MAC address format")
        assert err.status_code is None

    def test_no_retry_hint(self) -> None:
        err = ValidationError("schema mismatch")
        assert err.retry_hint is None

    def test_with_details(self) -> None:
        err = ValidationError(
            "invalid site_id",
            details={"field": "site_id", "value": "", "constraint": "non-empty string"},
        )
        assert err.details["field"] == "site_id"

    def test_str_is_clean(self) -> None:
        err = ValidationError("bad input")
        assert str(err) == "bad input"


# ---------------------------------------------------------------------------
# WriteGateError
# ---------------------------------------------------------------------------

class TestWriteGateError:
    """Tests for WriteGateError."""

    def test_env_var_disabled(self) -> None:
        err = WriteGateError(
            "Write operations are disabled",
            reason=WriteGateReason.ENV_VAR_DISABLED,
        )
        assert err.reason == WriteGateReason.ENV_VAR_DISABLED
        assert err.details["reason"] == "env_var_disabled"

    def test_apply_flag_missing(self) -> None:
        err = WriteGateError(
            "Missing --apply flag",
            reason=WriteGateReason.APPLY_FLAG_MISSING,
        )
        assert err.reason == WriteGateReason.APPLY_FLAG_MISSING
        assert err.details["reason"] == "apply_flag_missing"

    def test_no_status_code(self) -> None:
        err = WriteGateError("blocked", reason=WriteGateReason.ENV_VAR_DISABLED)
        assert err.status_code is None

    def test_no_endpoint(self) -> None:
        err = WriteGateError("blocked", reason=WriteGateReason.ENV_VAR_DISABLED)
        assert err.endpoint is None

    def test_retry_hint_for_env_var(self) -> None:
        err = WriteGateError("blocked", reason=WriteGateReason.ENV_VAR_DISABLED)
        assert err.retry_hint is not None
        assert "UNIFI_WRITE_ENABLED" in err.retry_hint

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
        assert "Write blocked" in result
        assert "Hint:" in result

    def test_custom_details_merged(self) -> None:
        err = WriteGateError(
            "blocked",
            reason=WriteGateReason.APPLY_FLAG_MISSING,
            details={"command": "port-profile create"},
        )
        assert err.details["reason"] == "apply_flag_missing"
        assert err.details["command"] == "port-profile create"


# ---------------------------------------------------------------------------
# WriteGateReason enum
# ---------------------------------------------------------------------------

class TestWriteGateReason:
    """Tests for the WriteGateReason enum."""

    def test_is_str_enum(self) -> None:
        assert isinstance(WriteGateReason.ENV_VAR_DISABLED, str)
        assert isinstance(WriteGateReason.APPLY_FLAG_MISSING, str)

    def test_values(self) -> None:
        assert WriteGateReason.ENV_VAR_DISABLED == "env_var_disabled"
        assert WriteGateReason.APPLY_FLAG_MISSING == "apply_flag_missing"

    def test_from_string(self) -> None:
        assert WriteGateReason("env_var_disabled") == WriteGateReason.ENV_VAR_DISABLED
        assert WriteGateReason("apply_flag_missing") == WriteGateReason.APPLY_FLAG_MISSING

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            WriteGateReason("invalid_reason")
