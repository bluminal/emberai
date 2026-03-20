"""Tests for the OPNsense REST API client.

Covers Tasks 81-84:
- Task 81: OPNsense REST client (Basic Auth, URL construction, SSL, error mapping)
- Task 82: Reconfigure pattern (write -> reconfigure -> cache flush)
- Task 83: Response normalization (search vs action formats)
- Task 84: Cache integration (hit/miss/flush, TTL, module-scoped flush)
- Task 85: This test file (50+ tests)

Test organization:
1.  Construction & configuration
2.  URL construction
3.  Basic Auth header encoding
4.  SSL verification toggle
5.  Async context manager
6.  GET requests (raw and normalized)
7.  POST requests
8.  Error status code mapping (401, 403, 404, 429, 5xx)
9.  Network errors (timeout, SSL, connection refused)
10. Write + reconfigure pattern
11. Cache integration (hit, miss, flush, module-scoped flush)
12. Response normalization (search vs action formats)
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.api.response import (
    NormalizedResponse,
    is_action_success,
    is_search_response,
    normalize_response,
)
from opnsense.cache import CacheTTL, TTLCache
from opnsense.errors import APIError, AuthenticationError, NetworkError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
    headers: dict | None = None,
) -> httpx.Response:
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.is_success = 200 <= status_code < 300
    response.json.return_value = json_data if json_data is not None else {}
    response.text = text
    response.headers = headers or {}
    return response


SEARCH_RESPONSE = {
    "rows": [
        {"uuid": "abc-123", "description": "Allow LAN", "action": "pass"},
        {"uuid": "def-456", "description": "Block IoT", "action": "block"},
    ],
    "rowCount": 2,
    "total": 10,
    "current": 1,
}

ACTION_RESPONSE_SAVED = {"result": "saved", "changed": True}
ACTION_RESPONSE_STATUS = {"status": "ok"}
FLAT_RESPONSE_ITEMS = {
    "items": [
        {"name": "WAN_GW", "status": "online"},
        {"name": "VPN_GW", "status": "online"},
    ],
}


# ---------------------------------------------------------------------------
# 1. Construction & configuration
# ---------------------------------------------------------------------------


class TestConstruction:
    """Client construction and parameter handling."""

    def test_creates_with_required_params(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="test-key",
            api_secret="test-secret",
        )
        assert client._base_url == "https://192.168.1.1"
        assert client._verify_ssl is True
        assert client._timeout == 30.0

    def test_strips_trailing_slash(self) -> None:
        client = OPNsenseClient(
            host="https://opnsense.local///",
            api_key="k",
            api_secret="s",
        )
        assert client._base_url == "https://opnsense.local"

    def test_adds_https_scheme_if_missing(self) -> None:
        client = OPNsenseClient(
            host="192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        assert client._base_url == "https://192.168.1.1"

    def test_preserves_http_scheme(self) -> None:
        client = OPNsenseClient(
            host="http://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        assert client._base_url == "http://192.168.1.1"

    def test_custom_timeout(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
            timeout=60.0,
        )
        assert client._timeout == 60.0

    def test_ssl_verification_defaults_true(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        assert client._verify_ssl is True

    def test_ssl_verification_can_be_disabled(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
            verify_ssl=False,
        )
        assert client._verify_ssl is False

    def test_custom_cache_injected(self) -> None:
        custom_cache = TTLCache(max_size=50, default_ttl=10.0)
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
            cache=custom_cache,
        )
        assert client._cache is custom_cache

    def test_default_cache_created(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        assert isinstance(client._cache, TTLCache)


# ---------------------------------------------------------------------------
# 2. URL construction
# ---------------------------------------------------------------------------


class TestURLConstruction:
    """URL building follows OPNsense API pattern."""

    def test_build_url_basic(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        url = client.build_url("firewall", "filter", "searchRule")
        assert url == "/api/firewall/filter/searchRule"

    def test_build_url_interfaces(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        url = client.build_url("interfaces", "overview", "export")
        assert url == "/api/interfaces/overview/export"

    def test_build_url_dhcp(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        url = client.build_url("kea", "leases4", "search")
        assert url == "/api/kea/leases4/search"

    def test_build_url_reconfigure(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        url = client.build_url("firewall", "filter", "reconfigure")
        assert url == "/api/firewall/filter/reconfigure"


# ---------------------------------------------------------------------------
# 3. Basic Auth header encoding
# ---------------------------------------------------------------------------


class TestBasicAuth:
    """HTTP Basic Auth header with base64-encoded api_key:api_secret."""

    def test_auth_header_format(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="my-api-key",
            api_secret="my-api-secret",
        )
        expected = base64.b64encode(b"my-api-key:my-api-secret").decode()
        assert client._auth_header == f"Basic {expected}"

    def test_auth_header_in_client_headers(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="key123",
            api_secret="secret456",
        )
        expected = base64.b64encode(b"key123:secret456").decode()
        assert client._client.headers["authorization"] == f"Basic {expected}"

    def test_auth_header_with_special_chars(self) -> None:
        """API keys may contain special characters."""
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="key+with/special=chars",
            api_secret="secret&with#special",
        )
        expected = base64.b64encode(
            b"key+with/special=chars:secret&with#special"
        ).decode()
        assert client._auth_header == f"Basic {expected}"

    def test_accept_header_is_json(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        assert client._client.headers["accept"] == "application/json"

    def test_content_type_header_is_json(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        assert client._client.headers["content-type"] == "application/json"


# ---------------------------------------------------------------------------
# 4. SSL verification toggle
# ---------------------------------------------------------------------------


class TestSSLVerification:
    """SSL verification behavior."""

    def test_ssl_enabled_by_default(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        assert client._verify_ssl is True

    def test_ssl_disabled_logs_warning(self) -> None:
        with patch("opnsense.api.opnsense_client.logger") as mock_logger:
            OPNsenseClient(
                host="https://192.168.1.1",
                api_key="k",
                api_secret="s",
                verify_ssl=False,
            )
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "SSL verification is disabled" in warning_msg

    def test_ssl_enabled_no_warning(self) -> None:
        with patch("opnsense.api.opnsense_client.logger") as mock_logger:
            OPNsenseClient(
                host="https://192.168.1.1",
                api_key="k",
                api_secret="s",
                verify_ssl=True,
            )
            mock_logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Async context manager
# ---------------------------------------------------------------------------


class TestAsyncContextManager:
    """Async context manager protocol."""

    @pytest.mark.asyncio
    async def test_aenter_returns_self(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        result = await client.__aenter__()
        assert result is client
        await client.close()

    @pytest.mark.asyncio
    async def test_aexit_calls_close(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        client.close = AsyncMock()  # type: ignore[method-assign]
        await client.__aexit__(None, None, None)
        client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_context_manager_usage(self) -> None:
        async with OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        ) as client:
            assert isinstance(client, OPNsenseClient)
        # After exiting, the client should be closed.


# ---------------------------------------------------------------------------
# 6. GET requests
# ---------------------------------------------------------------------------


class TestGetRequests:
    """GET request behavior."""

    @pytest.mark.asyncio
    async def test_get_returns_json(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(200, json_data=SEARCH_RESPONSE)
        client._client.request = AsyncMock(return_value=mock_resp)

        result = await client.get("firewall", "filter", "searchRule")

        assert result == SEARCH_RESPONSE
        client._client.request.assert_awaited_once_with(
            "GET",
            "/api/firewall/filter/searchRule",
            params=None,
            json=None,
        )
        await client.close()

    @pytest.mark.asyncio
    async def test_get_with_params(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(200, json_data=SEARCH_RESPONSE)
        client._client.request = AsyncMock(return_value=mock_resp)

        await client.get("firewall", "filter", "searchRule", params={"limit": 10})

        client._client.request.assert_awaited_once_with(
            "GET",
            "/api/firewall/filter/searchRule",
            params={"limit": 10},
            json=None,
        )
        await client.close()

    @pytest.mark.asyncio
    async def test_get_normalized_returns_normalized_response(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(200, json_data=SEARCH_RESPONSE)
        client._client.request = AsyncMock(return_value=mock_resp)

        result = await client.get_normalized("firewall", "filter", "searchRule")

        assert isinstance(result, NormalizedResponse)
        assert len(result.data) == 2
        assert result.count == 2
        assert result.total == 10
        assert result.current_page == 1
        await client.close()


# ---------------------------------------------------------------------------
# 7. POST requests
# ---------------------------------------------------------------------------


class TestPostRequests:
    """POST request behavior."""

    @pytest.mark.asyncio
    async def test_post_sends_data(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(200, json_data=ACTION_RESPONSE_SAVED)
        client._client.request = AsyncMock(return_value=mock_resp)

        result = await client.post(
            "firewall", "filter", "addRule",
            data={"action": "pass", "interface": "lan"},
        )

        assert result == ACTION_RESPONSE_SAVED
        client._client.request.assert_awaited_once_with(
            "POST",
            "/api/firewall/filter/addRule",
            params=None,
            json={"action": "pass", "interface": "lan"},
        )
        await client.close()

    @pytest.mark.asyncio
    async def test_post_without_data(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(200, json_data=ACTION_RESPONSE_STATUS)
        client._client.request = AsyncMock(return_value=mock_resp)

        result = await client.post("firewall", "filter", "reconfigure")

        assert result == ACTION_RESPONSE_STATUS
        client._client.request.assert_awaited_once_with(
            "POST",
            "/api/firewall/filter/reconfigure",
            params=None,
            json=None,
        )
        await client.close()


# ---------------------------------------------------------------------------
# 8. Error status code mapping
# ---------------------------------------------------------------------------


class TestErrorMapping401:
    """HTTP 401 -> AuthenticationError with env_var hint."""

    @pytest.mark.asyncio
    async def test_401_raises_authentication_error(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="bad-key",
            api_secret="bad-secret",
        )
        mock_resp = _mock_response(401, text="Unauthorized")
        client._client.request = AsyncMock(return_value=mock_resp)

        with pytest.raises(AuthenticationError) as exc_info:
            await client.get("firewall", "filter", "searchRule")

        err = exc_info.value
        assert err.status_code == 401
        assert err.env_var == "OPNSENSE_API_KEY"
        assert "OPNSENSE_API_KEY" in str(err)
        await client.close()

    @pytest.mark.asyncio
    async def test_401_includes_endpoint(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(401)
        client._client.request = AsyncMock(return_value=mock_resp)

        with pytest.raises(AuthenticationError) as exc_info:
            await client.get("firewall", "filter", "searchRule")

        assert exc_info.value.endpoint == "/api/firewall/filter/searchRule"
        await client.close()


class TestErrorMapping403:
    """HTTP 403 -> AuthenticationError with privilege hint."""

    @pytest.mark.asyncio
    async def test_403_raises_authentication_error(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(403, text="Forbidden")
        client._client.request = AsyncMock(return_value=mock_resp)

        with pytest.raises(AuthenticationError) as exc_info:
            await client.get("firewall", "filter", "searchRule")

        err = exc_info.value
        assert "Insufficient privileges" in err.message
        assert "Effective Privileges" in err.message
        await client.close()

    @pytest.mark.asyncio
    async def test_403_includes_privilege_hint_in_details(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(403)
        client._client.request = AsyncMock(return_value=mock_resp)

        with pytest.raises(AuthenticationError) as exc_info:
            await client.get("firewall", "filter", "searchRule")

        assert "hint" in exc_info.value.details
        assert "Effective Privileges" in exc_info.value.details["hint"]
        await client.close()


class TestErrorMapping404:
    """HTTP 404 -> APIError."""

    @pytest.mark.asyncio
    async def test_404_raises_api_error(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(404, text="Not Found")
        client._client.request = AsyncMock(return_value=mock_resp)

        with pytest.raises(APIError) as exc_info:
            await client.get("nonexistent", "module", "command")

        assert exc_info.value.status_code == 404
        assert exc_info.value.response_body == "Not Found"
        await client.close()


class TestErrorMapping429:
    """HTTP 429 -> APIError (rate limiting)."""

    @pytest.mark.asyncio
    async def test_429_raises_api_error(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(429, text="Too Many Requests")
        client._client.request = AsyncMock(return_value=mock_resp)

        with pytest.raises(APIError) as exc_info:
            await client.get("firewall", "filter", "searchRule")

        assert exc_info.value.status_code == 429
        await client.close()


class TestErrorMapping5xx:
    """HTTP 5xx -> APIError with retry hint."""

    @pytest.mark.asyncio
    async def test_500_raises_api_error(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(500, text="Internal Server Error")
        client._client.request = AsyncMock(return_value=mock_resp)

        with pytest.raises(APIError) as exc_info:
            await client.get("firewall", "filter", "searchRule")

        err = exc_info.value
        assert err.status_code == 500
        assert err.retry_hint is not None
        assert "retry" in err.retry_hint.lower()
        await client.close()

    @pytest.mark.asyncio
    async def test_502_raises_api_error(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(502, text="Bad Gateway")
        client._client.request = AsyncMock(return_value=mock_resp)

        with pytest.raises(APIError) as exc_info:
            await client.get("firewall", "filter", "searchRule")

        assert exc_info.value.status_code == 502
        assert exc_info.value.retry_hint is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_503_raises_api_error(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(503, text="Service Unavailable")
        client._client.request = AsyncMock(return_value=mock_resp)

        with pytest.raises(APIError) as exc_info:
            await client.get("firewall", "filter", "searchRule")

        assert exc_info.value.status_code == 503
        await client.close()

    @pytest.mark.asyncio
    async def test_other_4xx_raises_api_error(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(422, text="Unprocessable Entity")
        client._client.request = AsyncMock(return_value=mock_resp)

        with pytest.raises(APIError) as exc_info:
            await client.get("firewall", "filter", "addRule")

        assert exc_info.value.status_code == 422
        await client.close()


# ---------------------------------------------------------------------------
# 9. Network errors (timeout, SSL, connection refused)
# ---------------------------------------------------------------------------


class TestNetworkErrors:
    """Transport-level errors mapped to NetworkError."""

    @pytest.mark.asyncio
    async def test_timeout_raises_network_error(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        client._client.request = AsyncMock(
            side_effect=httpx.TimeoutException("read timed out")
        )

        with pytest.raises(NetworkError) as exc_info:
            await client.get("firewall", "filter", "searchRule")

        err = exc_info.value
        assert "timed out" in err.message.lower()
        assert err.endpoint == "/api/firewall/filter/searchRule"
        await client.close()

    @pytest.mark.asyncio
    async def test_ssl_error_raises_network_error_with_hint(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        client._client.request = AsyncMock(
            side_effect=httpx.ConnectError("SSL certificate verify failed")
        )

        with pytest.raises(NetworkError) as exc_info:
            await client.get("firewall", "filter", "searchRule")

        err = exc_info.value
        assert "SSL" in err.message
        assert err.retry_hint is not None
        assert "OPNSENSE_VERIFY_SSL=false" in err.retry_hint
        await client.close()

    @pytest.mark.asyncio
    async def test_connection_refused_raises_network_error(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        client._client.request = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(NetworkError) as exc_info:
            await client.get("firewall", "filter", "searchRule")

        assert "Connection refused" in exc_info.value.message
        await client.close()

    @pytest.mark.asyncio
    async def test_generic_http_error_raises_network_error(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        client._client.request = AsyncMock(
            side_effect=httpx.HTTPError("DNS resolution failed")
        )

        with pytest.raises(NetworkError) as exc_info:
            await client.get("firewall", "filter", "searchRule")

        assert "transport error" in exc_info.value.message.lower()
        await client.close()


# ---------------------------------------------------------------------------
# 10. Write + reconfigure pattern
# ---------------------------------------------------------------------------


class TestWriteMethod:
    """write() saves config without applying."""

    @pytest.mark.asyncio
    async def test_write_sends_post(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(200, json_data=ACTION_RESPONSE_SAVED)
        client._client.request = AsyncMock(return_value=mock_resp)

        result = await client.write(
            "firewall", "filter", "addRule",
            data={"action": "pass"},
        )

        assert result == ACTION_RESPONSE_SAVED
        client._client.request.assert_awaited_once_with(
            "POST",
            "/api/firewall/filter/addRule",
            params=None,
            json={"action": "pass"},
        )
        await client.close()

    @pytest.mark.asyncio
    async def test_write_without_data(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(200, json_data=ACTION_RESPONSE_SAVED)
        client._client.request = AsyncMock(return_value=mock_resp)

        result = await client.write("firewall", "filter", "delRule")

        assert result == ACTION_RESPONSE_SAVED
        await client.close()


class TestReconfigureMethod:
    """reconfigure() applies config to live system and flushes cache."""

    @pytest.mark.asyncio
    async def test_reconfigure_posts_to_reconfigure_endpoint(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        mock_resp = _mock_response(200, json_data=ACTION_RESPONSE_STATUS)
        client._client.request = AsyncMock(return_value=mock_resp)

        result = await client.reconfigure("firewall", "filter")

        assert result == ACTION_RESPONSE_STATUS
        client._client.request.assert_awaited_once_with(
            "POST",
            "/api/firewall/filter/reconfigure",
            params=None,
            json=None,
        )
        await client.close()

    @pytest.mark.asyncio
    async def test_reconfigure_flushes_module_cache(self) -> None:
        cache = TTLCache()
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
            cache=cache,
        )

        # Pre-populate cache with firewall entries.
        await cache.set("firewall:rules", [{"rule": 1}])
        await cache.set("firewall:aliases", [{"alias": 1}])
        await cache.set("interfaces:list", [{"iface": 1}])

        mock_resp = _mock_response(200, json_data=ACTION_RESPONSE_STATUS)
        client._client.request = AsyncMock(return_value=mock_resp)

        await client.reconfigure("firewall", "filter")

        # Firewall cache should be flushed.
        assert await cache.get("firewall:rules") is None
        assert await cache.get("firewall:aliases") is None
        # Interfaces cache should be preserved.
        assert await cache.get("interfaces:list") == [{"iface": 1}]
        await client.close()

    @pytest.mark.asyncio
    async def test_write_then_reconfigure_pattern(self) -> None:
        """Full write -> reconfigure -> cache flush pattern."""
        cache = TTLCache()
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
            cache=cache,
        )

        # Pre-populate cache.
        await cache.set("firewall:rules", [{"old": True}])

        saved_resp = _mock_response(200, json_data=ACTION_RESPONSE_SAVED)
        reconf_resp = _mock_response(200, json_data=ACTION_RESPONSE_STATUS)
        client._client.request = AsyncMock(
            side_effect=[saved_resp, reconf_resp]
        )

        # Step 1: Write (save config).
        write_result = await client.write(
            "firewall", "filter", "addRule",
            data={"action": "pass"},
        )
        assert write_result["result"] == "saved"

        # Cache should still have old data (write doesn't flush).
        assert await cache.get("firewall:rules") == [{"old": True}]

        # Step 2: Reconfigure (apply to live system).
        reconf_result = await client.reconfigure("firewall", "filter")
        assert reconf_result["status"] == "ok"

        # Cache should be flushed after reconfigure.
        assert await cache.get("firewall:rules") is None
        await client.close()


# ---------------------------------------------------------------------------
# 11. Cache integration
# ---------------------------------------------------------------------------


class TestCacheIntegration:
    """Cache integration with get_cached and module-scoped flushing."""

    @pytest.mark.asyncio
    async def test_get_cached_miss_fetches_from_api(self) -> None:
        cache = TTLCache()
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
            cache=cache,
        )
        mock_resp = _mock_response(200, json_data=SEARCH_RESPONSE)
        client._client.request = AsyncMock(return_value=mock_resp)

        result = await client.get_cached(
            "firewall", "filter", "searchRule",
            cache_key="firewall:rules",
            ttl=CacheTTL.FIREWALL_RULES,
        )

        assert result == SEARCH_RESPONSE
        client._client.request.assert_awaited_once()
        await client.close()

    @pytest.mark.asyncio
    async def test_get_cached_hit_skips_api(self) -> None:
        cache = TTLCache()
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
            cache=cache,
        )

        # Pre-populate cache.
        await cache.set("firewall:rules", SEARCH_RESPONSE, ttl=300.0)

        client._client.request = AsyncMock()

        result = await client.get_cached(
            "firewall", "filter", "searchRule",
            cache_key="firewall:rules",
        )

        assert result == SEARCH_RESPONSE
        client._client.request.assert_not_awaited()
        await client.close()

    @pytest.mark.asyncio
    async def test_get_cached_uses_ttl(self) -> None:
        cache = TTLCache()
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
            cache=cache,
        )
        mock_resp = _mock_response(200, json_data=SEARCH_RESPONSE)
        client._client.request = AsyncMock(return_value=mock_resp)

        await client.get_cached(
            "firewall", "filter", "searchRule",
            cache_key="firewall:rules",
            ttl=CacheTTL.FIREWALL_RULES,
        )

        # Verify value is cached.
        cached = await cache.get("firewall:rules")
        assert cached == SEARCH_RESPONSE
        await client.close()

    @pytest.mark.asyncio
    async def test_flush_cache_by_module(self) -> None:
        cache = TTLCache()
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
            cache=cache,
        )

        await cache.set("firewall:rules", [1])
        await cache.set("firewall:aliases", [2])
        await cache.set("interfaces:list", [3])

        await client.flush_cache("firewall")

        assert await cache.get("firewall:rules") is None
        assert await cache.get("firewall:aliases") is None
        assert await cache.get("interfaces:list") == [3]
        await client.close()

    @pytest.mark.asyncio
    async def test_flush_cache_all(self) -> None:
        cache = TTLCache()
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
            cache=cache,
        )

        await cache.set("firewall:rules", [1])
        await cache.set("interfaces:list", [2])

        await client.flush_cache()

        assert await cache.get("firewall:rules") is None
        assert await cache.get("interfaces:list") is None
        await client.close()

    @pytest.mark.asyncio
    async def test_cache_property_exposes_instance(self) -> None:
        cache = TTLCache()
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
            cache=cache,
        )
        assert client.cache is cache
        await client.close()

    @pytest.mark.asyncio
    async def test_get_cached_with_different_ttls(self) -> None:
        """Different data types should use appropriate TTL constants."""
        cache = TTLCache()
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
            cache=cache,
        )

        iface_resp = _mock_response(200, json_data={"rows": [{"name": "igb0"}]})
        dhcp_resp = _mock_response(200, json_data={"rows": [{"address": "192.168.1.100"}]})
        client._client.request = AsyncMock(side_effect=[iface_resp, dhcp_resp])

        # Interfaces: 5 min TTL.
        await client.get_cached(
            "interfaces", "overview", "export",
            cache_key="interfaces:list",
            ttl=CacheTTL.INTERFACES,
        )

        # DHCP leases: 1 min TTL.
        await client.get_cached(
            "kea", "leases4", "search",
            cache_key="dhcp:leases",
            ttl=CacheTTL.DHCP_LEASES,
        )

        assert await cache.get("interfaces:list") is not None
        assert await cache.get("dhcp:leases") is not None
        await client.close()


# ---------------------------------------------------------------------------
# 12. Response normalization (search vs action formats)
# ---------------------------------------------------------------------------


class TestResponseNormalizationSearch:
    """Search-style responses with rows/rowCount/total/current."""

    def test_search_response_extracts_rows(self) -> None:
        result = normalize_response(SEARCH_RESPONSE)
        assert len(result.data) == 2
        assert result.data[0]["uuid"] == "abc-123"
        assert result.data[1]["uuid"] == "def-456"

    def test_search_response_row_count(self) -> None:
        result = normalize_response(SEARCH_RESPONSE)
        assert result.count == 2

    def test_search_response_total(self) -> None:
        result = normalize_response(SEARCH_RESPONSE)
        assert result.total == 10

    def test_search_response_current_page(self) -> None:
        result = normalize_response(SEARCH_RESPONSE)
        assert result.current_page == 1

    def test_search_response_preserves_raw(self) -> None:
        result = normalize_response(SEARCH_RESPONSE)
        assert result.raw == SEARCH_RESPONSE

    def test_search_response_empty_rows(self) -> None:
        empty = {"rows": [], "rowCount": 0, "total": 0, "current": 1}
        result = normalize_response(empty)
        assert result.data == []
        assert result.count == 0
        assert result.total == 0

    def test_search_response_without_total(self) -> None:
        """Some endpoints may not include total."""
        partial = {"rows": [{"id": 1}], "rowCount": 1}
        result = normalize_response(partial)
        assert result.data == [{"id": 1}]
        assert result.total is None

    def test_is_search_response_true(self) -> None:
        assert is_search_response(SEARCH_RESPONSE) is True

    def test_is_search_response_false_for_action(self) -> None:
        assert is_search_response(ACTION_RESPONSE_SAVED) is False


class TestResponseNormalizationAction:
    """Action-style responses (flat JSON)."""

    def test_action_saved_wrapped_in_list(self) -> None:
        result = normalize_response(ACTION_RESPONSE_SAVED)
        assert len(result.data) == 1
        assert result.data[0] == ACTION_RESPONSE_SAVED

    def test_action_status_wrapped_in_list(self) -> None:
        result = normalize_response(ACTION_RESPONSE_STATUS)
        assert len(result.data) == 1
        assert result.data[0] == ACTION_RESPONSE_STATUS

    def test_flat_items_response_wrapped(self) -> None:
        result = normalize_response(FLAT_RESPONSE_ITEMS)
        assert len(result.data) == 1
        assert result.data[0] == FLAT_RESPONSE_ITEMS

    def test_action_response_count_is_one(self) -> None:
        result = normalize_response(ACTION_RESPONSE_SAVED)
        assert result.count == 1

    def test_action_response_total_is_none(self) -> None:
        result = normalize_response(ACTION_RESPONSE_SAVED)
        assert result.total is None

    def test_action_response_current_page_is_none(self) -> None:
        result = normalize_response(ACTION_RESPONSE_SAVED)
        assert result.current_page is None

    def test_is_action_success_saved(self) -> None:
        assert is_action_success({"result": "saved"}) is True

    def test_is_action_success_done(self) -> None:
        assert is_action_success({"result": "done"}) is True

    def test_is_action_success_status_ok(self) -> None:
        assert is_action_success({"status": "ok"}) is True

    def test_is_action_success_false(self) -> None:
        assert is_action_success({"result": "failed"}) is False

    def test_is_action_success_empty(self) -> None:
        assert is_action_success({}) is False

    def test_is_action_success_case_insensitive(self) -> None:
        assert is_action_success({"result": "Saved"}) is True
        assert is_action_success({"status": "OK"}) is True


class TestNormalizedResponseDataclass:
    """NormalizedResponse dataclass properties."""

    def test_frozen(self) -> None:
        result = normalize_response(SEARCH_RESPONSE)
        with pytest.raises(AttributeError):
            result.count = 999  # type: ignore[misc]

    def test_defaults(self) -> None:
        resp = NormalizedResponse(data=[], count=0)
        assert resp.total is None
        assert resp.current_page is None
        assert resp.raw == {}


# ---------------------------------------------------------------------------
# 13. Close / cleanup
# ---------------------------------------------------------------------------


class TestClose:
    """Client cleanup behavior."""

    @pytest.mark.asyncio
    async def test_close_calls_aclose_on_httpx(self) -> None:
        client = OPNsenseClient(
            host="https://192.168.1.1",
            api_key="k",
            api_secret="s",
        )
        client._client.aclose = AsyncMock()
        await client.close()
        client._client.aclose.assert_awaited_once()
