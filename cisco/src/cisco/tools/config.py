# SPDX-License-Identifier: MIT
"""Configuration management tools for Cisco SG-300.

Provides running/startup config retrieval and drift detection
via SSH CLI commands.
"""

from __future__ import annotations

import difflib
import logging
from typing import Any

from cisco.cache import CacheTTL, TTLCache
from cisco.errors import AuthenticationError, NetworkError, SSHCommandError
from cisco.safety import write_gate
from cisco.server import mcp_server
from cisco.ssh.client import get_client
from cisco.ssh.config_backup import get_config_backup

logger = logging.getLogger(__name__)

_cache = TTLCache(max_size=10, default_ttl=600.0)


@mcp_server.tool()
async def cisco__config__get_running_config() -> str:
    """Get the current running configuration.

    Returns the full running-config output as a string.
    """
    try:
        client = get_client()
    except AuthenticationError as exc:
        return f"Error: {exc}\nHint: {exc.retry_hint}"

    async def _fetch() -> str:
        await client.connect()
        return await client.send_command("show running-config")

    try:
        result: str = await _cache.get_or_fetch(
            "config:running",
            fetcher=_fetch,
            ttl=CacheTTL.RUNNING_CONFIG,
        )
        return result
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to get running config: %s", exc)
        return f"Error: {exc}"


@mcp_server.tool()
async def cisco__config__get_startup_config() -> str:
    """Get the startup (saved) configuration.

    Returns the full startup-config output as a string.
    """
    try:
        client = get_client()
    except AuthenticationError as exc:
        return f"Error: {exc}\nHint: {exc.retry_hint}"

    async def _fetch() -> str:
        await client.connect()
        return await client.send_command("show startup-config")

    try:
        result: str = await _cache.get_or_fetch(
            "config:startup",
            fetcher=_fetch,
            ttl=CacheTTL.RUNNING_CONFIG,
        )
        return result
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to get startup config: %s", exc)
        return f"Error: {exc}"


@mcp_server.tool()
async def cisco__config__detect_drift() -> dict[str, Any]:
    """Compare running vs startup config to detect unsaved changes.

    Returns a dict with keys:
    - has_drift: bool -- whether differences were found
    - added_lines: list[str] -- lines in running but not startup
    - removed_lines: list[str] -- lines in startup but not running
    - summary: str -- human-readable markdown summary
    """
    try:
        client = get_client()
    except AuthenticationError as exc:
        return {"error": str(exc), "hint": exc.retry_hint}

    try:
        await client.connect()
        running = await client.send_command("show running-config")
        startup = await client.send_command("show startup-config")

        # Normalize configs for comparison: strip trailing whitespace,
        # filter out lines that are timestamps or non-config noise
        running_lines = _normalize_config(running)
        startup_lines = _normalize_config(startup)

        # Compute unified diff
        diff = list(
            difflib.unified_diff(
                startup_lines,
                running_lines,
                fromfile="startup-config",
                tofile="running-config",
                lineterm="",
            )
        )

        added_lines = [
            line[1:] for line in diff
            if line.startswith("+") and not line.startswith("+++")
        ]
        removed_lines = [
            line[1:] for line in diff
            if line.startswith("-") and not line.startswith("---")
        ]

        has_drift = len(added_lines) > 0 or len(removed_lines) > 0

        # Build human-readable summary
        if has_drift:
            summary_parts = [
                "## Configuration Drift Detected",
                "",
                f"**Added lines (in running, not startup):** {len(added_lines)}",
                f"**Removed lines (in startup, not running):** {len(removed_lines)}",
                "",
            ]

            if added_lines:
                summary_parts.append("### Added to running-config")
                summary_parts.append("```")
                summary_parts.extend(added_lines[:50])
                if len(added_lines) > 50:
                    summary_parts.append(
                        f"... and {len(added_lines) - 50} more lines"
                    )
                summary_parts.append("```")

            if removed_lines:
                summary_parts.append("")
                summary_parts.append("### Removed from running-config")
                summary_parts.append("```")
                summary_parts.extend(removed_lines[:50])
                if len(removed_lines) > 50:
                    summary_parts.append(
                        f"... and {len(removed_lines) - 50} more lines"
                    )
                summary_parts.append("```")

            summary_parts.append("")
            summary_parts.append(
                "**Action:** Run `write memory` to save "
                "running-config to startup."
            )
            summary = "\n".join(summary_parts)
        else:
            summary = (
                "## No Configuration Drift\n\n"
                "Running config matches startup config. No unsaved changes."
            )

        return {
            "has_drift": has_drift,
            "added_lines": added_lines,
            "removed_lines": removed_lines,
            "summary": summary,
        }

    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to detect config drift: %s", exc)
        return {"error": str(exc), "hint": getattr(exc, "retry_hint", None)}


@mcp_server.tool()
@write_gate("CISCO")
async def cisco__config__save_config(*, apply: bool = False) -> dict[str, Any]:
    """Persist running-config to startup-config (write memory).

    Captures the current startup-config before saving, then compares
    old vs new startup-config to report what changed.

    Parameters
    ----------
    apply:
        Must be ``True`` to execute the write.

    Returns
    -------
    dict
        Result with keys: result, changes_count, diff_summary.
    """
    try:
        client = get_client()
    except AuthenticationError as exc:
        return {"error": str(exc), "hint": exc.retry_hint}

    try:
        await client.connect()

        # Capture current startup-config for diff
        old_startup = await client.send_command("show startup-config")

        # Capture config backup before saving
        backup = get_config_backup()
        await backup.capture(client, label="pre-save-config")

        # Save running-config to startup-config
        await client.save_config()

        # Get new startup-config
        new_startup = await client.send_command("show startup-config")

        # Diff old vs new
        old_lines = _normalize_config(old_startup)
        new_lines = _normalize_config(new_startup)

        diff = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile="old-startup-config",
                tofile="new-startup-config",
                lineterm="",
            )
        )

        added = [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]
        removed = [line[1:] for line in diff if line.startswith("-") and not line.startswith("---")]

        changes_count = len(added) + len(removed)

        if changes_count > 0:
            diff_summary = (
                f"{len(added)} line(s) added, {len(removed)} line(s) removed "
                f"in startup-config."
            )
        else:
            diff_summary = "No differences detected (running-config was already saved)."

        # Flush config cache so subsequent reads get fresh data
        await _cache.flush_by_prefix("config:")

        return {
            "result": "saved",
            "changes_count": changes_count,
            "diff_summary": diff_summary,
        }
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to save config: %s", exc)
        return {"error": str(exc), "hint": getattr(exc, "retry_hint", None)}


def _normalize_config(raw: str) -> list[str]:
    """Normalize config output for comparison.

    Strips trailing whitespace, removes empty lines, and filters out
    non-configuration lines (timestamps, banner markers, etc.) that
    would produce false-positive diffs.

    Parameters
    ----------
    raw:
        Raw config output from the switch.

    Returns
    -------
    list[str]
        Cleaned list of config lines.
    """
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.rstrip()
        # Skip empty lines
        if not stripped:
            continue
        # Skip timestamp/clock lines that differ between show commands
        if stripped.startswith("Current configuration") or stripped.startswith("!"):
            continue
        lines.append(stripped)
    return lines
