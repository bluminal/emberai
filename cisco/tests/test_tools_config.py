"""Tests for config MCP tools.

Mock-based: SSH client returns fixture text.
Covers: cisco__config__get_running_config, get_startup_config, detect_drift,
save_config.
Tests happy path, cache integration, auth failure, network errors, drift,
and write gate enforcement for save_config.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cisco.errors import AuthenticationError, NetworkError, WriteGateError
from cisco.tools.config import (
    _cache,
    _normalize_config,
    cisco__config__detect_drift,
    cisco__config__get_running_config,
    cisco__config__get_startup_config,
    cisco__config__save_config,
)
from tests.fixtures import load_fixture


@pytest.fixture(autouse=True)
async def _flush_cache():
    """Flush the config cache before each test."""
    await _cache.flush()
    yield
    await _cache.flush()


def _make_mock_client(
    running: str | None = None,
    startup: str | None = None,
) -> AsyncMock:
    """Build a mock SSH client that returns fixture or custom config."""
    client = AsyncMock()
    client.connect = AsyncMock()

    running_text = running if running is not None else load_fixture("show_running_config.txt")
    startup_text = startup if startup is not None else running_text

    command_map = {
        "show running-config": running_text,
        "show startup-config": startup_text,
    }

    async def _send(cmd: str) -> str:
        return command_map.get(cmd, "")

    client.send_command = AsyncMock(side_effect=_send)
    return client


# ---------------------------------------------------------------------------
# _normalize_config
# ---------------------------------------------------------------------------


class TestNormalizeConfig:
    """Tests for the config normalization helper."""

    def test_strips_empty_lines(self) -> None:
        raw = "line1\n\nline2\n\n"
        result = _normalize_config(raw)
        assert "" not in result

    def test_strips_comment_lines(self) -> None:
        raw = "! This is a comment\nhostname switch1\n"
        result = _normalize_config(raw)
        assert "!" not in " ".join(result)
        assert "hostname switch1" in result

    def test_strips_current_configuration_header(self) -> None:
        raw = "Current configuration : 1234 bytes\nhostname switch1\n"
        result = _normalize_config(raw)
        assert not any(line.startswith("Current configuration") for line in result)

    def test_strips_trailing_whitespace(self) -> None:
        raw = "hostname switch1   \ninterface gi1  \n"
        result = _normalize_config(raw)
        assert all(line == line.rstrip() for line in result)


# ---------------------------------------------------------------------------
# cisco__config__get_running_config
# ---------------------------------------------------------------------------


class TestGetRunningConfig:
    """Tests for the running config tool."""

    @pytest.mark.asyncio
    async def test_returns_config_string(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.config.get_client", return_value=mock_client):
            result = await cisco__config__get_running_config()
            assert isinstance(result, str)
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_cache_hit_skips_ssh(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.config.get_client", return_value=mock_client):
            await cisco__config__get_running_config()
            await cisco__config__get_running_config()
            assert mock_client.connect.await_count == 1

    @pytest.mark.asyncio
    async def test_auth_error_returns_error_string(self) -> None:
        with patch(
            "cisco.tools.config.get_client",
            side_effect=AuthenticationError("missing creds", env_var="CISCO_HOST"),
        ):
            result = await cisco__config__get_running_config()
            assert isinstance(result, str)
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_network_error_returns_error_string(self) -> None:
        mock_client = _make_mock_client()
        mock_client.send_command = AsyncMock(
            side_effect=NetworkError("connection lost"),
        )
        with patch("cisco.tools.config.get_client", return_value=mock_client):
            result = await cisco__config__get_running_config()
            assert "Error" in result


# ---------------------------------------------------------------------------
# cisco__config__get_startup_config
# ---------------------------------------------------------------------------


class TestGetStartupConfig:
    """Tests for the startup config tool."""

    @pytest.mark.asyncio
    async def test_returns_config_string(self) -> None:
        mock_client = _make_mock_client()
        with patch("cisco.tools.config.get_client", return_value=mock_client):
            result = await cisco__config__get_startup_config()
            assert isinstance(result, str)
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_auth_error_returns_error_string(self) -> None:
        with patch(
            "cisco.tools.config.get_client",
            side_effect=AuthenticationError("missing creds", env_var="CISCO_HOST"),
        ):
            result = await cisco__config__get_startup_config()
            assert "Error" in result


# ---------------------------------------------------------------------------
# cisco__config__detect_drift
# ---------------------------------------------------------------------------


class TestDetectDrift:
    """Tests for the config drift detection tool."""

    @pytest.mark.asyncio
    async def test_no_drift_when_configs_match(self) -> None:
        config_text = "hostname switch1\ninterface gi1\n speed 1000\n"
        mock_client = _make_mock_client(running=config_text, startup=config_text)
        with patch("cisco.tools.config.get_client", return_value=mock_client):
            result = await cisco__config__detect_drift()
            assert result["has_drift"] is False
            assert result["added_lines"] == []
            assert result["removed_lines"] == []
            assert "No Configuration Drift" in result["summary"]

    @pytest.mark.asyncio
    async def test_drift_detected_when_configs_differ(self) -> None:
        running = "hostname switch1\ninterface gi1\n speed 1000\nlogging host 10.0.0.1\n"
        startup = "hostname switch1\ninterface gi1\n speed 1000\n"
        mock_client = _make_mock_client(running=running, startup=startup)
        with patch("cisco.tools.config.get_client", return_value=mock_client):
            result = await cisco__config__detect_drift()
            assert result["has_drift"] is True
            assert len(result["added_lines"]) > 0
            assert "Drift Detected" in result["summary"]

    @pytest.mark.asyncio
    async def test_drift_shows_removed_lines(self) -> None:
        running = "hostname switch1\ninterface gi1\n"
        startup = "hostname switch1\ninterface gi1\nlogging host 10.0.0.1\n"
        mock_client = _make_mock_client(running=running, startup=startup)
        with patch("cisco.tools.config.get_client", return_value=mock_client):
            result = await cisco__config__detect_drift()
            assert result["has_drift"] is True
            assert len(result["removed_lines"]) > 0

    @pytest.mark.asyncio
    async def test_auth_error_returns_error_dict(self) -> None:
        with patch(
            "cisco.tools.config.get_client",
            side_effect=AuthenticationError("missing creds", env_var="CISCO_HOST"),
        ):
            result = await cisco__config__detect_drift()
            assert "error" in result

    @pytest.mark.asyncio
    async def test_network_error_returns_error_dict(self) -> None:
        mock_client = _make_mock_client()
        mock_client.send_command = AsyncMock(
            side_effect=NetworkError("timeout"),
        )
        with patch("cisco.tools.config.get_client", return_value=mock_client):
            result = await cisco__config__detect_drift()
            assert "error" in result


# ---------------------------------------------------------------------------
# cisco__config__save_config
# ---------------------------------------------------------------------------


def _make_save_mock_client(
    *,
    old_startup: str = "hostname switch1\n",
    new_startup: str = "hostname switch1\nvlan 100\n",
    running: str = "hostname switch1\nvlan 100\n",
) -> AsyncMock:
    """Build a mock SSH client for save_config tests.

    The client returns different startup configs before/after the save to
    simulate the effect of ``write memory``.
    """
    client = AsyncMock()
    client.connect = AsyncMock()
    client.save_config = AsyncMock(return_value="[OK]")

    startup_call_count = {"n": 0}

    async def _send(cmd: str) -> str:
        if cmd == "show startup-config":
            startup_call_count["n"] += 1
            # First call: old startup; second call: new startup
            if startup_call_count["n"] <= 1:
                return old_startup
            return new_startup
        if cmd == "show running-config":
            return running
        return ""

    client.send_command = AsyncMock(side_effect=_send)
    return client


class TestSaveConfig:
    """Tests for cisco__config__save_config."""

    @pytest.mark.asyncio
    async def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """save_config persists running to startup and reports changes."""
        monkeypatch.setenv("CISCO_WRITE_ENABLED", "true")

        mock_client = _make_save_mock_client(
            old_startup="hostname switch1\n",
            new_startup="hostname switch1\nvlan 100\n",
            running="hostname switch1\nvlan 100\n",
        )

        with (
            patch("cisco.tools.config.get_client", return_value=mock_client),
            patch("cisco.tools.config.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__config__save_config(apply=True)

        assert result["result"] == "saved"
        assert result["changes_count"] > 0
        assert "added" in result["diff_summary"].lower() or "line" in result["diff_summary"].lower()
        mock_client.save_config.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_changes_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When running matches startup, no changes reported."""
        monkeypatch.setenv("CISCO_WRITE_ENABLED", "true")

        config = "hostname switch1\nvlan 10\n"
        mock_client = _make_save_mock_client(
            old_startup=config,
            new_startup=config,
            running=config,
        )

        with (
            patch("cisco.tools.config.get_client", return_value=mock_client),
            patch("cisco.tools.config.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__config__save_config(apply=True)

        assert result["result"] == "saved"
        assert result["changes_count"] == 0
        summary = result["diff_summary"].lower()
        assert "already saved" in summary or "no diff" in summary

    @pytest.mark.asyncio
    async def test_write_gate_blocks_without_env(self) -> None:
        """save_config is blocked when CISCO_WRITE_ENABLED is not set."""
        with patch.dict(os.environ, {}, clear=True), pytest.raises(WriteGateError):
            await cisco__config__save_config(apply=True)

    @pytest.mark.asyncio
    async def test_write_gate_blocks_without_apply(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """save_config is blocked without apply=True."""
        monkeypatch.setenv("CISCO_WRITE_ENABLED", "true")
        with pytest.raises(WriteGateError):
            await cisco__config__save_config(apply=False)

    @pytest.mark.asyncio
    async def test_config_backup_captured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config backup is captured before saving."""
        monkeypatch.setenv("CISCO_WRITE_ENABLED", "true")

        mock_client = _make_save_mock_client()

        with (
            patch("cisco.tools.config.get_client", return_value=mock_client),
            patch("cisco.tools.config.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            await cisco__config__save_config(apply=True)

        mock_backup_instance.capture.assert_awaited_once()
        # Verify the label mentions "save"
        call_args = mock_backup_instance.capture.call_args
        label = call_args[1].get("label", call_args[0][1] if len(call_args[0]) > 1 else "")
        assert "save" in label.lower()

    @pytest.mark.asyncio
    async def test_diff_between_old_and_new_startup(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Save config reports diff with added and removed lines."""
        monkeypatch.setenv("CISCO_WRITE_ENABLED", "true")

        mock_client = _make_save_mock_client(
            old_startup="hostname switch1\nlogging host 10.0.0.1\n",
            new_startup="hostname switch1\nvlan 200\n",
            running="hostname switch1\nvlan 200\n",
        )

        with (
            patch("cisco.tools.config.get_client", return_value=mock_client),
            patch("cisco.tools.config.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__config__save_config(apply=True)

        assert result["changes_count"] > 0
        summary = result["diff_summary"].lower()
        assert "added" in summary or "removed" in summary

    @pytest.mark.asyncio
    async def test_auth_error_returns_error_dict(self) -> None:
        """AuthenticationError from save_config returns error dict."""
        with (
            patch.dict(os.environ, {"CISCO_WRITE_ENABLED": "true"}),
            patch(
                "cisco.tools.config.get_client",
                side_effect=AuthenticationError("bad creds", env_var="CISCO_HOST"),
            ),
        ):
            result = await cisco__config__save_config(apply=True)
        assert "error" in result
        assert "hint" in result

    @pytest.mark.asyncio
    async def test_network_error_returns_error_dict(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """NetworkError from save_config returns error dict."""
        monkeypatch.setenv("CISCO_WRITE_ENABLED", "true")

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock(side_effect=NetworkError("connection lost"))

        with patch("cisco.tools.config.get_client", return_value=mock_client):
            result = await cisco__config__save_config(apply=True)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_cache_flushed_after_save(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config cache is flushed after saving so subsequent reads are fresh."""
        monkeypatch.setenv("CISCO_WRITE_ENABLED", "true")

        mock_client = _make_save_mock_client()

        # Pre-populate cache
        await _cache.set("config:running", "old_cached_value")

        with (
            patch("cisco.tools.config.get_client", return_value=mock_client),
            patch("cisco.tools.config.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            await cisco__config__save_config(apply=True)

        # Cache should have been flushed -- the old value should be gone
        cached = await _cache.get("config:running")
        assert cached is None
