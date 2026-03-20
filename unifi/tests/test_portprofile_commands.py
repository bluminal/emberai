# SPDX-License-Identifier: MIT
"""Comprehensive tests for port-profile command-level MCP tools (Tasks 69-70).

Covers:
- Task 69: unifi_port_profile_create and unifi_port_profile_assign commands
- Task 70: M2.2 comprehensive test coverage

Test categories:
- Port-profile create: plan-only mode, apply mode, VLAN validation, three-phase model
- Port-profile assign: plan-only mode, apply mode, outage risk warning, switch lookup
- Write gate enforcement across both commands
- MCP tool registration
- Helper function unit tests (_verify_vlans_exist, _lookup_switch, _lookup_profile)

Note: The helper functions in commands.py use deferred imports (inside function
bodies), following the existing codebase convention.  Test patches must therefore
target the *source* modules (e.g. ``unifi.tools.topology.unifi__topology__get_vlans``),
not the commands module namespace.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from unifi.api.response import NormalizedResponse
from unifi.errors import ValidationError, WriteGateError
from unifi.safety import WriteBlockReason
from unifi.tools.commands import (
    _lookup_profile,
    _lookup_switch,
    _verify_vlans_exist,
    unifi_port_profile_assign,
    unifi_port_profile_create,
)

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

# Patch targets -- source modules where the functions are defined
_PATCH_GET_VLANS = "unifi.tools.topology.unifi__topology__get_vlans"
_PATCH_LIST_DEVICES = "unifi.tools.topology.unifi__topology__list_devices"
_PATCH_CONFIG_GET_CLIENT = "unifi.tools.config._get_client"
_PATCH_CREATE_PROFILE = "unifi.tools.config.unifi__config__create_port_profile"
_PATCH_ASSIGN_PROFILE = "unifi.tools.topology.unifi__topology__assign_port_profile"


def _mock_vlans(vlans: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Return a default set of VLAN dicts for testing."""
    if vlans is not None:
        return vlans
    return [
        {"name": "Default", "vlan_id": 1, "vlan_enabled": False},
        {"name": "Management", "vlan_id": 10, "vlan_enabled": True, "vlan": 10},
        {"name": "IoT", "vlan_id": 30, "vlan_enabled": True, "vlan": 30},
        {"name": "Guest", "vlan_id": 50, "vlan_enabled": True, "vlan": 50},
    ]


def _mock_devices(devices: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Return a default set of device dicts for testing."""
    if devices is not None:
        return devices
    return [
        {
            "device_id": "dev_switch_01",
            "mac": "aa:bb:cc:dd:ee:01",
            "name": "Core-Switch",
            "type": "usw",
            "port_overrides": [
                {"port_idx": 1, "portconf_id": "prof_trunk"},
                {"port_idx": 3, "portconf_id": "prof_iot"},
            ],
        },
        {
            "device_id": "dev_ap_01",
            "mac": "aa:bb:cc:dd:ee:02",
            "name": "Office-AP",
            "type": "uap",
            "port_overrides": [],
        },
    ]


def _mock_portconf_response(
    profiles: list[dict[str, Any]] | None = None,
) -> NormalizedResponse:
    """Return a NormalizedResponse with port profiles."""
    if profiles is None:
        profiles = [
            {"_id": "prof_trunk", "name": "Trunk-AP"},
            {"_id": "prof_iot", "name": "IoT-Only"},
            {"_id": "prof_all", "name": "All"},
        ]
    return NormalizedResponse(data=profiles, count=len(profiles), meta={"rc": "ok"})


def _mock_config_client(profiles: list[dict[str, Any]] | None = None) -> AsyncMock:
    """Create a mock client for profile lookup."""
    mock_client = AsyncMock()
    mock_client.get_normalized = AsyncMock(
        return_value=_mock_portconf_response(profiles),
    )
    mock_client.close = AsyncMock()
    return mock_client


# ===========================================================================
# Task 69a: unifi_port_profile_create -- Plan-only mode (no apply)
# ===========================================================================


class TestPortProfileCreatePlanOnly:
    """Port-profile create in plan-only mode (apply=False)."""

    async def test_plan_only_returns_change_plan(self) -> None:
        """Without apply, returns a change plan (not an execution result)."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with patch(_PATCH_GET_VLANS, mock_get_vlans):
            result = await unifi_port_profile_create(
                name="Trunk-AP", native_vlan=1,
            )

        assert "Change Plan" in result
        assert "Plan-only mode" in result

    async def test_plan_only_shows_profile_details(self) -> None:
        """Plan-only output includes the profile name and VLAN details."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with patch(_PATCH_GET_VLANS, mock_get_vlans):
            result = await unifi_port_profile_create(
                name="Trunk-AP", native_vlan=10, tagged_vlans="30,50",
            )

        assert "Trunk-AP" in result
        assert "10" in result
        assert "30" in result
        assert "50" in result

    async def test_plan_only_shows_poe_status(self) -> None:
        """Plan-only output shows PoE enabled/disabled."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with patch(_PATCH_GET_VLANS, mock_get_vlans):
            result_poe = await unifi_port_profile_create(
                name="PoE-AP", native_vlan=1, poe=True,
            )
            result_no_poe = await unifi_port_profile_create(
                name="No-PoE", native_vlan=1, poe=False,
            )

        assert "enabled" in result_poe
        assert "disabled" in result_no_poe

    async def test_plan_only_includes_write_status_disabled(self) -> None:
        """When writes are disabled, plan-only output notes this."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with (
            patch(_PATCH_GET_VLANS, mock_get_vlans),
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "false"}),
        ):
            result = await unifi_port_profile_create(
                name="Trunk-AP", native_vlan=1,
            )

        assert "disabled" in result.lower()
        assert "UNIFI_WRITE_ENABLED" in result

    async def test_plan_only_includes_write_status_enabled(self) -> None:
        """When writes are enabled, plan-only output mentions apply=True."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with (
            patch(_PATCH_GET_VLANS, mock_get_vlans),
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
        ):
            result = await unifi_port_profile_create(
                name="Trunk-AP", native_vlan=1,
            )

        assert "apply=True" in result

    async def test_plan_only_does_not_call_write_tool(self) -> None:
        """Plan-only mode must NOT call the underlying write tool."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())
        mock_create = AsyncMock()

        with (
            patch(_PATCH_GET_VLANS, mock_get_vlans),
            patch(_PATCH_CREATE_PROFILE, mock_create),
        ):
            await unifi_port_profile_create(name="Test", native_vlan=1)

        mock_create.assert_not_called()


# ===========================================================================
# Task 69a: unifi_port_profile_create -- VLAN validation (Phase 1)
# ===========================================================================


class TestPortProfileCreateVlanValidation:
    """VLAN existence verification for port-profile create."""

    async def test_missing_native_vlan_returns_error(self) -> None:
        """When the native VLAN does not exist, return a verification failure."""
        vlans = [
            {"name": "Default", "vlan_id": 1, "vlan_enabled": False},
        ]
        mock_get_vlans = AsyncMock(return_value=vlans)

        with patch(_PATCH_GET_VLANS, mock_get_vlans):
            result = await unifi_port_profile_create(
                name="Test", native_vlan=999,
            )

        assert "Verification Failed" in result
        assert "999" in result

    async def test_missing_tagged_vlan_returns_error(self) -> None:
        """When a tagged VLAN does not exist, return a verification failure."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with patch(_PATCH_GET_VLANS, mock_get_vlans):
            result = await unifi_port_profile_create(
                name="Test", native_vlan=1, tagged_vlans="30,999",
            )

        assert "Verification Failed" in result
        assert "999" in result

    async def test_all_vlans_exist_proceeds_to_plan(self) -> None:
        """When all VLANs exist, the plan is presented (no failure)."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with patch(_PATCH_GET_VLANS, mock_get_vlans):
            result = await unifi_port_profile_create(
                name="Test", native_vlan=1, tagged_vlans="30,50",
            )

        assert "Change Plan" in result
        assert "Verification Failed" not in result


# ===========================================================================
# Task 69a: unifi_port_profile_create -- Apply mode (Phase 3)
# ===========================================================================


class TestPortProfileCreateApplyMode:
    """Port-profile create with apply=True."""

    async def test_apply_delegates_to_write_tool(self) -> None:
        """With apply=True, delegates to unifi__config__create_port_profile."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())
        mock_create = AsyncMock(return_value={
            "profile_id": "prof_new",
            "name": "Trunk-AP",
            "native_vlan": 1,
            "tagged_vlans": ["30"],
            "poe": False,
            "site_id": "default",
        })

        with (
            patch(_PATCH_GET_VLANS, mock_get_vlans),
            patch(_PATCH_CREATE_PROFILE, mock_create),
        ):
            result = await unifi_port_profile_create(
                name="Trunk-AP", native_vlan=1, tagged_vlans="30", apply=True,
            )

        assert "Port Profile Created" in result
        assert "prof_new" in result
        mock_create.assert_called_once_with(
            name="Trunk-AP",
            native_vlan=1,
            tagged_vlans="30",
            poe=False,
            site_id="default",
            apply=True,
        )

    async def test_apply_with_write_gate_disabled_raises(self) -> None:
        """With apply=True but writes disabled, the write tool raises WriteGateError."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with (
            patch(_PATCH_GET_VLANS, mock_get_vlans),
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "false"}),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi_port_profile_create(
                name="Test", native_vlan=1, apply=True,
            )

        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    async def test_apply_returns_created_profile_details(self) -> None:
        """Successful apply returns formatted profile details."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())
        mock_create = AsyncMock(return_value={
            "profile_id": "prof_new",
            "name": "PoE-Profile",
            "native_vlan": 10,
            "tagged_vlans": ["30", "50"],
            "poe": True,
            "site_id": "default",
        })

        with (
            patch(_PATCH_GET_VLANS, mock_get_vlans),
            patch(_PATCH_CREATE_PROFILE, mock_create),
        ):
            result = await unifi_port_profile_create(
                name="PoE-Profile", native_vlan=10, tagged_vlans="30,50",
                poe=True, apply=True,
            )

        assert "PoE-Profile" in result
        assert "enabled" in result
        assert "30, 50" in result


# ===========================================================================
# Task 69b: unifi_port_profile_assign -- Plan-only mode
# ===========================================================================


class TestPortProfileAssignPlanOnly:
    """Port-profile assign in plan-only mode (apply=False)."""

    async def test_plan_only_returns_change_plan(self) -> None:
        """Without apply, returns a change plan with current -> new profile."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
        ):
            result = await unifi_port_profile_assign(
                switch="Core-Switch", port="5", profile="Trunk-AP",
            )

        assert "Change Plan" in result
        assert "Plan-only mode" in result

    async def test_plan_shows_current_and_new_profile(self) -> None:
        """Plan output shows the current profile -> new profile transition."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
        ):
            result = await unifi_port_profile_assign(
                switch="Core-Switch", port="1", profile="Trunk-AP",
            )

        # Port 1 has existing override with prof_trunk
        assert "Trunk-AP" in result
        assert "Core-Switch" in result

    async def test_plan_does_not_call_write_tool(self) -> None:
        """Plan-only mode must NOT call the underlying write tool."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()
        mock_assign = AsyncMock()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
            patch(_PATCH_ASSIGN_PROFILE, mock_assign),
        ):
            await unifi_port_profile_assign(
                switch="Core-Switch", port="5", profile="Trunk-AP",
            )

        mock_assign.assert_not_called()


# ===========================================================================
# Task 69b: unifi_port_profile_assign -- Outage risk warning
# ===========================================================================


class TestPortProfileAssignOutageRisk:
    """Outage risk warning for port-profile assign."""

    async def test_outage_risk_warning_present(self) -> None:
        """Plan output includes OutageRiskAgent unavailability warning."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
        ):
            result = await unifi_port_profile_assign(
                switch="Core-Switch", port="5", profile="Trunk-AP",
            )

        assert "OutageRiskAgent" in result
        assert "management session" in result

    async def test_outage_risk_in_change_plan_section(self) -> None:
        """The outage risk warning appears in the Outage Risk Assessment section."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
        ):
            result = await unifi_port_profile_assign(
                switch="Core-Switch", port="5", profile="Trunk-AP",
            )

        assert "Outage Risk Assessment" in result


# ===========================================================================
# Task 69b: unifi_port_profile_assign -- Switch lookup
# ===========================================================================


class TestPortProfileAssignSwitchLookup:
    """Switch lookup for port-profile assign."""

    async def test_lookup_by_name(self) -> None:
        """Can look up a switch by its name."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
        ):
            result = await unifi_port_profile_assign(
                switch="Core-Switch", port="5", profile="Trunk-AP",
            )

        assert "Change Plan" in result
        assert "Core-Switch" in result

    async def test_lookup_by_mac(self) -> None:
        """Can look up a switch by its MAC address."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
        ):
            result = await unifi_port_profile_assign(
                switch="aa:bb:cc:dd:ee:01", port="5", profile="Trunk-AP",
            )

        assert "Change Plan" in result

    async def test_lookup_by_device_id(self) -> None:
        """Can look up a switch by its device ID."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
        ):
            result = await unifi_port_profile_assign(
                switch="dev_switch_01", port="5", profile="Trunk-AP",
            )

        assert "Change Plan" in result

    async def test_switch_not_found_returns_message(self) -> None:
        """When no switch matches, return a 'not found' message."""
        mock_devices = AsyncMock(return_value=_mock_devices())

        with patch(_PATCH_LIST_DEVICES, mock_devices):
            result = await unifi_port_profile_assign(
                switch="Nonexistent-Switch", port="5", profile="Trunk-AP",
            )

        assert "Not Found" in result
        assert "Nonexistent-Switch" in result

    async def test_profile_not_found_returns_message(self) -> None:
        """When no profile matches, return a 'not found' message."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
        ):
            result = await unifi_port_profile_assign(
                switch="Core-Switch", port="5", profile="Nonexistent-Profile",
            )

        assert "Not Found" in result
        assert "Nonexistent-Profile" in result


# ===========================================================================
# Task 69b: unifi_port_profile_assign -- Apply mode
# ===========================================================================


class TestPortProfileAssignApplyMode:
    """Port-profile assign with apply=True."""

    async def test_apply_delegates_to_write_tool(self) -> None:
        """With apply=True, delegates to unifi__topology__assign_port_profile."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()
        mock_assign = AsyncMock(return_value={
            "device_id": "dev_switch_01",
            "port_idx": 5,
            "profile_applied": "Trunk-AP",
            "profile_id": "prof_trunk",
            "site_id": "default",
        })

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
            patch(_PATCH_ASSIGN_PROFILE, mock_assign),
        ):
            result = await unifi_port_profile_assign(
                switch="Core-Switch", port="5", profile="Trunk-AP", apply=True,
            )

        assert "Port Profile Assigned" in result
        assert "Trunk-AP" in result
        mock_assign.assert_called_once_with(
            device_id="dev_switch_01",
            port_idx=5,
            profile_name="Trunk-AP",
            site_id="default",
            apply=True,
        )

    async def test_apply_with_write_gate_disabled_raises(self) -> None:
        """With apply=True but writes disabled, the write tool raises WriteGateError."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "false"}),
            pytest.raises(WriteGateError),
        ):
            await unifi_port_profile_assign(
                switch="Core-Switch", port="5", profile="Trunk-AP", apply=True,
            )


# ===========================================================================
# Write gate enforcement
# ===========================================================================


class TestPortProfileWriteGate:
    """Write gate enforcement across both commands."""

    async def test_create_write_gate_env_var_disabled(self) -> None:
        """Create: WriteGateError with ENV_VAR_DISABLED when writes are off."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with (
            patch(_PATCH_GET_VLANS, mock_get_vlans),
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "false"}),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi_port_profile_create(
                name="Test", native_vlan=1, apply=True,
            )

        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    async def test_create_write_gate_env_var_unset(self) -> None:
        """Create: WriteGateError when UNIFI_WRITE_ENABLED is completely unset."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with (
            patch(_PATCH_GET_VLANS, mock_get_vlans),
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await unifi_port_profile_create(
                name="Test", native_vlan=1, apply=True,
            )

        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    async def test_assign_write_gate_env_var_disabled(self) -> None:
        """Assign: WriteGateError with ENV_VAR_DISABLED when writes are off."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "false"}),
            pytest.raises(WriteGateError),
        ):
            await unifi_port_profile_assign(
                switch="Core-Switch", port="5", profile="Trunk-AP", apply=True,
            )

    async def test_assign_write_gate_env_var_unset(self) -> None:
        """Assign: WriteGateError when UNIFI_WRITE_ENABLED is completely unset."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError),
        ):
            await unifi_port_profile_assign(
                switch="Core-Switch", port="5", profile="Trunk-AP", apply=True,
            )


# ===========================================================================
# Three-phase confirmation model validation
# ===========================================================================


class TestThreePhaseModel:
    """Validate the three-phase confirmation model."""

    async def test_create_phase1_vlan_check_before_plan(self) -> None:
        """Phase 1 (VLAN check) runs before Phase 2 (plan presentation)."""
        mock_get_vlans = AsyncMock(return_value=[])

        with patch(_PATCH_GET_VLANS, mock_get_vlans):
            result = await unifi_port_profile_create(
                name="Test", native_vlan=999,
            )

        # Should fail at Phase 1, never reach Phase 2
        assert "Verification Failed" in result
        assert "Change Plan" not in result

    async def test_create_phase2_plan_without_apply(self) -> None:
        """Phase 2 presents plan and returns without executing when apply=False."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with patch(_PATCH_GET_VLANS, mock_get_vlans):
            result = await unifi_port_profile_create(
                name="Test", native_vlan=1,
            )

        assert "Change Plan" in result
        assert "Execution Steps" in result
        assert "Plan-only mode" in result
        assert "Port Profile Created" not in result

    async def test_create_phase3_executes_with_apply(self) -> None:
        """Phase 3 executes the write when apply=True and gate passes."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())
        mock_create = AsyncMock(return_value={
            "profile_id": "prof_new",
            "name": "Test",
            "native_vlan": 1,
            "tagged_vlans": [],
            "poe": False,
            "site_id": "default",
        })

        with (
            patch(_PATCH_GET_VLANS, mock_get_vlans),
            patch(_PATCH_CREATE_PROFILE, mock_create),
        ):
            result = await unifi_port_profile_create(
                name="Test", native_vlan=1, apply=True,
            )

        assert "Port Profile Created" in result
        assert "Plan-only mode" not in result

    async def test_assign_phase1_lookup_before_plan(self) -> None:
        """Phase 1 (switch lookup) runs before Phase 2 (plan presentation)."""
        mock_devices = AsyncMock(return_value=_mock_devices())

        with patch(_PATCH_LIST_DEVICES, mock_devices):
            result = await unifi_port_profile_assign(
                switch="Nonexistent", port="5", profile="Trunk-AP",
            )

        assert "Not Found" in result
        assert "Change Plan" not in result

    async def test_assign_phase2_plan_without_apply(self) -> None:
        """Phase 2 presents plan with outage warning when apply=False."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
        ):
            result = await unifi_port_profile_assign(
                switch="Core-Switch", port="5", profile="Trunk-AP",
            )

        assert "Change Plan" in result
        assert "OutageRiskAgent" in result
        assert "Plan-only mode" in result

    async def test_assign_phase3_executes_with_apply(self) -> None:
        """Phase 3 executes the write when apply=True and gate passes."""
        mock_devices = AsyncMock(return_value=_mock_devices())
        mock_client = _mock_config_client()
        mock_assign = AsyncMock(return_value={
            "device_id": "dev_switch_01",
            "port_idx": 5,
            "profile_applied": "Trunk-AP",
            "profile_id": "prof_trunk",
            "site_id": "default",
        })

        with (
            patch(_PATCH_LIST_DEVICES, mock_devices),
            patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client),
            patch(_PATCH_ASSIGN_PROFILE, mock_assign),
        ):
            result = await unifi_port_profile_assign(
                switch="Core-Switch", port="5", profile="Trunk-AP", apply=True,
            )

        assert "Port Profile Assigned" in result
        assert "Plan-only mode" not in result


# ===========================================================================
# Input validation
# ===========================================================================


class TestPortProfileAssignValidation:
    """Input validation for port-profile assign."""

    async def test_invalid_port_non_numeric_raises(self) -> None:
        """Non-numeric port raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid port"):
            await unifi_port_profile_assign(
                switch="Core-Switch", port="abc", profile="Trunk-AP",
            )

    async def test_invalid_port_zero_raises(self) -> None:
        """Port index 0 raises ValidationError."""
        with pytest.raises(ValidationError, match="1-based"):
            await unifi_port_profile_assign(
                switch="Core-Switch", port="0", profile="Trunk-AP",
            )

    async def test_invalid_port_negative_raises(self) -> None:
        """Negative port index raises ValidationError."""
        with pytest.raises(ValidationError, match="1-based"):
            await unifi_port_profile_assign(
                switch="Core-Switch", port="-1", profile="Trunk-AP",
            )


# ===========================================================================
# Helper function unit tests
# ===========================================================================


class TestVerifyVlansExist:
    """Unit tests for _verify_vlans_exist helper."""

    async def test_all_vlans_found(self) -> None:
        """Returns empty missing list when all VLANs exist."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with patch(_PATCH_GET_VLANS, mock_get_vlans):
            existing, missing = await _verify_vlans_exist(1, "30,50", "default")

        assert len(missing) == 0
        assert len(existing) == 3  # native + 2 tagged

    async def test_some_vlans_missing(self) -> None:
        """Returns missing VLANs when they are not on the controller."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with patch(_PATCH_GET_VLANS, mock_get_vlans):
            _existing, missing = await _verify_vlans_exist(1, "30,999", "default")

        assert 999 in missing
        assert 30 not in missing

    async def test_empty_tagged_vlans(self) -> None:
        """No tagged VLANs means only native VLAN is checked."""
        mock_get_vlans = AsyncMock(return_value=_mock_vlans())

        with patch(_PATCH_GET_VLANS, mock_get_vlans):
            existing, missing = await _verify_vlans_exist(1, "", "default")

        assert len(missing) == 0
        assert len(existing) == 1


class TestLookupSwitch:
    """Unit tests for _lookup_switch helper."""

    async def test_find_by_name(self) -> None:
        """Finds a device by its name (case-insensitive)."""
        mock_devices = AsyncMock(return_value=_mock_devices())

        with patch(_PATCH_LIST_DEVICES, mock_devices):
            device = await _lookup_switch("core-switch", "default")

        assert device is not None
        assert device["name"] == "Core-Switch"

    async def test_find_by_mac(self) -> None:
        """Finds a device by its MAC address."""
        mock_devices = AsyncMock(return_value=_mock_devices())

        with patch(_PATCH_LIST_DEVICES, mock_devices):
            device = await _lookup_switch("aa:bb:cc:dd:ee:01", "default")

        assert device is not None
        assert device["mac"] == "aa:bb:cc:dd:ee:01"

    async def test_not_found_returns_none(self) -> None:
        """Returns None when no device matches."""
        mock_devices = AsyncMock(return_value=_mock_devices())

        with patch(_PATCH_LIST_DEVICES, mock_devices):
            device = await _lookup_switch("nonexistent", "default")

        assert device is None


class TestLookupProfile:
    """Unit tests for _lookup_profile helper."""

    async def test_find_by_name(self) -> None:
        """Finds a profile by name (case-insensitive)."""
        mock_client = _mock_config_client()

        with patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client):
            profile = await _lookup_profile("trunk-ap", "default")

        assert profile is not None
        assert profile["name"] == "Trunk-AP"

    async def test_not_found_returns_none(self) -> None:
        """Returns None when no profile matches."""
        mock_client = _mock_config_client()

        with patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client):
            profile = await _lookup_profile("nonexistent", "default")

        assert profile is None

    async def test_client_closed(self) -> None:
        """Client is closed after lookup, regardless of result."""
        mock_client = _mock_config_client()

        with patch(_PATCH_CONFIG_GET_CLIENT, return_value=mock_client):
            await _lookup_profile("any", "default")

        mock_client.close.assert_called_once()


# ===========================================================================
# MCP tool registration
# ===========================================================================


class TestPortProfileToolRegistration:
    """Verify port-profile command tools are registered on the MCP server."""

    def test_port_profile_create_registered(self) -> None:
        """unifi_port_profile_create is registered as an MCP tool."""
        from unifi.server import mcp_server

        tool_names = [t.name for t in mcp_server._tool_manager._tools.values()]
        assert "unifi_port_profile_create" in tool_names

    def test_port_profile_assign_registered(self) -> None:
        """unifi_port_profile_assign is registered as an MCP tool."""
        from unifi.server import mcp_server

        tool_names = [t.name for t in mcp_server._tool_manager._tools.values()]
        assert "unifi_port_profile_assign" in tool_names

    def test_create_tool_has_name_parameter(self) -> None:
        """unifi_port_profile_create tool accepts a name parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        tool = tools["unifi_port_profile_create"]
        schema = tool.parameters
        assert "name" in schema.get("properties", {})

    def test_create_tool_has_apply_parameter(self) -> None:
        """unifi_port_profile_create tool accepts an apply parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        tool = tools["unifi_port_profile_create"]
        schema = tool.parameters
        assert "apply" in schema.get("properties", {})

    def test_assign_tool_has_switch_parameter(self) -> None:
        """unifi_port_profile_assign tool accepts a switch parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        tool = tools["unifi_port_profile_assign"]
        schema = tool.parameters
        assert "switch" in schema.get("properties", {})

    def test_assign_tool_has_port_parameter(self) -> None:
        """unifi_port_profile_assign tool accepts a port parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        tool = tools["unifi_port_profile_assign"]
        schema = tool.parameters
        assert "port" in schema.get("properties", {})

    def test_assign_tool_has_profile_parameter(self) -> None:
        """unifi_port_profile_assign tool accepts a profile parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        tool = tools["unifi_port_profile_assign"]
        schema = tool.parameters
        assert "profile" in schema.get("properties", {})
