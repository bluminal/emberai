# SPDX-License-Identifier: MIT
"""Analytics agent -- dashboard-style summary per profile.

Composes multiple analytics MCP tool calls with OX formatters to produce
an operator-ready markdown dashboard showing query volume, top blocked
domains, active devices, and protocol/encryption health.
"""

from __future__ import annotations

import asyncio

from nextdns.output import (
    AnalyticsSummary,
    _format_key_value,
    _format_table,
    format_analytics_summary,
)
from nextdns.tools.analytics import (
    nextdns__analytics__get_devices,
    nextdns__analytics__get_encryption,
    nextdns__analytics__get_protocols,
    nextdns__analytics__get_status,
    nextdns__analytics__get_top_domains,
)


async def analytics_dashboard(
    profile_id: str,
    from_time: str | None = None,
    to_time: str | None = None,
) -> str:
    """Generate a formatted analytics dashboard for a profile.

    Fetches status, top blocked domains, devices, protocols, and
    encryption data in parallel, then assembles a multi-section
    dashboard report using OX formatters.

    Args:
        profile_id: The NextDNS profile identifier.
        from_time: Start of the date range (ISO 8601 or relative).
        to_time: End of the date range.

    Returns:
        A markdown-formatted analytics dashboard string.
    """
    # Fetch all analytics data in parallel.
    (
        status_data,
        top_blocked_data,
        devices_data,
        protocols_data,
        encryption_data,
    ) = await asyncio.gather(
        nextdns__analytics__get_status(profile_id, from_time=from_time, to_time=to_time),
        nextdns__analytics__get_top_domains(
            profile_id,
            status="blocked",
            from_time=from_time,
            to_time=to_time,
            limit=10,
        ),
        nextdns__analytics__get_devices(profile_id, from_time=from_time, to_time=to_time),
        nextdns__analytics__get_protocols(profile_id, from_time=from_time, to_time=to_time),
        nextdns__analytics__get_encryption(profile_id, from_time=from_time, to_time=to_time),
    )

    # --- Build Query Volume section from status data ---
    total_queries = 0
    blocked_queries = 0
    for entry in status_data:
        queries = entry.get("queries", 0)
        total_queries += queries
        if entry.get("status") == "blocked":
            blocked_queries = queries

    blocked_pct = (blocked_queries / total_queries * 100.0) if total_queries > 0 else 0.0

    # --- Build top blocked list ---
    top_blocked = [(d["name"], d["queries"]) for d in top_blocked_data]

    # --- Build device activity list ---
    devices = [(d.get("name") or d.get("id", "Unknown"), d.get("queries", 0)) for d in devices_data]

    # --- Format the core analytics summary ---
    summary = AnalyticsSummary(
        total_queries=total_queries,
        blocked_queries=blocked_queries,
        blocked_percent=blocked_pct,
        top_blocked=top_blocked,
        devices=devices,
    )

    lines: list[str] = [format_analytics_summary(summary)]

    # --- Protocol section ---
    protocol_list = protocols_data.get("protocols", [])
    if protocol_list:
        headers = ["Protocol", "Queries"]
        rows = [[p["name"], f"{p['queries']:,}"] for p in protocol_list]
        lines.append(_format_table(headers, rows, title="Protocol Breakdown"))

    unencrypted_warning = protocols_data.get("unencrypted_warning", False)
    if unencrypted_warning:
        lines.append(
            "[!] **Warning:** Unencrypted DNS protocols detected with active queries. "
            "Consider migrating all devices to DNS-over-HTTPS or DNS-over-TLS.\n"
        )

    # --- Encryption section ---
    enc_data: dict[str, str] = {
        "Encrypted queries": f"{encryption_data.get('encrypted', 0):,}",
        "Unencrypted queries": f"{encryption_data.get('unencrypted', 0):,}",
        "Total": f"{encryption_data.get('total', 0):,}",
        "Unencrypted percentage": f"{encryption_data.get('unencrypted_percentage', 0):.1f}%",
    }
    lines.append(_format_key_value(enc_data, title="Encryption"))

    if encryption_data.get("warning", False):
        lines.append(
            "[!] **Warning:** More than 10% of DNS traffic is unencrypted. "
            "Review device configurations to ensure encrypted DNS is enabled.\n"
        )

    return "\n".join(lines).rstrip() + "\n"
