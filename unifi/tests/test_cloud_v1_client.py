"""Tests for the CloudV1Client — UniFi Cloud V1 API client."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from unifi.api.cloud_v1_client import (
    _BACKOFF_MAX,
    CloudV1Client,
    normalize_cloud_v1_response,
)
from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, AuthenticationError, NetworkError, RateLimitError

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_log_propagation() -> Iterator[None]:
    """Ensure the ``unifi`` logger propagates to the root logger during tests.

    The server module sets ``propagate = False`` on the ``unifi`` logger at
    import time.  This fixture temporarily enables propagation so that
    ``caplog``-based assertions work.
    """
    unifi_logger = logging.getLogger("unifi")
    original_propagate = unifi_logger.propagate
    unifi_logger.propagate = True
    yield
    unifi_logger.propagate = original_propagate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_REQUEST = httpx.Request("GET", "https://fake")


def _mock_response(
    status_code: int = 200,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    text: str = "",
) -> httpx.Response:
    """Build a fake httpx.Response for testing."""
    content = json.dumps(json_data).encode() if json_data is not None else text.encode()

    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers or {},
        request=_FAKE_REQUEST,
    )


def _cloud_v1_envelope(
    data: Any = None,
    status_code: int = 200,
    trace_id: str = "test-trace-123",
) -> dict[str, Any]:
    """Build a Cloud V1 response envelope."""
    return {
        "data": data,
        "httpStatusCode": status_code,
        "traceId": trace_id,
    }


# ---------------------------------------------------------------------------
# Construction & initialisation
# ---------------------------------------------------------------------------


class TestConstruction:
    """Tests for CloudV1Client.__init__ configuration."""

    def test_base_url_default(self) -> None:
        client = CloudV1Client(api_key="test-key")
        assert client._base_url == "https://api.ui.com/v1/"

    def test_base_url_custom(self) -> None:
        client = CloudV1Client(api_key="test-key", base_url="https://custom.api.com/v2")
        assert client._base_url == "https://custom.api.com/v2/"

    def test_base_url_trailing_slash_normalised(self) -> None:
        client = CloudV1Client(api_key="test-key", base_url="https://api.ui.com/v1/")
        assert client._base_url == "https://api.ui.com/v1/"

    def test_default_timeout(self) -> None:
        client = CloudV1Client(api_key="test-key")
        assert client._timeout == 30.0

    def test_custom_timeout(self) -> None:
        client = CloudV1Client(api_key="test-key", timeout=10.0)
        assert client._timeout == 10.0

    def test_ssl_verification_enabled(self) -> None:
        """Cloud V1 is a public API — SSL must always be verified."""
        client = CloudV1Client(api_key="test-key")
        assert client._client._transport._pool._ssl_context.verify_mode.name != "CERT_NONE"

    def test_rate_limit_remaining_initially_none(self) -> None:
        client = CloudV1Client(api_key="test-key")
        assert client.rate_limit_remaining is None


# ---------------------------------------------------------------------------
# Auth header injection
# ---------------------------------------------------------------------------


class TestAuthHeader:
    """Tests that the X-API-KEY header is correctly set."""

    def test_api_key_header_present(self) -> None:
        client = CloudV1Client(api_key="my-secret-key")
        assert client._client.headers["x-api-key"] == "my-secret-key"

    def test_accept_json_header_present(self) -> None:
        client = CloudV1Client(api_key="test-key")
        assert client._client.headers["accept"] == "application/json"

    @pytest.mark.asyncio
    async def test_api_key_redacted_in_debug_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(200, json_data=envelope)

        with caplog.at_level(logging.DEBUG, logger="unifi.api.cloud_v1_client"):
            async with CloudV1Client(api_key="super-secret-key-12345") as client:
                client._client.request = AsyncMock(return_value=mock_resp)
                await client.get("sites")

        assert "super-secret-key-12345" not in caplog.text
        assert "***" in caplog.text


# ---------------------------------------------------------------------------
# Cloud V1 envelope normalization
# ---------------------------------------------------------------------------


class TestNormalizeCloudV1Response:
    """Tests for the normalize_cloud_v1_response function."""

    def test_list_data_unwrapped(self) -> None:
        raw = _cloud_v1_envelope(data=[{"id": "1"}, {"id": "2"}])
        result = normalize_cloud_v1_response(raw)

        assert isinstance(result, NormalizedResponse)
        assert len(result.data) == 2
        assert result.count == 2
        assert result.data[0]["id"] == "1"

    def test_dict_data_wrapped_in_list(self) -> None:
        raw = _cloud_v1_envelope(data={"id": "single-item", "name": "site1"})
        result = normalize_cloud_v1_response(raw)

        assert len(result.data) == 1
        assert result.data[0]["id"] == "single-item"
        assert result.count == 1

    def test_none_data_returns_empty_list(self) -> None:
        raw = _cloud_v1_envelope(data=None)
        result = normalize_cloud_v1_response(raw)

        assert result.data == []
        assert result.count == 0

    def test_missing_data_key_returns_empty_list(self) -> None:
        raw = {"httpStatusCode": 200, "traceId": "abc"}
        result = normalize_cloud_v1_response(raw)

        assert result.data == []
        assert result.count == 0

    def test_meta_includes_trace_id(self) -> None:
        raw = _cloud_v1_envelope(data=[], trace_id="trace-xyz")
        result = normalize_cloud_v1_response(raw)

        assert result.meta["traceId"] == "trace-xyz"

    def test_meta_includes_http_status_code(self) -> None:
        raw = _cloud_v1_envelope(data=[], status_code=200)
        result = normalize_cloud_v1_response(raw)

        assert result.meta["httpStatusCode"] == 200

    def test_total_count_is_none(self) -> None:
        """Cloud V1 does not provide pagination metadata in the envelope."""
        raw = _cloud_v1_envelope(data=[{"id": "1"}])
        result = normalize_cloud_v1_response(raw)

        assert result.total_count is None

    def test_error_status_in_envelope_raises_api_error(self) -> None:
        raw = {
            "data": None,
            "httpStatusCode": 404,
            "traceId": "err-trace",
            "message": "Resource not found",
        }

        with pytest.raises(APIError) as exc_info:
            normalize_cloud_v1_response(raw)

        assert exc_info.value.status_code == 404
        assert "Resource not found" in exc_info.value.message

    def test_error_envelope_with_error_field(self) -> None:
        raw = {
            "data": None,
            "httpStatusCode": 500,
            "traceId": "err-trace",
            "error": "Internal server error",
        }

        with pytest.raises(APIError) as exc_info:
            normalize_cloud_v1_response(raw)

        assert "Internal server error" in exc_info.value.message

    def test_error_envelope_fallback_message(self) -> None:
        raw = {
            "data": None,
            "httpStatusCode": 400,
            "traceId": "err-trace",
        }

        with pytest.raises(APIError) as exc_info:
            normalize_cloud_v1_response(raw)

        assert "status 400" in exc_info.value.message

    def test_non_standard_data_type_wrapped(self) -> None:
        """Non-dict, non-list data is wrapped for safety."""
        raw = _cloud_v1_envelope(data="unexpected-string")
        result = normalize_cloud_v1_response(raw)

        assert len(result.data) == 1
        assert result.data[0] == {"value": "unexpected-string"}

    def test_empty_list_data(self) -> None:
        raw = _cloud_v1_envelope(data=[])
        result = normalize_cloud_v1_response(raw)

        assert result.data == []
        assert result.count == 0


# ---------------------------------------------------------------------------
# Successful requests
# ---------------------------------------------------------------------------


class TestSuccessfulRequests:
    """Tests for successful GET responses."""

    @pytest.mark.asyncio
    async def test_get_returns_json(self) -> None:
        envelope = _cloud_v1_envelope(data=[{"id": "site-1"}])
        mock_resp = _mock_response(200, json_data=envelope)

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            result = await client.get("sites")

        assert result == envelope

    @pytest.mark.asyncio
    async def test_get_passes_params(self) -> None:
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(200, json_data=envelope)

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get("sites", params={"limit": "10"})

            call_kwargs = client._client.request.call_args
            assert call_kwargs.kwargs["params"] == {"limit": "10"}

    @pytest.mark.asyncio
    async def test_get_with_no_params(self) -> None:
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(200, json_data=envelope)

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get("sites")

            call_kwargs = client._client.request.call_args
            assert call_kwargs.kwargs["params"] is None

    @pytest.mark.asyncio
    async def test_get_uses_get_method(self) -> None:
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(200, json_data=envelope)

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get("sites")

            call_args = client._client.request.call_args
            assert call_args.args[0] == "GET"

    @pytest.mark.asyncio
    async def test_get_normalized_returns_normalized_response(self) -> None:
        envelope = _cloud_v1_envelope(data=[{"id": "s1"}, {"id": "s2"}])
        mock_resp = _mock_response(200, json_data=envelope)

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            result = await client.get_normalized("sites")

        assert isinstance(result, NormalizedResponse)
        assert len(result.data) == 2
        assert result.count == 2

    @pytest.mark.asyncio
    async def test_get_normalized_passes_params(self) -> None:
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(200, json_data=envelope)

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get_normalized("sites", params={"q": "test"})

            call_kwargs = client._client.request.call_args
            assert call_kwargs.kwargs["params"] == {"q": "test"}


# ---------------------------------------------------------------------------
# Error status code mapping
# ---------------------------------------------------------------------------


class TestErrorStatusCodeMapping:
    """Tests that HTTP error codes map to the correct error types."""

    @pytest.mark.asyncio
    async def test_401_raises_authentication_error(self) -> None:
        mock_resp = _mock_response(401, text="Unauthorized")

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(AuthenticationError) as exc_info:
                await client.get("sites")

            err = exc_info.value
            assert err.env_var == "UNIFI_API_KEY"
            assert err.status_code == 401
            assert err.endpoint == "sites"

    @pytest.mark.asyncio
    async def test_403_raises_authentication_error_with_permissions_hint(self) -> None:
        mock_resp = _mock_response(403, text="Forbidden")

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(AuthenticationError) as exc_info:
                await client.get("sites")

            err = exc_info.value
            assert err.env_var == "UNIFI_API_KEY"
            assert "permissions" in err.message.lower()
            assert err.details.get("hint") is not None

    @pytest.mark.asyncio
    async def test_404_raises_api_error(self) -> None:
        mock_resp = _mock_response(404, text="Not Found")

        async with CloudV1Client(api_key="key", max_retries=0) as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get("nonexistent")

            err = exc_info.value
            assert err.status_code == 404
            assert err.endpoint == "nonexistent"

    @pytest.mark.asyncio
    async def test_500_raises_api_error_with_retry_hint(self) -> None:
        mock_resp = _mock_response(500, text="Internal Server Error")

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get("sites")

            err = exc_info.value
            assert err.status_code == 500
            assert err.retry_hint is not None
            assert "retry" in err.retry_hint.lower()

    @pytest.mark.asyncio
    async def test_502_raises_api_error(self) -> None:
        mock_resp = _mock_response(502, text="Bad Gateway")

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get("sites")

            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_503_raises_api_error(self) -> None:
        mock_resp = _mock_response(503, text="Service Unavailable")

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get("sites")

            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_400_raises_api_error(self) -> None:
        mock_resp = _mock_response(400, text="Bad Request")

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get("sites")

            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_api_error_includes_response_body(self) -> None:
        mock_resp = _mock_response(500, text="detailed error info from server")

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get("sites")

            assert exc_info.value.response_body == "detailed error info from server"


# ---------------------------------------------------------------------------
# Rate limit tracking
# ---------------------------------------------------------------------------


class TestRateLimitTracking:
    """Tests for rate-limit quota tracking via X-RateLimit-Remaining header."""

    @pytest.mark.asyncio
    async def test_remaining_tracked_from_header(self) -> None:
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(
            200,
            json_data=envelope,
            headers={"X-RateLimit-Remaining": "8500"},
        )

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get("sites")

            assert client.rate_limit_remaining == 8500

    @pytest.mark.asyncio
    async def test_remaining_none_when_header_absent(self) -> None:
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(200, json_data=envelope)

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get("sites")

            assert client.rate_limit_remaining is None

    @pytest.mark.asyncio
    async def test_low_quota_warning_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(
            200,
            json_data=envelope,
            headers={"X-RateLimit-Remaining": "1500"},
        )

        with caplog.at_level(logging.WARNING, logger="unifi.api.cloud_v1_client"):
            async with CloudV1Client(api_key="key") as client:
                client._client.request = AsyncMock(return_value=mock_resp)
                await client.get("sites")

        assert "rate-limit quota low" in caplog.text.lower()
        assert "1500" in caplog.text

    @pytest.mark.asyncio
    async def test_above_threshold_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(
            200,
            json_data=envelope,
            headers={"X-RateLimit-Remaining": "5000"},
        )

        with caplog.at_level(logging.WARNING, logger="unifi.api.cloud_v1_client"):
            async with CloudV1Client(api_key="key") as client:
                client._client.request = AsyncMock(return_value=mock_resp)
                await client.get("sites")

        assert "rate-limit quota low" not in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_invalid_remaining_header_ignored(self) -> None:
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(
            200,
            json_data=envelope,
            headers={"X-RateLimit-Remaining": "not-a-number"},
        )

        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get("sites")

            assert client.rate_limit_remaining is None

    @pytest.mark.asyncio
    async def test_boundary_at_threshold_triggers_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Exactly at threshold (1999) should still trigger warning."""
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(
            200,
            json_data=envelope,
            headers={"X-RateLimit-Remaining": "1999"},
        )

        with caplog.at_level(logging.WARNING, logger="unifi.api.cloud_v1_client"):
            async with CloudV1Client(api_key="key") as client:
                client._client.request = AsyncMock(return_value=mock_resp)
                await client.get("sites")

        assert "rate-limit quota low" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_exactly_at_threshold_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Exactly at threshold value (2000) should NOT trigger warning."""
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(
            200,
            json_data=envelope,
            headers={"X-RateLimit-Remaining": "2000"},
        )

        with caplog.at_level(logging.WARNING, logger="unifi.api.cloud_v1_client"):
            async with CloudV1Client(api_key="key") as client:
                client._client.request = AsyncMock(return_value=mock_resp)
                await client.get("sites")

        assert "rate-limit quota low" not in caplog.text.lower()


# ---------------------------------------------------------------------------
# 429 handling with exponential backoff
# ---------------------------------------------------------------------------


class TestRateLimitRetry:
    """Tests for 429 retry with exponential backoff."""

    @pytest.mark.asyncio
    async def test_429_retries_and_succeeds(self) -> None:
        """First request returns 429, second succeeds."""
        rate_limit_resp = _mock_response(429, text="Too Many Requests")
        success_envelope = _cloud_v1_envelope(data=[{"id": "1"}])
        success_resp = _mock_response(200, json_data=success_envelope)

        async with CloudV1Client(api_key="key", max_retries=3) as client:
            client._client.request = AsyncMock(side_effect=[rate_limit_resp, success_resp])

            with patch("unifi.api.cloud_v1_client.asyncio.sleep", new_callable=AsyncMock):
                result = await client.get("sites")

        assert result == success_envelope

    @pytest.mark.asyncio
    async def test_429_exhausts_retries_raises_rate_limit_error(self) -> None:
        """All retries fail with 429."""
        rate_limit_resp = _mock_response(429, text="Too Many Requests")

        async with CloudV1Client(api_key="key", max_retries=2) as client:
            # 3 total attempts (initial + 2 retries), all return 429
            client._client.request = AsyncMock(return_value=rate_limit_resp)

            with (
                patch("unifi.api.cloud_v1_client.asyncio.sleep", new_callable=AsyncMock),
                pytest.raises(RateLimitError) as exc_info,
            ):
                await client.get("sites")

            assert exc_info.value.status_code == 429
            assert exc_info.value.endpoint == "sites"

    @pytest.mark.asyncio
    async def test_429_retry_uses_exponential_backoff(self) -> None:
        """Verify that sleep delays increase exponentially."""
        rate_limit_resp = _mock_response(429, text="Too Many Requests")
        success_envelope = _cloud_v1_envelope(data=[])
        success_resp = _mock_response(200, json_data=success_envelope)

        async with CloudV1Client(api_key="key", max_retries=3) as client:
            client._client.request = AsyncMock(
                side_effect=[rate_limit_resp, rate_limit_resp, success_resp]
            )

            mock_sleep = AsyncMock()
            with (
                patch("unifi.api.cloud_v1_client.asyncio.sleep", mock_sleep),
                patch("unifi.api.cloud_v1_client.random.random", return_value=0.5),
            ):
                await client.get("sites")

            assert mock_sleep.call_count == 2
            # With random()=0.5, jitter factor = 0.5*(2*0.5-1) = 0, so no jitter
            first_delay = mock_sleep.call_args_list[0].args[0]
            second_delay = mock_sleep.call_args_list[1].args[0]
            # First delay should be ~1s, second ~2s (exponential)
            assert 0.5 <= first_delay <= 1.5
            assert 1.0 <= second_delay <= 3.0

    @pytest.mark.asyncio
    async def test_429_retry_respects_retry_after_header(self) -> None:
        """Retry-After header should be used as the delay floor."""
        rate_limit_resp = _mock_response(
            429,
            text="Too Many Requests",
            headers={"Retry-After": "10"},
        )
        success_envelope = _cloud_v1_envelope(data=[])
        success_resp = _mock_response(200, json_data=success_envelope)

        async with CloudV1Client(api_key="key", max_retries=2) as client:
            client._client.request = AsyncMock(side_effect=[rate_limit_resp, success_resp])

            mock_sleep = AsyncMock()
            with (
                patch("unifi.api.cloud_v1_client.asyncio.sleep", mock_sleep),
                patch("unifi.api.cloud_v1_client.random.random", return_value=0.5),
            ):
                await client.get("sites")

            # Should use Retry-After (10) since it's larger than initial backoff (1)
            delay = mock_sleep.call_args_list[0].args[0]
            assert delay >= 9.0  # 10 with potential negative jitter

    @pytest.mark.asyncio
    async def test_429_retry_delay_capped_at_max(self) -> None:
        """Backoff delay should never exceed _BACKOFF_MAX."""
        rate_limit_resp = _mock_response(
            429,
            text="Too Many Requests",
            headers={"Retry-After": "120"},  # Larger than max
        )
        success_envelope = _cloud_v1_envelope(data=[])
        success_resp = _mock_response(200, json_data=success_envelope)

        async with CloudV1Client(api_key="key", max_retries=2) as client:
            client._client.request = AsyncMock(side_effect=[rate_limit_resp, success_resp])

            mock_sleep = AsyncMock()
            with (
                patch("unifi.api.cloud_v1_client.asyncio.sleep", mock_sleep),
                patch("unifi.api.cloud_v1_client.random.random", return_value=0.5),
            ):
                await client.get("sites")

            delay = mock_sleep.call_args_list[0].args[0]
            assert delay <= _BACKOFF_MAX

    @pytest.mark.asyncio
    async def test_429_retry_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        rate_limit_resp = _mock_response(429, text="Too Many Requests")
        success_envelope = _cloud_v1_envelope(data=[])
        success_resp = _mock_response(200, json_data=success_envelope)

        with caplog.at_level(logging.WARNING, logger="unifi.api.cloud_v1_client"):
            async with CloudV1Client(api_key="key", max_retries=2) as client:
                client._client.request = AsyncMock(side_effect=[rate_limit_resp, success_resp])

                with patch("unifi.api.cloud_v1_client.asyncio.sleep", new_callable=AsyncMock):
                    await client.get("sites")

        assert "Rate limited (429)" in caplog.text
        assert "Retrying" in caplog.text

    @pytest.mark.asyncio
    async def test_non_429_errors_not_retried(self) -> None:
        """Non-429 errors should propagate immediately, no retry."""
        mock_resp = _mock_response(500, text="Server Error")

        async with CloudV1Client(api_key="key", max_retries=3) as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get("sites")

            assert exc_info.value.status_code == 500
            # Should only have been called once (no retries)
            assert client._client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_auth_errors_not_retried(self) -> None:
        """401/403 should propagate immediately, no retry."""
        mock_resp = _mock_response(401, text="Unauthorized")

        async with CloudV1Client(api_key="key", max_retries=3) as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(AuthenticationError):
                await client.get("sites")

            assert client._client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_max_retries_zero_no_retry(self) -> None:
        """With max_retries=0, 429 should be raised immediately."""
        mock_resp = _mock_response(429, text="Too Many Requests")

        async with CloudV1Client(api_key="key", max_retries=0) as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(RateLimitError):
                await client.get("sites")

            assert client._client.request.call_count == 1


# ---------------------------------------------------------------------------
# Connection failure handling
# ---------------------------------------------------------------------------


class TestConnectionFailures:
    """Tests for transport-level error handling."""

    @pytest.mark.asyncio
    async def test_timeout_raises_network_error(self) -> None:
        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(side_effect=httpx.ReadTimeout("read timed out"))

            with pytest.raises(NetworkError) as exc_info:
                await client.get("sites")

            assert "timed out" in exc_info.value.message.lower()
            assert exc_info.value.endpoint == "sites"

    @pytest.mark.asyncio
    async def test_connect_timeout_raises_network_error(self) -> None:
        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(
                side_effect=httpx.ConnectTimeout("connect timed out")
            )

            with pytest.raises(NetworkError) as exc_info:
                await client.get("sites")

            assert "timed out" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_connection_refused_raises_network_error(self) -> None:
        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

            with pytest.raises(NetworkError) as exc_info:
                await client.get("sites")

            assert "refused" in exc_info.value.message.lower()
            assert exc_info.value.endpoint == "sites"

    @pytest.mark.asyncio
    async def test_ssl_error_raises_network_error_with_hint(self) -> None:
        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(
                side_effect=httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED")
            )

            with pytest.raises(NetworkError) as exc_info:
                await client.get("sites")

            err = exc_info.value
            assert "ssl" in err.message.lower()
            assert err.retry_hint is not None
            assert "ssl" in err.retry_hint.lower()

    @pytest.mark.asyncio
    async def test_generic_http_error_raises_network_error(self) -> None:
        async with CloudV1Client(api_key="key") as client:
            client._client.request = AsyncMock(side_effect=httpx.HTTPError("Something went wrong"))

            with pytest.raises(NetworkError) as exc_info:
                await client.get("sites")

            assert exc_info.value.endpoint == "sites"

    @pytest.mark.asyncio
    async def test_network_errors_not_retried(self) -> None:
        """Network errors should propagate immediately, not be retried."""
        async with CloudV1Client(api_key="key", max_retries=3) as client:
            client._client.request = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

            with pytest.raises(NetworkError):
                await client.get("sites")

            assert client._client.request.call_count == 1


# ---------------------------------------------------------------------------
# Logging verification
# ---------------------------------------------------------------------------


class TestLogging:
    """Tests for request/response logging output."""

    @pytest.mark.asyncio
    async def test_info_log_on_success(self, caplog: pytest.LogCaptureFixture) -> None:
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(200, json_data=envelope)

        with caplog.at_level(logging.INFO, logger="unifi.api.cloud_v1_client"):
            async with CloudV1Client(api_key="key") as client:
                client._client.request = AsyncMock(return_value=mock_resp)
                await client.get("sites")

        assert "200" in caplog.text
        assert "sites" in caplog.text

    @pytest.mark.asyncio
    async def test_warning_log_on_non_200(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_resp = _mock_response(404, text="Not Found")

        with caplog.at_level(logging.WARNING, logger="unifi.api.cloud_v1_client"):
            async with CloudV1Client(api_key="key") as client:
                client._client.request = AsyncMock(return_value=mock_resp)

                with pytest.raises(APIError):
                    await client.get("nonexistent")

        assert "Non-200 response" in caplog.text
        assert "404" in caplog.text

    @pytest.mark.asyncio
    async def test_warning_log_on_slow_request(self, caplog: pytest.LogCaptureFixture) -> None:
        envelope = _cloud_v1_envelope(data=[])
        mock_resp = _mock_response(200, json_data=envelope)

        with caplog.at_level(logging.WARNING, logger="unifi.api.cloud_v1_client"):
            async with CloudV1Client(api_key="key") as client:
                call_count = 0

                def fake_monotonic() -> float:
                    nonlocal call_count
                    call_count += 1
                    if call_count <= 1:
                        return 1000.0
                    return 1006.0  # 6s elapsed > 5s threshold

                client._client.request = AsyncMock(return_value=mock_resp)
                with patch(
                    "unifi.api.cloud_v1_client.time.monotonic",
                    side_effect=fake_monotonic,
                ):
                    await client.get("sites")

        assert "Slow request" in caplog.text

    @pytest.mark.asyncio
    async def test_error_log_on_connection_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.ERROR, logger="unifi.api.cloud_v1_client"):
            async with CloudV1Client(api_key="key") as client:
                client._client.request = AsyncMock(
                    side_effect=httpx.ConnectError("Connection refused")
                )

                with pytest.raises(NetworkError):
                    await client.get("sites")

        assert "Connection refused" in caplog.text

    @pytest.mark.asyncio
    async def test_error_log_on_auth_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_resp = _mock_response(401, text="Unauthorized")

        with caplog.at_level(logging.ERROR, logger="unifi.api.cloud_v1_client"):
            async with CloudV1Client(api_key="key") as client:
                client._client.request = AsyncMock(return_value=mock_resp)

                with pytest.raises(AuthenticationError):
                    await client.get("sites")

        assert "Authentication failed" in caplog.text

    @pytest.mark.asyncio
    async def test_debug_log_on_close(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="unifi.api.cloud_v1_client"):
            client = CloudV1Client(api_key="key")
            await client.close()

        assert "Closed CloudV1Client" in caplog.text


# ---------------------------------------------------------------------------
# Async context manager
# ---------------------------------------------------------------------------


class TestAsyncContextManager:
    """Tests for async with usage."""

    @pytest.mark.asyncio
    async def test_context_manager_returns_client(self) -> None:
        async with CloudV1Client(api_key="key") as client:
            assert isinstance(client, CloudV1Client)

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self) -> None:
        client = CloudV1Client(api_key="key")

        async with client:
            pass

        assert client._client.is_closed

    @pytest.mark.asyncio
    async def test_context_manager_closes_on_exception(self) -> None:
        client = CloudV1Client(api_key="key")

        with pytest.raises(RuntimeError):
            async with client:
                raise RuntimeError("boom")

        assert client._client.is_closed

    @pytest.mark.asyncio
    async def test_explicit_close(self) -> None:
        client = CloudV1Client(api_key="key")
        await client.close()
        assert client._client.is_closed


# ---------------------------------------------------------------------------
# _parse_retry_after (static method)
# ---------------------------------------------------------------------------


class TestParseRetryAfter:
    """Tests for the Retry-After header parser."""

    def test_integer_value(self) -> None:
        resp = _mock_response(429, headers={"Retry-After": "60"})
        assert CloudV1Client._parse_retry_after(resp) == 60.0

    def test_float_value(self) -> None:
        resp = _mock_response(429, headers={"Retry-After": "30.5"})
        assert CloudV1Client._parse_retry_after(resp) == 30.5

    def test_missing_header(self) -> None:
        resp = _mock_response(429)
        assert CloudV1Client._parse_retry_after(resp) is None

    def test_non_numeric_header(self) -> None:
        resp = _mock_response(429, headers={"Retry-After": "Wed, 21 Oct 2025 07:28:00 GMT"})
        assert CloudV1Client._parse_retry_after(resp) is None

    def test_empty_header(self) -> None:
        resp = _mock_response(429, headers={"Retry-After": ""})
        assert CloudV1Client._parse_retry_after(resp) is None
