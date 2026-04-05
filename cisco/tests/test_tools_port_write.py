"""Tests for port management write MCP tools.

Mock-based: SSH client returns fixture text.
Covers: cisco__interfaces__set_port_description, cisco__interfaces__set_port_state.
Tests happy path, write gate enforcement, validation, MAC address warnings,
verification, and error handling.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cisco.errors import AuthenticationError, NetworkError, SSHCommandError, WriteGateError
from cisco.tools.port_write import (
    _cache,
    cisco__interfaces__set_port_description,
    cisco__interfaces__set_port_state,
)
from tests.fixtures import load_fixture

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(
    *,
    mac_output: str | None = None,
    interfaces_output: str | None = None,
) -> AsyncMock:
    """Build a mock SSH client for port write tests.

    Parameters
    ----------
    mac_output:
        Text returned for ``show mac address-table``.
    interfaces_output:
        Text returned for ``show interfaces status``.
    """
    client = AsyncMock()
    client.connect = AsyncMock()
    client.send_config_set = AsyncMock(return_value="")

    _mac = mac_output if mac_output is not None else load_fixture("show_mac_address_table.txt")
    _ifaces = (
        interfaces_output
        if interfaces_output is not None
        else load_fixture("show_interfaces_status.txt")
    )

    async def _send_command(command: str) -> str:
        if command == "show mac address-table":
            return _mac
        if command == "show interfaces status":
            return _ifaces
        if command == "show running-config":
            return load_fixture("show_running_config.txt")
        return ""

    client.send_command = AsyncMock(side_effect=_send_command)
    return client


@pytest.fixture(autouse=True)
async def _flush_cache():
    """Flush the port write cache before each test."""
    await _cache.flush()
    yield
    await _cache.flush()


@pytest.fixture()
def _enable_writes(monkeypatch: pytest.MonkeyPatch):
    """Enable writes and set apply=True environment."""
    monkeypatch.setenv("CISCO_WRITE_ENABLED", "true")


# ===========================================================================
# cisco__interfaces__set_port_description
# ===========================================================================


class TestSetPortDescription:
    """Tests for cisco__interfaces__set_port_description."""

    @pytest.mark.asyncio
    async def test_happy_path(self, _enable_writes: None) -> None:
        """Set port description on gi3."""
        client = _make_mock_client()

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_port_description(
                "gi3", "AP-Living-Room", apply=True,
            )

        assert result["result"] == "configured"
        assert result["port"] == "gi3"
        assert result["description"] == "AP-Living-Room"
        assert result["verified"] is True

        # Verify CLI commands
        client.send_config_set.assert_awaited_once()
        commands = client.send_config_set.call_args[0][0]
        assert "interface gi3" in commands
        assert "description AP-Living-Room" in commands
        assert "exit" in commands

    @pytest.mark.asyncio
    async def test_description_whitespace_stripped(self, _enable_writes: None) -> None:
        """Leading/trailing whitespace in description is stripped."""
        client = _make_mock_client()

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_port_description(
                "gi3", "  NAS-Primary  ", apply=True,
            )

        assert result["description"] == "NAS-Primary"
        commands = client.send_config_set.call_args[0][0]
        assert "description NAS-Primary" in commands

    @pytest.mark.asyncio
    async def test_empty_description_rejected(self, _enable_writes: None) -> None:
        """Empty description returns error."""
        result = await cisco__interfaces__set_port_description("gi3", "", apply=True)
        assert "error" in result
        assert "empty" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_whitespace_only_description_rejected(self, _enable_writes: None) -> None:
        """Whitespace-only description returns error."""
        result = await cisco__interfaces__set_port_description("gi3", "   ", apply=True)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_port_rejected(self, _enable_writes: None) -> None:
        """Invalid port format returns error."""
        for bad_port in ("eth1", "x", "123", ""):
            result = await cisco__interfaces__set_port_description(
                bad_port, "test", apply=True,
            )
            assert "error" in result, f"Expected error for port: {bad_port!r}"
            assert "Invalid port" in result["error"]

    @pytest.mark.asyncio
    async def test_write_gate_enforcement_env(self) -> None:
        """Write gate blocks without CISCO_WRITE_ENABLED."""
        with patch.dict(os.environ, {}, clear=True), pytest.raises(WriteGateError):
            await cisco__interfaces__set_port_description(
                "gi3", "test", apply=True,
            )

    @pytest.mark.asyncio
    async def test_write_gate_enforcement_apply(self, _enable_writes: None) -> None:
        """Write gate blocks without apply=True."""
        with pytest.raises(WriteGateError):
            await cisco__interfaces__set_port_description(
                "gi3", "test", apply=False,
            )

    @pytest.mark.asyncio
    async def test_config_backup_captured(self, _enable_writes: None) -> None:
        """Config backup is captured before making changes."""
        client = _make_mock_client()

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            await cisco__interfaces__set_port_description("gi3", "test", apply=True)

        mock_backup_instance.capture.assert_awaited_once()
        call_args = mock_backup_instance.capture.call_args
        positional = call_args[0]
        label = call_args[1].get(
            "label",
            positional[1] if len(positional) > 1 else None,
        )
        assert label is not None
        assert "gi3" in label

    @pytest.mark.asyncio
    async def test_network_error_handling(self, _enable_writes: None) -> None:
        """NetworkError returns error dict."""
        client = AsyncMock()
        client.connect = AsyncMock(side_effect=NetworkError("timeout"))

        with patch("cisco.tools.port_write.get_client", return_value=client):
            result = await cisco__interfaces__set_port_description(
                "gi3", "test", apply=True,
            )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_auth_error_handling(self, _enable_writes: None) -> None:
        """AuthenticationError returns error dict with hint."""
        with patch(
            "cisco.tools.port_write.get_client",
            side_effect=AuthenticationError("bad creds", env_var="CISCO_SSH_PASSWORD"),
        ):
            result = await cisco__interfaces__set_port_description(
                "gi3", "test", apply=True,
            )

        assert "error" in result
        assert "hint" in result

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, _enable_writes: None) -> None:
        """Cache is flushed after a successful description change."""
        client = _make_mock_client()

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
            patch("cisco.tools.port_write._invalidate_caches") as mock_invalidate,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            await cisco__interfaces__set_port_description("gi3", "test", apply=True)

        mock_invalidate.assert_awaited_once()


# ===========================================================================
# cisco__interfaces__set_port_state
# ===========================================================================


class TestSetPortState:
    """Tests for cisco__interfaces__set_port_state."""

    @pytest.mark.asyncio
    async def test_enable_port(self, _enable_writes: None) -> None:
        """Enable port (no shutdown) sends correct commands."""
        client = _make_mock_client()

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_port_state("gi3", True, apply=True)

        assert result["result"] == "configured"
        assert result["port"] == "gi3"
        assert result["enabled"] is True
        assert result["verified"] is True

        commands = client.send_config_set.call_args[0][0]
        assert "interface gi3" in commands
        assert "no shutdown" in commands
        assert "exit" in commands
        # Should NOT have "shutdown" as a standalone command
        assert commands[1] == "no shutdown"

    @pytest.mark.asyncio
    async def test_disable_port(self, _enable_writes: None) -> None:
        """Disable port (shutdown) sends correct commands."""
        client = _make_mock_client()

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_port_state("gi3", False, apply=True)

        assert result["result"] == "configured"
        assert result["enabled"] is False

        commands = client.send_config_set.call_args[0][0]
        assert "shutdown" in commands
        # Make sure it's "shutdown" not "no shutdown"
        assert commands[1] == "shutdown"

    @pytest.mark.asyncio
    async def test_warning_when_disabling_port_with_active_macs(
        self, _enable_writes: None,
    ) -> None:
        """Disabling a port with active MAC entries includes a warning."""
        # The fixture has MAC entry on gi3: 1c:0b:8b:70:ae:b4
        client = _make_mock_client(
            mac_output=load_fixture("show_mac_address_table.txt"),
        )

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_port_state("gi3", False, apply=True)

        assert result["result"] == "configured"
        assert "active_macs_warning" in result
        assert "gi3" in result["active_macs_warning"]
        assert "1c:0b:8b:70:ae:b4" in result["active_macs_warning"].lower()

    @pytest.mark.asyncio
    async def test_no_warning_when_disabling_port_with_no_macs(
        self, _enable_writes: None,
    ) -> None:
        """Disabling a port with no active MACs has no warning."""
        # Use empty MAC table
        client = _make_mock_client(
            mac_output=load_fixture("show_mac_address_table_empty.txt"),
        )

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_port_state("gi7", False, apply=True)

        assert result["result"] == "configured"
        assert "active_macs_warning" not in result

    @pytest.mark.asyncio
    async def test_no_mac_check_when_enabling(self, _enable_writes: None) -> None:
        """Enabling a port does NOT check MAC table."""
        client = _make_mock_client()

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_port_state("gi3", True, apply=True)

        assert "active_macs_warning" not in result
        # send_command calls should NOT include "show mac address-table"
        mac_calls = [
            c
            for c in client.send_command.call_args_list
            if "mac address-table" in str(c)
        ]
        assert len(mac_calls) == 0

    @pytest.mark.asyncio
    async def test_invalid_port_rejected(self, _enable_writes: None) -> None:
        """Invalid port format returns error."""
        for bad_port in ("eth1", "x", "ge1", ""):
            result = await cisco__interfaces__set_port_state(bad_port, True, apply=True)
            assert "error" in result, f"Expected error for port: {bad_port!r}"
            assert "Invalid port" in result["error"]

    @pytest.mark.asyncio
    async def test_write_gate_enforcement_env(self) -> None:
        """Write gate blocks without CISCO_WRITE_ENABLED."""
        with patch.dict(os.environ, {}, clear=True), pytest.raises(WriteGateError):
            await cisco__interfaces__set_port_state("gi3", True, apply=True)

    @pytest.mark.asyncio
    async def test_write_gate_enforcement_apply(self, _enable_writes: None) -> None:
        """Write gate blocks without apply=True."""
        with pytest.raises(WriteGateError):
            await cisco__interfaces__set_port_state("gi3", True, apply=False)

    @pytest.mark.asyncio
    async def test_verification_checks_interfaces_status(self, _enable_writes: None) -> None:
        """After changing state, show interfaces status is parsed for verification."""
        client = _make_mock_client()

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_port_state("gi3", True, apply=True)

        assert result["verified"] is True
        # send_command should have been called with "show interfaces status"
        status_calls = [
            c
            for c in client.send_command.call_args_list
            if "show interfaces status" in str(c)
        ]
        assert len(status_calls) >= 1

    @pytest.mark.asyncio
    async def test_network_error_handling(self, _enable_writes: None) -> None:
        """NetworkError returns error dict."""
        client = AsyncMock()
        client.connect = AsyncMock(side_effect=NetworkError("timeout"))

        with patch("cisco.tools.port_write.get_client", return_value=client):
            result = await cisco__interfaces__set_port_state("gi3", True, apply=True)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_ssh_command_error_handling(self, _enable_writes: None) -> None:
        """SSHCommandError returns error dict."""
        client = AsyncMock()
        client.connect = AsyncMock()
        client.send_config_set = AsyncMock(
            side_effect=SSHCommandError("command rejected"),
        )

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_port_state("gi3", True, apply=True)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_auth_error_handling(self, _enable_writes: None) -> None:
        """AuthenticationError returns error dict with hint."""
        with patch(
            "cisco.tools.port_write.get_client",
            side_effect=AuthenticationError("bad creds", env_var="CISCO_SSH_PASSWORD"),
        ):
            result = await cisco__interfaces__set_port_state("gi3", True, apply=True)

        assert "error" in result
        assert "hint" in result

    @pytest.mark.asyncio
    async def test_config_backup_captured_before_changes(self, _enable_writes: None) -> None:
        """Config backup must be captured before send_config_set."""
        client = _make_mock_client()
        call_order: list[str] = []

        async def _track_config_set(cmds: list[str]) -> str:
            call_order.append("config_set")
            return ""

        async def _track_capture(*args: object, **kwargs: object) -> MagicMock:
            call_order.append("capture")
            return MagicMock()

        client.send_config_set = AsyncMock(side_effect=_track_config_set)

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock(side_effect=_track_capture)
            mock_backup.return_value = mock_backup_instance

            await cisco__interfaces__set_port_state("gi3", True, apply=True)

        assert call_order == ["capture", "config_set"]

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, _enable_writes: None) -> None:
        """Cache is flushed after a successful port state change."""
        client = _make_mock_client()

        with (
            patch("cisco.tools.port_write.get_client", return_value=client),
            patch("cisco.tools.port_write.get_config_backup") as mock_backup,
            patch("cisco.tools.port_write._invalidate_caches") as mock_invalidate,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            await cisco__interfaces__set_port_state("gi3", True, apply=True)

        mock_invalidate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_various_valid_ports(self, _enable_writes: None) -> None:
        """Various valid port formats are accepted."""
        client = _make_mock_client()

        for port in ("gi1", "fa2", "Po1", "te1"):
            with (
                patch("cisco.tools.port_write.get_client", return_value=client),
                patch("cisco.tools.port_write.get_config_backup") as mock_backup,
            ):
                mock_backup_instance = MagicMock()
                mock_backup_instance.capture = AsyncMock()
                mock_backup.return_value = mock_backup_instance

                result = await cisco__interfaces__set_port_state(port, True, apply=True)
                assert "error" not in result, f"Unexpected error for valid port: {port!r}"
