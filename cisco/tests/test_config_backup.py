"""Tests for the config backup utility.

Covers: ConfigBackup.capture, get_last_backup, max_backups enforcement,
diff_with_current, empty backup store, backup_count, clear.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cisco.ssh.config_backup import ConfigBackup, ConfigSnapshot, get_config_backup

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_ssh_client(config_text: str = "hostname switch1\n") -> AsyncMock:
    """Build a mock SSH client that returns the given config text."""
    client = AsyncMock()

    async def _send_command(command: str) -> str:
        if command == "show running-config":
            return config_text
        return ""

    client.send_command = AsyncMock(side_effect=_send_command)
    return client


# ===========================================================================
# ConfigSnapshot
# ===========================================================================


class TestConfigSnapshot:
    """Basic sanity checks on the dataclass."""

    def test_snapshot_fields(self) -> None:
        snap = ConfigSnapshot(config="hostname test", timestamp=1000.0, label="test")
        assert snap.config == "hostname test"
        assert snap.timestamp == 1000.0
        assert snap.label == "test"


# ===========================================================================
# ConfigBackup.capture
# ===========================================================================


class TestCapture:
    """Tests for ConfigBackup.capture()."""

    @pytest.mark.asyncio
    async def test_capture_stores_snapshot_with_timestamp(self) -> None:
        """capture() should store a snapshot with a real timestamp."""
        backup = ConfigBackup(max_backups=5)
        client = _make_mock_ssh_client("hostname switch1\nvlan 10\n")

        snapshot = await backup.capture(client, label="pre-test")

        assert isinstance(snapshot, ConfigSnapshot)
        assert snapshot.label == "pre-test"
        assert "hostname switch1" in snapshot.config
        assert "vlan 10" in snapshot.config
        assert snapshot.timestamp > 0
        assert backup.backup_count == 1

    @pytest.mark.asyncio
    async def test_capture_calls_show_running_config(self) -> None:
        """capture() must call send_command with 'show running-config'."""
        backup = ConfigBackup()
        client = _make_mock_ssh_client()

        await backup.capture(client, label="test")

        client.send_command.assert_awaited_once_with("show running-config")

    @pytest.mark.asyncio
    async def test_multiple_captures_stored_in_order(self) -> None:
        """Multiple captures should be stored in chronological order."""
        backup = ConfigBackup(max_backups=10)
        client = _make_mock_ssh_client()

        await backup.capture(client, label="first")
        await backup.capture(client, label="second")
        await backup.capture(client, label="third")

        assert backup.backup_count == 3
        last = backup.get_last_backup()
        assert last is not None
        assert last.label == "third"


# ===========================================================================
# ConfigBackup.get_last_backup
# ===========================================================================


class TestGetLastBackup:
    """Tests for ConfigBackup.get_last_backup()."""

    def test_empty_store_returns_none(self) -> None:
        """get_last_backup() returns None when no backups exist."""
        backup = ConfigBackup()
        assert backup.get_last_backup() is None

    @pytest.mark.asyncio
    async def test_returns_most_recent(self) -> None:
        """get_last_backup() returns the most recently captured snapshot."""
        backup = ConfigBackup(max_backups=5)
        client = _make_mock_ssh_client()

        await backup.capture(client, label="first")
        await backup.capture(client, label="second")

        last = backup.get_last_backup()
        assert last is not None
        assert last.label == "second"


# ===========================================================================
# Max backups enforcement
# ===========================================================================


class TestMaxBackups:
    """Tests for bounded deque -- oldest backups are dropped."""

    @pytest.mark.asyncio
    async def test_max_backups_enforced(self) -> None:
        """When max_backups is exceeded, oldest snapshot is dropped."""
        max_backups = 3
        backup = ConfigBackup(max_backups=max_backups)
        client = _make_mock_ssh_client()

        # Capture 5 backups (more than max of 3)
        for i in range(5):
            await backup.capture(client, label=f"backup-{i}")

        assert backup.backup_count == max_backups
        # The last 3 should remain
        last = backup.get_last_backup()
        assert last is not None
        assert last.label == "backup-4"

    @pytest.mark.asyncio
    async def test_max_backups_of_one(self) -> None:
        """With max_backups=1, only the latest snapshot is retained."""
        backup = ConfigBackup(max_backups=1)
        client = _make_mock_ssh_client()

        await backup.capture(client, label="first")
        await backup.capture(client, label="second")

        assert backup.backup_count == 1
        last = backup.get_last_backup()
        assert last is not None
        assert last.label == "second"


# ===========================================================================
# ConfigBackup.diff_with_current
# ===========================================================================


class TestDiffWithCurrent:
    """Tests for ConfigBackup.diff_with_current()."""

    @pytest.mark.asyncio
    async def test_produces_meaningful_diff(self) -> None:
        """diff_with_current() shows differences between backup and current."""
        backup = ConfigBackup()

        # Capture the "before" state
        before_client = _make_mock_ssh_client("hostname switch1\nvlan 10\n")
        await backup.capture(before_client, label="before-change")

        # Current state is different (added vlan 20)
        after_client = _make_mock_ssh_client("hostname switch1\nvlan 10\nvlan 20\n")

        diff = await backup.diff_with_current(after_client)

        assert "vlan 20" in diff
        assert "backup" in diff.lower() or "---" in diff
        assert "current" in diff.lower() or "+++" in diff

    @pytest.mark.asyncio
    async def test_empty_diff_when_no_changes(self) -> None:
        """diff_with_current() returns empty string if configs are identical."""
        backup = ConfigBackup()

        config = "hostname switch1\nvlan 10\n"
        client = _make_mock_ssh_client(config)
        await backup.capture(client, label="snapshot")

        diff = await backup.diff_with_current(client)
        assert diff == ""

    @pytest.mark.asyncio
    async def test_empty_diff_when_no_backup_exists(self) -> None:
        """diff_with_current() returns empty string if no backup exists."""
        backup = ConfigBackup()
        client = _make_mock_ssh_client()

        diff = await backup.diff_with_current(client)
        assert diff == ""

    @pytest.mark.asyncio
    async def test_diff_calls_show_running_config(self) -> None:
        """diff_with_current() calls send_command for current config."""
        backup = ConfigBackup()
        client = _make_mock_ssh_client("hostname old\n")
        await backup.capture(client, label="snap")

        new_client = _make_mock_ssh_client("hostname new\n")
        await backup.diff_with_current(new_client)

        new_client.send_command.assert_awaited_once_with("show running-config")


# ===========================================================================
# ConfigBackup.backup_count and clear
# ===========================================================================


class TestBackupCountAndClear:
    """Tests for backup_count property and clear()."""

    def test_backup_count_starts_at_zero(self) -> None:
        backup = ConfigBackup()
        assert backup.backup_count == 0

    @pytest.mark.asyncio
    async def test_backup_count_increments(self) -> None:
        backup = ConfigBackup()
        client = _make_mock_ssh_client()

        await backup.capture(client, label="a")
        assert backup.backup_count == 1
        await backup.capture(client, label="b")
        assert backup.backup_count == 2

    @pytest.mark.asyncio
    async def test_clear_removes_all(self) -> None:
        backup = ConfigBackup()
        client = _make_mock_ssh_client()

        await backup.capture(client, label="a")
        await backup.capture(client, label="b")
        assert backup.backup_count == 2

        backup.clear()
        assert backup.backup_count == 0
        assert backup.get_last_backup() is None


# ===========================================================================
# Module-level singleton
# ===========================================================================


class TestModuleSingleton:
    """Tests for get_config_backup() module-level singleton."""

    def test_get_config_backup_returns_same_instance(self) -> None:
        """get_config_backup() always returns the same instance."""
        a = get_config_backup()
        b = get_config_backup()
        assert a is b

    def test_get_config_backup_returns_config_backup(self) -> None:
        assert isinstance(get_config_backup(), ConfigBackup)
