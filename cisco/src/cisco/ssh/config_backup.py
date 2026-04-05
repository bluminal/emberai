# SPDX-License-Identifier: MIT
"""Config backup utility for write safety on SG-300.

The SG-300 has no candidate config or commit/rollback model.
Config commands take effect immediately. This utility captures
the running config before writes so we can attempt manual
rollback if something goes wrong.
"""

from __future__ import annotations

import difflib
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cisco.ssh.client import CiscoSSHClient


@dataclass
class ConfigSnapshot:
    """A point-in-time capture of the running configuration."""

    config: str
    timestamp: float
    label: str  # e.g., "pre-create-vlan-100"


class ConfigBackup:
    """In-memory config backup store.

    Maintains a bounded deque of :class:`ConfigSnapshot` instances captured
    before write operations.  Older snapshots are automatically discarded
    when the deque exceeds ``max_backups``.

    Parameters
    ----------
    max_backups:
        Maximum number of snapshots to retain.  Must be positive.
    """

    def __init__(self, max_backups: int = 10) -> None:
        self._backups: deque[ConfigSnapshot] = deque(maxlen=max_backups)

    async def capture(self, ssh_client: CiscoSSHClient, label: str) -> ConfigSnapshot:
        """Capture current running-config before a write operation.

        Parameters
        ----------
        ssh_client:
            Connected SSH client to read the running config from.
        label:
            A descriptive label for this snapshot (e.g. ``"pre-create-vlan-100"``).

        Returns
        -------
        ConfigSnapshot
            The captured snapshot.
        """
        config = await ssh_client.send_command("show running-config")
        snapshot = ConfigSnapshot(config=config, timestamp=time.time(), label=label)
        self._backups.append(snapshot)
        return snapshot

    def get_last_backup(self) -> ConfigSnapshot | None:
        """Return the most recent snapshot, or ``None`` if no backups exist."""
        return self._backups[-1] if self._backups else None

    async def diff_with_current(self, ssh_client: CiscoSSHClient) -> str:
        """Diff the last backup against the current running-config.

        Parameters
        ----------
        ssh_client:
            Connected SSH client to read the current running config.

        Returns
        -------
        str
            Unified diff output.  Empty string if no backup exists or
            configs are identical.
        """
        last = self.get_last_backup()
        if last is None:
            return ""

        current = await ssh_client.send_command("show running-config")
        diff_lines = difflib.unified_diff(
            last.config.splitlines(),
            current.splitlines(),
            fromfile=f"backup ({last.label})",
            tofile="current running-config",
            lineterm="",
        )
        return "\n".join(diff_lines)

    @property
    def backup_count(self) -> int:
        """Return the number of stored backups."""
        return len(self._backups)

    def clear(self) -> None:
        """Remove all stored backups."""
        self._backups.clear()


# Module-level singleton
_backup = ConfigBackup()


def get_config_backup() -> ConfigBackup:
    """Return the module-level singleton :class:`ConfigBackup` instance."""
    return _backup
