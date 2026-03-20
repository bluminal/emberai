# SPDX-License-Identifier: MIT
"""Tests for firmware status Cloud V1 fallback (Task 56).

Verifies that unifi__health__get_firmware_status uses Cloud V1 /v1/devices
when UNIFI_API_KEY is available, and falls back to local API otherwise.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, NetworkError
from unifi.tools.health import (
    _firmware_status_cloud,
    _firmware_status_local,
    _get_cloud_client,
    _has_cloud_api_key,
    unifi__health__get_firmware_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cloud_normalized(data: list[dict[str, Any]]) -> NormalizedResponse:
    """Build a NormalizedResponse like CloudV1Client returns."""
    return NormalizedResponse(
        data=data,
        count=len(data),
        total_count=None,
        meta={"httpStatusCode": 200, "traceId": "test"},
    )


def _local_normalized(data: list[dict[str, Any]]) -> NormalizedResponse:
    """Build a NormalizedResponse like LocalGatewayClient returns."""
    return NormalizedResponse(
        data=data,
        count=len(data),
        total_count=None,
        meta={"rc": "ok"},
    )


def _sample_device(
    device_id: str = "dev001",
    model: str = "U6-Pro",
    version: str = "7.0.76",
    upgradable: bool = False,
    upgrade_to: str = "",
    product_line: str = "network",
    state: int | str = 1,
) -> dict[str, Any]:
    """Build a sample device dict for firmware status testing."""
    d: dict[str, Any] = {
        "_id": device_id,
        "model": model,
        "version": version,
        "upgradable": upgradable,
        "state": state,
        "product_line": product_line,
    }
    if upgrade_to:
        d["upgrade_to_firmware"] = upgrade_to
    return d


# ---------------------------------------------------------------------------
# _has_cloud_api_key (health module)
# ---------------------------------------------------------------------------


class TestHasCloudApiKeyHealth:
    """Verify Cloud API key detection in health module."""

    def test_key_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "cloud-key")
        assert _has_cloud_api_key() is True

    def test_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNIFI_API_KEY", raising=False)
        assert _has_cloud_api_key() is False

    def test_key_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "")
        assert _has_cloud_api_key() is False

    def test_key_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "  ")
        assert _has_cloud_api_key() is False


# ---------------------------------------------------------------------------
# _get_cloud_client (health module)
# ---------------------------------------------------------------------------


class TestGetCloudClientHealth:
    """Verify the Cloud V1 client factory in the health module."""

    def test_creates_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "my-cloud-key")
        client = _get_cloud_client()
        assert client._api_key == "my-cloud-key"

    def test_empty_key_creates_client_with_empty_key(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The health module's _get_cloud_client does not raise on empty key --
        it's only called after _has_cloud_api_key() returns True."""
        monkeypatch.setenv("UNIFI_API_KEY", "")
        client = _get_cloud_client()
        assert client._api_key == ""


# ---------------------------------------------------------------------------
# Firmware status routing
# ---------------------------------------------------------------------------


class TestFirmwareStatusRouting:
    """Verify firmware status routes to cloud or local based on UNIFI_API_KEY."""

    async def test_routes_to_cloud_when_key_present(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With UNIFI_API_KEY set, should use Cloud V1 /v1/devices."""
        monkeypatch.setenv("UNIFI_API_KEY", "cloud-key")

        mock_cloud = AsyncMock(return_value=[{"device_id": "d1"}])
        mock_local = AsyncMock(return_value=[{"device_id": "d2"}])

        with (
            patch("unifi.tools.health._firmware_status_cloud", mock_cloud),
            patch("unifi.tools.health._firmware_status_local", mock_local),
        ):
            result = await unifi__health__get_firmware_status()

        mock_cloud.assert_called_once()
        mock_local.assert_not_called()
        assert result == [{"device_id": "d1"}]

    async def test_routes_to_local_when_key_absent(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without UNIFI_API_KEY, should fall back to local API."""
        monkeypatch.delenv("UNIFI_API_KEY", raising=False)

        mock_cloud = AsyncMock(return_value=[{"device_id": "d1"}])
        mock_local = AsyncMock(return_value=[{"device_id": "d2"}])

        with (
            patch("unifi.tools.health._firmware_status_cloud", mock_cloud),
            patch("unifi.tools.health._firmware_status_local", mock_local),
        ):
            result = await unifi__health__get_firmware_status()

        mock_cloud.assert_not_called()
        mock_local.assert_called_once_with("default")
        assert result == [{"device_id": "d2"}]

    async def test_routes_to_local_with_custom_site_id(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Custom site_id should be passed to the local fallback."""
        monkeypatch.delenv("UNIFI_API_KEY", raising=False)

        mock_local = AsyncMock(return_value=[])

        with patch("unifi.tools.health._firmware_status_local", mock_local):
            await unifi__health__get_firmware_status(site_id="branch")

        mock_local.assert_called_once_with("branch")

    async def test_routes_to_local_when_key_empty(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Empty UNIFI_API_KEY should route to local."""
        monkeypatch.setenv("UNIFI_API_KEY", "")

        mock_cloud = AsyncMock()
        mock_local = AsyncMock(return_value=[])

        with (
            patch("unifi.tools.health._firmware_status_cloud", mock_cloud),
            patch("unifi.tools.health._firmware_status_local", mock_local),
        ):
            await unifi__health__get_firmware_status()

        mock_cloud.assert_not_called()
        mock_local.assert_called_once_with("default")


# ---------------------------------------------------------------------------
# _firmware_status_cloud
# ---------------------------------------------------------------------------


class TestFirmwareStatusCloud:
    """Test the Cloud V1 firmware status fetcher."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_API_KEY", "test-key")

    async def test_returns_firmware_list(self) -> None:
        """Cloud firmware status should return parsed firmware dicts."""
        devices = [
            _sample_device("d1", "U6-Pro", "7.0.76", upgradable=False),
            _sample_device("d2", "USW-24", "7.0.50", upgradable=True, upgrade_to="7.0.72"),
        ]
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=_cloud_normalized(devices),
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.health._get_cloud_client", return_value=mock_client):
            result = await _firmware_status_cloud()

        assert len(result) == 2
        assert result[0]["device_id"] == "d1"
        assert result[0]["upgrade_available"] is False
        assert result[1]["device_id"] == "d2"
        assert result[1]["upgrade_available"] is True
        assert result[1]["latest_version"] == "7.0.72"

        mock_client.get_normalized.assert_called_once_with("devices")
        mock_client.close.assert_called_once()

    async def test_empty_device_list(self) -> None:
        """Should return empty list when no devices exist."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=_cloud_normalized([]),
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.health._get_cloud_client", return_value=mock_client):
            result = await _firmware_status_cloud()

        assert result == []
        mock_client.close.assert_called_once()

    async def test_unparseable_device_skipped(self) -> None:
        """Devices that fail validation should be skipped."""
        good_device = _sample_device("d1")
        bad_device = {"state": 1}  # Missing required fields

        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=_cloud_normalized([good_device, bad_device]),
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.health._get_cloud_client", return_value=mock_client):
            result = await _firmware_status_cloud()

        assert len(result) == 1
        assert result[0]["device_id"] == "d1"

    async def test_state_converted_to_string(self) -> None:
        """Integer state codes should be converted before parsing."""
        device = _sample_device("d1", state=4)  # upgrading
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=_cloud_normalized([device]),
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.health._get_cloud_client", return_value=mock_client):
            result = await _firmware_status_cloud()

        assert len(result) == 1

    async def test_api_error_propagates(self) -> None:
        """APIError from Cloud V1 should propagate."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Cloud error", status_code=500),
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.health._get_cloud_client", return_value=mock_client),
            pytest.raises(APIError, match="Cloud error"),
        ):
            await _firmware_status_cloud()

        mock_client.close.assert_called_once()

    async def test_network_error_propagates(self) -> None:
        """NetworkError from Cloud V1 should propagate."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=NetworkError("Connection timed out"),
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.health._get_cloud_client", return_value=mock_client),
            pytest.raises(NetworkError),
        ):
            await _firmware_status_cloud()

        mock_client.close.assert_called_once()

    async def test_client_closed_on_success(self) -> None:
        """Cloud client should be closed on success."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=_cloud_normalized([_sample_device()]),
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.health._get_cloud_client", return_value=mock_client):
            await _firmware_status_cloud()

        mock_client.close.assert_called_once()

    async def test_client_closed_on_error(self) -> None:
        """Cloud client should be closed even on error."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Error", status_code=500),
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.health._get_cloud_client", return_value=mock_client),
            pytest.raises(APIError),
        ):
            await _firmware_status_cloud()

        mock_client.close.assert_called_once()

    async def test_product_line_preserved(self) -> None:
        """Product line field should be carried through."""
        device = _sample_device("d1", product_line="protect")
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=_cloud_normalized([device]),
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.health._get_cloud_client", return_value=mock_client):
            result = await _firmware_status_cloud()

        assert result[0]["product_line"] == "protect"


# ---------------------------------------------------------------------------
# _firmware_status_local
# ---------------------------------------------------------------------------


class TestFirmwareStatusLocal:
    """Test the local gateway firmware status fetcher."""

    async def test_returns_firmware_list(self) -> None:
        """Local firmware status should return parsed firmware dicts."""
        devices = [
            _sample_device("d1", "U6-Pro", "7.0.76"),
            _sample_device("d2", "USW-24", "7.0.50", upgradable=True, upgrade_to="7.0.72"),
        ]
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=_local_normalized(devices),
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await _firmware_status_local("default")

        assert len(result) == 2
        mock_client.get_normalized.assert_called_once_with(
            "/api/s/default/stat/device",
        )
        mock_client.close.assert_called_once()

    async def test_custom_site_id(self) -> None:
        """Custom site_id should be passed to the local endpoint."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=_local_normalized([]),
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            await _firmware_status_local("branch-office")

        mock_client.get_normalized.assert_called_once_with(
            "/api/s/branch-office/stat/device",
        )

    async def test_empty_device_list(self) -> None:
        """Should return empty list when no devices exist."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=_local_normalized([]),
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await _firmware_status_local("default")

        assert result == []

    async def test_api_error_propagates(self) -> None:
        """APIError from local gateway should propagate."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Local error", status_code=500),
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.health._get_client", return_value=mock_client),
            pytest.raises(APIError, match="Local error"),
        ):
            await _firmware_status_local("default")

        mock_client.close.assert_called_once()

    async def test_state_converted_to_string(self) -> None:
        """Integer state codes should be converted before parsing."""
        device = _sample_device("d1", state=0)  # disconnected
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=_local_normalized([device]),
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await _firmware_status_local("default")

        assert len(result) == 1

    async def test_unparseable_device_skipped(self) -> None:
        """Devices that fail validation should be skipped."""
        good = _sample_device("d1")
        bad = {"state": 1}
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=_local_normalized([good, bad]),
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.health._get_client", return_value=mock_client):
            result = await _firmware_status_local("default")

        assert len(result) == 1
        assert result[0]["device_id"] == "d1"
