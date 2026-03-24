# SPDX-License-Identifier: MIT
"""Firewall skill MCP tools -- rules, aliases, and NAT operations.

Provides MCP tools for listing and inspecting firewall rules, aliases,
and NAT rules on an OPNsense firewall, as well as write-gated tools
for adding rules, toggling rules, and creating aliases.

Write tools follow the OPNsense two-step pattern: write (save config)
then reconfigure (apply to live system). All write tools are protected
by the ``@write_gate("OPNSENSE")`` decorator.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.api.response import is_action_success, normalize_response
from opnsense.cache import CacheTTL
from opnsense.errors import APIError, ValidationError
from opnsense.models.firewall import Alias, FirewallRule, NATRule
from opnsense.safety import write_gate
from opnsense.server import mcp_server

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OPNsense API coercion helpers
# ---------------------------------------------------------------------------

_BOOL_FIELDS_RULE = ("enabled", "log")
_STR_BOOL_TRUE = frozenset({"1", "true", "yes"})


def _coerce_rule_booleans(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce OPNsense string booleans to Python bools for Pydantic strict mode.

    The OPNsense API returns ``"1"``/``"0"`` for boolean fields in
    search-style responses, but our Pydantic models use ``strict=True``.
    This helper converts those string representations before validation.
    """
    coerced = dict(row)
    for field in _BOOL_FIELDS_RULE:
        if field in coerced and isinstance(coerced[field], str):
            coerced[field] = coerced[field].lower() in _STR_BOOL_TRUE
    return coerced


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def _get_client() -> OPNsenseClient:
    """Get a configured OPNsenseClient from environment variables."""
    host = os.environ.get("OPNSENSE_HOST", "")
    api_key = os.environ.get("OPNSENSE_API_KEY", "")
    api_secret = os.environ.get("OPNSENSE_API_SECRET", "")
    verify_ssl = os.environ.get("OPNSENSE_VERIFY_SSL", "true").lower() != "false"
    return OPNsenseClient(
        host=host,
        api_key=api_key,
        api_secret=api_secret,
        verify_ssl=verify_ssl,
    )


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def opnsense__firewall__list_rules(
    interface: str | None = None,
) -> list[dict[str, Any]]:
    """List all firewall filter rules on the OPNsense firewall.

    Returns rule inventory with UUID, description, action, enabled status,
    direction, protocol, source, destination, log flag, position, and
    interface.

    Args:
        interface: Optional interface name to filter rules
            (e.g. 'lan', 'wan', 'opt1'). If not provided, returns
            all rules.

    API endpoint: GET /api/firewall/filter/searchRule
    """
    client = _get_client()
    try:
        raw = await client.get_cached(
            "firewall",
            "filter",
            "searchRule",
            cache_key="firewall:rules",
            ttl=CacheTTL.FIREWALL_RULES,
            params={"rowCount": -1, "current": 1},
        )
    finally:
        await client.close()

    normalized = normalize_response(raw)

    rules: list[dict[str, Any]] = []
    for row in normalized.data:
        try:
            coerced = _coerce_rule_booleans(row)
            rule = FirewallRule.model_validate(coerced)
            rule_dict = rule.model_dump(by_alias=False)

            # Apply interface filter if specified
            if interface and rule_dict.get("interface") != interface:
                continue

            rules.append(rule_dict)
        except Exception:
            logger.warning(
                "Skipping unparseable firewall rule: %s",
                row.get("uuid", row.get("description", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Listed %d firewall rules%s",
        len(rules),
        f" for interface {interface}" if interface else "",
        extra={"component": "firewall"},
    )

    return rules


@mcp_server.tool()
async def opnsense__firewall__get_rule(uuid: str) -> dict[str, Any]:
    """Get detailed information for a single firewall rule.

    Args:
        uuid: The UUID of the firewall rule to retrieve.

    API endpoint: GET /api/firewall/filter/getRule/{uuid}
    """
    if not uuid or not uuid.strip():
        raise ValidationError(
            "UUID must not be empty.",
            details={"field": "uuid"},
        )

    client = _get_client()
    try:
        raw = await client.get("firewall", "filter", f"getRule/{uuid.strip()}")
    finally:
        await client.close()

    # getRule returns a nested structure with the rule under a key
    rule_data: dict[str, Any] = raw.get("rule", raw)

    logger.info(
        "Retrieved firewall rule: %s",
        uuid,
        extra={"component": "firewall"},
    )

    return rule_data


@mcp_server.tool()
async def opnsense__firewall__list_aliases() -> list[dict[str, Any]]:
    """List all firewall aliases (named address/port groups).

    Returns alias inventory with UUID, name, type, description,
    and content.

    API endpoint: GET /api/firewall/alias/searchItem
    """
    client = _get_client()
    try:
        raw = await client.get_cached(
            "firewall",
            "alias",
            "searchItem",
            cache_key="firewall:aliases",
            ttl=CacheTTL.FIREWALL_ALIASES,
            params={"rowCount": -1, "current": 1},
        )
    finally:
        await client.close()

    normalized = normalize_response(raw)

    aliases: list[dict[str, Any]] = []
    for row in normalized.data:
        try:
            alias = Alias.model_validate(row)
            aliases.append(alias.model_dump(by_alias=False))
        except Exception:
            logger.warning(
                "Skipping unparseable alias entry: %s",
                row.get("name", row.get("uuid", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Listed %d firewall aliases",
        len(aliases),
        extra={"component": "firewall"},
    )

    return aliases


@mcp_server.tool()
async def opnsense__firewall__list_nat_rules() -> list[dict[str, Any]]:
    """List all source NAT rules on the OPNsense firewall.

    Returns NAT rule inventory with UUID, description, interface,
    protocol, source, destination, target, target port, and
    enabled status.

    API endpoint: GET /api/firewall/source_nat/searchRule
    """
    client = _get_client()
    try:
        raw = await client.get_cached(
            "firewall",
            "source_nat",
            "searchRule",
            cache_key="firewall:nat_rules",
            ttl=CacheTTL.NAT_RULES,
            params={"rowCount": -1, "current": 1},
        )
    finally:
        await client.close()

    normalized = normalize_response(raw)

    nat_rules: list[dict[str, Any]] = []
    for row in normalized.data:
        try:
            nat_rule = NATRule.model_validate(row)
            nat_rules.append(nat_rule.model_dump(by_alias=False))
        except Exception:
            logger.warning(
                "Skipping unparseable NAT rule: %s",
                row.get("uuid", row.get("description", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Listed %d NAT rules",
        len(nat_rules),
        extra={"component": "firewall"},
    )

    return nat_rules


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__firewall__add_rule(
    interface: str,
    action: str,
    src: str,
    dst: str,
    protocol: str = "any",
    description: str = "",
    position: int | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Add a new firewall filter rule.

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        interface: Interface to apply the rule on (e.g. 'lan', 'wan', 'opt1').
        action: Rule action: 'pass', 'block', or 'reject'.
        src: Source address or alias (e.g. '192.168.1.0/24', 'any').
        dst: Destination address or alias (e.g. '192.168.1.0/24', 'any').
        protocol: IP protocol (e.g. 'TCP', 'UDP', 'ICMP', 'any').
        description: Human-readable rule description.
        position: Optional rule position in the filter chain.
        apply: Must be True to execute (write gate).

    API endpoint: POST /api/firewall/filter/addRule
    """
    valid_actions = {"pass", "block", "reject"}
    if action.lower() not in valid_actions:
        raise ValidationError(
            f"Action must be one of {valid_actions}, got '{action}'",
            details={"field": "action", "value": action},
        )

    if not interface or not interface.strip():
        raise ValidationError(
            "Interface must not be empty.",
            details={"field": "interface"},
        )

    rule_data: dict[str, Any] = {
        "rule": {
            "interface": interface.strip(),
            "action": action.lower(),
            "direction": "in",
            "quick": "1",
            "source_net": src,
            "destination_net": dst,
            "ipprotocol": "inet",
            "protocol": protocol,
            "description": description,
            "enabled": "1",
        },
    }

    if position is not None:
        rule_data["rule"]["sequence"] = str(position)

    client = _get_client()
    try:
        write_result = await client.write(
            "firewall",
            "filter",
            "addRule",
            data=rule_data,
        )

        if not is_action_success(write_result):
            validations = write_result.get("validations", {})
            detail = f"validations={validations}" if validations else f"response={write_result}"
            raise APIError(
                f"Failed to add firewall rule: "
                f"{write_result.get('result', 'unknown error')} -- {detail}",
                status_code=400,
                endpoint="/api/firewall/filter/addRule",
                response_body=str(write_result),
            )

        # OPNsense 26.x uses savepoint/apply/cancelRollback for firewall
        savepoint_result = await client.post(
            "firewall",
            "filter",
            "savepoint",
        )
        revision = savepoint_result.get("revision", "")
        if revision:
            await client.post(
                "firewall",
                "filter",
                f"apply/{revision}",
            )
            await client.post(
                "firewall",
                "filter",
                f"cancelRollback/{revision}",
            )

    finally:
        await client.close()

    logger.info(
        "Added firewall rule: %s %s -> %s on %s (protocol=%s)",
        action,
        src,
        dst,
        interface,
        protocol,
        extra={"component": "firewall"},
    )

    return {
        "status": "created",
        "interface": interface.strip(),
        "action": action.lower(),
        "source": src,
        "destination": dst,
        "protocol": protocol,
        "description": description,
        "uuid": write_result.get("uuid", ""),
    }


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__firewall__toggle_rule(
    uuid: str,
    enabled: bool,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Enable or disable a firewall rule.

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        uuid: The UUID of the firewall rule to toggle.
        enabled: True to enable, False to disable.
        apply: Must be True to execute (write gate).

    API endpoint: POST /api/firewall/filter/toggleRule/{uuid}/{state}
    """
    if not uuid or not uuid.strip():
        raise ValidationError(
            "UUID must not be empty.",
            details={"field": "uuid"},
        )

    state = "1" if enabled else "0"
    client = _get_client()
    try:
        write_result = await client.write(
            "firewall",
            "filter",
            f"toggleRule/{uuid.strip()}/{state}",
        )

        if not is_action_success(write_result):
            raise APIError(
                f"Failed to toggle firewall rule {uuid}: "
                f"{write_result.get('result', 'unknown error')}",
                status_code=400,
                endpoint=f"/api/firewall/filter/toggleRule/{uuid}/{state}",
                response_body=str(write_result),
            )

        await client.reconfigure("firewall", "filter")

    finally:
        await client.close()

    action_str = "enabled" if enabled else "disabled"
    logger.info(
        "Toggled firewall rule %s: %s",
        uuid,
        action_str,
        extra={"component": "firewall"},
    )

    return {
        "status": action_str,
        "uuid": uuid.strip(),
        "enabled": enabled,
    }


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__firewall__add_alias(
    name: str,
    alias_type: str,
    content: str,
    description: str = "",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Add a new firewall alias (named address/port group).

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        name: Alias name (e.g. 'trusted_hosts', 'blocked_nets').
        alias_type: Alias type: 'host', 'network', 'port', or 'url'.
        content: Alias content -- newline-separated CIDRs, IPs, ports,
            or URLs depending on type.
        description: Human-readable alias description.
        apply: Must be True to execute (write gate).

    API endpoint: POST /api/firewall/alias/addItem
    """
    valid_types = {"host", "network", "port", "url"}
    if alias_type.lower() not in valid_types:
        raise ValidationError(
            f"Alias type must be one of {valid_types}, got '{alias_type}'",
            details={"field": "alias_type", "value": alias_type},
        )

    if not name or not name.strip():
        raise ValidationError(
            "Alias name must not be empty.",
            details={"field": "name"},
        )
    if not content or not content.strip():
        raise ValidationError(
            "Alias content must not be empty.",
            details={"field": "content"},
        )

    client = _get_client()
    try:
        write_result = await client.write(
            "firewall",
            "alias",
            "addItem",
            data={
                "alias": {
                    "name": name.strip(),
                    "type": alias_type.lower(),
                    "content": content.strip(),
                    "description": description,
                },
            },
        )

        if not is_action_success(write_result):
            raise APIError(
                f"Failed to add alias '{name}': {write_result.get('result', 'unknown error')}",
                status_code=400,
                endpoint="/api/firewall/alias/addItem",
                response_body=str(write_result),
            )

        await client.reconfigure("firewall", "alias")

    finally:
        await client.close()

    logger.info(
        "Added firewall alias: name='%s', type='%s'",
        name,
        alias_type,
        extra={"component": "firewall"},
    )

    return {
        "status": "created",
        "name": name.strip(),
        "alias_type": alias_type.lower(),
        "content": content.strip(),
        "description": description,
        "uuid": write_result.get("uuid", ""),
    }
