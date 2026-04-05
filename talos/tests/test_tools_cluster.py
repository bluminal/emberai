"""Tests for Talos cluster lifecycle MCP tools.

Covers all 7 tools in ``talos.tools.cluster``:
- apply_config: insecure first-time, normal apply, dry-run, write gate blocked
- bootstrap: etcd already exists (blocked), etcd empty (proceeds), write gate
- kubeconfig: to stdout, to file
- health: all healthy, degraded
- set_endpoints: success, VIP warning
- merge_talosconfig: success
- get_version: success
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from talos.api.talosctl_client import TalosCtlClient, TalosCtlResult
from talos.errors import TalosCtlError, WriteGateError, WriteGateReason


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    parsed: dict[str, Any] | list[Any] | None = None,
) -> TalosCtlResult:
    """Create a TalosCtlResult for mocking."""
    return TalosCtlResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        parsed=parsed,
    )


# ---------------------------------------------------------------------------
# apply_config
# ---------------------------------------------------------------------------


class TestApplyConfig:
    """Tests for talos__cluster__apply_config."""

    @pytest.mark.asyncio
    async def test_apply_config_success(self) -> None:
        """Normal apply with validation passing first."""
        from talos.tools.cluster import talos__cluster__apply_config

        validate_result = _make_result(stdout="config is valid")
        apply_result = _make_result(stdout="Applied configuration")

        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            patch.object(
                TalosCtlClient,
                "run",
                new_callable=AsyncMock,
                side_effect=[validate_result, apply_result],
            ),
            patch.object(TalosCtlClient, "flush_cache", new_callable=AsyncMock),
        ):
            result = await talos__cluster__apply_config(
                "192.168.30.10", "/tmp/controlplane.yaml", apply=True
            )

            assert result["status"] == "ok"
            assert result["operation"] == "apply_config"
            assert result["node"] == "192.168.30.10"
            assert result["insecure"] is False

    @pytest.mark.asyncio
    async def test_apply_config_insecure(self) -> None:
        """First-time apply with insecure mode."""
        from talos.tools.cluster import talos__cluster__apply_config

        validate_result = _make_result(stdout="config is valid")
        apply_result = _make_result(stdout="Applied configuration (insecure)")

        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            patch.object(
                TalosCtlClient,
                "run",
                new_callable=AsyncMock,
                return_value=validate_result,
            ),
            patch.object(
                TalosCtlClient,
                "run_insecure",
                new_callable=AsyncMock,
                return_value=apply_result,
            ),
            patch.object(TalosCtlClient, "flush_cache", new_callable=AsyncMock),
        ):
            result = await talos__cluster__apply_config(
                "192.168.30.10",
                "/tmp/controlplane.yaml",
                insecure=True,
                apply=True,
            )

            assert result["status"] == "ok"
            assert result["insecure"] is True

    @pytest.mark.asyncio
    async def test_apply_config_dry_run(self) -> None:
        """Dry run validates config but does not apply."""
        from talos.tools.cluster import talos__cluster__apply_config

        validate_result = _make_result(stdout="config is valid")

        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            patch.object(
                TalosCtlClient,
                "run",
                new_callable=AsyncMock,
                return_value=validate_result,
            ),
        ):
            result = await talos__cluster__apply_config(
                "192.168.30.10",
                "/tmp/controlplane.yaml",
                dry_run=True,
                apply=True,
            )

            assert result["status"] == "ok"
            assert result["operation"] == "dry_run"
            assert "Dry run" in result["message"]

    @pytest.mark.asyncio
    async def test_apply_config_validation_fails(self) -> None:
        """Config validation failure returns error without applying."""
        from talos.tools.cluster import talos__cluster__apply_config

        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            patch.object(
                TalosCtlClient,
                "run",
                new_callable=AsyncMock,
                side_effect=TalosCtlError(
                    "config is invalid",
                    stderr="1 error occurred: unknown field",
                    exit_code=1,
                ),
            ),
        ):
            result = await talos__cluster__apply_config(
                "192.168.30.10",
                "/tmp/bad.yaml",
                apply=True,
            )

            assert result["status"] == "error"
            assert result["operation"] == "validate"
            assert "validation failed" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_apply_config_write_gate_blocked(self) -> None:
        """Write gate blocks when TALOS_WRITE_ENABLED is not set."""
        from talos.tools.cluster import talos__cluster__apply_config

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await talos__cluster__apply_config(
                    "192.168.30.10",
                    "/tmp/controlplane.yaml",
                    apply=True,
                )
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_apply_config_apply_flag_missing(self) -> None:
        """Write gate blocks when apply=False."""
        from talos.tools.cluster import talos__cluster__apply_config

        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await talos__cluster__apply_config(
                    "192.168.30.10",
                    "/tmp/controlplane.yaml",
                    apply=False,
                )
            assert exc_info.value.reason == WriteGateReason.APPLY_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_apply_config_invalid_mode(self) -> None:
        """Invalid mode returns error."""
        from talos.tools.cluster import talos__cluster__apply_config

        validate_result = _make_result(stdout="config is valid")

        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            patch.object(
                TalosCtlClient,
                "run",
                new_callable=AsyncMock,
                return_value=validate_result,
            ),
        ):
            result = await talos__cluster__apply_config(
                "192.168.30.10",
                "/tmp/controlplane.yaml",
                mode="bogus",
                apply=True,
            )

            assert result["status"] == "error"
            assert "Invalid mode" in result["error"]


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


class TestBootstrap:
    """Tests for talos__cluster__bootstrap."""

    @pytest.mark.asyncio
    async def test_bootstrap_success(self) -> None:
        """Bootstrap succeeds when etcd_members_count=0."""
        from talos.tools.cluster import talos__cluster__bootstrap

        bootstrap_result = _make_result(stdout="bootstrap initiated")

        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            patch.object(
                TalosCtlClient,
                "run",
                new_callable=AsyncMock,
                return_value=bootstrap_result,
            ),
            patch.object(TalosCtlClient, "flush_cache", new_callable=AsyncMock),
        ):
            result = await talos__cluster__bootstrap(
                "192.168.30.10", etcd_members_count=0, apply=True
            )

            assert result["status"] == "ok"
            assert result["operation"] == "bootstrap"
            assert "ONE-TIME" in result["warning"]

    @pytest.mark.asyncio
    async def test_bootstrap_blocked_etcd_exists(self) -> None:
        """Bootstrap blocked when etcd already has members."""
        from talos.tools.cluster import talos__cluster__bootstrap

        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await talos__cluster__bootstrap(
                    "192.168.30.10", etcd_members_count=3, apply=True
                )
            assert exc_info.value.reason == WriteGateReason.BOOTSTRAP_BLOCKED

    @pytest.mark.asyncio
    async def test_bootstrap_blocked_single_member(self) -> None:
        """Even one etcd member blocks bootstrap."""
        from talos.tools.cluster import talos__cluster__bootstrap

        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await talos__cluster__bootstrap(
                    "192.168.30.10", etcd_members_count=1, apply=True
                )
            assert exc_info.value.reason == WriteGateReason.BOOTSTRAP_BLOCKED

    @pytest.mark.asyncio
    async def test_bootstrap_write_gate_blocked(self) -> None:
        """Write gate blocks when disabled."""
        from talos.tools.cluster import talos__cluster__bootstrap

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await talos__cluster__bootstrap(
                    "192.168.30.10", etcd_members_count=0, apply=True
                )
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_bootstrap_error_from_talosctl(self) -> None:
        """talosctl error returns structured error response."""
        from talos.tools.cluster import talos__cluster__bootstrap

        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            patch.object(
                TalosCtlClient,
                "run",
                new_callable=AsyncMock,
                side_effect=TalosCtlError(
                    "bootstrap failed: etcd is already running",
                    stderr="etcd is already running",
                    exit_code=1,
                ),
            ),
        ):
            result = await talos__cluster__bootstrap(
                "192.168.30.10", etcd_members_count=0, apply=True
            )

            assert result["status"] == "error"
            assert "bootstrap failed" in result["error"]


# ---------------------------------------------------------------------------
# kubeconfig
# ---------------------------------------------------------------------------


class TestKubeconfig:
    """Tests for talos__cluster__kubeconfig."""

    @pytest.mark.asyncio
    async def test_kubeconfig_to_stdout(self) -> None:
        """Kubeconfig returned directly when no output_path."""
        from talos.tools.cluster import talos__cluster__kubeconfig

        kubeconfig_content = "apiVersion: v1\nkind: Config\nclusters: []"
        kube_result = _make_result(stdout=kubeconfig_content)

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            return_value=kube_result,
        ):
            result = await talos__cluster__kubeconfig(node="192.168.30.10")

            assert result["status"] == "ok"
            assert result["kubeconfig"] == kubeconfig_content

    @pytest.mark.asyncio
    async def test_kubeconfig_to_file(self) -> None:
        """Kubeconfig written to file when output_path provided."""
        from talos.tools.cluster import talos__cluster__kubeconfig

        kube_result = _make_result(stdout="")

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            return_value=kube_result,
        ):
            result = await talos__cluster__kubeconfig(
                node="192.168.30.10",
                output_path="/tmp/kubeconfig",
            )

            assert result["status"] == "ok"
            assert result["output_path"] == "/tmp/kubeconfig"
            assert "written" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_kubeconfig_error(self) -> None:
        """Error from talosctl returned gracefully."""
        from talos.tools.cluster import talos__cluster__kubeconfig

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            side_effect=TalosCtlError(
                "failed to get kubeconfig",
                stderr="connection refused",
                exit_code=1,
            ),
        ):
            result = await talos__cluster__kubeconfig(node="192.168.30.10")

            assert result["status"] == "error"
            assert "kubeconfig" in result["error"]

    @pytest.mark.asyncio
    async def test_kubeconfig_default_node(self) -> None:
        """Empty node uses default (no --nodes flag)."""
        from talos.tools.cluster import talos__cluster__kubeconfig

        kube_result = _make_result(stdout="kubeconfig-content")

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            return_value=kube_result,
        ) as mock_run:
            await talos__cluster__kubeconfig()

            call_kwargs = mock_run.call_args
            assert call_kwargs.kwargs.get("nodes") is None


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


class TestHealth:
    """Tests for talos__cluster__health."""

    @pytest.mark.asyncio
    async def test_health_all_ok(self, health_output: dict[str, Any]) -> None:
        """All nodes healthy returns severity OK."""
        from talos.tools.cluster import talos__cluster__health

        health_result = _make_result(
            stdout=json.dumps(health_output),
            parsed=health_output,
        )

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            return_value=health_result,
        ):
            result = await talos__cluster__health(node="192.168.30.10")

            assert result["status"] == "ok"
            assert result["severity"] == "OK"
            assert result["cluster"]["nodes_healthy"] == 3
            assert result["cluster"]["nodes_total"] == 3

    @pytest.mark.asyncio
    async def test_health_degraded(
        self, health_degraded_output: dict[str, Any]
    ) -> None:
        """One unhealthy node returns severity WARNING."""
        from talos.tools.cluster import talos__cluster__health

        health_result = _make_result(
            stdout=json.dumps(health_degraded_output),
            parsed=health_degraded_output,
        )

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            return_value=health_result,
        ):
            result = await talos__cluster__health(node="192.168.30.10")

            assert result["status"] == "ok"
            assert result["severity"] == "WARNING"
            assert result["cluster"]["nodes_healthy"] == 2
            assert result["cluster"]["nodes_total"] == 3
            # Check that the unhealthy node has error info
            unhealthy = [n for n in result["nodes"] if not n["ready"]]
            assert len(unhealthy) == 1
            assert "error" in unhealthy[0]

    @pytest.mark.asyncio
    async def test_health_critical_on_failure(self) -> None:
        """talosctl health failure returns CRITICAL severity."""
        from talos.tools.cluster import talos__cluster__health

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            side_effect=TalosCtlError(
                "health check failed: etcd unhealthy",
                stderr="etcd cluster is unavailable",
                exit_code=1,
            ),
        ):
            result = await talos__cluster__health(node="192.168.30.10")

            assert result["status"] == "error"
            assert result["severity"] == "CRITICAL"

    @pytest.mark.asyncio
    async def test_health_with_wait_timeout(self) -> None:
        """Wait timeout is passed to talosctl."""
        from talos.tools.cluster import talos__cluster__health

        health_result = _make_result(stdout="ok", parsed=None)

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            return_value=health_result,
        ) as mock_run:
            await talos__cluster__health(wait_timeout="5m")

            call_args = mock_run.call_args[0][0]
            assert "--wait-timeout" in call_args
            assert "5m" in call_args


# ---------------------------------------------------------------------------
# get_version
# ---------------------------------------------------------------------------


class TestGetVersion:
    """Tests for talos__cluster__get_version."""

    @pytest.mark.asyncio
    async def test_get_version_success(
        self, version_output: dict[str, Any]
    ) -> None:
        """Version info returned from both client and server."""
        from talos.tools.cluster import talos__cluster__get_version

        version_result = _make_result(
            stdout=json.dumps(version_output),
            parsed=version_output,
        )

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            return_value=version_result,
        ):
            result = await talos__cluster__get_version(node="192.168.30.10")

            assert result["status"] == "ok"
            assert result["client_version"]["tag"] == "v1.12.0"
            assert len(result["server_versions"]) == 1
            assert result["server_versions"][0]["hostname"] == "talos-cp-1"

    @pytest.mark.asyncio
    async def test_get_version_error(self) -> None:
        """Error from talosctl returned gracefully."""
        from talos.tools.cluster import talos__cluster__get_version

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            side_effect=TalosCtlError(
                "connection refused",
                stderr="connection refused",
                exit_code=1,
            ),
        ):
            result = await talos__cluster__get_version(node="192.168.30.10")

            assert result["status"] == "error"
            assert "connection refused" in result["error"]


# ---------------------------------------------------------------------------
# set_endpoints
# ---------------------------------------------------------------------------


class TestSetEndpoints:
    """Tests for talos__cluster__set_endpoints."""

    @pytest.mark.asyncio
    async def test_set_endpoints_success(self) -> None:
        """Endpoints set successfully."""
        from talos.tools.cluster import talos__cluster__set_endpoints

        ep_result = _make_result(stdout="")

        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            patch.object(
                TalosCtlClient,
                "run",
                new_callable=AsyncMock,
                return_value=ep_result,
            ),
        ):
            result = await talos__cluster__set_endpoints(
                "192.168.30.10 192.168.30.11 192.168.30.12",
                apply=True,
            )

            assert result["status"] == "ok"
            assert len(result["endpoints"]) == 3

    @pytest.mark.asyncio
    async def test_set_endpoints_vip_warning(self) -> None:
        """VIP in endpoint list triggers warning."""
        from talos.tools.cluster import talos__cluster__set_endpoints

        ep_result = _make_result(stdout="")

        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            patch.object(
                TalosCtlClient,
                "run",
                new_callable=AsyncMock,
                return_value=ep_result,
            ),
        ):
            result = await talos__cluster__set_endpoints(
                "192.168.30.10 vip.cluster.local",
                apply=True,
            )

            assert result["status"] == "ok"
            assert "warning" in result
            assert "VIP" in result["warning"]

    @pytest.mark.asyncio
    async def test_set_endpoints_empty(self) -> None:
        """Empty endpoints string returns error."""
        from talos.tools.cluster import talos__cluster__set_endpoints

        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            result = await talos__cluster__set_endpoints("", apply=True)

            assert result["status"] == "error"
            assert "No endpoints" in result["error"]

    @pytest.mark.asyncio
    async def test_set_endpoints_write_gate_blocked(self) -> None:
        """Write gate blocks when disabled."""
        from talos.tools.cluster import talos__cluster__set_endpoints

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await talos__cluster__set_endpoints(
                    "192.168.30.10",
                    apply=True,
                )
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED


# ---------------------------------------------------------------------------
# merge_talosconfig
# ---------------------------------------------------------------------------


class TestMergeTalosconfig:
    """Tests for talos__cluster__merge_talosconfig."""

    @pytest.mark.asyncio
    async def test_merge_success(self) -> None:
        """Talosconfig merged successfully."""
        from talos.tools.cluster import talos__cluster__merge_talosconfig

        merge_result = _make_result(stdout="")

        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            patch.object(
                TalosCtlClient,
                "run",
                new_callable=AsyncMock,
                return_value=merge_result,
            ),
        ):
            result = await talos__cluster__merge_talosconfig(
                "/tmp/new-talosconfig",
                apply=True,
            )

            assert result["status"] == "ok"
            assert result["operation"] == "merge_talosconfig"
            assert result["talosconfig_path"] == "/tmp/new-talosconfig"

    @pytest.mark.asyncio
    async def test_merge_empty_path(self) -> None:
        """Empty path returns error."""
        from talos.tools.cluster import talos__cluster__merge_talosconfig

        with patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}):
            result = await talos__cluster__merge_talosconfig("", apply=True)

            assert result["status"] == "error"
            assert "No talosconfig path" in result["error"]

    @pytest.mark.asyncio
    async def test_merge_talosctl_error(self) -> None:
        """Error from talosctl returned gracefully."""
        from talos.tools.cluster import talos__cluster__merge_talosconfig

        with (
            patch.dict(os.environ, {"TALOS_WRITE_ENABLED": "true"}),
            patch.object(
                TalosCtlClient,
                "run",
                new_callable=AsyncMock,
                side_effect=TalosCtlError(
                    "file not found: /tmp/missing",
                    stderr="no such file",
                    exit_code=1,
                ),
            ),
        ):
            result = await talos__cluster__merge_talosconfig(
                "/tmp/missing",
                apply=True,
            )

            assert result["status"] == "error"
            assert "file not found" in result["error"]

    @pytest.mark.asyncio
    async def test_merge_write_gate_blocked(self) -> None:
        """Write gate blocks when disabled."""
        from talos.tools.cluster import talos__cluster__merge_talosconfig

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await talos__cluster__merge_talosconfig(
                    "/tmp/talosconfig",
                    apply=True,
                )
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED
