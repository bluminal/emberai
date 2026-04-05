"""Tests for VLAN write MCP tools.

Mock-based: SSH client returns fixture text.
Covers: cisco__interfaces__create_vlan, delete_vlan, set_port_vlan, set_trunk_port.
Tests happy path, write gate enforcement, validation, SSH errors, cache invalidation,
config backup capture, and verification.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cisco.errors import AuthenticationError, NetworkError, SSHCommandError, WriteGateError
from cisco.models.vlan import VLAN
from cisco.tools.vlan_write import (
    _cache,
    cisco__interfaces__create_vlan,
    cisco__interfaces__delete_vlan,
    cisco__interfaces__set_port_vlan,
    cisco__interfaces__set_trunk_port,
)
from tests.fixtures import load_fixture

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vlans(*ids_and_names: tuple[int, str, list[str]]) -> list[VLAN]:
    """Build a list of VLAN models for mocking _get_existing_vlans."""
    return [
        VLAN(id=vid, name=name, ports=ports, tagged_ports=[])
        for vid, name, ports in ids_and_names
    ]


def _make_mock_client(
    *,
    existing_vlans: list[VLAN] | None = None,
    updated_vlans: list[VLAN] | None = None,
    switchport_output: str | None = None,
) -> AsyncMock:
    """Build a mock SSH client for VLAN write tests.

    Parameters
    ----------
    existing_vlans:
        VLANs returned by the first ``show vlan`` call (pre-check).
    updated_vlans:
        VLANs returned by the second ``show vlan`` call (verification).
        Defaults to ``existing_vlans`` if not provided.
    switchport_output:
        Text returned for ``show interfaces switchport ...`` commands.
    """
    client = AsyncMock()
    client.connect = AsyncMock()
    client.send_config_set = AsyncMock(return_value="")

    if existing_vlans is None:
        existing_vlans = _make_vlans(
            (1, "default", ["gi1", "gi2", "gi4"]),
            (10, "Admin", ["gi3"]),
            (20, "Management", []),
        )

    if updated_vlans is None:
        updated_vlans = list(existing_vlans)

    # Track call count to alternate between first/second show vlan
    call_count = {"vlan": 0}

    async def _send_command(command: str) -> str:
        if command == "show vlan":
            call_count["vlan"] += 1
            if call_count["vlan"] <= 1:
                return load_fixture("show_vlan.txt")
            return load_fixture("show_vlan.txt")
        if command == "show running-config":
            return load_fixture("show_running_config.txt")
        if command.startswith("show interfaces switchport"):
            return switchport_output or load_fixture("show_switchport_access.txt")
        return ""

    client.send_command = AsyncMock(side_effect=_send_command)
    return client


@pytest.fixture(autouse=True)
async def _flush_cache():
    """Flush the VLAN write cache before each test."""
    await _cache.flush()
    yield
    await _cache.flush()


@pytest.fixture()
def _enable_writes(monkeypatch: pytest.MonkeyPatch):
    """Enable writes and set apply=True environment."""
    monkeypatch.setenv("CISCO_WRITE_ENABLED", "true")


# ===========================================================================
# cisco__interfaces__create_vlan
# ===========================================================================


class TestCreateVlan:
    """Tests for cisco__interfaces__create_vlan."""

    @pytest.mark.asyncio
    async def test_happy_path_creates_vlan(self, _enable_writes: None) -> None:
        """Create VLAN 100 -- verifies CLI commands and result shape."""
        client = _make_mock_client()

        # Patch parse_show_vlan to return different lists on first/second call
        first_vlans = _make_vlans(
            (1, "default", []),
            (10, "Admin", ["gi3"]),
        )
        second_vlans = [*first_vlans, VLAN(id=100, name="Lab", ports=[], tagged_ports=[])]

        call_count = {"n": 0}

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return load_fixture("show_running_config.txt")
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans") as mock_get_vlans,
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            # First call: check existence; second call: verify creation
            def _side_effect(_client: object) -> list[VLAN]:
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return first_vlans
                return second_vlans

            mock_get_vlans.side_effect = _side_effect
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__create_vlan(100, "Lab", apply=True)

        assert result["result"] == "created"
        assert result["vlan_id"] == 100
        assert result["name"] == "Lab"
        assert result["verified"] is True

        # Config set should include vlan 100, name Lab, exit
        client.send_config_set.assert_awaited_once()
        commands = client.send_config_set.call_args[0][0]
        assert "vlan 100" in commands
        assert "name Lab" in commands
        assert "exit" in commands

    @pytest.mark.asyncio
    async def test_config_backup_captured_before_changes(self, _enable_writes: None) -> None:
        """Config backup must be captured before send_config_set."""
        client = _make_mock_client()
        first_vlans = _make_vlans((1, "default", []))
        second_vlans = [*first_vlans, VLAN(id=100, name="Test", ports=[], tagged_ports=[])]

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return load_fixture("show_running_config.txt")
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        call_order: list[str] = []

        async def _track_config_set(cmds: list[str]) -> str:
            call_order.append("config_set")
            return ""

        async def _track_capture(*args: object, **kwargs: object) -> MagicMock:
            call_order.append("capture")
            return MagicMock()

        client.send_config_set = AsyncMock(side_effect=_track_config_set)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans") as mock_get_vlans,
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            call_n = {"n": 0}

            def _side_effect(_client: object) -> list[VLAN]:
                call_n["n"] += 1
                return first_vlans if call_n["n"] == 1 else second_vlans

            mock_get_vlans.side_effect = _side_effect
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock(side_effect=_track_capture)
            mock_backup.return_value = mock_backup_instance

            await cisco__interfaces__create_vlan(100, "Test", apply=True)

        assert call_order == ["capture", "config_set"]

    @pytest.mark.asyncio
    async def test_write_gate_blocks_without_env_var(self) -> None:
        """Without CISCO_WRITE_ENABLED, write gate raises error."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await cisco__interfaces__create_vlan(100, "Lab", apply=True)
            assert exc_info.value.reason.value == "env_var_disabled"

    @pytest.mark.asyncio
    async def test_write_gate_blocks_without_apply(self, _enable_writes: None) -> None:
        """Without apply=True, write gate raises error."""
        with pytest.raises(WriteGateError) as exc_info:
            await cisco__interfaces__create_vlan(100, "Lab", apply=False)
        assert exc_info.value.reason.value == "apply_flag_missing"

    @pytest.mark.asyncio
    async def test_duplicate_vlan_rejected(self, _enable_writes: None) -> None:
        """Creating an already-existing VLAN returns an error dict."""
        client = _make_mock_client()
        existing = _make_vlans(
            (1, "default", []),
            (10, "Admin", ["gi3"]),
        )

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans", return_value=existing),
        ):
            result = await cisco__interfaces__create_vlan(10, "DuplicateAdmin", apply=True)

        assert "error" in result
        assert "already exists" in result["error"]
        assert result["vlan_id"] == 10
        # send_config_set should NOT have been called
        client.send_config_set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_vlan_id_1_rejected(self, _enable_writes: None) -> None:
        """VLAN 1 (default) cannot be created."""
        result = await cisco__interfaces__create_vlan(1, "Default", apply=True)
        assert "error" in result
        assert "VLAN 1" in result["error"] or "default" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_vlan_id_0_rejected(self, _enable_writes: None) -> None:
        """VLAN 0 is out of range."""
        result = await cisco__interfaces__create_vlan(0, "Invalid", apply=True)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_vlan_id_4095_rejected(self, _enable_writes: None) -> None:
        """VLAN 4095 is out of range."""
        result = await cisco__interfaces__create_vlan(4095, "Invalid", apply=True)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_vlan_id_negative_rejected(self, _enable_writes: None) -> None:
        """Negative VLAN ID is out of range."""
        result = await cisco__interfaces__create_vlan(-1, "Invalid", apply=True)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_verification_after_creation(self, _enable_writes: None) -> None:
        """After creation, show vlan is called again to verify."""
        client = _make_mock_client()
        first_vlans = _make_vlans((1, "default", []))
        # Verification returns VLAN 200 present
        second_vlans = [*first_vlans, VLAN(id=200, name="New", ports=[], tagged_ports=[])]

        call_count = {"n": 0}

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans") as mock_get_vlans,
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            def _side_effect(_client: object) -> list[VLAN]:
                call_count["n"] += 1
                return first_vlans if call_count["n"] == 1 else second_vlans

            mock_get_vlans.side_effect = _side_effect
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__create_vlan(200, "New", apply=True)

        assert result["verified"] is True
        # _get_existing_vlans called twice (check + verify)
        assert mock_get_vlans.call_count == 2

    @pytest.mark.asyncio
    async def test_network_error_handling(self, _enable_writes: None) -> None:
        """NetworkError during creation returns error dict."""
        client = AsyncMock()
        client.connect = AsyncMock(side_effect=NetworkError("SSH connection refused"))

        with patch("cisco.tools.vlan_write.get_client", return_value=client):
            result = await cisco__interfaces__create_vlan(100, "Lab", apply=True)

        assert "error" in result
        assert "connection refused" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_auth_error_handling(self, _enable_writes: None) -> None:
        """AuthenticationError returns error dict with hint."""
        with patch(
            "cisco.tools.vlan_write.get_client",
            side_effect=AuthenticationError("bad creds", env_var="CISCO_SSH_PASSWORD"),
        ):
            result = await cisco__interfaces__create_vlan(100, "Lab", apply=True)

        assert "error" in result
        assert "hint" in result

    @pytest.mark.asyncio
    async def test_ssh_command_error_handling(self, _enable_writes: None) -> None:
        """SSHCommandError returns error dict."""
        client = AsyncMock()
        client.connect = AsyncMock()
        client.send_command = AsyncMock()

        # Make _get_existing_vlans work, but send_config_set fails
        first_vlans = _make_vlans((1, "default", []))

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)
        client.send_config_set = AsyncMock(
            side_effect=SSHCommandError("command rejected", command="vlan 100"),
        )

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans", return_value=first_vlans),
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__create_vlan(100, "Lab", apply=True)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_cache_invalidation_after_creation(self, _enable_writes: None) -> None:
        """Cache should be flushed after a successful creation."""
        client = _make_mock_client()
        first_vlans = _make_vlans((1, "default", []))
        second_vlans = [*first_vlans, VLAN(id=100, name="Lab", ports=[], tagged_ports=[])]

        call_count = {"n": 0}

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans") as mock_get_vlans,
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
            patch("cisco.tools.vlan_write._invalidate_caches") as mock_invalidate,
        ):
            def _side_effect(_client: object) -> list[VLAN]:
                call_count["n"] += 1
                return first_vlans if call_count["n"] == 1 else second_vlans

            mock_get_vlans.side_effect = _side_effect
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            await cisco__interfaces__create_vlan(100, "Lab", apply=True)

        mock_invalidate.assert_awaited_once()


# ===========================================================================
# cisco__interfaces__delete_vlan
# ===========================================================================


class TestDeleteVlan:
    """Tests for cisco__interfaces__delete_vlan."""

    @pytest.mark.asyncio
    async def test_happy_path_deletes_vlan(self, _enable_writes: None) -> None:
        """Delete VLAN 100 -- verifies result and CLI commands."""
        client = _make_mock_client()
        existing_vlans = _make_vlans(
            (1, "default", []),
            (100, "Lab", []),
        )
        # After deletion, VLAN 100 is gone
        after_vlans = _make_vlans((1, "default", []))

        call_count = {"n": 0}

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans") as mock_get_vlans,
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            def _side_effect(_client: object) -> list[VLAN]:
                call_count["n"] += 1
                return existing_vlans if call_count["n"] == 1 else after_vlans

            mock_get_vlans.side_effect = _side_effect
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__delete_vlan(100, apply=True)

        assert result["result"] == "deleted"
        assert result["vlan_id"] == 100
        assert result["verified"] is True

        # Config set should include "no vlan 100"
        client.send_config_set.assert_awaited_once()
        commands = client.send_config_set.call_args[0][0]
        assert "no vlan 100" in commands

    @pytest.mark.asyncio
    async def test_vlan_1_deletion_refused(self, _enable_writes: None) -> None:
        """Cannot delete VLAN 1 (default)."""
        result = await cisco__interfaces__delete_vlan(1, apply=True)
        assert "error" in result
        assert "VLAN 1" in result["error"] or "default" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_warning_when_ports_assigned(self, _enable_writes: None) -> None:
        """Deleting a VLAN with assigned ports includes a warning."""
        client = _make_mock_client()
        existing_vlans = _make_vlans(
            (1, "default", []),
            (60, "IoT", ["gi5", "gi6", "gi7"]),
        )
        after_vlans = _make_vlans((1, "default", []))

        call_count = {"n": 0}

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans") as mock_get_vlans,
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            def _side_effect(_client: object) -> list[VLAN]:
                call_count["n"] += 1
                return existing_vlans if call_count["n"] == 1 else after_vlans

            mock_get_vlans.side_effect = _side_effect
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__delete_vlan(60, apply=True)

        assert result["result"] == "deleted"
        assert "warning" in result
        assert "gi5" in result["warning"]
        assert "gi6" in result["warning"]

    @pytest.mark.asyncio
    async def test_vlan_doesnt_exist_error(self, _enable_writes: None) -> None:
        """Deleting a non-existent VLAN returns error."""
        client = _make_mock_client()
        existing_vlans = _make_vlans((1, "default", []))

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans", return_value=existing_vlans),
        ):
            result = await cisco__interfaces__delete_vlan(999, apply=True)

        assert "error" in result
        assert "does not exist" in result["error"]
        client.send_config_set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_write_gate_enforcement(self) -> None:
        """Write gate blocks delete without env var."""
        with patch.dict(os.environ, {}, clear=True), pytest.raises(WriteGateError):
            await cisco__interfaces__delete_vlan(100, apply=True)

    @pytest.mark.asyncio
    async def test_write_gate_blocks_without_apply(self, _enable_writes: None) -> None:
        """Write gate blocks delete without apply=True."""
        with pytest.raises(WriteGateError):
            await cisco__interfaces__delete_vlan(100, apply=False)


# ===========================================================================
# cisco__interfaces__set_port_vlan
# ===========================================================================


class TestSetPortVlan:
    """Tests for cisco__interfaces__set_port_vlan."""

    @pytest.mark.asyncio
    async def test_happy_path_sets_access_vlan(self, _enable_writes: None) -> None:
        """Set gi3 to VLAN 10 -- verifies CLI commands and result."""
        client = _make_mock_client(
            switchport_output=load_fixture("show_switchport_access.txt"),
        )
        existing_vlans = _make_vlans(
            (1, "default", []),
            (10, "Admin", ["gi3"]),
        )

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            if command.startswith("show interfaces switchport"):
                return load_fixture("show_switchport_access.txt")
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans", return_value=existing_vlans),
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_port_vlan("gi3", 10, apply=True)

        assert result["result"] == "configured"
        assert result["port"] == "gi3"
        assert result["vlan_id"] == 10
        assert result["verified"] is True

        # Verify CLI commands
        client.send_config_set.assert_awaited_once()
        commands = client.send_config_set.call_args[0][0]
        assert "interface gi3" in commands
        assert "switchport mode access" in commands
        assert "switchport access vlan 10" in commands

    @pytest.mark.asyncio
    async def test_invalid_port_format_rejected(self, _enable_writes: None) -> None:
        """Invalid port format (e.g. 'eth1', 'x') returns error."""
        for bad_port in ("eth1", "x", "ge1", "123", "", "gi-1"):
            result = await cisco__interfaces__set_port_vlan(bad_port, 10, apply=True)
            assert "error" in result, f"Expected error for port: {bad_port!r}"
            assert "Invalid port" in result["error"]

    @pytest.mark.asyncio
    async def test_vlan_doesnt_exist_rejected(self, _enable_writes: None) -> None:
        """Setting a port to a non-existent VLAN returns error."""
        client = _make_mock_client()
        existing_vlans = _make_vlans((1, "default", []))

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans", return_value=existing_vlans),
        ):
            result = await cisco__interfaces__set_port_vlan("gi3", 999, apply=True)

        assert "error" in result
        assert "does not exist" in result["error"]
        client.send_config_set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_write_gate_enforcement(self) -> None:
        """Write gate blocks without env var."""
        with patch.dict(os.environ, {}, clear=True), pytest.raises(WriteGateError):
            await cisco__interfaces__set_port_vlan("gi3", 10, apply=True)

    @pytest.mark.asyncio
    async def test_write_gate_blocks_without_apply(self, _enable_writes: None) -> None:
        """Write gate blocks without apply=True."""
        with pytest.raises(WriteGateError):
            await cisco__interfaces__set_port_vlan("gi3", 10, apply=False)

    @pytest.mark.asyncio
    async def test_verification_with_switchport(self, _enable_writes: None) -> None:
        """After setting port VLAN, switchport output is parsed for verification."""
        client = _make_mock_client()
        existing_vlans = _make_vlans(
            (1, "default", []),
            (10, "Admin", []),
        )

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            if command.startswith("show interfaces switchport"):
                return load_fixture("show_switchport_access.txt")
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans", return_value=existing_vlans),
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_port_vlan("gi3", 10, apply=True)

        assert result["verified"] is True
        # send_command should have been called with switchport query
        switchport_calls = [
            c
            for c in client.send_command.call_args_list
            if "show interfaces switchport" in str(c)
        ]
        assert len(switchport_calls) >= 1

    @pytest.mark.asyncio
    async def test_vlan_id_out_of_range(self, _enable_writes: None) -> None:
        """VLAN IDs outside 1-4094 are rejected."""
        for bad_id in (0, -1, 4095, 5000):
            result = await cisco__interfaces__set_port_vlan("gi3", bad_id, apply=True)
            assert "error" in result, f"Expected error for VLAN {bad_id}"

    @pytest.mark.asyncio
    async def test_switchport_parse_error_returns_error(self, _enable_writes: None) -> None:
        """ValueError from switchport parsing returns error dict."""
        client = _make_mock_client()
        existing_vlans = _make_vlans(
            (1, "default", []),
            (10, "Admin", []),
        )

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            if command.startswith("show interfaces switchport"):
                return "garbage output with no port info"
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write._get_existing_vlans", return_value=existing_vlans),
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_port_vlan("gi3", 10, apply=True)

        assert "error" in result
        assert "verify" in result["error"].lower() or "Failed" in result["error"]


# ===========================================================================
# cisco__interfaces__set_trunk_port
# ===========================================================================


class TestSetTrunkPort:
    """Tests for cisco__interfaces__set_trunk_port."""

    @pytest.mark.asyncio
    async def test_happy_path_add_operation(self, _enable_writes: None) -> None:
        """Configure trunk with operation='add'."""
        client = _make_mock_client()

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            if command.startswith("show interfaces switchport"):
                return load_fixture("show_switchport_trunk.txt")
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_trunk_port(
                "gi24", "10,20,30", operation="add", apply=True,
            )

        assert result["result"] == "configured"
        assert result["port"] == "gi24"
        assert result["operation"] == "add"
        assert result["verified"] is True

        commands = client.send_config_set.call_args[0][0]
        assert "interface gi24" in commands
        assert "switchport mode trunk" in commands
        assert "switchport trunk allowed vlan add 10,20,30" in commands

    @pytest.mark.asyncio
    async def test_remove_operation(self, _enable_writes: None) -> None:
        """Configure trunk with operation='remove'."""
        client = _make_mock_client()

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            if command.startswith("show interfaces switchport"):
                return load_fixture("show_switchport_trunk.txt")
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_trunk_port(
                "gi24", "70,80", operation="remove", apply=True,
            )

        assert result["result"] == "configured"
        assert result["operation"] == "remove"

        commands = client.send_config_set.call_args[0][0]
        assert "switchport trunk allowed vlan remove 70,80" in commands

    @pytest.mark.asyncio
    async def test_replace_operation(self, _enable_writes: None) -> None:
        """Configure trunk with operation='replace'."""
        client = _make_mock_client()

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            if command.startswith("show interfaces switchport"):
                return load_fixture("show_switchport_trunk.txt")
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_trunk_port(
                "gi24", "10,20", operation="replace", apply=True,
            )

        assert result["result"] == "configured"
        assert result["operation"] == "replace"

        commands = client.send_config_set.call_args[0][0]
        assert "switchport trunk allowed vlan 10,20" in commands

    @pytest.mark.asyncio
    async def test_invalid_operation_rejected(self, _enable_writes: None) -> None:
        """Invalid operation (e.g. 'update') returns error."""
        result = await cisco__interfaces__set_trunk_port(
            "gi24", "10,20", operation="update", apply=True,
        )
        assert "error" in result
        assert "Invalid operation" in result["error"]

    @pytest.mark.asyncio
    async def test_native_vlan_setting(self, _enable_writes: None) -> None:
        """Native VLAN is included in commands when provided."""
        client = _make_mock_client()

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            if command.startswith("show interfaces switchport"):
                return load_fixture("show_switchport_trunk.txt")
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_trunk_port(
                "gi24", "10,20", operation="add", native_vlan=10, apply=True,
            )

        assert result["native_vlan"] == 10
        commands = client.send_config_set.call_args[0][0]
        assert "switchport trunk native vlan 10" in commands

    @pytest.mark.asyncio
    async def test_invalid_port_rejected(self, _enable_writes: None) -> None:
        """Invalid port format returns error."""
        result = await cisco__interfaces__set_trunk_port(
            "eth1", "10,20", operation="add", apply=True,
        )
        assert "error" in result
        assert "Invalid port" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_vlan_list_non_numeric(self, _enable_writes: None) -> None:
        """Non-numeric VLAN list returns error."""
        result = await cisco__interfaces__set_trunk_port(
            "gi24", "abc,def", operation="add", apply=True,
        )
        assert "error" in result
        assert "Invalid VLAN list" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_vlan_list_out_of_range(self, _enable_writes: None) -> None:
        """VLAN IDs out of range (>4094) return error."""
        result = await cisco__interfaces__set_trunk_port(
            "gi24", "10,5000", operation="add", apply=True,
        )
        assert "error" in result
        assert "out of range" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_vlan_list_rejected(self, _enable_writes: None) -> None:
        """Empty VLAN list returns error."""
        result = await cisco__interfaces__set_trunk_port(
            "gi24", "", operation="add", apply=True,
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_native_vlan_out_of_range(self, _enable_writes: None) -> None:
        """Native VLAN out of range returns error."""
        result = await cisco__interfaces__set_trunk_port(
            "gi24", "10,20", operation="add", native_vlan=5000, apply=True,
        )
        assert "error" in result
        assert "out of range" in result["error"]

    @pytest.mark.asyncio
    async def test_write_gate_enforcement(self) -> None:
        """Write gate blocks without env var."""
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError),
        ):
            await cisco__interfaces__set_trunk_port(
                "gi24", "10,20", operation="add", apply=True,
            )

    @pytest.mark.asyncio
    async def test_write_gate_blocks_without_apply(self, _enable_writes: None) -> None:
        """Write gate blocks without apply=True."""
        with pytest.raises(WriteGateError):
            await cisco__interfaces__set_trunk_port(
                "gi24", "10,20", operation="add", apply=False,
            )

    @pytest.mark.asyncio
    async def test_network_error_handling(self, _enable_writes: None) -> None:
        """NetworkError during trunk config returns error dict."""
        client = AsyncMock()
        client.connect = AsyncMock(side_effect=NetworkError("timeout"))

        with patch("cisco.tools.vlan_write.get_client", return_value=client):
            result = await cisco__interfaces__set_trunk_port(
                "gi24", "10,20", operation="add", apply=True,
            )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_switchport_parse_error_returns_error(self, _enable_writes: None) -> None:
        """ValueError from switchport parsing returns error dict."""
        client = _make_mock_client()

        async def _mock_send(command: str) -> str:
            if command == "show running-config":
                return "hostname test"
            if command.startswith("show interfaces switchport"):
                return "invalid switchport output"
            return ""

        client.send_command = AsyncMock(side_effect=_mock_send)

        with (
            patch("cisco.tools.vlan_write.get_client", return_value=client),
            patch("cisco.tools.vlan_write.get_config_backup") as mock_backup,
        ):
            mock_backup_instance = MagicMock()
            mock_backup_instance.capture = AsyncMock()
            mock_backup.return_value = mock_backup_instance

            result = await cisco__interfaces__set_trunk_port(
                "gi24", "10,20", operation="add", apply=True,
            )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_auth_error_handling(self, _enable_writes: None) -> None:
        """AuthenticationError returns error dict with hint."""
        with patch(
            "cisco.tools.vlan_write.get_client",
            side_effect=AuthenticationError("bad password", env_var="CISCO_SSH_PASSWORD"),
        ):
            result = await cisco__interfaces__set_trunk_port(
                "gi24", "10,20", operation="add", apply=True,
            )

        assert "error" in result
        assert "hint" in result
