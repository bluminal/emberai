# SPDX-License-Identifier: MIT
"""Tests for response normalization — envelope unwrapping, pagination, error handling."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import httpx
import pytest

from unifi.api.local_gateway_client import LocalGatewayClient
from unifi.api.response import NormalizedResponse, normalize_response, normalize_single
from unifi.errors import APIError

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
    """Build a fake httpx.Response for testing."""
    content = json.dumps(json_data).encode() if json_data is not None else text.encode()
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers or {},
        request=_FAKE_REQUEST,
    )


# ===========================================================================
# normalize_response — pure function tests
# ===========================================================================


class TestNormalizeResponseSuccess:
    """Tests for successful envelope unwrapping."""

    def test_standard_envelope(self) -> None:
        raw = {
            "data": [{"mac": "aa:bb:cc:dd:ee:ff"}, {"mac": "11:22:33:44:55:66"}],
            "meta": {"rc": "ok"},
        }
        result = normalize_response(raw)

        assert isinstance(result, NormalizedResponse)
        assert len(result.data) == 2
        assert result.data[0]["mac"] == "aa:bb:cc:dd:ee:ff"
        assert result.count == 2
        assert result.total_count is None
        assert result.meta == {"rc": "ok"}

    def test_empty_data_array(self) -> None:
        raw = {"data": [], "meta": {"rc": "ok"}}
        result = normalize_response(raw)

        assert result.data == []
        assert result.count == 0
        assert result.total_count is None

    def test_with_count_fields(self) -> None:
        raw = {
            "data": [{"name": "device1"}, {"name": "device2"}],
            "meta": {"rc": "ok"},
            "count": 2,
            "totalCount": 50,
        }
        result = normalize_response(raw)

        assert result.count == 2
        assert result.total_count == 50
        assert len(result.data) == 2

    def test_count_field_overrides_len(self) -> None:
        """When 'count' is explicitly provided, it takes precedence over len(data)."""
        raw = {
            "data": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
            "meta": {"rc": "ok"},
            "count": 10,
        }
        result = normalize_response(raw)

        assert result.count == 10
        assert len(result.data) == 3

    def test_preserves_meta(self) -> None:
        raw = {
            "data": [{"mac": "aa:bb:cc:dd:ee:ff"}],
            "meta": {"rc": "ok", "extra_field": "value"},
        }
        result = normalize_response(raw)

        assert result.meta["rc"] == "ok"
        assert result.meta["extra_field"] == "value"

    def test_with_device_list_fixture(self, device_list_response: dict[str, Any]) -> None:
        """Use a realistic fixture to verify envelope unwrapping."""
        result = normalize_response(device_list_response)

        assert len(result.data) == 3
        assert result.count == 3
        assert result.meta["rc"] == "ok"
        # Spot-check the first device.
        assert result.data[0]["name"] == "USG-Gateway"
        assert result.data[0]["type"] == "ugw"

    def test_with_client_list_fixture(self, client_list_response: dict[str, Any]) -> None:
        result = normalize_response(client_list_response)

        assert len(result.data) == 6
        assert result.count == 6


class TestNormalizeResponseError:
    """Tests for error envelope handling."""

    def test_error_envelope_raises_api_error(self) -> None:
        raw = {
            "data": [],
            "meta": {"rc": "error", "msg": "api.err.Invalid"},
        }

        with pytest.raises(APIError) as exc_info:
            normalize_response(raw)

        err = exc_info.value
        assert "api.err.Invalid" in err.message
        assert err.status_code == 200
        assert err.details["meta"]["msg"] == "api.err.Invalid"

    def test_error_envelope_unknown_message(self) -> None:
        raw = {
            "data": [],
            "meta": {"rc": "error"},
        }

        with pytest.raises(APIError) as exc_info:
            normalize_response(raw)

        assert "Unknown API error" in exc_info.value.message

    def test_error_envelope_with_data_still_raises(self) -> None:
        """Even if data is present, an error rc should raise."""
        raw = {
            "data": [{"stale": "data"}],
            "meta": {"rc": "error", "msg": "api.err.Stale"},
        }

        with pytest.raises(APIError):
            normalize_response(raw)


class TestNormalizeResponseFlatResponse:
    """Tests for responses that lack the standard envelope."""

    def test_flat_dict_wrapped_in_list(self) -> None:
        raw = {"version": "7.0.23", "build": "atag_7.0.23_12345"}
        result = normalize_response(raw)

        assert len(result.data) == 1
        assert result.data[0] == raw
        assert result.count == 1
        assert result.total_count is None
        assert result.meta == {}

    def test_dict_with_non_list_data_treated_as_flat(self) -> None:
        """If 'data' is not a list, treat the response as flat."""
        raw = {"data": "not-a-list", "meta": {"rc": "ok"}}
        result = normalize_response(raw)

        assert len(result.data) == 1
        assert result.data[0] == raw

    def test_missing_meta_with_data_list(self) -> None:
        """A valid data list without a meta block should still normalize."""
        raw = {"data": [{"id": "1"}, {"id": "2"}]}
        result = normalize_response(raw)

        assert len(result.data) == 2
        assert result.meta == {}


class TestNormalizeResponseImmutability:
    """Tests that NormalizedResponse is frozen."""

    def test_frozen_dataclass(self) -> None:
        result = normalize_response({"data": [{"a": 1}], "meta": {"rc": "ok"}})

        with pytest.raises(AttributeError):
            result.count = 999  # type: ignore[misc]


# ===========================================================================
# normalize_single — pure function tests
# ===========================================================================


class TestNormalizeSingle:
    """Tests for the normalize_single helper."""

    def test_returns_first_item(self) -> None:
        raw = {
            "data": [{"mac": "aa:bb:cc:dd:ee:ff", "name": "USG"}],
            "meta": {"rc": "ok"},
        }
        result = normalize_single(raw)

        assert result["mac"] == "aa:bb:cc:dd:ee:ff"
        assert result["name"] == "USG"

    def test_returns_first_when_multiple_items(self) -> None:
        raw = {
            "data": [{"id": "first"}, {"id": "second"}],
            "meta": {"rc": "ok"},
        }
        result = normalize_single(raw)
        assert result["id"] == "first"

    def test_empty_data_raises_api_error(self) -> None:
        raw = {"data": [], "meta": {"rc": "ok"}}

        with pytest.raises(APIError) as exc_info:
            normalize_single(raw)

        assert "empty" in exc_info.value.message.lower()

    def test_error_envelope_raises_before_empty_check(self) -> None:
        """Error envelope should raise APIError with the API message, not 'empty data'."""
        raw = {"data": [], "meta": {"rc": "error", "msg": "api.err.NoSuchDevice"}}

        with pytest.raises(APIError) as exc_info:
            normalize_single(raw)

        assert "api.err.NoSuchDevice" in exc_info.value.message

    def test_with_device_single_fixture(self, device_single_response: dict[str, Any]) -> None:
        result = normalize_single(device_single_response)

        assert result["name"] == "Office-Switch-16"
        assert result["model"] == "USLITE16P"
        assert "port_table" in result

    def test_flat_response_returns_dict(self) -> None:
        raw = {"version": "7.0.23"}
        result = normalize_single(raw)

        assert result == {"version": "7.0.23"}


# ===========================================================================
# LocalGatewayClient.get_normalized — integration tests
# ===========================================================================


class TestGetNormalized:
    """Tests for the get_normalized convenience method on LocalGatewayClient."""

    @pytest.mark.asyncio
    async def test_returns_normalized_response(self) -> None:
        envelope = {
            "data": [{"mac": "aa:bb:cc:dd:ee:ff"}],
            "meta": {"rc": "ok"},
        }
        mock_resp = _mock_response(200, json_data=envelope)

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            result = await client.get_normalized("/api/s/default/stat/device")

        assert isinstance(result, NormalizedResponse)
        assert len(result.data) == 1
        assert result.data[0]["mac"] == "aa:bb:cc:dd:ee:ff"

    @pytest.mark.asyncio
    async def test_passes_params(self) -> None:
        mock_resp = _mock_response(200, json_data={"data": [], "meta": {"rc": "ok"}})

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get_normalized(
                "/api/s/default/stat/sta",
                params={"type": "all"},
            )

            call_kwargs = client._client.request.call_args
            assert call_kwargs.kwargs["params"] == {"type": "all"}

    @pytest.mark.asyncio
    async def test_raises_on_error_envelope(self) -> None:
        envelope = {
            "data": [],
            "meta": {"rc": "error", "msg": "api.err.Invalid"},
        }
        mock_resp = _mock_response(200, json_data=envelope)

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get_normalized("/api/s/default/stat/device")

            assert "api.err.Invalid" in exc_info.value.message


# ===========================================================================
# LocalGatewayClient.get_single — integration tests
# ===========================================================================


class TestGetSingle:
    """Tests for the get_single convenience method on LocalGatewayClient."""

    @pytest.mark.asyncio
    async def test_returns_single_item(self) -> None:
        envelope = {
            "data": [{"mac": "aa:bb:cc:dd:ee:ff", "name": "USG"}],
            "meta": {"rc": "ok"},
        }
        mock_resp = _mock_response(200, json_data=envelope)

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            result = await client.get_single("/api/s/default/stat/device")

        assert result["mac"] == "aa:bb:cc:dd:ee:ff"

    @pytest.mark.asyncio
    async def test_raises_on_empty_data(self) -> None:
        envelope = {"data": [], "meta": {"rc": "ok"}}
        mock_resp = _mock_response(200, json_data=envelope)

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await client.get_single("/api/s/default/stat/device")

            assert "empty" in exc_info.value.message.lower()


# ===========================================================================
# LocalGatewayClient.get_all — pagination integration tests
# ===========================================================================


class TestGetAll:
    """Tests for the get_all paginated fetch method."""

    @pytest.mark.asyncio
    async def test_single_page_no_pagination(self) -> None:
        """When totalCount is absent, a single page is returned."""
        envelope = {
            "data": [{"id": "1"}, {"id": "2"}],
            "meta": {"rc": "ok"},
        }
        mock_resp = _mock_response(200, json_data=envelope)

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            result = await client.get_all("/api/s/default/stat/device")

        assert len(result.data) == 2
        assert result.total_count is None
        # Only one request should have been made.
        assert client._client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_multi_page_pagination(self) -> None:
        """When totalCount > count, multiple pages should be fetched."""
        page1 = {
            "data": [{"id": "1"}, {"id": "2"}],
            "meta": {"rc": "ok"},
            "count": 2,
            "totalCount": 5,
        }
        page2 = {
            "data": [{"id": "3"}, {"id": "4"}],
            "meta": {"rc": "ok"},
            "count": 2,
            "totalCount": 5,
        }
        page3 = {
            "data": [{"id": "5"}],
            "meta": {"rc": "ok"},
            "count": 1,
            "totalCount": 5,
        }

        responses = [
            _mock_response(200, json_data=page1),
            _mock_response(200, json_data=page2),
            _mock_response(200, json_data=page3),
        ]

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(side_effect=responses)
            result = await client.get_all("/api/s/default/stat/sta", page_size=2)

        assert len(result.data) == 5
        assert result.count == 5
        assert result.total_count == 5
        assert [item["id"] for item in result.data] == ["1", "2", "3", "4", "5"]
        assert client._client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_pagination_params_passed(self) -> None:
        """Verify offset and limit params are set correctly on each page request."""
        page1 = {
            "data": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
            "meta": {"rc": "ok"},
            "count": 3,
            "totalCount": 6,
        }
        page2 = {
            "data": [{"id": "4"}, {"id": "5"}, {"id": "6"}],
            "meta": {"rc": "ok"},
            "count": 3,
            "totalCount": 6,
        }

        responses = [
            _mock_response(200, json_data=page1),
            _mock_response(200, json_data=page2),
        ]

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(side_effect=responses)
            await client.get_all(
                "/api/s/default/stat/sta",
                params={"site": "default"},
                page_size=3,
            )

            calls = client._client.request.call_args_list
            # First call: offset=0, limit=3
            assert calls[0].kwargs["params"]["offset"] == 0
            assert calls[0].kwargs["params"]["limit"] == 3
            assert calls[0].kwargs["params"]["site"] == "default"
            # Second call: offset=3, limit=3
            assert calls[1].kwargs["params"]["offset"] == 3
            assert calls[1].kwargs["params"]["limit"] == 3
            assert calls[1].kwargs["params"]["site"] == "default"

    @pytest.mark.asyncio
    async def test_pagination_stops_on_empty_page(self) -> None:
        """If a page returns no data, pagination stops to avoid infinite loops."""
        page1 = {
            "data": [{"id": "1"}],
            "meta": {"rc": "ok"},
            "count": 1,
            "totalCount": 100,
        }
        page2_empty = {
            "data": [],
            "meta": {"rc": "ok"},
            "count": 0,
            "totalCount": 100,
        }

        responses = [
            _mock_response(200, json_data=page1),
            _mock_response(200, json_data=page2_empty),
        ]

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(side_effect=responses)
            result = await client.get_all("/api/s/default/stat/sta", page_size=10)

        assert len(result.data) == 1
        assert result.total_count == 100
        assert client._client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_pagination_error_on_middle_page(self) -> None:
        """If a page returns an API error, it should propagate immediately."""
        page1 = {
            "data": [{"id": "1"}],
            "meta": {"rc": "ok"},
            "count": 1,
            "totalCount": 10,
        }
        page2_error = {
            "data": [],
            "meta": {"rc": "error", "msg": "api.err.ServerBusy"},
        }

        responses = [
            _mock_response(200, json_data=page1),
            _mock_response(200, json_data=page2_error),
        ]

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(side_effect=responses)

            with pytest.raises(APIError) as exc_info:
                await client.get_all("/api/s/default/stat/sta", page_size=1)

            assert "api.err.ServerBusy" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_preserves_base_params(self) -> None:
        """Base params should not be mutated by pagination."""
        envelope = {
            "data": [{"id": "1"}],
            "meta": {"rc": "ok"},
        }
        mock_resp = _mock_response(200, json_data=envelope)

        base_params = {"site": "default"}

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get_all(
                "/api/s/default/stat/sta",
                params=base_params,
            )

        # Original params should not have been mutated.
        assert "offset" not in base_params
        assert "limit" not in base_params

    @pytest.mark.asyncio
    async def test_exact_total_count_boundary(self) -> None:
        """Pagination stops when accumulated data equals totalCount exactly."""
        page1 = {
            "data": [{"id": "1"}, {"id": "2"}],
            "meta": {"rc": "ok"},
            "count": 2,
            "totalCount": 4,
        }
        page2 = {
            "data": [{"id": "3"}, {"id": "4"}],
            "meta": {"rc": "ok"},
            "count": 2,
            "totalCount": 4,
        }

        responses = [
            _mock_response(200, json_data=page1),
            _mock_response(200, json_data=page2),
        ]

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(side_effect=responses)
            result = await client.get_all("/api/s/default/stat/sta", page_size=2)

        assert len(result.data) == 4
        assert result.count == 4
        assert result.total_count == 4
        # Exactly 2 requests, no third request made.
        assert client._client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_default_page_size(self) -> None:
        """Default page_size should be 100."""
        envelope = {
            "data": [{"id": "1"}],
            "meta": {"rc": "ok"},
        }
        mock_resp = _mock_response(200, json_data=envelope)

        async with LocalGatewayClient(host="192.168.1.1", api_key="key") as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get_all("/api/s/default/stat/sta")

            call_kwargs = client._client.request.call_args
            assert call_kwargs.kwargs["params"]["limit"] == 100


# ===========================================================================
# Logging verification
# ===========================================================================


class TestNormalizationLogging:
    """Tests for log output during normalization."""

    def test_error_envelope_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        raw = {"data": [], "meta": {"rc": "error", "msg": "api.err.Invalid"}}

        with caplog.at_level(logging.ERROR, logger="unifi.api.response"), pytest.raises(APIError):
            normalize_response(raw)

        assert "api.err.Invalid" in caplog.text

    def test_flat_response_logs_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        raw = {"version": "7.0.23"}

        with caplog.at_level(logging.DEBUG, logger="unifi.api.response"):
            normalize_response(raw)

        assert "no 'data' envelope" in caplog.text
