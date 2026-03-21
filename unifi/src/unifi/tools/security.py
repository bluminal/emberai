# SPDX-License-Identifier: MIT
"""Security skill MCP tools -- firewall rules, ZBF policies, ACLs, port forwards, IDS alerts.

Provides MCP tools for auditing UniFi network security posture including
firewall rules, zone-based firewall policies, access control lists,
port forwarding rules, and IDS/IPS alert retrieval via the Local Gateway API.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from unifi.api.local_gateway_client import LocalGatewayClient
from unifi.api.response import NormalizedResponse
from unifi.server import mcp_server
from unifi.tools._client_factory import get_local_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


_get_client = get_local_client  # Shared factory with credential validation


# ---------------------------------------------------------------------------
# Tool 1: Firewall Rules
# ---------------------------------------------------------------------------


def _format_firewall_rule(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize relevant fields from a raw firewall rule."""
    return {
        "rule_id": raw.get("_id", ""),
        "name": raw.get("name", ""),
        "action": raw.get("action", ""),
        "enabled": raw.get("enabled", True),
        "src": raw.get("src_address", raw.get("src_firewallgroup_ids", "")),
        "dst": raw.get("dst_address", raw.get("dst_firewallgroup_ids", "")),
        "protocol": raw.get("protocol", "all"),
        "position": raw.get("rule_index", raw.get("ruleset", "")),
    }


@mcp_server.tool()
async def unifi__security__get_firewall_rules(
    site_id: str = "default",
) -> list[dict[str, Any]]:
    """Get all firewall rules for a site.

    Returns the list of firewall rules with action, source, destination,
    protocol, enabled status, and position.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/rest/firewallrule")
    finally:
        await client.close()

    rules = [_format_firewall_rule(r) for r in normalized.data]

    logger.info(
        "Retrieved %d firewall rules for site '%s'",
        len(rules),
        site_id,
        extra={"component": "security"},
    )

    return rules


# ---------------------------------------------------------------------------
# Tool 2: Zone-Based Firewall (ZBF) Policies
# ---------------------------------------------------------------------------


def _format_zbf_policy(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize relevant fields from a raw ZBF policy."""
    return {
        "policy_id": raw.get("_id", ""),
        "from_zone": raw.get("src_zone", raw.get("from_zone", "")),
        "to_zone": raw.get("dst_zone", raw.get("to_zone", "")),
        "action": raw.get("action", ""),
        "match_all": raw.get("match_all", False),
    }


@mcp_server.tool()
async def unifi__security__get_zbf_policies(
    site_id: str = "default",
) -> list[dict[str, Any]]:
    """Get zone-based firewall policies for a site.

    Returns ZBF policies showing traffic flow rules between network zones
    (e.g., LAN-to-WAN, Guest-to-LAN).

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/rest/firewallzone")
    finally:
        await client.close()

    policies = [_format_zbf_policy(p) for p in normalized.data]

    logger.info(
        "Retrieved %d ZBF policies for site '%s'",
        len(policies),
        site_id,
        extra={"component": "security"},
    )

    return policies


# ---------------------------------------------------------------------------
# Tool 3: ACLs
# ---------------------------------------------------------------------------


def _format_acl(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize relevant fields from a raw ACL entry."""
    return {
        "acl_id": raw.get("_id", ""),
        "name": raw.get("name", ""),
        "entries": raw.get("entries", raw.get("rules", [])),
        "applied_to": raw.get("applied_to", raw.get("device_ids", [])),
    }


@mcp_server.tool()
async def unifi__security__get_acls(
    site_id: str = "default",
) -> list[dict[str, Any]]:
    """Get access control list (ACL) rules for a site.

    Returns ACL rules with entries and the devices/interfaces they are applied to.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/rest/firewallgroup")
    finally:
        await client.close()

    acls = [_format_acl(a) for a in normalized.data]

    logger.info(
        "Retrieved %d ACLs for site '%s'",
        len(acls),
        site_id,
        extra={"component": "security"},
    )

    return acls


# ---------------------------------------------------------------------------
# Tool 4: Port Forwards
# ---------------------------------------------------------------------------


def _format_port_forward(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize relevant fields from a raw port forward rule."""
    return {
        "rule_id": raw.get("_id", ""),
        "name": raw.get("name", ""),
        "proto": raw.get("proto", raw.get("protocol", "")),
        "wan_port": raw.get("dst_port", raw.get("fwd_port", "")),
        "lan_host": raw.get("fwd", raw.get("fwd_host", "")),
        "lan_port": raw.get("fwd_port", raw.get("dst_port", "")),
        "enabled": raw.get("enabled", True),
    }


@mcp_server.tool()
async def unifi__security__get_port_forwards(
    site_id: str = "default",
) -> list[dict[str, Any]]:
    """Get port forwarding rules for a site.

    Returns all port forwarding (DNAT) rules showing WAN-to-LAN port
    mappings, protocols, and enabled status.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/rest/portforward")
    finally:
        await client.close()

    forwards = [_format_port_forward(f) for f in normalized.data]

    logger.info(
        "Retrieved %d port forward rules for site '%s'",
        len(forwards),
        site_id,
        extra={"component": "security"},
    )

    return forwards


# ---------------------------------------------------------------------------
# Tool 5: IDS/IPS Alerts
# ---------------------------------------------------------------------------


def _filter_ids_by_time(
    events: list[dict[str, Any]],
    hours: int,
) -> list[dict[str, Any]]:
    """Filter IDS events to only those within the last *hours* hours."""
    cutoff = datetime.now(tz=UTC) - timedelta(hours=hours)
    filtered: list[dict[str, Any]] = []

    for event in events:
        ts_raw = event.get("timestamp", event.get("datetime"))
        if ts_raw is None:
            continue

        if isinstance(ts_raw, str):
            try:
                event_dt = datetime.fromisoformat(ts_raw)
                if event_dt.tzinfo is None:
                    event_dt = event_dt.replace(tzinfo=UTC)
            except ValueError:
                continue
        elif isinstance(ts_raw, (int, float)):
            # UniFi IDS timestamps are typically milliseconds
            if ts_raw > 1e12:
                ts_raw = ts_raw / 1000
            event_dt = datetime.fromtimestamp(ts_raw, tz=UTC)
        else:
            continue

        if event_dt >= cutoff:
            filtered.append(event)

    return filtered


def _format_ids_alert(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize relevant fields from a raw IDS/IPS alert."""
    # Handle timestamp (could be epoch ms or ISO string)
    ts_raw = raw.get("timestamp", raw.get("datetime"))
    timestamp = ""
    if isinstance(ts_raw, (int, float)):
        if ts_raw > 1e12:
            ts_raw = ts_raw / 1000
        timestamp = datetime.fromtimestamp(ts_raw, tz=UTC).isoformat()
    elif isinstance(ts_raw, str):
        timestamp = ts_raw

    return {
        "timestamp": timestamp,
        "signature": raw.get("inner_alert_signature", raw.get("msg", "")),
        "severity": raw.get("inner_alert_severity", raw.get("catname", "unknown")),
        "src_ip": raw.get("src_ip", ""),
        "dst_ip": raw.get("dst_ip", ""),
        "action_taken": raw.get("inner_alert_action", raw.get("action", "alert")),
    }


@mcp_server.tool()
async def unifi__security__get_ids_alerts(
    site_id: str = "default",
    hours: int = 24,
) -> list[dict[str, Any]]:
    """Get IDS/IPS alerts for a site within a time window.

    Returns intrusion detection/prevention alerts including signature,
    severity, source/destination IPs, and the action taken.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
        hours: Number of hours to look back. Defaults to 24.
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/stat/ips/event")
    finally:
        await client.close()

    # Filter by time window
    events_raw = _filter_ids_by_time(normalized.data, hours)

    alerts = [_format_ids_alert(e) for e in events_raw]

    logger.info(
        "Retrieved %d IDS alerts for site '%s' (hours=%d)",
        len(alerts),
        site_id,
        hours,
        extra={"component": "security"},
    )

    return alerts
