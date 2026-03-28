# SPDX-License-Identifier: MIT
"""Log tools -- search, stream, download, and clear DNS query logs.

Provides MCP tools for accessing NextDNS DNS query logs. Includes
search with filtering, polling-based streaming (since SSE is not
feasible in the MCP context), bulk download URL generation, and
write-gated log clearing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from nextdns.models.logs import LogEntry
from nextdns.safety import clear_logs_gate
from nextdns.server import mcp_server
from nextdns.tools._client_factory import get_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def nextdns__logs__search(
    profile_id: str,
    domain: str | None = None,
    status: str | None = None,
    device: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Search DNS query logs for a NextDNS profile.

    Returns matching log entries with pagination support and a stream ID
    that can be used to resume with the streaming tool.

    Args:
        profile_id: NextDNS profile ID (e.g. "abc123").
        domain: Filter by domain substring (partial match).
        status: Filter by status: "default", "blocked", "allowed", or "error".
        device: Filter by device ID.
        from_time: Start time (ISO 8601, Unix timestamp, or relative like "-6h").
        to_time: End time (ISO 8601, Unix timestamp, or relative like "-1h").
        limit: Max results to return (10-1000, default 100).
    """
    client = get_client()
    params: dict[str, Any] = {"limit": min(max(limit, 10), 1000)}
    if domain:
        params["search"] = domain
    if status:
        params["status"] = status
    if device:
        params["device"] = device
    if from_time:
        params["from"] = from_time
    if to_time:
        params["to"] = to_time

    raw = await client.get(f"/profiles/{profile_id}/logs", params=params)
    data = raw.get("data", [])
    meta = raw.get("meta", {})

    entries = [LogEntry.model_validate(e).model_dump(by_alias=True) for e in data]

    result: dict[str, Any] = {"entries": entries, "count": len(entries)}

    # Include pagination cursor if more results are available.
    cursor = meta.get("pagination", {}).get("cursor")
    if cursor:
        result["next_cursor"] = cursor

    # Include stream ID for live streaming continuation.
    stream_id = meta.get("stream", {}).get("id")
    if stream_id:
        result["stream_id"] = stream_id

    logger.info(
        "Log search returned %d entries for profile %s",
        len(entries),
        profile_id,
        extra={"component": "logs"},
    )
    return result


@mcp_server.tool()
async def nextdns__logs__stream(
    profile_id: str,
    device: str | None = None,
    status: str | None = None,
    domain: str | None = None,
    duration_seconds: int = 30,
) -> dict[str, Any]:
    """Stream live DNS query logs for a NextDNS profile via polling.

    Since SSE streaming is not directly feasible in the MCP tool context,
    this tool polls the logs endpoint at 5-second intervals for the
    specified duration, collecting new entries as they arrive.

    Useful for real-time monitoring of DNS activity (e.g. watching what a
    specific device is querying, or monitoring for blocked domains).

    Args:
        profile_id: NextDNS profile ID (e.g. "abc123").
        device: Filter by device ID.
        status: Filter by status: "default", "blocked", "allowed", or "error".
        domain: Filter by domain substring (partial match).
        duration_seconds: How long to collect logs (5-120 seconds, default 30).
    """
    client = get_client()
    duration = min(max(duration_seconds, 5), 120)

    all_entries: list[dict[str, Any]] = []
    seen_timestamps: set[str] = set()

    base_params: dict[str, Any] = {"sort": "desc", "limit": 50}
    if device:
        base_params["device"] = device
    if status:
        base_params["status"] = status
    if domain:
        base_params["search"] = domain

    start = time.monotonic()
    last_timestamp: str | None = None
    poll_count = 0

    while time.monotonic() - start < duration:
        params = dict(base_params)
        if last_timestamp:
            params["from"] = last_timestamp
            params["sort"] = "asc"  # Get entries after last seen

        raw = await client.get(f"/profiles/{profile_id}/logs", params=params)
        data = raw.get("data", [])
        poll_count += 1

        for entry_data in data:
            entry = LogEntry.model_validate(entry_data)
            ts = entry.timestamp
            if ts not in seen_timestamps:
                seen_timestamps.add(ts)
                all_entries.append(entry.model_dump(by_alias=True))
                if last_timestamp is None or ts > last_timestamp:
                    last_timestamp = ts

        # Wait 5 seconds before next poll.
        remaining = duration - (time.monotonic() - start)
        if remaining > 5:
            await asyncio.sleep(5)
        else:
            break

    # Sort by timestamp descending (most recent first).
    all_entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    elapsed = round(time.monotonic() - start, 1)

    logger.info(
        "Log stream collected %d entries over %.1fs (%d polls) for profile %s",
        len(all_entries),
        elapsed,
        poll_count,
        profile_id,
        extra={"component": "logs"},
    )

    return {
        "entries": all_entries,
        "count": len(all_entries),
        "duration_seconds": elapsed,
        "polls": poll_count,
        "polling_note": (
            "Live streaming via SSE is not feasible in the MCP context. "
            "Used polling with 5-second intervals instead."
        ),
    }


@mcp_server.tool()
async def nextdns__logs__download(
    profile_id: str,
    from_time: str | None = None,
    to_time: str | None = None,
) -> dict[str, Any]:
    """Get a download URL for bulk DNS query logs.

    Returns a URL that can be used to download logs as a file.
    Large date ranges may produce very large files.

    Args:
        profile_id: NextDNS profile ID (e.g. "abc123").
        from_time: Start time (ISO 8601 or Unix timestamp).
        to_time: End time (ISO 8601 or Unix timestamp).
    """
    client = get_client()
    params: dict[str, Any] = {"redirect": "0"}  # Get JSON with URL instead of redirect
    if from_time:
        params["from"] = from_time
    if to_time:
        params["to"] = to_time

    raw = await client.get(f"/profiles/{profile_id}/logs/download", params=params)

    # The API returns the download URL in the response -- try common field names.
    download_url = raw.get("data", raw.get("url", ""))

    result: dict[str, Any] = {
        "profile_id": profile_id,
        "download_url": download_url,
    }

    if from_time or to_time:
        result["time_range"] = {"from": from_time, "to": to_time}
    else:
        result["warning"] = (
            "No time range specified -- this may download ALL logs, "
            "which could be a very large file."
        )

    logger.info(
        "Generated download URL for profile %s logs",
        profile_id,
        extra={"component": "logs"},
    )
    return result


@mcp_server.tool()
@clear_logs_gate
async def nextdns__logs__clear(
    profile_id: str,
    *,
    apply: bool = False,
    clear_logs: bool = False,
) -> dict[str, Any]:
    """Clear all DNS query logs for a NextDNS profile.

    WARNING: This is a destructive, irreversible operation. All stored
    DNS query logs for this profile will be permanently deleted.

    Requires both --apply and --clear-logs flags for safety. Also
    requires NEXTDNS_WRITE_ENABLED=true in environment.

    Args:
        profile_id: NextDNS profile ID (e.g. "abc123").
        apply: Must be True to execute the write (safety gate step 2).
        clear_logs: Must be True to confirm log clearing (safety gate step 3).
    """
    client = get_client()
    await client.delete(f"/profiles/{profile_id}/logs")

    logger.info(
        "Cleared all logs for profile %s",
        profile_id,
        extra={"component": "logs"},
    )

    return {
        "profile_id": profile_id,
        "status": "cleared",
        "message": f"All DNS query logs for profile {profile_id} have been permanently deleted.",
    }
