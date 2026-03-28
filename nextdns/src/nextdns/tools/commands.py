# SPDX-License-Identifier: MIT
"""High-level command tools -- operator-facing MCP tools that compose agents.

Commands are the primary interface operators use to interact with the NextDNS
plugin.  Each command maps to a verb in the ``nextdns`` command namespace
and composes one or more agents/tools into a cohesive workflow.

Commands return formatted markdown strings (via OX formatters) -- never raw
dicts.  Write operations are gated at the underlying tool level; the
``manage`` command checks the gate proactively so it can return a plan-only
message when writes are disabled or ``--apply`` is not set.
"""

from __future__ import annotations

import logging
from typing import Any

from nextdns.agents.analytics import analytics_dashboard
from nextdns.agents.logs import investigate_device
from nextdns.agents.profiles import profile_detail, profile_list_summary
from nextdns.agents.security_posture import security_audit, security_compare
from nextdns.output import LogEntry as OXLogEntry
from nextdns.output import format_log_entries
from nextdns.safety import check_write_enabled, describe_write_status
from nextdns.server import mcp_server
from nextdns.tools.logs import (
    nextdns__logs__download,
    nextdns__logs__search,
    nextdns__logs__stream,
)
from nextdns.tools.profile_writes import (
    nextdns__profiles__add_allowlist_entry,
    nextdns__profiles__add_denylist_entry,
    nextdns__profiles__remove_allowlist_entry,
    nextdns__profiles__remove_denylist_entry,
    nextdns__profiles__update_security,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatting helpers for log results
# ---------------------------------------------------------------------------


def _format_log_entries_from_raw(entries: list[dict[str, Any]]) -> str:
    """Convert raw log entry dicts to OX-formatted log table."""
    ox_entries = [
        OXLogEntry(
            timestamp=e.get("timestamp", ""),
            domain=e.get("domain", ""),
            status=e.get("status", "default"),
            device=_device_name(e),
            protocol=e.get("protocol", ""),
        )
        for e in entries
    ]
    return format_log_entries(ox_entries)


def _device_name(entry: dict[str, Any]) -> str:
    """Extract a human-readable device name from a log entry dict."""
    device = entry.get("device")
    if isinstance(device, dict):
        name = device.get("name") or device.get("id") or ""
        return str(name)
    return str(device) if device else ""


def format_download_result(result: dict[str, Any]) -> str:
    """Format a log download result as a markdown report."""
    lines: list[str] = [
        "## Log Download",
        "",
    ]

    url = result.get("download_url", "")
    if url:
        lines.append(f"**Download URL:** {url}")
    else:
        lines.append("**Download URL:** Not available")

    if "time_range" in result:
        tr = result["time_range"]
        lines.append(f"**From:** {tr.get('from', 'N/A')}")
        lines.append(f"**To:** {tr.get('to', 'N/A')}")

    if "warning" in result:
        lines.append("")
        lines.append(f"[!] **Warning:** {result['warning']}")

    lines.append("")
    return "\n".join(lines)


def format_stream_result(result: dict[str, Any]) -> str:
    """Format a log stream result as a markdown report."""
    entries = result.get("entries", [])
    count = result.get("count", 0)
    duration = result.get("duration_seconds", 0)
    polls = result.get("polls", 0)

    lines: list[str] = [
        "## Live Log Stream",
        "",
        f"**Duration:** {duration}s ({polls} polls)",
        f"**Entries collected:** {count}",
        "",
    ]

    if result.get("polling_note"):
        lines.append(f"*Note: {result['polling_note']}*")
        lines.append("")

    if entries:
        lines.append(_format_log_entries_from_raw(entries[:50]))

    return "\n".join(lines)


def format_log_search_result(result: dict[str, Any]) -> str:
    """Format a log search result as a markdown report."""
    entries = result.get("entries", [])
    count = result.get("count", 0)

    lines: list[str] = [
        "## Log Search Results",
        "",
        f"**Entries found:** {count}",
    ]

    if result.get("next_cursor"):
        lines.append("**More results available** (pagination cursor present)")

    lines.append("")

    if entries:
        lines.append(_format_log_entries_from_raw(entries))
    else:
        lines.append("No matching log entries found.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Task 248: nextdns profiles command
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def nextdns__cmd__profiles(
    detail_id: str | None = None,
) -> str:
    """List NextDNS profiles or show detail for a specific profile.

    Without arguments: list all profiles with key indicators.
    With detail_id: show full settings for that profile.

    Args:
        detail_id: Optional profile ID to show detailed settings for.
    """
    if detail_id:
        logger.info(
            "Command: profiles detail for %s",
            detail_id,
            extra={"component": "commands"},
        )
        return await profile_detail(detail_id)

    logger.info(
        "Command: profiles list",
        extra={"component": "commands"},
    )
    return await profile_list_summary()


# ---------------------------------------------------------------------------
# Task 249: nextdns analytics command
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def nextdns__cmd__analytics(
    profile_id: str,
    from_time: str | None = None,
    to_time: str | None = None,
    device: str | None = None,
) -> str:
    """Show DNS analytics dashboard for a NextDNS profile.

    Provides query volume, top blocked domains, device activity,
    protocol breakdown, and encryption health.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        from_time: Start of the date range (ISO 8601 or relative like "-7d").
        to_time: End of the date range.
        device: Filter analytics by device ID.
    """
    logger.info(
        "Command: analytics dashboard for profile %s",
        profile_id,
        extra={"component": "commands"},
    )
    return await analytics_dashboard(profile_id, from_time, to_time)


# ---------------------------------------------------------------------------
# Task 250: nextdns audit command
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def nextdns__cmd__audit(
    profile_id: str | None = None,
    compare_a: str | None = None,
    compare_b: str | None = None,
) -> str:
    """Audit security posture or compare two profiles.

    No args: audit all profiles.
    profile_id: audit a single profile.
    compare_a + compare_b: side-by-side diff of two profiles.

    Args:
        profile_id: Audit a single profile (optional).
        compare_a: First profile ID for comparison.
        compare_b: Second profile ID for comparison.
    """
    if compare_a and compare_b:
        logger.info(
            "Command: security compare %s vs %s",
            compare_a,
            compare_b,
            extra={"component": "commands"},
        )
        return await security_compare(compare_a, compare_b)

    logger.info(
        "Command: security audit (profile_id=%s)",
        profile_id,
        extra={"component": "commands"},
    )
    return await security_audit(profile_id)


# ---------------------------------------------------------------------------
# Task 251: nextdns logs command
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def nextdns__cmd__logs(
    profile_id: str,
    domain: str | None = None,
    status: str | None = None,
    device: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
    stream: bool = False,
    download: bool = False,
    limit: int = 50,
) -> str:
    """Search, stream, or download DNS query logs.

    Default: search recent logs with optional filters.
    stream=True: live monitoring via polling.
    download=True: get bulk download URL.
    device (without stream/download): investigate a specific device.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        domain: Filter by domain substring (partial match).
        status: Filter by status: "default", "blocked", "allowed", or "error".
        device: Filter by device ID.
        from_time: Start time (ISO 8601, Unix timestamp, or relative like "-6h").
        to_time: End time.
        stream: Enable live log streaming via polling.
        download: Get a bulk download URL instead of inline results.
        limit: Max results for search mode (default 50).
    """
    if download:
        logger.info(
            "Command: logs download for profile %s",
            profile_id,
            extra={"component": "commands"},
        )
        result = await nextdns__logs__download(profile_id, from_time, to_time)
        return format_download_result(result)

    if stream:
        logger.info(
            "Command: logs stream for profile %s",
            profile_id,
            extra={"component": "commands"},
        )
        result = await nextdns__logs__stream(
            profile_id, device=device, status=status, domain=domain,
        )
        return format_stream_result(result)

    # Device investigation mode
    if device and not domain and not status:
        logger.info(
            "Command: logs investigate device %s for profile %s",
            device,
            profile_id,
            extra={"component": "commands"},
        )
        return await investigate_device(profile_id, device)

    # Default: search
    logger.info(
        "Command: logs search for profile %s",
        profile_id,
        extra={"component": "commands"},
    )
    result = await nextdns__logs__search(
        profile_id,
        domain=domain,
        status=status,
        device=device,
        from_time=from_time,
        to_time=to_time,
        limit=limit,
    )
    return format_log_search_result(result)


# ---------------------------------------------------------------------------
# Task 252: nextdns manage command
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def nextdns__cmd__manage(
    profile_id: str,
    add_deny: str | None = None,
    remove_deny: str | None = None,
    add_allow: str | None = None,
    remove_allow: str | None = None,
    enable_all_security: bool = False,
    *,
    apply: bool = False,
) -> str:
    """Manage a NextDNS profile configuration.

    Provides quick actions for common profile management tasks.
    All modifications require --apply flag (write-gated).

    Without action flags: show current profile summary.
    With action flags: perform the specified action.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        add_deny: Domain to add to the deny list.
        remove_deny: Domain to remove from the deny list.
        add_allow: Domain to add to the allow list.
        remove_allow: Domain to remove from the allow list.
        enable_all_security: Enable all 12 security toggles.
        apply: Must be True to execute write operations (safety gate).
    """
    # Determine if any action is requested
    has_action = any([
        add_deny,
        remove_deny,
        add_allow,
        remove_allow,
        enable_all_security,
    ])

    # No action: show profile summary
    if not has_action:
        logger.info(
            "Command: manage profile %s (show summary)",
            profile_id,
            extra={"component": "commands"},
        )
        return await profile_detail(profile_id)

    # Action requested but apply not set: return plan-only message
    if not apply:
        actions = _describe_planned_actions(
            add_deny=add_deny,
            remove_deny=remove_deny,
            add_allow=add_allow,
            remove_allow=remove_allow,
            enable_all_security=enable_all_security,
        )

        lines: list[str] = [
            "## Manage Profile: Plan Only",
            "",
            f"**Profile:** {profile_id}",
            "",
            "### Planned Actions",
            "",
        ]
        for action in actions:
            lines.append(f"- {action}")
        lines.append("")
        lines.append(f"**Write status:** {describe_write_status()}")
        lines.append("")
        lines.append("Re-run with `apply=True` to execute these changes.")
        lines.append("")
        return "\n".join(lines)

    # Action requested with apply: check write gate proactively
    if not check_write_enabled():
        lines = [
            "## Manage Profile: Blocked",
            "",
            f"**Profile:** {profile_id}",
            "",
            f"**Write status:** {describe_write_status()}",
            "",
            "Cannot execute changes: write operations are disabled.",
            "Set `NEXTDNS_WRITE_ENABLED=true` in the environment to enable.",
            "",
        ]
        return "\n".join(lines)

    # Execute the requested actions
    logger.info(
        "Command: manage profile %s (apply=True)",
        profile_id,
        extra={"component": "commands"},
    )

    results: list[str] = []

    if add_deny:
        await nextdns__profiles__add_denylist_entry(
            profile_id, add_deny, apply=True,
        )
        results.append(f"Added `{add_deny}` to deny list")

    if remove_deny:
        await nextdns__profiles__remove_denylist_entry(
            profile_id, remove_deny, apply=True,
        )
        results.append(f"Removed `{remove_deny}` from deny list")

    if add_allow:
        await nextdns__profiles__add_allowlist_entry(
            profile_id, add_allow, apply=True,
        )
        results.append(f"Added `{add_allow}` to allow list")

    if remove_allow:
        await nextdns__profiles__remove_allowlist_entry(
            profile_id, remove_allow, apply=True,
        )
        results.append(f"Removed `{remove_allow}` from allow list")

    if enable_all_security:
        all_security = {
            "threat_intelligence_feeds": True,
            "ai_threat_detection": True,
            "google_safe_browsing": True,
            "cryptojacking": True,
            "dns_rebinding": True,
            "idn_homographs": True,
            "typosquatting": True,
            "dga": True,
            "nrd": True,
            "ddns": True,
            "parking": True,
            "csam": True,
        }
        await nextdns__profiles__update_security(
            profile_id, **all_security, apply=True,
        )
        results.append("Enabled all 12 security toggles")

    lines = [
        "## Manage Profile: Changes Applied",
        "",
        f"**Profile:** {profile_id}",
        "",
        "### Results",
        "",
    ]
    for r in results:
        lines.append(f"- {r}")
    lines.append("")

    return "\n".join(lines)


def _describe_planned_actions(
    *,
    add_deny: str | None = None,
    remove_deny: str | None = None,
    add_allow: str | None = None,
    remove_allow: str | None = None,
    enable_all_security: bool = False,
) -> list[str]:
    """Build a list of human-readable action descriptions for plan mode."""
    actions: list[str] = []
    if add_deny:
        actions.append(f"Add `{add_deny}` to deny list")
    if remove_deny:
        actions.append(f"Remove `{remove_deny}` from deny list")
    if add_allow:
        actions.append(f"Add `{add_allow}` to allow list")
    if remove_allow:
        actions.append(f"Remove `{remove_allow}` from allow list")
    if enable_all_security:
        actions.append("Enable all 12 security toggles")
    return actions
