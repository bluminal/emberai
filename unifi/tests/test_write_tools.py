# SPDX-License-Identifier: MIT
"""Tests for write-gated MCP tools (Tasks 66-68).

Covers:
- Task 66: unifi__config__save_baseline
- Task 67: unifi__config__create_port_profile
- Task 68: unifi__topology__assign_port_profile

Test categories:
- Write gate enforcement (env var disabled, apply missing)
- Successful writes with apply=True
- Error handling (API errors, validation errors)
- Port profile creation with various VLAN configs
- Port profile assignment with port_overrides
- Edge cases and input validation
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, ValidationError, WriteGateError
from unifi.safety import WriteBlockReason
from unifi.tools.config import (
    _baselines,
    _parse_tagged_vlans,
    _validate_vlan_id,
    unifi__config__create_port_profile,
    unifi__config__save_baseline,
)
from unifi.tools.topology import (
    _build_port_overrides,
    unifi__topology__assign_port_profile,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client_for_snapshot() -> AsyncMock:
    """Create a mock client that returns data for all config snapshot endpoints."""
    mock_client = AsyncMock()

    async def mock_get_normalized(endpoint: str) -> NormalizedResponse:
        if "networkconf" in endpoint:
            return NormalizedResponse(
                data=[
                    {"_id": "net1", "name": "Default"},
                    {"_id": "net2", "name": "Guest"},
                ],
                count=2,
                meta={"rc": "ok"},
            )
        elif "wlanconf" in endpoint:
            return NormalizedResponse(
                data=[{"_id": "wlan1", "name": "HomeNet"}],
                count=1,
                meta={"rc": "ok"},
            )
        elif "firewallrule" in endpoint:
            return NormalizedResponse(
                data=[{"_id": "rule1", "name": "Allow-DNS"}],
                count=1,
                meta={"rc": "ok"},
            )
        return NormalizedResponse(data=[], count=0, meta={"rc": "ok"})

    mock_client.get_normalized = AsyncMock(side_effect=mock_get_normalized)
    mock_client.close = AsyncMock()
    return mock_client


def _mock_client_for_portconf_create(profile_id: str = "prof001") -> AsyncMock:
    """Create a mock client that returns a success response for POST portconf."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value={
            "data": [{"_id": profile_id, "name": "Trunk-AP"}],
            "meta": {"rc": "ok"},
        }
    )
    mock_client.close = AsyncMock()
    return mock_client


def _mock_client_for_port_assign(
    existing_overrides: list[dict[str, Any]] | None = None,
    profile_name: str = "Trunk-AP",
    profile_id: str = "prof001",
) -> AsyncMock:
    """Create a mock client for assign_port_profile (GET device, GET portconf, PUT)."""
    mock_client = AsyncMock()

    device_data = {
        "_id": "dev123",
        "mac": "aa:bb:cc:dd:ee:ff",
        "name": "Test-Switch",
        "port_overrides": existing_overrides or [],
    }
    mock_client.get_single = AsyncMock(return_value=device_data)

    portconf_data = NormalizedResponse(
        data=[
            {"_id": profile_id, "name": profile_name},
            {"_id": "prof002", "name": "All"},
        ],
        count=2,
        meta={"rc": "ok"},
    )
    mock_client.get_normalized = AsyncMock(return_value=portconf_data)

    mock_client.put = AsyncMock(
        return_value={
            "data": [
                {
                    "_id": "dev123",
                    "port_overrides": [{"port_idx": 5, "portconf_id": profile_id}],
                }
            ],
            "meta": {"rc": "ok"},
        }
    )
    mock_client.close = AsyncMock()
    return mock_client


# ===========================================================================
# Task 66: unifi__config__save_baseline
# ===========================================================================


class TestSaveBaselineWriteGate:
    """Write gate enforcement for save_baseline."""

    def setup_method(self) -> None:
        _baselines.clear()

    async def test_blocked_when_env_var_disabled(self) -> None:
        """save_baseline must be blocked when UNIFI_WRITE_ENABLED is not true."""
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "false"}, clear=False),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi__config__save_baseline(apply=True)
        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    async def test_blocked_when_env_var_unset(self) -> None:
        """save_baseline must be blocked when UNIFI_WRITE_ENABLED is unset."""
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi__config__save_baseline(apply=True)
        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    async def test_blocked_when_apply_missing(self) -> None:
        """save_baseline must be blocked when apply=False (default)."""
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi__config__save_baseline()
        assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    async def test_blocked_when_apply_explicitly_false(self) -> None:
        """save_baseline must be blocked when apply=False is explicit."""
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi__config__save_baseline(apply=False)
        assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING


class TestSaveBaselineSuccess:
    """Successful save_baseline operations."""

    def setup_method(self) -> None:
        _baselines.clear()

    async def test_saves_baseline_and_returns_metadata(self) -> None:
        """Successful save should return baseline_id and timestamp."""
        mock_client = _mock_client_for_snapshot()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.config._get_client", return_value=mock_client),
        ):
            result = await unifi__config__save_baseline(apply=True)

        assert "baseline_id" in result
        assert len(result["baseline_id"]) == 12  # uuid hex[:12]
        assert "timestamp" in result
        assert result["site_id"] == "default"
        assert result["network_count"] == 2
        assert result["wlan_count"] == 1
        assert result["rule_count"] == 1

    async def test_stores_baseline_under_id_and_latest(self) -> None:
        """Baseline should be stored under both the generated ID and 'latest'."""
        mock_client = _mock_client_for_snapshot()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.config._get_client", return_value=mock_client),
        ):
            result = await unifi__config__save_baseline(apply=True)

        baseline_id = result["baseline_id"]
        assert f"default:{baseline_id}" in _baselines
        assert "default:latest" in _baselines
        # Both should point to the same config data
        assert _baselines[f"default:{baseline_id}"] == _baselines["default:latest"]

    async def test_custom_site_id(self) -> None:
        """Baseline should be stored under the specified site_id."""
        mock_client = _mock_client_for_snapshot()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.config._get_client", return_value=mock_client),
        ):
            result = await unifi__config__save_baseline(site_id="branch", apply=True)

        assert result["site_id"] == "branch"
        assert "branch:latest" in _baselines

    async def test_client_closed_on_success(self) -> None:
        """Client should be closed after successful save."""
        mock_client = _mock_client_for_snapshot()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.config._get_client", return_value=mock_client),
        ):
            await unifi__config__save_baseline(apply=True)

        mock_client.close.assert_called_once()

    async def test_client_closed_on_error(self) -> None:
        """Client should be closed even when the API call fails."""
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Server error", status_code=500)
        )
        mock_client.close = AsyncMock()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.config._get_client", return_value=mock_client),
            pytest.raises(APIError, match="Server error"),
        ):
            await unifi__config__save_baseline(apply=True)

        mock_client.close.assert_called_once()


# ===========================================================================
# Task 67: unifi__config__create_port_profile
# ===========================================================================


class TestCreatePortProfileWriteGate:
    """Write gate enforcement for create_port_profile."""

    async def test_blocked_when_env_var_disabled(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "false"}),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi__config__create_port_profile(
                name="Test",
                native_vlan=10,
                apply=True,
            )
        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    async def test_blocked_when_apply_missing(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi__config__create_port_profile(
                name="Test",
                native_vlan=10,
            )
        assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    async def test_blocked_when_env_var_unset(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi__config__create_port_profile(
                name="Test",
                native_vlan=10,
                apply=True,
            )
        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED


class TestCreatePortProfileValidation:
    """Input validation for create_port_profile."""

    async def test_empty_name_raises_validation_error(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(ValidationError, match="name must not be empty"),
        ):
            await unifi__config__create_port_profile(
                name="",
                native_vlan=10,
                apply=True,
            )

    async def test_whitespace_name_raises_validation_error(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(ValidationError, match="name must not be empty"),
        ):
            await unifi__config__create_port_profile(
                name="   ",
                native_vlan=10,
                apply=True,
            )

    async def test_native_vlan_zero_raises_validation_error(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(ValidationError, match="Invalid native_vlan"),
        ):
            await unifi__config__create_port_profile(
                name="Test",
                native_vlan=0,
                apply=True,
            )

    async def test_native_vlan_above_4094_raises_validation_error(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(ValidationError, match="Invalid native_vlan"),
        ):
            await unifi__config__create_port_profile(
                name="Test",
                native_vlan=4095,
                apply=True,
            )

    async def test_invalid_tagged_vlan_raises_validation_error(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(ValidationError, match="Invalid tagged VLAN ID"),
        ):
            await unifi__config__create_port_profile(
                name="Test",
                native_vlan=10,
                tagged_vlans="abc",
                apply=True,
            )

    async def test_tagged_vlan_out_of_range_raises_validation_error(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(ValidationError, match="Invalid tagged_vlans"),
        ):
            await unifi__config__create_port_profile(
                name="Test",
                native_vlan=10,
                tagged_vlans="5000",
                apply=True,
            )


class TestCreatePortProfileSuccess:
    """Successful create_port_profile operations."""

    async def test_creates_profile_with_defaults(self) -> None:
        mock_client = _mock_client_for_portconf_create()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.config._get_client", return_value=mock_client),
        ):
            result = await unifi__config__create_port_profile(
                name="Trunk-AP",
                native_vlan=1,
                apply=True,
            )

        assert result["profile_id"] == "prof001"
        assert result["name"] == "Trunk-AP"
        assert result["native_vlan"] == 1
        assert result["tagged_vlans"] == []
        assert result["poe"] is False

        # Verify the POST payload
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/api/s/default/rest/portconf"
        body = call_args[1]["data"] if "data" in call_args[1] else call_args[0][1]
        assert body["name"] == "Trunk-AP"
        assert body["native_networkconf_id"] == "1"
        assert body["tagged_networkconf_ids"] == []
        assert body["poe_mode"] == "off"

    async def test_creates_profile_with_tagged_vlans(self) -> None:
        mock_client = _mock_client_for_portconf_create()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.config._get_client", return_value=mock_client),
        ):
            result = await unifi__config__create_port_profile(
                name="Trunk-AP",
                native_vlan=1,
                tagged_vlans="30,50,60",
                apply=True,
            )

        assert result["tagged_vlans"] == ["30", "50", "60"]

        call_args = mock_client.post.call_args
        body = call_args[1]["data"] if "data" in call_args[1] else call_args[0][1]
        assert body["tagged_networkconf_ids"] == ["30", "50", "60"]

    async def test_creates_profile_with_poe_enabled(self) -> None:
        mock_client = _mock_client_for_portconf_create()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.config._get_client", return_value=mock_client),
        ):
            result = await unifi__config__create_port_profile(
                name="PoE-AP",
                native_vlan=10,
                poe=True,
                apply=True,
            )

        assert result["poe"] is True

        call_args = mock_client.post.call_args
        body = call_args[1]["data"] if "data" in call_args[1] else call_args[0][1]
        assert body["poe_mode"] == "auto"

    async def test_custom_site_id(self) -> None:
        mock_client = _mock_client_for_portconf_create()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.config._get_client", return_value=mock_client),
        ):
            result = await unifi__config__create_port_profile(
                name="Test",
                native_vlan=10,
                site_id="branch",
                apply=True,
            )

        assert result["site_id"] == "branch"
        call_args = mock_client.post.call_args
        assert "/api/s/branch/rest/portconf" in call_args[0][0]

    async def test_api_error_propagates(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=APIError("Server error", status_code=500))
        mock_client.close = AsyncMock()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.config._get_client", return_value=mock_client),
            pytest.raises(APIError, match="Server error"),
        ):
            await unifi__config__create_port_profile(
                name="Test",
                native_vlan=10,
                apply=True,
            )

        mock_client.close.assert_called_once()

    async def test_client_closed_on_success(self) -> None:
        mock_client = _mock_client_for_portconf_create()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.config._get_client", return_value=mock_client),
        ):
            await unifi__config__create_port_profile(
                name="Test",
                native_vlan=10,
                apply=True,
            )

        mock_client.close.assert_called_once()


# ===========================================================================
# Task 68: unifi__topology__assign_port_profile
# ===========================================================================


class TestAssignPortProfileWriteGate:
    """Write gate enforcement for assign_port_profile."""

    async def test_blocked_when_env_var_disabled(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "false"}),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=5,
                profile_name="Trunk-AP",
                apply=True,
            )
        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    async def test_blocked_when_apply_missing(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=5,
                profile_name="Trunk-AP",
            )
        assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    async def test_blocked_when_env_var_unset(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=5,
                profile_name="Trunk-AP",
                apply=True,
            )
        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED


class TestAssignPortProfileValidation:
    """Input validation for assign_port_profile."""

    async def test_port_idx_zero_raises_validation_error(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(ValidationError, match="port_idx"),
        ):
            await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=0,
                profile_name="Trunk-AP",
                apply=True,
            )

    async def test_port_idx_negative_raises_validation_error(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(ValidationError, match="port_idx"),
        ):
            await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=-1,
                profile_name="Trunk-AP",
                apply=True,
            )

    async def test_empty_profile_name_raises_validation_error(self) -> None:
        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(ValidationError, match="name must not be empty"),
        ):
            await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=5,
                profile_name="",
                apply=True,
            )

    async def test_profile_not_found_raises_validation_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_single = AsyncMock(
            return_value={
                "_id": "dev123",
                "port_overrides": [],
            }
        )
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(
                data=[{"_id": "prof001", "name": "Other-Profile"}],
                count=1,
                meta={"rc": "ok"},
            )
        )
        mock_client.close = AsyncMock()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.topology._get_client", return_value=mock_client),
            pytest.raises(ValidationError, match="not found"),
        ):
            await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=5,
                profile_name="Nonexistent",
                apply=True,
            )

        mock_client.close.assert_called_once()


class TestAssignPortProfileSuccess:
    """Successful assign_port_profile operations."""

    async def test_assigns_profile_to_empty_overrides(self) -> None:
        mock_client = _mock_client_for_port_assign()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.topology._get_client", return_value=mock_client),
        ):
            result = await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=5,
                profile_name="Trunk-AP",
                apply=True,
            )

        assert result["device_id"] == "dev123"
        assert result["port_idx"] == 5
        assert result["profile_applied"] == "Trunk-AP"
        assert result["profile_id"] == "prof001"

        # Verify the PUT was called with correct port_overrides
        mock_client.put.assert_called_once()
        put_args = mock_client.put.call_args
        body = put_args[1]["data"] if "data" in put_args[1] else put_args[0][1]
        assert any(
            o["port_idx"] == 5 and o["portconf_id"] == "prof001" for o in body["port_overrides"]
        )

    async def test_assigns_profile_to_existing_overrides(self) -> None:
        """When port_overrides already has other ports, they should be preserved."""
        existing = [
            {"port_idx": 1, "portconf_id": "prof_old"},
            {"port_idx": 3, "portconf_id": "prof_old2"},
        ]
        mock_client = _mock_client_for_port_assign(existing_overrides=existing)

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.topology._get_client", return_value=mock_client),
        ):
            result = await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=5,
                profile_name="Trunk-AP",
                apply=True,
            )

        assert result["profile_applied"] == "Trunk-AP"

        put_args = mock_client.put.call_args
        body = put_args[1]["data"] if "data" in put_args[1] else put_args[0][1]
        overrides = body["port_overrides"]
        # Original overrides should be preserved
        assert len(overrides) == 3
        assert {"port_idx": 1, "portconf_id": "prof_old"} in overrides
        assert {"port_idx": 3, "portconf_id": "prof_old2"} in overrides

    async def test_updates_existing_override_for_same_port(self) -> None:
        """When the port already has an override, it should be updated, not duplicated."""
        existing = [
            {"port_idx": 5, "portconf_id": "old_prof"},
            {"port_idx": 1, "portconf_id": "other_prof"},
        ]
        mock_client = _mock_client_for_port_assign(existing_overrides=existing)

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.topology._get_client", return_value=mock_client),
        ):
            await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=5,
                profile_name="Trunk-AP",
                apply=True,
            )

        put_args = mock_client.put.call_args
        body = put_args[1]["data"] if "data" in put_args[1] else put_args[0][1]
        overrides = body["port_overrides"]
        # Should still be 2 entries, not 3 (updated, not appended)
        assert len(overrides) == 2
        port5 = next(o for o in overrides if o["port_idx"] == 5)
        assert port5["portconf_id"] == "prof001"

    async def test_custom_site_id(self) -> None:
        mock_client = _mock_client_for_port_assign()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.topology._get_client", return_value=mock_client),
        ):
            result = await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=5,
                profile_name="Trunk-AP",
                site_id="branch",
                apply=True,
            )

        assert result["site_id"] == "branch"
        # Verify correct site_id in all API calls
        mock_client.get_single.assert_called_once_with(
            "/api/s/branch/stat/device/dev123",
        )
        mock_client.get_normalized.assert_called_once_with(
            "/api/s/branch/rest/portconf",
        )

    async def test_api_error_on_get_device_propagates(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_single = AsyncMock(
            side_effect=APIError("Device not found", status_code=404)
        )
        mock_client.close = AsyncMock()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.topology._get_client", return_value=mock_client),
            pytest.raises(APIError, match="Device not found"),
        ):
            await unifi__topology__assign_port_profile(
                device_id="bad-id",
                port_idx=5,
                profile_name="Trunk-AP",
                apply=True,
            )

        mock_client.close.assert_called_once()

    async def test_api_error_on_put_propagates(self) -> None:
        mock_client = _mock_client_for_port_assign()
        mock_client.put = AsyncMock(side_effect=APIError("Internal error", status_code=500))

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.topology._get_client", return_value=mock_client),
            pytest.raises(APIError, match="Internal error"),
        ):
            await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=5,
                profile_name="Trunk-AP",
                apply=True,
            )

        mock_client.close.assert_called_once()

    async def test_client_closed_on_success(self) -> None:
        mock_client = _mock_client_for_port_assign()

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.tools.topology._get_client", return_value=mock_client),
        ):
            await unifi__topology__assign_port_profile(
                device_id="dev123",
                port_idx=5,
                profile_name="Trunk-AP",
                apply=True,
            )

        mock_client.close.assert_called_once()


# ===========================================================================
# Unit tests for helper functions
# ===========================================================================


class TestParseTaggedVlans:
    """Unit tests for _parse_tagged_vlans helper."""

    def test_empty_string(self) -> None:
        assert _parse_tagged_vlans("") == []

    def test_whitespace_only(self) -> None:
        assert _parse_tagged_vlans("   ") == []

    def test_single_vlan(self) -> None:
        assert _parse_tagged_vlans("30") == ["30"]

    def test_multiple_vlans(self) -> None:
        assert _parse_tagged_vlans("30,50,60") == ["30", "50", "60"]

    def test_strips_whitespace(self) -> None:
        assert _parse_tagged_vlans(" 30 , 50 , 60 ") == ["30", "50", "60"]

    def test_filters_empty_entries(self) -> None:
        assert _parse_tagged_vlans("30,,50,") == ["30", "50"]


class TestValidateVlanId:
    """Unit tests for _validate_vlan_id helper."""

    def test_valid_min(self) -> None:
        _validate_vlan_id(1)  # Should not raise

    def test_valid_max(self) -> None:
        _validate_vlan_id(4094)  # Should not raise

    def test_invalid_zero(self) -> None:
        with pytest.raises(ValidationError, match="Invalid"):
            _validate_vlan_id(0)

    def test_invalid_above_max(self) -> None:
        with pytest.raises(ValidationError, match="Invalid"):
            _validate_vlan_id(4095)

    def test_invalid_negative(self) -> None:
        with pytest.raises(ValidationError, match="Invalid"):
            _validate_vlan_id(-1)


class TestBuildPortOverrides:
    """Unit tests for _build_port_overrides helper."""

    def test_appends_to_empty_list(self) -> None:
        result = _build_port_overrides([], 5, "prof001")
        assert result == [{"port_idx": 5, "portconf_id": "prof001"}]

    def test_appends_new_port(self) -> None:
        existing = [{"port_idx": 1, "portconf_id": "old"}]
        result = _build_port_overrides(existing, 5, "prof001")
        assert len(result) == 2
        assert {"port_idx": 5, "portconf_id": "prof001"} in result

    def test_updates_existing_port(self) -> None:
        existing = [
            {"port_idx": 5, "portconf_id": "old"},
            {"port_idx": 1, "portconf_id": "other"},
        ]
        result = _build_port_overrides(existing, 5, "new_prof")
        assert len(result) == 2
        port5 = next(o for o in result if o["port_idx"] == 5)
        assert port5["portconf_id"] == "new_prof"

    def test_does_not_mutate_original(self) -> None:
        existing = [{"port_idx": 5, "portconf_id": "old"}]
        _build_port_overrides(existing, 5, "new")
        assert existing[0]["portconf_id"] == "old"  # Original unchanged
