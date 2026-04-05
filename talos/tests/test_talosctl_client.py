"""Tests for the TalosCtl async subprocess client."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from talos.api.talosctl_client import TalosCtlClient, TalosCtlResult
from talos.cache import TTLCache
from talos.errors import (
    AuthenticationError,
    ConfigParseError,
    NetworkError,
    TalosCtlError,
    TalosCtlNotFoundError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_process(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    """Create a mock subprocess with the given stdout/stderr/returncode."""
    proc = MagicMock()
    proc.returncode = returncode

    async def communicate() -> tuple[bytes, bytes]:
        return stdout.encode(), stderr.encode()

    proc.communicate = communicate
    return proc


def _make_talosconfig(tmp_path: Path, contexts: dict[str, Any] | None = None) -> str:
    """Write a minimal talosconfig YAML and return its path."""
    data: dict[str, Any] = {
        "context": "homelab",
        "contexts": contexts or {
            "homelab": {
                "endpoints": ["192.168.100.10", "192.168.100.11"],
                "nodes": ["192.168.100.10", "192.168.100.11", "192.168.100.12"],
                "ca": "base64ca==",
                "crt": "base64crt==",
                "key": "base64key==",
            },
            "staging": {
                "endpoints": ["10.0.0.1"],
                "nodes": ["10.0.0.1"],
            },
        },
    }
    config_path = tmp_path / "talosconfig"
    config_path.write_text(yaml.dump(data))
    return str(config_path)


# ---------------------------------------------------------------------------
# Binary validation
# ---------------------------------------------------------------------------


class TestBinaryValidation:
    """Tests for talosctl binary discovery and validation."""

    def test_find_binary_success(self) -> None:
        with patch("shutil.which", return_value="/usr/local/bin/talosctl"):
            client = TalosCtlClient(config_path="/dev/null")
            path = client._find_binary()
            assert path == "/usr/local/bin/talosctl"

    def test_find_binary_not_found(self) -> None:
        with patch("shutil.which", return_value=None):
            client = TalosCtlClient(config_path="/dev/null")
            with pytest.raises(TalosCtlNotFoundError):
                client._find_binary()

    @pytest.mark.asyncio
    async def test_validate_binary_success(self) -> None:
        proc = _make_process(stdout="v1.12.0\n")
        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc),
        ):
            client = TalosCtlClient(config_path="/dev/null")
            version = await client.validate_binary()
            assert version == "v1.12.0"

    @pytest.mark.asyncio
    async def test_validate_binary_failure(self) -> None:
        proc = _make_process(stderr="error: unknown flag", returncode=1)
        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc),
        ):
            client = TalosCtlClient(config_path="/dev/null")
            with pytest.raises(TalosCtlError) as exc_info:
                await client.validate_binary()
            assert exc_info.value.exit_code == 1

    @pytest.mark.asyncio
    async def test_validate_binary_caches_result(self) -> None:
        proc = _make_process(stdout="v1.12.0\n")
        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
        ):
            client = TalosCtlClient(config_path="/dev/null")
            v1 = await client.validate_binary()
            v2 = await client.validate_binary()
            assert v1 == v2
            # Second call should not spawn a new process
            assert mock_exec.call_count == 1


# ---------------------------------------------------------------------------
# Talosconfig management
# ---------------------------------------------------------------------------


class TestTalosconfigManagement:
    """Tests for talosconfig parsing and context resolution."""

    def test_get_contexts(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)
        client = TalosCtlClient(config_path=config_path)
        contexts = client.get_contexts()
        assert sorted(contexts) == ["homelab", "staging"]

    def test_get_current_context_from_file(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)
        client = TalosCtlClient(config_path=config_path)
        assert client.get_current_context() == "homelab"

    def test_get_current_context_explicit_override(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)
        client = TalosCtlClient(config_path=config_path, context="staging")
        assert client.get_current_context() == "staging"

    def test_get_current_context_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _make_talosconfig(tmp_path)
        monkeypatch.setenv("TALOS_CONTEXT", "staging")
        client = TalosCtlClient(config_path=config_path)
        assert client.get_current_context() == "staging"

    def test_missing_talosconfig_raises(self) -> None:
        client = TalosCtlClient(config_path="/nonexistent/path/talosconfig")
        with pytest.raises(AuthenticationError, match="not found"):
            client.get_contexts()

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "talosconfig"
        bad_file.write_text(": : : invalid yaml [[[")
        client = TalosCtlClient(config_path=str(bad_file))
        with pytest.raises(AuthenticationError, match="Failed to parse"):
            client.get_contexts()


# ---------------------------------------------------------------------------
# Node targeting
# ---------------------------------------------------------------------------


class TestNodeTargeting:
    """Tests for node resolution priority."""

    def test_nodes_from_talosconfig(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)
        client = TalosCtlClient(config_path=config_path)
        nodes = client.get_default_nodes()
        assert nodes == ["192.168.100.10", "192.168.100.11", "192.168.100.12"]

    def test_env_var_overrides_talosconfig(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = _make_talosconfig(tmp_path)
        monkeypatch.setenv("TALOS_NODES", "10.0.0.1,10.0.0.2")
        client = TalosCtlClient(config_path=config_path)
        nodes = client.get_default_nodes()
        assert nodes == ["10.0.0.1", "10.0.0.2"]

    def test_empty_env_var_falls_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = _make_talosconfig(tmp_path)
        monkeypatch.setenv("TALOS_NODES", "")
        client = TalosCtlClient(config_path=config_path)
        nodes = client.get_default_nodes()
        assert nodes == ["192.168.100.10", "192.168.100.11", "192.168.100.12"]

    def test_no_config_no_env_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TALOS_NODES", raising=False)
        client = TalosCtlClient(config_path="/nonexistent")
        nodes = client.get_default_nodes()
        assert nodes == []


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


class TestJsonParsing:
    """Tests for JSON/NDJSON output parsing."""

    def test_single_json_object(self) -> None:
        data = {"version": "v1.12.0"}
        result = TalosCtlClient._parse_json_output(json.dumps(data))
        assert result == data

    def test_json_array(self) -> None:
        data = [{"id": "1"}, {"id": "2"}]
        result = TalosCtlClient._parse_json_output(json.dumps(data))
        assert result == data

    def test_ndjson(self) -> None:
        lines = json.dumps({"node": "cp1"}) + "\n" + json.dumps({"node": "cp2"})
        result = TalosCtlClient._parse_json_output(lines)
        assert result == [{"node": "cp1"}, {"node": "cp2"}]

    def test_empty_string(self) -> None:
        assert TalosCtlClient._parse_json_output("") is None
        assert TalosCtlClient._parse_json_output("   ") is None

    def test_invalid_json(self) -> None:
        assert TalosCtlClient._parse_json_output("not json at all") is None

    def test_partial_ndjson_returns_none(self) -> None:
        # First line valid JSON, second line not
        lines = json.dumps({"ok": True}) + "\nnot json"
        assert TalosCtlClient._parse_json_output(lines) is None


# ---------------------------------------------------------------------------
# Core run method
# ---------------------------------------------------------------------------


class TestRun:
    """Tests for the core run() method."""

    @pytest.mark.asyncio
    async def test_basic_command(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)
        output = json.dumps({"version": "v1.12.0"})
        proc = _make_process(stdout=output)

        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc),
        ):
            client = TalosCtlClient(config_path=config_path)
            result = await client.run(["version"])

            assert result.exit_code == 0
            assert result.parsed == {"version": "v1.12.0"}

    @pytest.mark.asyncio
    async def test_command_with_explicit_nodes(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)
        output = json.dumps({"status": "ok"})
        proc = _make_process(stdout=output)

        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
        ):
            client = TalosCtlClient(config_path=config_path)
            await client.run(["health"], nodes=["192.168.100.10"])

            # Verify --nodes was passed in the command
            call_args = mock_exec.call_args[0]
            assert "--nodes" in call_args
            nodes_idx = list(call_args).index("--nodes")
            assert call_args[nodes_idx + 1] == "192.168.100.10"

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)
        proc = _make_process(stderr="rpc error: connection refused", returncode=1)

        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc),
        ):
            client = TalosCtlClient(config_path=config_path)
            with pytest.raises(TalosCtlError) as exc_info:
                await client.run(["health"], nodes="192.168.100.10")

            assert exc_info.value.exit_code == 1
            assert "connection refused" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_timeout_raises_network_error(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)

        async def slow_communicate() -> tuple[bytes, bytes]:
            await asyncio.sleep(10)
            return b"", b""

        proc = MagicMock()
        proc.communicate = slow_communicate
        proc.returncode = 0

        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc),
        ):
            client = TalosCtlClient(config_path=config_path)
            with pytest.raises(NetworkError, match="timed out"):
                await client.run(["health"], timeout=0.01)

    @pytest.mark.asyncio
    async def test_json_parse_failure_returns_none_parsed(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)
        proc = _make_process(stdout="not json output\nsome text")

        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc),
        ):
            client = TalosCtlClient(config_path=config_path)
            result = await client.run(["dashboard"])

            assert result.parsed is None
            assert result.stdout == "not json output\nsome text"

    @pytest.mark.asyncio
    async def test_no_json_flag_when_disabled(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)
        proc = _make_process(stdout="text output")

        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
        ):
            client = TalosCtlClient(config_path=config_path)
            await client.run(["dashboard"], json_output=False)

            call_args = mock_exec.call_args[0]
            assert "-o" not in call_args
            assert "json" not in call_args


# ---------------------------------------------------------------------------
# Cache integration
# ---------------------------------------------------------------------------


class TestCacheIntegration:
    """Tests for TTL cache integration."""

    @pytest.mark.asyncio
    async def test_cache_hit(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)
        cache = TTLCache(max_size=100, default_ttl=300.0)
        output = json.dumps({"version": "v1.12.0"})
        proc = _make_process(stdout=output)

        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
        ):
            client = TalosCtlClient(config_path=config_path, cache=cache)

            # First call populates cache
            r1 = await client.run(["version"], nodes="192.168.100.10")
            # Second call should hit cache
            r2 = await client.run(["version"], nodes="192.168.100.10")

            assert r1.parsed == r2.parsed
            # Subprocess only called once
            assert mock_exec.call_count == 1

    @pytest.mark.asyncio
    async def test_write_commands_skip_cache(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)
        cache = TTLCache(max_size=100, default_ttl=300.0)
        output = json.dumps({"ok": True})
        proc = _make_process(stdout=output)

        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
        ):
            client = TalosCtlClient(config_path=config_path, cache=cache)

            await client.run(["apply-config"], nodes="192.168.100.10")
            await client.run(["apply-config"], nodes="192.168.100.10")

            # Both calls should invoke the subprocess (no caching)
            assert mock_exec.call_count == 2

    @pytest.mark.asyncio
    async def test_flush_cache(self, tmp_path: Path) -> None:
        config_path = _make_talosconfig(tmp_path)
        cache = TTLCache(max_size=100, default_ttl=300.0)
        output = json.dumps({"version": "v1.12.0"})
        proc = _make_process(stdout=output)

        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
        ):
            client = TalosCtlClient(config_path=config_path, cache=cache)

            await client.run(["version"], nodes="192.168.100.10")
            await client.flush_cache()
            await client.run(["version"], nodes="192.168.100.10")

            # After flush, subprocess is called again
            assert mock_exec.call_count == 2


# ---------------------------------------------------------------------------
# Insecure mode
# ---------------------------------------------------------------------------


class TestInsecureMode:
    """Tests for run_insecure() used during initial node setup."""

    @pytest.mark.asyncio
    async def test_insecure_flag_added(self) -> None:
        output = json.dumps({"version": "v1.12.0"})
        proc = _make_process(stdout=output)

        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
        ):
            client = TalosCtlClient(config_path="/dev/null")
            await client.run_insecure(["version"], nodes="192.168.100.10")

            call_args = mock_exec.call_args[0]
            assert "--insecure" in call_args

    @pytest.mark.asyncio
    async def test_insecure_no_talosconfig(self) -> None:
        """Insecure mode should not require talosconfig."""
        output = json.dumps({"status": "maintenance"})
        proc = _make_process(stdout=output)

        with (
            patch("shutil.which", return_value="/usr/local/bin/talosctl"),
            patch("asyncio.create_subprocess_exec", return_value=proc),
        ):
            # Config path doesn't exist — should still work in insecure mode
            client = TalosCtlClient(config_path="/nonexistent")
            result = await client.run_insecure(["version"], nodes="192.168.100.10")
            assert result.parsed == {"status": "maintenance"}
