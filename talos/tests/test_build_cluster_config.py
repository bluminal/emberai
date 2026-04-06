"""Tests for the ``build_cluster_config`` orchestration helper.

Covers:
    - Full success path (secrets + config + VIP + validation)
    - Success without VIP
    - Success with KubeSpan enabled
    - Success with additional custom patches
    - Validation failure at step 6 (after all patches applied)
    - gen_secrets failure at step 1
    - gen_config failure at step 2
    - Patch failure during VIP application
    - Pre-existing secrets file (skips gen_secrets)
    - Output directory propagation
    - Worker-only validation skipped when no workers
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from talos.agents.cluster_setup import build_cluster_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CP_IPS = ["10.0.0.11", "10.0.0.12", "10.0.0.13"]
WORKER_IPS = ["10.0.0.21", "10.0.0.22"]
VIP = "10.0.0.10"
CLUSTER_NAME = "test-cluster"
ENDPOINT = "https://10.0.0.10:6443"


def _success(**extra: Any) -> dict[str, Any]:
    """Build a successful tool result."""
    result: dict[str, Any] = {"status": "success"}
    result.update(extra)
    return result


def _pass_result(**extra: Any) -> dict[str, Any]:
    """Build a passing validation result."""
    result: dict[str, Any] = {"status": "pass", "message": "Configuration is valid."}
    result.update(extra)
    return result


def _error(msg: str = "something failed", **extra: Any) -> dict[str, Any]:
    """Build a failed tool result."""
    result: dict[str, Any] = {"status": "error", "error": msg}
    result.update(extra)
    return result


def _fail_result(errors: str = "validation error", **extra: Any) -> dict[str, Any]:
    """Build a failed validation result."""
    result: dict[str, Any] = {"status": "fail", "errors": errors}
    result.update(extra)
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildClusterConfig:
    """Tests for the build_cluster_config orchestration helper."""

    @pytest.mark.asyncio
    async def test_full_success_with_vip(self) -> None:
        """Full success path: gen_secrets, gen_config, VIP patch, validate."""
        mock_gen_secrets = AsyncMock(return_value=_success(output_path="secrets.yaml"))
        mock_gen_config = AsyncMock(return_value=_success(
            generated_files=["controlplane.yaml", "worker.yaml", "talosconfig"],
        ))
        mock_patch = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
                vip=VIP,
            )

        assert result["status"] == "success"
        assert result["cluster_name"] == CLUSTER_NAME
        assert result["endpoint"] == ENDPOINT
        assert result["control_plane_ips"] == CP_IPS
        assert result["worker_ips"] == WORKER_IPS
        assert result["vip"] == VIP
        assert result["secrets_file"] == "secrets.yaml"
        assert result["controlplane_config"] == "controlplane.yaml"
        assert result["worker_config"] == "worker.yaml"
        assert result["talosconfig"] == "talosconfig"
        assert f"VIP {VIP}" in result["patches_applied"]

        # gen_secrets was called (no secrets_file provided)
        mock_gen_secrets.assert_awaited_once()
        # gen_config was called
        mock_gen_config.assert_awaited_once()
        # VIP patch was applied to controlplane config
        assert mock_patch.await_count == 1
        patch_call = mock_patch.call_args
        assert VIP in patch_call.args[1]  # patches string
        assert patch_call.args[0] == "controlplane.yaml"  # config_file
        # Both configs validated (CP + worker)
        assert mock_validate.await_count == 2

    @pytest.mark.asyncio
    async def test_success_without_vip(self) -> None:
        """Success path without VIP -- no VIP patch step."""
        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_patch = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
            )

        assert result["status"] == "success"
        assert result["vip"] is None
        # No patches should have been applied
        mock_patch.assert_not_awaited()
        assert result["patches_applied"] == []

    @pytest.mark.asyncio
    async def test_success_with_kubespan(self) -> None:
        """KubeSpan enabled applies patch to both CP and worker configs."""
        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_patch = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
                enable_kubespan=True,
            )

        assert result["status"] == "success"
        assert "KubeSpan enabled" in result["patches_applied"]

        # KubeSpan patch applied to both configs
        assert mock_patch.await_count == 2
        patch_calls = mock_patch.call_args_list
        config_files_patched = [c.args[0] for c in patch_calls]
        assert "controlplane.yaml" in config_files_patched
        assert "worker.yaml" in config_files_patched
        # Verify kubespan patch content
        for call in patch_calls:
            assert "kubespan" in call.args[1]
            assert '"enabled": true' in call.args[1]

    @pytest.mark.asyncio
    async def test_success_with_additional_patches(self) -> None:
        """Additional patches are applied to both CP and worker configs."""
        custom_patch_1 = '[{"op": "add", "path": "/machine/network/hostname", "value": "node1"}]'
        custom_patch_2 = '[{"op": "add", "path": "/machine/time/servers", "value": ["ntp.local"]}]'

        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_patch = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
                patches=[custom_patch_1, custom_patch_2],
            )

        assert result["status"] == "success"
        assert "custom patch 1" in result["patches_applied"]
        assert "custom patch 2" in result["patches_applied"]

        # 2 patches x 2 configs = 4 calls
        assert mock_patch.await_count == 4

    @pytest.mark.asyncio
    async def test_validation_failure_controlplane(self) -> None:
        """Validation failure at step 6 for controlplane config."""
        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_patch = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(
            return_value=_fail_result("machine.install.disk is required"),
        )

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
                vip=VIP,
            )

        assert result["status"] == "error"
        assert result["phase"] == "validate_controlplane"
        assert "machine.install.disk is required" in result["error"]

    @pytest.mark.asyncio
    async def test_validation_failure_worker(self) -> None:
        """Validation failure at step 6 for worker config (CP passes)."""
        call_count = 0

        async def validate_side_effect(
            config_file: str, *, mode: str = "metal"
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # CP passes
                return _pass_result()
            # Worker fails
            return _fail_result("worker config invalid")

        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_patch = AsyncMock(return_value=_success())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                validate_side_effect,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
            )

        assert result["status"] == "error"
        assert result["phase"] == "validate_worker"
        assert "worker config invalid" in result["error"]

    @pytest.mark.asyncio
    async def test_gen_secrets_failure(self) -> None:
        """gen_secrets failure at step 1 stops execution immediately."""
        mock_gen_secrets = AsyncMock(
            return_value=_error("disk full"),
        )
        mock_gen_config = AsyncMock(return_value=_success())
        mock_patch = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
            )

        assert result["status"] == "error"
        assert result["phase"] == "gen_secrets"
        assert "disk full" in result["error"]

        # Subsequent steps should NOT have been called
        mock_gen_config.assert_not_awaited()
        mock_patch.assert_not_awaited()
        mock_validate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_gen_config_failure(self) -> None:
        """gen_config failure at step 2 stops execution."""
        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_error("bad endpoint"))
        mock_patch = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
            )

        assert result["status"] == "error"
        assert result["phase"] == "gen_config"
        assert "bad endpoint" in result["error"]
        mock_patch.assert_not_awaited()
        mock_validate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_vip_patch_failure(self) -> None:
        """VIP patch failure at step 3 stops execution."""
        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_patch = AsyncMock(return_value=_error("patch syntax error"))
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
                vip=VIP,
            )

        assert result["status"] == "error"
        assert result["phase"] == "patch_vip"
        assert "patch syntax error" in result["error"]
        mock_validate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_existing_secrets_file_skips_gen_secrets(self) -> None:
        """When secrets_file is provided, gen_secrets is skipped."""
        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_patch = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
                secrets_file="/existing/secrets.yaml",
            )

        assert result["status"] == "success"
        assert result["secrets_file"] == "/existing/secrets.yaml"
        # gen_secrets was NOT called
        mock_gen_secrets.assert_not_awaited()
        # gen_config uses the provided secrets file
        gen_config_kwargs = mock_gen_config.call_args[1]
        assert gen_config_kwargs["secrets_file"] == "/existing/secrets.yaml"

    @pytest.mark.asyncio
    async def test_output_dir_propagation(self) -> None:
        """Custom output_dir is reflected in all file paths."""
        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_patch = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
                output_dir="/tmp/talos-setup",
            )

        assert result["status"] == "success"
        assert result["secrets_file"] == "/tmp/talos-setup/secrets.yaml"
        assert result["controlplane_config"] == "/tmp/talos-setup/controlplane.yaml"
        assert result["worker_config"] == "/tmp/talos-setup/worker.yaml"
        assert result["talosconfig"] == "/tmp/talos-setup/talosconfig"

    @pytest.mark.asyncio
    async def test_no_worker_validation_without_workers(self) -> None:
        """When worker_ips is empty, only controlplane is validated."""
        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_patch = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=[],
            )

        assert result["status"] == "success"
        # Only 1 validate call (controlplane), not 2
        assert mock_validate.await_count == 1
        validate_call = mock_validate.call_args
        assert validate_call.args[0] == "controlplane.yaml"

    @pytest.mark.asyncio
    async def test_kubernetes_version_passed_to_gen_config(self) -> None:
        """Kubernetes version is forwarded to gen_config."""
        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                AsyncMock(return_value=_success()),
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
                kubernetes_version="1.31.0",
            )

        assert result["status"] == "success"
        gen_config_kwargs = mock_gen_config.call_args[1]
        assert gen_config_kwargs["kubernetes_version"] == "1.31.0"

    @pytest.mark.asyncio
    async def test_vip_and_kubespan_and_patches_combined(self) -> None:
        """VIP, KubeSpan, and custom patches can all be applied together."""
        custom_patch = '[{"op": "add", "path": "/machine/time", "value": {"servers": ["ntp"]}}]'

        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_patch = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                mock_patch,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
                vip=VIP,
                enable_kubespan=True,
                patches=[custom_patch],
            )

        assert result["status"] == "success"
        assert f"VIP {VIP}" in result["patches_applied"]
        assert "KubeSpan enabled" in result["patches_applied"]
        assert "custom patch 1" in result["patches_applied"]

        # VIP patch: 1 call (CP only)
        # KubeSpan patch: 2 calls (CP + worker)
        # Custom patch: 2 calls (CP + worker)
        # Total: 5 calls
        assert mock_patch.await_count == 5

    @pytest.mark.asyncio
    async def test_kubespan_patch_failure_stops_execution(self) -> None:
        """KubeSpan patch failure on worker config stops execution."""
        call_count = 0

        async def patch_side_effect(
            config_file: str,
            patches: str,
            *,
            output_file: str = "",
            apply: bool = False,
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            # First call (CP KubeSpan) succeeds, second (worker) fails
            if call_count <= 1:
                return _success()
            return _error("worker patch failed")

        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                patch_side_effect,
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=WORKER_IPS,
                enable_kubespan=True,
            )

        assert result["status"] == "error"
        assert result["phase"] == "patch_kubespan_worker"
        assert "worker patch failed" in result["error"]
        mock_validate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_install_disk_forwarded(self) -> None:
        """Custom install_disk is forwarded to gen_config."""
        mock_gen_secrets = AsyncMock(return_value=_success())
        mock_gen_config = AsyncMock(return_value=_success())
        mock_validate = AsyncMock(return_value=_pass_result())

        with (
            patch(
                "talos.tools.config.talos__config__gen_secrets",
                mock_gen_secrets,
            ),
            patch(
                "talos.tools.config.talos__config__gen_config",
                mock_gen_config,
            ),
            patch(
                "talos.tools.config.talos__config__patch_machineconfig",
                AsyncMock(return_value=_success()),
            ),
            patch(
                "talos.tools.config.talos__config__validate",
                mock_validate,
            ),
        ):
            result = await build_cluster_config(
                cluster_name=CLUSTER_NAME,
                endpoint=ENDPOINT,
                control_plane_ips=CP_IPS,
                worker_ips=[],
                install_disk="/dev/nvme0n1",
            )

        assert result["status"] == "success"
        gen_config_kwargs = mock_gen_config.call_args[1]
        assert gen_config_kwargs["install_disk"] == "/dev/nvme0n1"
