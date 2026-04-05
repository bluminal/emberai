"""Tests for the Talos config MCP tools.

Covers all five tools in ``talos.tools.config``:
- ``talos__config__gen_secrets``
- ``talos__config__gen_config``
- ``talos__config__validate``
- ``talos__config__patch_machineconfig``
- ``talos__config__get_machineconfig``

Each tool has success and error path tests.  Write-gated tools also
test that the gate blocks when TALOS_WRITE_ENABLED is unset or
apply=False.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from talos.api.talosctl_client import TalosCtlClient, TalosCtlResult
from talos.errors import TalosCtlError, WriteGateError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    parsed: dict[str, Any] | list[Any] | None = None,
) -> TalosCtlResult:
    """Build a TalosCtlResult for test assertions."""
    return TalosCtlResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        parsed=parsed,
    )


def _make_talosctl_error(
    message: str = "command failed",
    stderr: str = "error details",
    exit_code: int = 1,
) -> TalosCtlError:
    """Build a TalosCtlError for test assertions."""
    return TalosCtlError(
        message,
        stderr=stderr,
        exit_code=exit_code,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable TALOS_WRITE_ENABLED for all tests by default.

    Individual tests that need it disabled will override this.
    """
    monkeypatch.setenv("TALOS_WRITE_ENABLED", "true")


@pytest.fixture(autouse=True)
def _reset_module_client() -> None:
    """Reset the module-level client singleton between tests."""
    import talos.tools.config as cfg

    cfg._client = None


# ---------------------------------------------------------------------------
# talos__config__gen_secrets
# ---------------------------------------------------------------------------


class TestGenSecrets:
    """Tests for talos__config__gen_secrets."""

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        from talos.tools.config import talos__config__gen_secrets

        mock_run = AsyncMock(
            return_value=_make_result(stdout="generating secrets\n")
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__gen_secrets(
                "/tmp/secrets.yaml", apply=True,
            )

        assert result["status"] == "success"
        assert result["output_path"] == "/tmp/secrets.yaml"
        assert "SECURITY" in result["warning"]

        # Verify correct talosctl args
        mock_run.assert_awaited_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["gen", "secrets", "-o", "/tmp/secrets.yaml"]
        assert call_args[1]["json_output"] is False

    @pytest.mark.asyncio
    async def test_talosctl_error(self) -> None:
        from talos.tools.config import talos__config__gen_secrets

        mock_run = AsyncMock(
            side_effect=_make_talosctl_error("gen secrets failed", "disk full")
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__gen_secrets(
                "/tmp/secrets.yaml", apply=True,
            )

        assert result["status"] == "error"
        assert "gen secrets failed" in result["error"]
        assert result["stderr"] == "disk full"

    @pytest.mark.asyncio
    async def test_write_gate_env_disabled(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from talos.tools.config import talos__config__gen_secrets

        monkeypatch.setenv("TALOS_WRITE_ENABLED", "false")
        with pytest.raises(WriteGateError, match="disabled"):
            await talos__config__gen_secrets(
                "/tmp/secrets.yaml", apply=True,
            )

    @pytest.mark.asyncio
    async def test_write_gate_apply_false(self) -> None:
        from talos.tools.config import talos__config__gen_secrets

        with pytest.raises(WriteGateError, match="--apply"):
            await talos__config__gen_secrets(
                "/tmp/secrets.yaml", apply=False,
            )


# ---------------------------------------------------------------------------
# talos__config__gen_config
# ---------------------------------------------------------------------------


class TestGenConfig:
    """Tests for talos__config__gen_config."""

    @pytest.mark.asyncio
    async def test_success_minimal(self) -> None:
        from talos.tools.config import talos__config__gen_config

        mock_run = AsyncMock(
            return_value=_make_result(stdout="generating config\n")
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__gen_config(
                "homelab", "https://10.0.0.1:6443", apply=True,
            )

        assert result["status"] == "success"
        assert result["cluster_name"] == "homelab"
        assert result["endpoint"] == "https://10.0.0.1:6443"
        assert "controlplane.yaml" in result["generated_files"]

        call_args = mock_run.call_args[0][0]
        assert call_args[:4] == ["gen", "config", "homelab", "https://10.0.0.1:6443"]
        # Default install-disk should be present
        assert "--install-disk" in call_args
        assert "/dev/sda" in call_args

    @pytest.mark.asyncio
    async def test_success_all_flags(self) -> None:
        from talos.tools.config import talos__config__gen_config

        mock_run = AsyncMock(
            return_value=_make_result(stdout="done\n")
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__gen_config(
                "prod",
                "https://k8s.example.com:6443",
                secrets_file="/tmp/secrets.yaml",
                install_disk="/dev/nvme0n1",
                kubernetes_version="1.31.0",
                talos_version="v1.12.0",
                output_dir="/tmp/configs",
                apply=True,
            )

        assert result["status"] == "success"
        assert result["output_dir"] == "/tmp/configs"

        call_args = mock_run.call_args[0][0]
        assert "--with-secrets" in call_args
        assert "/tmp/secrets.yaml" in call_args
        assert "--install-disk" in call_args
        assert "/dev/nvme0n1" in call_args
        assert "--kubernetes-version" in call_args
        assert "1.31.0" in call_args
        assert "--talos-version" in call_args
        assert "v1.12.0" in call_args
        assert "--output-dir" in call_args
        assert "/tmp/configs" in call_args

    @pytest.mark.asyncio
    async def test_talosctl_error(self) -> None:
        from talos.tools.config import talos__config__gen_config

        mock_run = AsyncMock(
            side_effect=_make_talosctl_error("bad endpoint", "invalid URL")
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__gen_config(
                "homelab", "not-a-url", apply=True,
            )

        assert result["status"] == "error"
        assert "bad endpoint" in result["error"]

    @pytest.mark.asyncio
    async def test_write_gate_env_disabled(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from talos.tools.config import talos__config__gen_config

        monkeypatch.setenv("TALOS_WRITE_ENABLED", "false")
        with pytest.raises(WriteGateError, match="disabled"):
            await talos__config__gen_config(
                "homelab", "https://10.0.0.1:6443", apply=True,
            )

    @pytest.mark.asyncio
    async def test_write_gate_apply_false(self) -> None:
        from talos.tools.config import talos__config__gen_config

        with pytest.raises(WriteGateError, match="--apply"):
            await talos__config__gen_config(
                "homelab", "https://10.0.0.1:6443", apply=False,
            )


# ---------------------------------------------------------------------------
# talos__config__validate
# ---------------------------------------------------------------------------


class TestValidate:
    """Tests for talos__config__validate."""

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        from talos.tools.config import talos__config__validate

        mock_run = AsyncMock(
            return_value=_make_result(stdout="controlplane.yaml is valid\n")
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__validate("/tmp/controlplane.yaml")

        assert result["status"] == "pass"
        assert result["config_file"] == "/tmp/controlplane.yaml"
        assert result["mode"] == "metal"

        call_args = mock_run.call_args[0][0]
        assert "validate" in call_args
        assert "--strict" in call_args
        assert "--mode" in call_args
        assert "metal" in call_args

    @pytest.mark.asyncio
    async def test_success_cloud_mode(self) -> None:
        from talos.tools.config import talos__config__validate

        mock_run = AsyncMock(
            return_value=_make_result(stdout="valid\n")
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__validate(
                "/tmp/worker.yaml", mode="cloud",
            )

        assert result["status"] == "pass"
        assert result["mode"] == "cloud"

        call_args = mock_run.call_args[0][0]
        assert "cloud" in call_args

    @pytest.mark.asyncio
    async def test_validation_failure(self) -> None:
        from talos.tools.config import talos__config__validate

        mock_run = AsyncMock(
            side_effect=_make_talosctl_error(
                "validation failed",
                "1 error occurred:\n\t* machine.install.disk is required",
                exit_code=1,
            )
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__validate("/tmp/bad.yaml")

        assert result["status"] == "fail"
        assert "machine.install.disk is required" in result["errors"]
        assert result["exit_code"] == 1

    @pytest.mark.asyncio
    async def test_no_write_gate_required(self) -> None:
        """Validate is read-only and must not require write gate."""
        from talos.tools.config import talos__config__validate

        # Even with writes disabled, validate should work
        os.environ["TALOS_WRITE_ENABLED"] = "false"
        mock_run = AsyncMock(
            return_value=_make_result(stdout="valid\n")
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__validate("/tmp/controlplane.yaml")
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# talos__config__patch_machineconfig
# ---------------------------------------------------------------------------


class TestPatchMachineconfig:
    """Tests for talos__config__patch_machineconfig."""

    @pytest.mark.asyncio
    async def test_success_inline_patch_with_output(self) -> None:
        from talos.tools.config import talos__config__patch_machineconfig

        mock_run = AsyncMock(
            return_value=_make_result(stdout="")
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__patch_machineconfig(
                "/tmp/controlplane.yaml",
                '[{"op": "replace", "path": "/machine/network/hostname", "value": "node1"}]',
                output_file="/tmp/patched.yaml",
                apply=True,
            )

        assert result["status"] == "success"
        assert result["output_file"] == "/tmp/patched.yaml"
        assert "patched_config" not in result

        call_args = mock_run.call_args[0][0]
        assert call_args[0:3] == ["machineconfig", "patch", "/tmp/controlplane.yaml"]
        assert "--patch" in call_args
        assert "--output" in call_args
        assert "/tmp/patched.yaml" in call_args

    @pytest.mark.asyncio
    async def test_success_inline_patch_stdout(self) -> None:
        from talos.tools.config import talos__config__patch_machineconfig

        mock_run = AsyncMock(
            return_value=_make_result(stdout="machine:\n  network:\n    hostname: node1\n")
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__patch_machineconfig(
                "/tmp/controlplane.yaml",
                '[{"op": "replace", "path": "/machine/network/hostname", "value": "node1"}]',
                apply=True,
            )

        assert result["status"] == "success"
        assert "patched_config" in result
        assert "hostname: node1" in result["patched_config"]
        assert "output_file" not in result

    @pytest.mark.asyncio
    async def test_success_file_patch(self) -> None:
        from talos.tools.config import talos__config__patch_machineconfig

        mock_run = AsyncMock(
            return_value=_make_result(stdout="patched output")
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__patch_machineconfig(
                "/tmp/controlplane.yaml",
                "@/tmp/patch.json",
                apply=True,
            )

        assert result["status"] == "success"
        call_args = mock_run.call_args[0][0]
        assert "@/tmp/patch.json" in call_args

    @pytest.mark.asyncio
    async def test_talosctl_error(self) -> None:
        from talos.tools.config import talos__config__patch_machineconfig

        mock_run = AsyncMock(
            side_effect=_make_talosctl_error("patch failed", "invalid JSON patch")
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__patch_machineconfig(
                "/tmp/controlplane.yaml",
                "bad-json",
                apply=True,
            )

        assert result["status"] == "error"
        assert "patch failed" in result["error"]

    @pytest.mark.asyncio
    async def test_write_gate_env_disabled(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from talos.tools.config import talos__config__patch_machineconfig

        monkeypatch.setenv("TALOS_WRITE_ENABLED", "false")
        with pytest.raises(WriteGateError, match="disabled"):
            await talos__config__patch_machineconfig(
                "/tmp/cp.yaml", "[]", apply=True,
            )

    @pytest.mark.asyncio
    async def test_write_gate_apply_false(self) -> None:
        from talos.tools.config import talos__config__patch_machineconfig

        with pytest.raises(WriteGateError, match="--apply"):
            await talos__config__patch_machineconfig(
                "/tmp/cp.yaml", "[]", apply=False,
            )


# ---------------------------------------------------------------------------
# talos__config__get_machineconfig
# ---------------------------------------------------------------------------


class TestGetMachineconfig:
    """Tests for talos__config__get_machineconfig."""

    @pytest.mark.asyncio
    async def test_success_with_json(self) -> None:
        from talos.tools.config import talos__config__get_machineconfig

        config_data = {
            "machine": {
                "type": "controlplane",
                "token": "super-secret-token",
                "ca": {"crt": "base64cert", "key": "base64key"},
                "network": {"hostname": "node1"},
            },
            "cluster": {
                "secret": "cluster-secret",
                "aescbcEncryptionSecret": "encryption-key",
                "bootstrapToken": "boot-token",
            },
        }

        mock_run = AsyncMock(
            return_value=_make_result(parsed=config_data)
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__get_machineconfig()

        assert result["status"] == "success"
        mc = result["machineconfig"]

        # Secrets should be redacted
        assert mc["machine"]["token"] == "[REDACTED]"
        assert mc["machine"]["ca"]["crt"] == "[REDACTED]"
        assert mc["machine"]["ca"]["key"] == "[REDACTED]"
        assert mc["cluster"]["secret"] == "[REDACTED]"
        assert mc["cluster"]["aescbcEncryptionSecret"] == "[REDACTED]"
        assert mc["cluster"]["bootstrapToken"] == "[REDACTED]"

        # Non-secrets should be preserved
        assert mc["machine"]["type"] == "controlplane"
        assert mc["machine"]["network"]["hostname"] == "node1"

    @pytest.mark.asyncio
    async def test_success_with_node(self) -> None:
        from talos.tools.config import talos__config__get_machineconfig

        mock_run = AsyncMock(
            return_value=_make_result(parsed={"machine": {"type": "worker"}})
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__get_machineconfig(node="192.168.1.10")

        assert result["status"] == "success"
        assert result["node"] == "192.168.1.10"

        # Check node was passed to client
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["nodes"] == "192.168.1.10"

    @pytest.mark.asyncio
    async def test_fallback_to_raw_stdout(self) -> None:
        from talos.tools.config import talos__config__get_machineconfig

        mock_run = AsyncMock(
            return_value=_make_result(
                stdout="machine:\n  type: controlplane\n",
                parsed=None,
            )
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__get_machineconfig()

        assert result["status"] == "success"
        assert "raw_output" in result
        assert "machineconfig" not in result

    @pytest.mark.asyncio
    async def test_talosctl_error(self) -> None:
        from talos.tools.config import talos__config__get_machineconfig

        mock_run = AsyncMock(
            side_effect=_make_talosctl_error(
                "node unreachable", "connection refused", exit_code=1,
            )
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__get_machineconfig(node="10.0.0.99")

        assert result["status"] == "error"
        assert "node unreachable" in result["error"]

    @pytest.mark.asyncio
    async def test_no_write_gate_required(self) -> None:
        """get_machineconfig is read-only and must not require write gate."""
        from talos.tools.config import talos__config__get_machineconfig

        os.environ["TALOS_WRITE_ENABLED"] = "false"
        mock_run = AsyncMock(
            return_value=_make_result(parsed={"machine": {"type": "worker"}})
        )
        with patch.object(TalosCtlClient, "run", mock_run):
            result = await talos__config__get_machineconfig()
        assert result["status"] == "success"


# ---------------------------------------------------------------------------
# Sanitisation helper unit tests
# ---------------------------------------------------------------------------


class TestSanitizeConfig:
    """Direct tests for the _sanitize_config helper."""

    def test_redacts_known_secret_keys(self) -> None:
        from talos.tools.config import _sanitize_config

        data = {
            "token": "abc",
            "key": "def",
            "secret": "ghi",
            "ca": "jkl",
            "crt": "mno",
            "cert": "pqr",
            "bootstraptoken": "stu",
            "aescbcEncryptionSecret": "vwx",
        }
        sanitized = _sanitize_config(data)
        for v in sanitized.values():
            assert v == "[REDACTED]"

    def test_preserves_non_secret_keys(self) -> None:
        from talos.tools.config import _sanitize_config

        data = {
            "hostname": "node1",
            "type": "controlplane",
            "version": "v1.12.0",
        }
        sanitized = _sanitize_config(data)
        assert sanitized == data

    def test_handles_nested_structures(self) -> None:
        from talos.tools.config import _sanitize_config

        data = {
            "machine": {
                "network": {"hostname": "node1"},
                "token": "secret-value",
            },
            "items": [
                {"name": "a", "key": "private"},
                {"name": "b", "value": "public"},
            ],
        }
        sanitized = _sanitize_config(data)
        assert sanitized["machine"]["network"]["hostname"] == "node1"
        assert sanitized["machine"]["token"] == "[REDACTED]"
        assert sanitized["items"][0]["name"] == "a"
        assert sanitized["items"][0]["key"] == "[REDACTED]"
        assert sanitized["items"][1]["value"] == "public"

    def test_handles_empty_and_scalar(self) -> None:
        from talos.tools.config import _sanitize_config

        assert _sanitize_config({}) == {}
        assert _sanitize_config([]) == []
        assert _sanitize_config("hello") == "hello"
        assert _sanitize_config(42) == 42
        assert _sanitize_config(None) is None
