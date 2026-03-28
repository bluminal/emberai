# SPDX-License-Identifier: MIT
"""Logs agent -- orchestrates log search and streaming for investigation.

Composes MCP tool calls with OX formatters to produce operator-ready
markdown output for DNS query log investigation, device activity analysis,
and blocked query review.
"""

from __future__ import annotations

from typing import Any

from nextdns.output import LogEntry as OXLogEntry
from nextdns.output import format_log_entries
from nextdns.tools.logs import nextdns__logs__search


async def investigate_device(
    profile_id: str,
    device_id: str,
    hours: int = 1,
) -> str:
    """Investigate what a specific device queried recently.

    Searches logs for the given device over the specified time window
    and produces a formatted report including query count, blocked count,
    top domains, and any suspicious activity flags.

    Args:
        profile_id: NextDNS profile ID.
        device_id: Device identifier to investigate.
        hours: How many hours back to search (default 1, max 24).
    """
    hours = min(max(hours, 1), 24)
    from_time = f"-{hours}h"

    raw = await nextdns__logs__search(
        profile_id=profile_id,
        device=device_id,
        from_time=from_time,
        limit=1000,
    )
    entries = raw.get("entries", [])

    if not entries:
        return (
            f"## Device Investigation: {device_id}\n\n"
            f"No DNS queries found for device `{device_id}` "
            f"in the last {hours} hour(s).\n"
        )

    # Tally statistics.
    total = len(entries)
    blocked = sum(1 for e in entries if e.get("status") == "blocked")
    allowed = sum(1 for e in entries if e.get("status") == "allowed")
    errors = sum(1 for e in entries if e.get("status") == "error")

    # Top domains by frequency.
    domain_counts: dict[str, int] = {}
    for e in entries:
        domain = e.get("domain", "unknown")
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
    top_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Top blocked domains.
    blocked_counts: dict[str, int] = {}
    for e in entries:
        if e.get("status") == "blocked":
            domain = e.get("domain", "unknown")
            blocked_counts[domain] = blocked_counts.get(domain, 0) + 1
    top_blocked = sorted(blocked_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Build report.
    lines: list[str] = [
        f"## Device Investigation: {device_id}",
        "",
        f"**Time window:** last {hours} hour(s)",
        f"**Total queries:** {total}",
        f"**Blocked:** {blocked} ({blocked * 100 // total if total else 0}%)",
        f"**Allowed (explicit):** {allowed}",
        f"**Errors:** {errors}",
        "",
    ]

    if top_domains:
        lines.append("### Top Queried Domains")
        lines.append("")
        lines.append("| Domain | Count |")
        lines.append("| ------ | ----- |")
        for domain, count in top_domains:
            lines.append(f"| {domain} | {count} |")
        lines.append("")

    if top_blocked:
        lines.append("### Top Blocked Domains")
        lines.append("")
        lines.append("| Domain | Count |")
        lines.append("| ------ | ----- |")
        for domain, count in top_blocked:
            lines.append(f"| {domain} | {count} |")
        lines.append("")

    # Format the most recent entries via OX formatter.
    recent_ox = [
        OXLogEntry(
            timestamp=e.get("timestamp", ""),
            domain=e.get("domain", ""),
            status=e.get("status", "default"),
            device=_device_name(e),
            protocol=e.get("protocol", ""),
        )
        for e in entries[:20]
    ]
    lines.append(format_log_entries(recent_ox))

    return "\n".join(lines).rstrip() + "\n"


async def recent_blocks(profile_id: str, limit: int = 20) -> str:
    """Show recent blocked queries for a profile.

    Fetches the most recent blocked DNS queries and formats them as a
    log table with device and reason information.

    Args:
        profile_id: NextDNS profile ID.
        limit: Maximum number of blocked entries to show (default 20, max 100).
    """
    limit = min(max(limit, 1), 100)

    raw = await nextdns__logs__search(
        profile_id=profile_id,
        status="blocked",
        limit=limit,
    )
    entries = raw.get("entries", [])

    if not entries:
        return "## Recent Blocked Queries\n\nNo blocked queries found.\n"

    # Tally by block reason.
    reason_counts: dict[str, int] = {}
    for e in entries:
        reasons = e.get("reasons", [])
        for r in reasons:
            name = r.get("name", r.get("id", "unknown"))
            reason_counts[name] = reason_counts.get(name, 0) + 1

    lines: list[str] = [
        "## Recent Blocked Queries",
        "",
        f"**Showing:** {len(entries)} most recent blocked queries",
        "",
    ]

    if reason_counts:
        lines.append("### Block Reasons")
        lines.append("")
        lines.append("| Reason | Count |")
        lines.append("| ------ | ----- |")
        for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {reason} | {count} |")
        lines.append("")

    # Format entries via OX formatter.
    ox_entries = [
        OXLogEntry(
            timestamp=e.get("timestamp", ""),
            domain=e.get("domain", ""),
            status=e.get("status", "blocked"),
            device=_device_name(e),
            protocol=e.get("protocol", ""),
        )
        for e in entries
    ]
    lines.append(format_log_entries(ox_entries))

    return "\n".join(lines).rstrip() + "\n"


def _device_name(entry: dict[str, Any]) -> str:
    """Extract a human-readable device name from a log entry dict."""
    device = entry.get("device")
    if isinstance(device, dict):
        name = device.get("name") or device.get("id") or ""
        return str(name)
    return str(device) if device else ""
