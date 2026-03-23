"""Tests for the LocalGatewayClient — UniFi Local Gateway API client."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from unifi.api.local_gateway_client import LocalGatewayClient
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
    import time (module-level ``_configure_logging()``).  This prevents
    pytest's ``caplog`` fixture from capturing log records.  This fixture
    temporarily enables propagation so that ``caplog``-based assertions work.
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
    """Build a fake httpx.Response for testing.

    Uses ``content`` (bytes) so that ``response.json()`` and ``response.text``
    both work correctly with httpx's internal parsing.
    """
    content = json.dumps(json_data).encode() if json_data is not None else text.encode()

    resp = httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers or {},
        request=_FAKE_REQUEST,
    )
    return resp


# ---------------------------------------------------------------------------
# Construction & initialisation
# ---------------------------------------------------------------------------


class TestConstruction:
    """Tests for LocalGatewayClient.__init__ configuration."""

    def test_base_url_formation(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1", api_key="test-key")
        assert client._base_url == "https://192.168.1.1/proxy/network"

    def test_base_url_strips_trailing_slash(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1/", api_key="test-key")
        assert client._base_url == "https://192.168.1.1/proxy/network"

    def test_base_url_preserves_explicit_scheme(self) -> None:
        client = LocalGatewayClient(host="https://unifi.local", api_key="test-key")
        assert client._base_url == "https://unifi.local/proxy/network"

    def test_base_url_preserves_http_scheme(self) -> None:
        client = LocalGatewayClient(host="http://192.168.1.1", api_key="test-key")
        assert client._base_url == "http://192.168.1.1/proxy/network"

    def test_default_verify_ssl_false(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1", api_key="test-key")
        assert client._verify_ssl is False

    def test_custom_verify_ssl_true(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1", api_key="test-key", verify_ssl=True)
        assert client._verify_ssl is True

    def test_default_timeout(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1", api_key="test-key")
        assert client._timeout == 30.0

    def test_custom_timeout(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1", api_key="test-key", timeout=10.0)
        assert client._timeout == 10.0

    def test_ssl_disabled_warning_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            LocalGatewayClient(host="192.168.1.1", api_key="test-key", verify_ssl=False)
        assert "SSL verification is disabled" in caplog.text

    def test_ssl_enabled_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            LocalGatewayClient(host="192.168.1.1", api_key="test-key", verify_ssl=True)
        assert "SSL verification is disabled" not in caplog.text


# ---------------------------------------------------------------------------
# Auth header injection
# ---------------------------------------------------------------------------


class TestAuthHeader:
    """Tests that the X-API-KEY header is correctly set."""

    def test_api_key_header_present(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1", api_key="my-secret-key")
        assert client._client.headers["x-api-key"] == "my-secret-key"

    def test_accept_json_header_present(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1", api_key="test-key")
        assert client._client.headers["accept"] == "application/json"


# ---------------------------------------------------------------------------
# Successful requests
# ---------------------------------------------------------------------------


class TestSuccessfulRequests:
    """Tests for successful GET and POST responses."""

    @pytest.mark.asyncio
    async def test_get_returns_json(self) -> None:
        response_data = {"data": [{"mac": "aa:bb:cc:dd:ee:ff"}], "meta": {"rc": "ok"}}
        mock_resp = _mock_response(200, json_data=response_data)

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            result = await client.get("/api/s/default/stat/device")

        assert result == response_data

    @pytest.mark.asyncio
    async def test_get_passes_params(self) -> None:
        mock_resp = _mock_response(200, json_data={"data": []})

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get("/api/s/default/stat/sta", params={"type": "all"})

            call_kwargs = client._client.request.call_args
            assert call_kwargs.kwargs["params"] == {"type": "all"}

    @pytest.mark.asyncio
    async def test_post_returns_json(self) -> None:
        response_data = {"data": [], "meta": {"rc": "ok"}}
        mock_resp = _mock_response(200, json_data=response_data)

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            result = await client.post("/api/s/default/cmd/devmgr", data={"cmd": "restart"})

        assert result == response_data

    @pytest.mark.asyncio
    async def test_post_passes_json_body(self) -> None:
        mock_resp = _mock_response(200, json_data={"data": []})

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.post("/api/s/default/cmd/devmgr", data={"cmd": "restart"})

            call_kwargs = client._client.request.call_args
            assert call_kwargs.kwargs["json"] == {"cmd": "restart"}

    @pytest.mark.asyncio
    async def test_get_with_no_params(self) -> None:
        mock_resp = _mock_response(200, json_data={"data": []})

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get("/api/s/default/stat/device")

            call_kwargs = client._client.request.call_args
            assert call_kwargs.kwargs["params"] is None

    @pytest.mark.asyncio
    async def test_post_with_no_data(self) -> None:
        mock_resp = _mock_response(200, json_data={"data": []})

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.post("/api/s/default/cmd/devmgr")

            call_kwargs = client._client.request.call_args
            assert call_kwargs.kwargs["json"] is None

    @pytest.mark.asyncio
    async def test_returns_raw_envelope(self) -> None:
        """Client must return the full response envelope, not unwrap it."""
        envelope = {
            "data": [{"name": "USG"}, {"name": "AP-LR"}],
            "meta": {"rc": "ok"},
        }
        mock_resp = _mock_response(200, json_data=envelope)

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            result = await client.get("/api/s/default/stat/device")

        # Both "data" and "meta" should be present — no unwrapping.
        assert "data" in result
        assert "meta" in result
        assert len(result["data"]) == 2


# ---------------------------------------------------------------------------
# Error status code mapping
# ---------------------------------------------------------------------------


class TestErrorStatusCodeMapping:
    """Tests that HTTP error codes map to the correct error types."""

    @pytest.mark.asyncio
    async def test_401_raises_authentication_error(self) -> None:
        mock_resp = _mock_response(401, text="Unauthorized")

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(AuthenticationError) as exc_info:
                await client.get("/api/s/default/stat/device")

            err = exc_info.value
            assert err.env_var == "UNIFI_LOCAL_KEY"
            assert err.status_code == 401
            assert err.endpoint == "/api/s/default/stat/device"

    @pytest.mark.asyncio
    async def test_403_raises_authentication_error_with_permissions_hint(self) -> None:
        mock_resp = _mock_response(403, text="Forbidden")

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(AuthenticationError) as exc_info:
                await client.get("/api/s/default/stat/device")

            err = exc_info.value
            assert err.env_var == "UNIFI_LOCAL_KEY"
            assert "permissions" in err.message.lower()
            assert err.details.get("hint") is not None

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit_error_with_retry_after(self) -> None:
        mock_resp = _mock_response(
            429,
            text="Too Many Requests",
            headers={"Retry-After": "30"},
        )

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(RateLimitError) as exc_info:
                await client.get("/api/s/default/stat/device")

            err = exc_info.value
            assert err.retry_after_seconds == 30.0
            assert err.status_code == 429
            assert err.endpoint == "/api/s/default/stat/device"

    @pytest.mark.asyncio
    async def test_429_without_retry_after_header(self) -> None:
        mock_resp = _mock_response(429, text="Too Many Requests")

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(RateLimitError) as exc_info:
                await client.get("/api/s/default/stat/device")

            assert exc_info.value.retry_after_seconds is None

    @pytest.mark.asyncio
    async def test_429_with_invalid_retry_after_header(self) -> None:
        mock_resp = _mock_response(
            429,
            text="Too Many Requests",
            headers={"Retry-After": "not-a-number"},
        )

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(RateLimitError) as exc_info:
                await client.get("/api/s/default/stat/device")

            assert exc_info.value.retry_after_seconds is None

    @pytest.mark.asyncio
    async def test_404_raises_api_error(self) -> None:
        mock_resp = _mock_response(404, text="Not Found")

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get("/api/s/default/nonexistent")

            err = exc_info.value
            assert err.status_code == 404
            assert err.endpoint == "/api/s/default/nonexistent"

    @pytest.mark.asyncio
    async def test_500_raises_api_error_with_retry_hint(self) -> None:
        mock_resp = _mock_response(500, text="Internal Server Error")

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get("/api/s/default/stat/device")

            err = exc_info.value
            assert err.status_code == 500
            assert err.retry_hint is not None
            assert "retry" in err.retry_hint.lower()

    @pytest.mark.asyncio
    async def test_502_raises_api_error(self) -> None:
        mock_resp = _mock_response(502, text="Bad Gateway")

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get("/api/s/default/stat/device")

            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_503_raises_api_error(self) -> None:
        mock_resp = _mock_response(503, text="Service Unavailable")

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get("/api/s/default/stat/device")

            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_400_raises_api_error(self) -> None:
        mock_resp = _mock_response(400, text="Bad Request")

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.post("/api/s/default/cmd/devmgr", data={"bad": "data"})

            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_api_error_includes_response_body(self) -> None:
        mock_resp = _mock_response(500, text="detailed error info from server")

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get("/api/s/default/stat/device")

            assert exc_info.value.response_body == "detailed error info from server"


# ---------------------------------------------------------------------------
# Connection failure handling
# ---------------------------------------------------------------------------


class TestConnectionFailures:
    """Tests for transport-level error handling."""

    @pytest.mark.asyncio
    async def test_timeout_raises_network_error(self) -> None:
        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(side_effect=httpx.ReadTimeout("read timed out"))

            with pytest.raises(NetworkError) as exc_info:
                await client.get("/api/s/default/stat/device")

            assert "timed out" in exc_info.value.message.lower()
            assert exc_info.value.endpoint == "/api/s/default/stat/device"

    @pytest.mark.asyncio
    async def test_connect_timeout_raises_network_error(self) -> None:
        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(
                side_effect=httpx.ConnectTimeout("connect timed out")
            )

            with pytest.raises(NetworkError) as exc_info:
                await client.get("/api/s/default/stat/device")

            assert "timed out" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_connection_refused_raises_network_error(self) -> None:
        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

            with pytest.raises(NetworkError) as exc_info:
                await client.get("/api/s/default/stat/device")

            assert "refused" in exc_info.value.message.lower()
            assert exc_info.value.endpoint == "/api/s/default/stat/device"

    @pytest.mark.asyncio
    async def test_ssl_error_raises_network_error_with_hint(self) -> None:
        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(
                side_effect=httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED")
            )

            with pytest.raises(NetworkError) as exc_info:
                await client.get("/api/s/default/stat/device")

            err = exc_info.value
            assert "ssl" in err.message.lower()
            assert err.retry_hint == "Check UNIFI_LOCAL_HOST or SSL settings"

    @pytest.mark.asyncio
    async def test_certificate_error_raises_network_error_with_hint(self) -> None:
        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(
                side_effect=httpx.ConnectError("certificate verify failed")
            )

            with pytest.raises(NetworkError) as exc_info:
                await client.get("/api/s/default/stat/device")

            assert exc_info.value.retry_hint == "Check UNIFI_LOCAL_HOST or SSL settings"

    @pytest.mark.asyncio
    async def test_generic_http_error_raises_network_error(self) -> None:
        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(side_effect=httpx.HTTPError("Something went wrong"))

            with pytest.raises(NetworkError) as exc_info:
                await client.get("/api/s/default/stat/device")

            assert exc_info.value.endpoint == "/api/s/default/stat/device"


# ---------------------------------------------------------------------------
# SSL verification toggle
# ---------------------------------------------------------------------------


class TestSSLVerification:
    """Tests for the SSL verification configuration."""

    def test_ssl_disabled_passes_verify_false(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1", api_key="key", verify_ssl=False)
        # httpx stores the verify parameter on the client.
        assert client._client._transport._pool._ssl_context.verify_mode.name == "CERT_NONE"

    def test_ssl_enabled_passes_verify_true(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1", api_key="key", verify_ssl=True)
        assert client._client._transport._pool._ssl_context.verify_mode.name != "CERT_NONE"


# ---------------------------------------------------------------------------
# Logging verification
# ---------------------------------------------------------------------------


class TestLogging:
    """Tests for request/response logging output."""

    @pytest.mark.asyncio
    async def test_debug_logs_redact_api_key(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_resp = _mock_response(200, json_data={"data": []})

        with caplog.at_level(logging.DEBUG, logger="unifi.api.local_gateway_client"):
            async with LocalGatewayClient(
                host="192.168.1.1", api_key="super-secret-key-12345"
            ) as client:
                client._client.request = AsyncMock(return_value=mock_resp)
                await client.get("/api/s/default/stat/device")

        # The API key should be redacted in debug output.
        assert "super-secret-key-12345" not in caplog.text
        assert "***" in caplog.text

    @pytest.mark.asyncio
    async def test_info_log_on_success(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_resp = _mock_response(200, json_data={"data": []})

        with caplog.at_level(logging.INFO, logger="unifi.api.local_gateway_client"):
            async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
                client._client.request = AsyncMock(return_value=mock_resp)
                await client.get("/api/s/default/stat/device")

        assert "200" in caplog.text
        assert "/api/s/default/stat/device" in caplog.text

    @pytest.mark.asyncio
    async def test_warning_log_on_non_200(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_resp = _mock_response(404, text="Not Found")

        with caplog.at_level(logging.WARNING, logger="unifi.api.local_gateway_client"):
            async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
                client._client.request = AsyncMock(return_value=mock_resp)

                with pytest.raises(APIError):
                    await client.get("/api/s/default/nonexistent")

        assert "Non-200 response" in caplog.text
        assert "404" in caplog.text

    @pytest.mark.asyncio
    async def test_warning_log_on_slow_request(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_resp = _mock_response(200, json_data={"data": []})

        with caplog.at_level(logging.WARNING, logger="unifi.api.local_gateway_client"):
            async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
                # Patch time.monotonic to simulate a slow request.
                call_count = 0

                def fake_monotonic() -> float:
                    nonlocal call_count
                    call_count += 1
                    # First call is start time, second is elapsed time.
                    if call_count <= 1:
                        return 1000.0
                    return 1006.0  # 6 seconds elapsed (> 5s threshold)

                client._client.request = AsyncMock(return_value=mock_resp)
                monotonic_path = "unifi.api.local_gateway_client.time.monotonic"
                with patch(monotonic_path, side_effect=fake_monotonic):
                    await client.get("/api/s/default/stat/device")

        assert "Slow request" in caplog.text

    @pytest.mark.asyncio
    async def test_error_log_on_connection_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.ERROR, logger="unifi.api.local_gateway_client"):
            async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
                client._client.request = AsyncMock(
                    side_effect=httpx.ConnectError("Connection refused")
                )

                with pytest.raises(NetworkError):
                    await client.get("/api/s/default/stat/device")

        assert "Connection refused" in caplog.text

    @pytest.mark.asyncio
    async def test_error_log_on_auth_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_resp = _mock_response(401, text="Unauthorized")

        with caplog.at_level(logging.ERROR, logger="unifi.api.local_gateway_client"):
            async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
                client._client.request = AsyncMock(return_value=mock_resp)

                with pytest.raises(AuthenticationError):
                    await client.get("/api/s/default/stat/device")

        assert "Authentication failed" in caplog.text

    @pytest.mark.asyncio
    async def test_debug_log_on_close(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="unifi.api.local_gateway_client"):
            client = LocalGatewayClient(host="192.168.1.1", api_key="key")
            await client.close()

        assert "Closed LocalGatewayClient" in caplog.text


# ---------------------------------------------------------------------------
# Async context manager
# ---------------------------------------------------------------------------


class TestAsyncContextManager:
    """Tests for async with usage."""

    @pytest.mark.asyncio
    async def test_context_manager_returns_client(self) -> None:
        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            assert isinstance(client, LocalGatewayClient)

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1", api_key="key")

        async with client:
            pass

        # After exiting the context, the underlying httpx client should be closed.
        assert client._client.is_closed

    @pytest.mark.asyncio
    async def test_context_manager_closes_on_exception(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1", api_key="key")

        with pytest.raises(RuntimeError):
            async with client:
                raise RuntimeError("boom")

        assert client._client.is_closed

    @pytest.mark.asyncio
    async def test_explicit_close(self) -> None:
        client = LocalGatewayClient(host="192.168.1.1", api_key="key")
        await client.close()
        assert client._client.is_closed


# ---------------------------------------------------------------------------
# Request method passthrough
# ---------------------------------------------------------------------------


class TestRequestMethodPassthrough:
    """Tests that GET/POST correctly pass the HTTP method to the underlying client."""

    @pytest.mark.asyncio
    async def test_get_uses_get_method(self) -> None:
        mock_resp = _mock_response(200, json_data={"data": []})

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get("/api/s/default/stat/device")

            call_args = client._client.request.call_args
            assert call_args.args[0] == "GET"

    @pytest.mark.asyncio
    async def test_post_uses_post_method(self) -> None:
        mock_resp = _mock_response(200, json_data={"data": []})

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.post("/api/s/default/cmd/devmgr")

            call_args = client._client.request.call_args
            assert call_args.args[0] == "POST"


# ---------------------------------------------------------------------------
# _parse_retry_after (static method)
# ---------------------------------------------------------------------------


class TestParseRetryAfter:
    """Tests for the Retry-After header parser."""

    def test_integer_value(self) -> None:
        resp = _mock_response(429, headers={"Retry-After": "60"})
        assert LocalGatewayClient._parse_retry_after(resp) == 60.0

    def test_float_value(self) -> None:
        resp = _mock_response(429, headers={"Retry-After": "30.5"})
        assert LocalGatewayClient._parse_retry_after(resp) == 30.5

    def test_missing_header(self) -> None:
        resp = _mock_response(429)
        assert LocalGatewayClient._parse_retry_after(resp) is None

    def test_non_numeric_header(self) -> None:
        resp = _mock_response(429, headers={"Retry-After": "Wed, 21 Oct 2025 07:28:00 GMT"})
        assert LocalGatewayClient._parse_retry_after(resp) is None

    def test_empty_header(self) -> None:
        resp = _mock_response(429, headers={"Retry-After": ""})
        assert LocalGatewayClient._parse_retry_after(resp) is None
