"""Tests for the guided cluster setup orchestration.

Covers all three phases:
    Phase 1 -- Gather: Input validation (valid inputs, insufficient CPs,
               VIP collision, invalid IP format, duplicates)
    Phase 2 -- Plan:   Step count, ordering, VIP patch presence/absence,
               KubeSpan patches, worker-only vs no-worker plans
    Phase 3 -- Execute: All steps succeed, failure mid-execution stops and
               reports, bootstrap pre-flight etcd poll, recovery guidance
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from talos.agents.cluster_setup import (
    ClusterSetupPlan,
    SetupResult,
    SetupStep,
    StepStatus,
    _is_step_success,
    _recovery_guidance_for_step,
    build_setup_plan,
    execute_setup_plan,
    validate_cluster_inputs,
)
from talos.api.talosctl_client import TalosCtlClient, TalosCtlResult
from talos.errors import TalosCtlError, ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Standard 3-CP + 2-worker test inputs
CP_IPS = ["10.0.0.11", "10.0.0.12", "10.0.0.13"]
WORKER_IPS = ["10.0.0.21", "10.0.0.22"]
VIP = "10.0.0.10"
CLUSTER_NAME = "test-cluster"


def _make_plan(**overrides: Any) -> ClusterSetupPlan:
    """Create a standard ClusterSetupPlan with optional overrides."""
    defaults: dict[str, Any] = {
        "cluster_name": CLUSTER_NAME,
        "control_plane_ips": list(CP_IPS),
        "worker_ips": list(WORKER_IPS),
        "vip": VIP,
    }
    defaults.update(overrides)
    return ClusterSetupPlan(**defaults)


def _make_success_result(**extra: Any) -> dict[str, Any]:
    """Create a tool result dict indicating success."""
    result: dict[str, Any] = {"status": "success"}
    result.update(extra)
    return result


def _make_ok_result(**extra: Any) -> dict[str, Any]:
    """Create a tool result dict indicating ok."""
    result: dict[str, Any] = {"status": "ok"}
    result.update(extra)
    return result


def _make_pass_result(**extra: Any) -> dict[str, Any]:
    """Create a tool result dict indicating pass (validation)."""
    result: dict[str, Any] = {"status": "pass"}
    result.update(extra)
    return result


def _make_error_result(error: str = "something failed") -> dict[str, Any]:
    """Create a tool result dict indicating failure."""
    return {"status": "error", "error": error}


def _mock_tool_fn(result: dict[str, Any]) -> AsyncMock:
    """Create an async mock that returns the given result."""
    return AsyncMock(return_value=result)


# ---------------------------------------------------------------------------
# Phase 1: Gather -- validate_cluster_inputs
# ---------------------------------------------------------------------------


class TestValidateClusterInputs:
    """Tests for Phase 1: input validation."""

    def test_valid_inputs_pass(self) -> None:
        """All valid inputs produce a ClusterSetupPlan."""
        plan = validate_cluster_inputs(
            cluster_name=CLUSTER_NAME,
            control_plane_ips=CP_IPS,
            worker_ips=WORKER_IPS,
            vip=VIP,
        )
        assert plan.cluster_name == CLUSTER_NAME
        assert plan.control_plane_ips == CP_IPS
        assert plan.worker_ips == WORKER_IPS
        assert plan.vip == VIP
        assert plan.endpoint == f"https://{VIP}:6443"

    def test_valid_inputs_no_vip(self) -> None:
        """No VIP uses first CP IP for endpoint."""
        plan = validate_cluster_inputs(
            cluster_name=CLUSTER_NAME,
            control_plane_ips=CP_IPS,
            worker_ips=WORKER_IPS,
        )
        assert plan.vip is None
        assert plan.endpoint == f"https://{CP_IPS[0]}:6443"

    def test_valid_inputs_no_workers(self) -> None:
        """CP-only cluster is valid."""
        plan = validate_cluster_inputs(
            cluster_name=CLUSTER_NAME,
            control_plane_ips=CP_IPS,
            worker_ips=[],
        )
        assert plan.worker_ips == []

    def test_insufficient_cp_nodes_rejected(self) -> None:
        """Fewer than 3 CP nodes raises ValidationError."""
        with pytest.raises(ValidationError, match="At least 3 control plane"):
            validate_cluster_inputs(
                cluster_name=CLUSTER_NAME,
                control_plane_ips=["10.0.0.11", "10.0.0.12"],
                worker_ips=[],
            )

    def test_single_cp_node_rejected(self) -> None:
        """Single CP node raises ValidationError."""
        with pytest.raises(ValidationError, match="At least 3 control plane"):
            validate_cluster_inputs(
                cluster_name=CLUSTER_NAME,
                control_plane_ips=["10.0.0.11"],
                worker_ips=[],
            )

    def test_empty_cp_list_rejected(self) -> None:
        """Empty CP list raises ValidationError."""
        with pytest.raises(ValidationError, match="At least 3 control plane"):
            validate_cluster_inputs(
                cluster_name=CLUSTER_NAME,
                control_plane_ips=[],
                worker_ips=[],
            )

    def test_vip_collision_rejected(self) -> None:
        """VIP matching a CP IP raises ValidationError."""
        with pytest.raises(ValidationError, match="VIP.*must not be the same"):
            validate_cluster_inputs(
                cluster_name=CLUSTER_NAME,
                control_plane_ips=CP_IPS,
                worker_ips=[],
                vip=CP_IPS[0],
            )

    def test_vip_collision_with_worker_rejected(self) -> None:
        """VIP matching a worker IP raises ValidationError."""
        with pytest.raises(ValidationError, match="VIP.*must not be the same"):
            validate_cluster_inputs(
                cluster_name=CLUSTER_NAME,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
                vip=WORKER_IPS[0],
            )

    def test_invalid_ip_format_rejected(self) -> None:
        """Invalid IP format raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid IP address"):
            validate_cluster_inputs(
                cluster_name=CLUSTER_NAME,
                control_plane_ips=["10.0.0.11", "10.0.0.12", "not-an-ip"],
                worker_ips=[],
            )

    def test_invalid_vip_format_rejected(self) -> None:
        """Invalid VIP format raises ValidationError."""
        with pytest.raises(ValidationError, match="VIP is not a valid"):
            validate_cluster_inputs(
                cluster_name=CLUSTER_NAME,
                control_plane_ips=CP_IPS,
                worker_ips=[],
                vip="bad-vip",
            )

    def test_empty_cluster_name_rejected(self) -> None:
        """Empty cluster name raises ValidationError."""
        with pytest.raises(ValidationError, match="cluster_name must be"):
            validate_cluster_inputs(
                cluster_name="",
                control_plane_ips=CP_IPS,
                worker_ips=[],
            )

    def test_whitespace_only_cluster_name_rejected(self) -> None:
        """Whitespace-only cluster name raises ValidationError."""
        with pytest.raises(ValidationError, match="cluster_name must be"):
            validate_cluster_inputs(
                cluster_name="   ",
                control_plane_ips=CP_IPS,
                worker_ips=[],
            )

    def test_duplicate_ips_rejected(self) -> None:
        """Duplicate IPs across CP and workers raises ValidationError."""
        with pytest.raises(ValidationError, match="Duplicate IP"):
            validate_cluster_inputs(
                cluster_name=CLUSTER_NAME,
                control_plane_ips=["10.0.0.11", "10.0.0.12", "10.0.0.13"],
                worker_ips=["10.0.0.11"],
            )

    def test_ipv6_addresses_accepted(self) -> None:
        """IPv6 addresses are valid."""
        plan = validate_cluster_inputs(
            cluster_name=CLUSTER_NAME,
            control_plane_ips=["fd00::1", "fd00::2", "fd00::3"],
            worker_ips=["fd00::10"],
        )
        assert plan.control_plane_ips == ["fd00::1", "fd00::2", "fd00::3"]

    def test_custom_install_disk(self) -> None:
        """Custom install disk is preserved."""
        plan = validate_cluster_inputs(
            cluster_name=CLUSTER_NAME,
            control_plane_ips=CP_IPS,
            worker_ips=[],
            install_disk="/dev/nvme0n1",
        )
        assert plan.install_disk == "/dev/nvme0n1"

    def test_kubernetes_version_preserved(self) -> None:
        """Kubernetes version is preserved."""
        plan = validate_cluster_inputs(
            cluster_name=CLUSTER_NAME,
            control_plane_ips=CP_IPS,
            worker_ips=[],
            kubernetes_version="1.30.0",
        )
        assert plan.kubernetes_version == "1.30.0"

    def test_multiple_errors_collected(self) -> None:
        """Multiple validation errors are collected and reported together."""
        with pytest.raises(ValidationError) as exc_info:
            validate_cluster_inputs(
                cluster_name="",
                control_plane_ips=["not-an-ip"],
                worker_ips=[],
            )
        # Should have at least cluster name error, CP count error, and IP format error
        assert len(exc_info.value.details["errors"]) >= 3


# ---------------------------------------------------------------------------
# Phase 2: Plan -- build_setup_plan
# ---------------------------------------------------------------------------


class TestBuildSetupPlan:
    """Tests for Phase 2: plan construction."""

    def test_correct_step_count_with_vip_and_workers(self) -> None:
        """Standard 3CP + 2W + VIP produces the expected number of steps."""
        plan = _make_plan()
        steps = build_setup_plan(plan)

        # Expected steps:
        # 1 gen_secrets + 1 gen_config + 1 VIP patch
        # + 1 validate CP + 1 validate worker
        # + 3 apply CP + 2 apply worker
        # + 1 set_endpoints + 1 merge_talosconfig
        # + 1 bootstrap + 1 health + 1 kubeconfig
        # = 15 steps
        assert len(steps) == 15

    def test_correct_step_count_no_vip_no_workers(self) -> None:
        """CP-only cluster without VIP produces fewer steps."""
        plan = _make_plan(vip=None, worker_ips=[])
        steps = build_setup_plan(plan)

        # 1 gen_secrets + 1 gen_config
        # + 1 validate CP (no worker validate since no workers)
        # + 3 apply CP (no worker applies)
        # + 1 set_endpoints + 1 merge_talosconfig
        # + 1 bootstrap + 1 health + 1 kubeconfig
        # = 11 steps
        assert len(steps) == 11

    def test_step_ordering(self) -> None:
        """Steps are in the correct order."""
        plan = _make_plan()
        steps = build_setup_plan(plan)

        tool_names = [s.tool_name for s in steps]

        # Secrets must come first
        assert tool_names[0] == "talos__config__gen_secrets"
        # Gen config must come second
        assert tool_names[1] == "talos__config__gen_config"

        # Bootstrap must come before health
        bootstrap_idx = next(i for i, s in enumerate(steps) if "bootstrap" in s.tool_name)
        health_idx = next(i for i, s in enumerate(steps) if "health" in s.tool_name)
        kubeconfig_idx = next(i for i, s in enumerate(steps) if "kubeconfig" in s.tool_name)
        assert bootstrap_idx < health_idx < kubeconfig_idx

        # set_endpoints and merge must come before bootstrap
        endpoints_idx = next(i for i, s in enumerate(steps) if "set_endpoints" in s.tool_name)
        merge_idx = next(i for i, s in enumerate(steps) if "merge_talosconfig" in s.tool_name)
        assert endpoints_idx < bootstrap_idx
        assert merge_idx < bootstrap_idx

    def test_vip_patch_included_when_vip_specified(self) -> None:
        """VIP patch step is present when VIP is provided."""
        plan = _make_plan(vip=VIP)
        steps = build_setup_plan(plan)

        patch_steps = [s for s in steps if s.tool_name == "talos__config__patch_machineconfig"]
        vip_patches = [s for s in patch_steps if "VIP" in s.description]
        assert len(vip_patches) == 1
        assert VIP in vip_patches[0].args["patches"]

    def test_no_vip_patch_when_vip_not_specified(self) -> None:
        """No VIP patch step when VIP is None."""
        plan = _make_plan(vip=None)
        steps = build_setup_plan(plan)

        vip_patches = [
            s for s in steps
            if s.tool_name == "talos__config__patch_machineconfig" and "VIP" in s.description
        ]
        assert len(vip_patches) == 0

    def test_kubespan_patches_when_enabled(self) -> None:
        """KubeSpan patch steps added for both CP and worker configs."""
        plan = _make_plan(enable_kubespan=True)
        steps = build_setup_plan(plan)

        kubespan_steps = [
            s for s in steps
            if s.tool_name == "talos__config__patch_machineconfig"
            and "KubeSpan" in s.description
        ]
        # One for CP, one for worker
        assert len(kubespan_steps) == 2
        descriptions = [s.description for s in kubespan_steps]
        assert any("controlplane" in d for d in descriptions)
        assert any("worker" in d for d in descriptions)

    def test_no_kubespan_patches_when_disabled(self) -> None:
        """No KubeSpan patches when enable_kubespan is False."""
        plan = _make_plan(enable_kubespan=False)
        steps = build_setup_plan(plan)

        kubespan_steps = [
            s for s in steps
            if "KubeSpan" in s.description
        ]
        assert len(kubespan_steps) == 0

    def test_apply_steps_use_insecure_mode(self) -> None:
        """All apply-config steps use insecure=True for first-time setup."""
        plan = _make_plan()
        steps = build_setup_plan(plan)

        apply_steps = [s for s in steps if s.tool_name == "talos__cluster__apply_config"]
        assert len(apply_steps) == 5  # 3 CP + 2 worker
        for step in apply_steps:
            assert step.args["insecure"] is True

    def test_apply_steps_target_correct_nodes(self) -> None:
        """Apply steps target the correct node IPs."""
        plan = _make_plan()
        steps = build_setup_plan(plan)

        apply_steps = [s for s in steps if s.tool_name == "talos__cluster__apply_config"]
        apply_nodes = [s.args["node"] for s in apply_steps]

        # First 3 should be CP nodes, last 2 should be workers
        assert apply_nodes[:3] == CP_IPS
        assert apply_nodes[3:] == WORKER_IPS

    def test_bootstrap_targets_first_cp(self) -> None:
        """Bootstrap step targets the first control plane node."""
        plan = _make_plan()
        steps = build_setup_plan(plan)

        bootstrap = next(s for s in steps if s.tool_name == "talos__cluster__bootstrap")
        assert bootstrap.args["node"] == CP_IPS[0]
        assert bootstrap.args["etcd_members_count"] == 0

    def test_set_endpoints_uses_all_cp_ips(self) -> None:
        """Set endpoints step includes all CP IPs."""
        plan = _make_plan()
        steps = build_setup_plan(plan)

        ep_step = next(s for s in steps if s.tool_name == "talos__cluster__set_endpoints")
        for cp_ip in CP_IPS:
            assert cp_ip in ep_step.args["endpoints"]

    def test_step_numbers_are_sequential(self) -> None:
        """Step numbers are sequential starting from 1."""
        plan = _make_plan()
        steps = build_setup_plan(plan)

        for i, step in enumerate(steps, 1):
            assert step.step_number == i

    def test_all_steps_start_pending(self) -> None:
        """All steps start with PENDING status."""
        plan = _make_plan()
        steps = build_setup_plan(plan)

        for step in steps:
            assert step.status == StepStatus.PENDING

    def test_output_dir_propagates_to_paths(self) -> None:
        """Custom output_dir is used in file path arguments."""
        plan = _make_plan()
        steps = build_setup_plan(plan, output_dir="/tmp/talos-setup")

        gen_secrets = steps[0]
        assert "/tmp/talos-setup" in gen_secrets.args["output_path"]

    def test_no_worker_validate_when_no_workers(self) -> None:
        """Worker validate step is omitted when there are no workers."""
        plan = _make_plan(worker_ips=[], vip=None)
        steps = build_setup_plan(plan)

        validate_steps = [s for s in steps if s.tool_name == "talos__config__validate"]
        # Only CP validate, no worker validate
        assert len(validate_steps) == 1
        assert "controlplane" in validate_steps[0].description.lower()


# ---------------------------------------------------------------------------
# Phase 3: Execute -- execute_setup_plan
# ---------------------------------------------------------------------------


class TestExecuteSetupPlan:
    """Tests for Phase 3: plan execution."""

    @pytest.mark.asyncio
    async def test_all_steps_succeed(self) -> None:
        """All steps succeeding returns success with cluster summary."""
        plan = _make_plan(vip=None, worker_ips=[])
        steps = build_setup_plan(plan)

        # Build a mock registry where every tool returns success
        mock_registry: dict[str, AsyncMock] = {}
        for step in steps:
            if step.tool_name not in mock_registry:
                if step.tool_name == "talos__config__validate":
                    mock_registry[step.tool_name] = _mock_tool_fn(
                        _make_pass_result(message="valid")
                    )
                elif step.tool_name == "talos__cluster__kubeconfig":
                    mock_registry[step.tool_name] = _mock_tool_fn(
                        _make_ok_result(kubeconfig="apiVersion: v1\nkind: Config")
                    )
                elif step.tool_name in (
                    "talos__config__gen_secrets",
                    "talos__config__gen_config",
                ):
                    mock_registry[step.tool_name] = _mock_tool_fn(
                        _make_success_result()
                    )
                else:
                    mock_registry[step.tool_name] = _mock_tool_fn(
                        _make_ok_result()
                    )

        # Mock the etcd members poll to succeed immediately
        mock_client = MagicMock(spec=TalosCtlClient)
        mock_client.run = AsyncMock(
            return_value=TalosCtlResult(
                stdout="",
                stderr="",
                exit_code=0,
                parsed={"messages": [{"members": [
                    {"id": "1"}, {"id": "2"}, {"id": "3"},
                ]}]},
            )
        )

        result = await execute_setup_plan(
            steps, plan, client=mock_client, tool_registry=mock_registry
        )

        assert result.status == "success"
        assert len(result.completed_steps) == len(steps)
        assert result.failed_step is None
        assert result.cluster_summary["cluster_name"] == CLUSTER_NAME
        assert result.cluster_summary["total_nodes"] == 3
        assert result.cluster_summary["kubeconfig_retrieved"] is True

    @pytest.mark.asyncio
    async def test_failure_at_step_n_stops_execution(self) -> None:
        """Failure mid-execution stops and reports the failed step."""
        plan = _make_plan(vip=None, worker_ips=[])
        steps = build_setup_plan(plan)

        # First two steps succeed, third step (validate) fails
        call_count = 0

        async def conditional_tool(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return _make_success_result()
            return _make_error_result("validation failed: bad config")

        # All tools point to the same conditional mock
        mock_registry = {
            step.tool_name: conditional_tool
            for step in steps
        }

        mock_client = MagicMock(spec=TalosCtlClient)

        result = await execute_setup_plan(
            steps, plan, client=mock_client, tool_registry=mock_registry
        )

        assert result.status == "failed"
        assert len(result.completed_steps) == 2
        assert result.failed_step is not None
        assert result.failed_step.step_number == 3
        assert result.failed_step.status == StepStatus.FAILED
        assert result.recovery_guidance != ""

    @pytest.mark.asyncio
    async def test_exception_in_step_is_caught(self) -> None:
        """Exception raised by a tool function is caught and reported."""
        plan = _make_plan(vip=None, worker_ips=[])
        steps = build_setup_plan(plan)

        async def exploding_tool(**kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("unexpected explosion")

        mock_registry = {
            step.tool_name: exploding_tool
            for step in steps
        }

        mock_client = MagicMock(spec=TalosCtlClient)

        result = await execute_setup_plan(
            steps, plan, client=mock_client, tool_registry=mock_registry
        )

        assert result.status == "failed"
        assert result.failed_step is not None
        assert result.failed_step.step_number == 1
        assert "explosion" in (result.failed_step.error or "")

    @pytest.mark.asyncio
    async def test_bootstrap_triggers_etcd_poll(self) -> None:
        """After bootstrap step, etcd members are polled."""
        plan = _make_plan(vip=None, worker_ips=[])
        steps = build_setup_plan(plan)

        # All tools succeed
        mock_registry = {
            step.tool_name: _mock_tool_fn(_make_ok_result())
            for step in steps
        }
        # Override specific tools that need different statuses
        mock_registry["talos__config__gen_secrets"] = _mock_tool_fn(_make_success_result())
        mock_registry["talos__config__gen_config"] = _mock_tool_fn(_make_success_result())
        mock_registry["talos__config__validate"] = _mock_tool_fn(_make_pass_result())
        mock_registry["talos__config__patch_machineconfig"] = _mock_tool_fn(
            _make_success_result()
        )
        mock_registry["talos__cluster__kubeconfig"] = _mock_tool_fn(
            _make_ok_result(kubeconfig="content")
        )

        # Mock client for etcd poll
        mock_client = MagicMock(spec=TalosCtlClient)
        mock_client.run = AsyncMock(
            return_value=TalosCtlResult(
                stdout="",
                stderr="",
                exit_code=0,
                parsed={"messages": [{"members": [
                    {"id": "1"}, {"id": "2"}, {"id": "3"},
                ]}]},
            )
        )

        result = await execute_setup_plan(
            steps, plan, client=mock_client, tool_registry=mock_registry
        )

        assert result.status == "success"
        # Verify etcd poll was called
        mock_client.run.assert_called()
        # Check that at least one call was for etcd members
        etcd_calls = [
            c for c in mock_client.run.call_args_list
            if "etcd" in str(c)
        ]
        assert len(etcd_calls) > 0

    @pytest.mark.asyncio
    async def test_etcd_poll_timeout_does_not_fail_setup(self) -> None:
        """etcd poll timeout logs a warning but does not fail the setup."""
        plan = _make_plan(vip=None, worker_ips=[])
        steps = build_setup_plan(plan)

        # All tools succeed
        mock_registry = {
            step.tool_name: _mock_tool_fn(_make_ok_result())
            for step in steps
        }
        mock_registry["talos__config__gen_secrets"] = _mock_tool_fn(_make_success_result())
        mock_registry["talos__config__gen_config"] = _mock_tool_fn(_make_success_result())
        mock_registry["talos__config__validate"] = _mock_tool_fn(_make_pass_result())
        mock_registry["talos__config__patch_machineconfig"] = _mock_tool_fn(
            _make_success_result()
        )
        mock_registry["talos__cluster__kubeconfig"] = _mock_tool_fn(
            _make_ok_result(kubeconfig="content")
        )

        # Mock client that always fails etcd poll (simulating slow convergence)
        mock_client = MagicMock(spec=TalosCtlClient)
        mock_client.run = AsyncMock(
            side_effect=TalosCtlError("etcd not ready", stderr="", exit_code=1)
        )

        # Use a very short timeout so the test doesn't hang
        with patch(
            "talos.agents.cluster_setup._poll_etcd_members",
            new_callable=AsyncMock,
            return_value={"status": "timeout", "member_count": 0, "expected_count": 3},
        ):
            result = await execute_setup_plan(
                steps, plan, client=mock_client, tool_registry=mock_registry
            )

        # Setup should still succeed even with etcd poll timeout
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_first_step_failure_returns_empty_completed(self) -> None:
        """Failure on the very first step returns empty completed list."""
        plan = _make_plan(vip=None, worker_ips=[])
        steps = build_setup_plan(plan)

        mock_registry = {
            step.tool_name: _mock_tool_fn(_make_error_result("gen secrets failed"))
            for step in steps
        }
        mock_client = MagicMock(spec=TalosCtlClient)

        result = await execute_setup_plan(
            steps, plan, client=mock_client, tool_registry=mock_registry
        )

        assert result.status == "failed"
        assert len(result.completed_steps) == 0
        assert result.failed_step is not None
        assert result.failed_step.step_number == 1

    @pytest.mark.asyncio
    async def test_step_statuses_updated_correctly(self) -> None:
        """Step statuses are updated to SUCCESS on completion."""
        plan = _make_plan(vip=None, worker_ips=[])
        steps = build_setup_plan(plan)

        mock_registry = {
            step.tool_name: _mock_tool_fn(_make_ok_result())
            for step in steps
        }
        mock_registry["talos__config__gen_secrets"] = _mock_tool_fn(_make_success_result())
        mock_registry["talos__config__gen_config"] = _mock_tool_fn(_make_success_result())
        mock_registry["talos__config__validate"] = _mock_tool_fn(_make_pass_result())
        mock_registry["talos__cluster__kubeconfig"] = _mock_tool_fn(
            _make_ok_result(kubeconfig="content")
        )

        mock_client = MagicMock(spec=TalosCtlClient)
        mock_client.run = AsyncMock(
            return_value=TalosCtlResult(
                stdout="", stderr="", exit_code=0,
                parsed={"messages": [{"members": [
                    {"id": "1"}, {"id": "2"}, {"id": "3"},
                ]}]},
            )
        )

        result = await execute_setup_plan(
            steps, plan, client=mock_client, tool_registry=mock_registry
        )

        for step in result.completed_steps:
            assert step.status == StepStatus.SUCCESS


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_is_step_success_for_ok(self) -> None:
        assert _is_step_success({"status": "ok"}) is True

    def test_is_step_success_for_success(self) -> None:
        assert _is_step_success({"status": "success"}) is True

    def test_is_step_success_for_pass(self) -> None:
        assert _is_step_success({"status": "pass"}) is True

    def test_is_step_success_for_error(self) -> None:
        assert _is_step_success({"status": "error"}) is False

    def test_is_step_success_for_fail(self) -> None:
        assert _is_step_success({"status": "fail"}) is False

    def test_recovery_guidance_gen_secrets(self) -> None:
        step = SetupStep(
            step_number=1,
            description="",
            tool_name="talos__config__gen_secrets",
        )
        plan = _make_plan()
        guidance = _recovery_guidance_for_step(step, plan)
        assert "Secret generation" in guidance

    def test_recovery_guidance_apply_config(self) -> None:
        step = SetupStep(
            step_number=5,
            description="",
            tool_name="talos__cluster__apply_config",
            args={"node": "10.0.0.11"},
        )
        plan = _make_plan()
        guidance = _recovery_guidance_for_step(step, plan)
        assert "10.0.0.11" in guidance
        assert "maintenance mode" in guidance

    def test_recovery_guidance_bootstrap(self) -> None:
        step = SetupStep(
            step_number=10,
            description="",
            tool_name="talos__cluster__bootstrap",
        )
        plan = _make_plan()
        guidance = _recovery_guidance_for_step(step, plan)
        assert "bootstrap" in guidance.lower()

    def test_recovery_guidance_unknown_tool(self) -> None:
        step = SetupStep(
            step_number=1,
            description="",
            tool_name="unknown_tool",
        )
        plan = _make_plan()
        guidance = _recovery_guidance_for_step(step, plan)
        assert "Review the error" in guidance


# ---------------------------------------------------------------------------
# MCP tool wrapper (setup.py)
# ---------------------------------------------------------------------------


class TestSetupTool:
    """Tests for the talos__cluster__setup MCP tool wrapper."""

    @pytest.mark.asyncio
    async def test_write_gate_blocks_without_env(self) -> None:
        """Write gate blocks when TALOS_WRITE_ENABLED is not set."""
        from talos.errors import WriteGateError
        from talos.tools.setup import talos__cluster__setup

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError):
                await talos__cluster__setup(
                    cluster_name=CLUSTER_NAME,
                    control_plane_ips=",".join(CP_IPS),
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_validation_error_returned_not_raised(self) -> None:
        """Validation errors are returned as error dicts, not raised."""
        from talos.tools.setup import talos__cluster__setup

        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            result = await talos__cluster__setup(
                cluster_name=CLUSTER_NAME,
                control_plane_ips="10.0.0.11,10.0.0.12",  # Only 2 CPs
                apply=True,
            )

            assert result["status"] == "error"
            assert result["phase"] == "gather"
            assert "At least 3" in result["error"]

    @pytest.mark.asyncio
    async def test_parses_comma_separated_ips(self) -> None:
        """Comma-separated IP strings are parsed correctly."""
        from talos.tools.setup import talos__cluster__setup

        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            patch(
                "talos.tools.setup.execute_setup_plan",
                new_callable=AsyncMock,
                return_value=SetupResult(
                    status="success",
                    completed_steps=[],
                    cluster_summary={"cluster_name": CLUSTER_NAME},
                ),
            ) as mock_execute,
            patch(
                "talos.tools.setup.build_setup_plan",
                return_value=[],
            ),
        ):
            result = await talos__cluster__setup(
                cluster_name=CLUSTER_NAME,
                control_plane_ips="10.0.0.11, 10.0.0.12, 10.0.0.13",
                worker_ips="10.0.0.21, 10.0.0.22",
                apply=True,
            )

            assert result["status"] == "success"
