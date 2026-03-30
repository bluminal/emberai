# SPDX-License-Identifier: MIT
"""Firewall skill MCP tools -- rules, aliases, NAT, and DNAT operations.

Provides MCP tools for listing and inspecting firewall rules, aliases,
NAT rules, and DNAT port forward rules on an OPNsense firewall, as well
as write-gated tools for adding rules, toggling rules, creating aliases,
and managing DNAT port forwards.

Write tools follow the OPNsense two-step pattern: write (save config)
then reconfigure/apply (push to live system). All write tools are
protected by the ``@write_gate("OPNSENSE")`` decorator.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from opnsense.api.opnsense_client import OPNsenseClient, truncate_response_body
from opnsense.api.response import is_action_success, normalize_response
from opnsense.cache import CacheTTL
from opnsense.errors import APIError, ValidationError
from opnsense.models.firewall import Alias, FirewallRule, NATRule
from opnsense.safety import write_gate
from opnsense.server import mcp_server
from opnsense.validation import validate_path_param

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
    # Coerce sequence (position) from string to int
    if "sequence" in coerced and isinstance(coerced["sequence"], str):
        try:
            coerced["sequence"] = int(coerced["sequence"])
        except (ValueError, TypeError):
            coerced["sequence"] = None
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
        except (PydanticValidationError, KeyError, TypeError, ValueError):
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
    uuid = validate_path_param(uuid, "uuid")

    client = _get_client()
    try:
        raw = await client.get("firewall", "filter", f"getRule/{uuid}")
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
        except (PydanticValidationError, KeyError, TypeError, ValueError):
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
        except (PydanticValidationError, KeyError, TypeError, ValueError):
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


@mcp_server.tool()
async def opnsense__firewall__list_port_forwards() -> list[dict[str, Any]]:
    """List all DNAT port forward rules on the OPNsense firewall.

    Returns rule inventory with UUID, interface, protocol,
    source/destination with ports, target IP, target port,
    description, and enabled status.

    API endpoint: POST /api/firewall/d_nat/searchRule
    """
    client = _get_client()
    try:
        raw = await client.get_cached(
            "firewall",
            "d_nat",
            "searchRule",
            cache_key="firewall:dnat_rules",
            ttl=CacheTTL.DNAT_RULES,
            params={"rowCount": -1, "current": 1},
        )
    finally:
        await client.close()

    normalized = normalize_response(raw)

    rules: list[dict[str, Any]] = []
    for row in normalized.data:
        try:
            coerced = _coerce_rule_booleans(row)
            rules.append({
                "uuid": coerced.get("uuid", ""),
                "interface": coerced.get("interface", ""),
                "protocol": coerced.get("protocol", ""),
                "source_net": coerced.get("src_network", coerced.get("source_net", "")),
                "source_port": coerced.get("src_port", ""),
                "destination_net": coerced.get(
                    "dst_network", coerced.get("destination_net", ""),
                ),
                "destination_port": coerced.get("dst_port", ""),
                "target": coerced.get("target", ""),
                "local_port": coerced.get("local_port", ""),
                "description": coerced.get("descr", coerced.get("description", "")),
                "enabled": coerced.get("enabled", False),
                "log": coerced.get("log", False),
            })
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "Skipping unparseable DNAT rule: %s",
                row.get("uuid", row.get("descr", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Listed %d DNAT port forward rules",
        len(rules),
        extra={"component": "firewall"},
    )

    return rules


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
    gateway: str = "",
    dst_port: str = "",
    src_port: str = "",
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
        gateway: Optional gateway or gateway group name for policy-based
            routing (e.g. 'WAN1_Failover'). Only applies to 'pass' rules.
        dst_port: Optional destination port, range, or alias name
            (e.g. '443', '80-443', 'Jailed_Allowed_Ports').
        src_port: Optional source port, range, or alias name.
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

    if dst_port and dst_port.strip():
        rule_data["rule"]["destination_port"] = dst_port.strip()

    if src_port and src_port.strip():
        rule_data["rule"]["source_port"] = src_port.strip()

    if gateway and gateway.strip():
        if action.lower() != "pass":
            raise ValidationError(
                "Gateway can only be set on 'pass' rules (policy-based routing).",
                details={"field": "gateway", "action": action},
            )
        rule_data["rule"]["gateway"] = gateway.strip()

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
                response_body=truncate_response_body(str(write_result)),
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
        "Added firewall rule: %s %s -> %s on %s (protocol=%s, gateway=%s)",
        action,
        src,
        dst,
        interface,
        protocol,
        gateway or "default",
        extra={"component": "firewall"},
    )

    result: dict[str, Any] = {
        "status": "created",
        "interface": interface.strip(),
        "action": action.lower(),
        "source": src,
        "destination": dst,
        "protocol": protocol,
        "description": description,
        "uuid": write_result.get("uuid", ""),
    }
    if gateway and gateway.strip():
        result["gateway"] = gateway.strip()
    if dst_port and dst_port.strip():
        result["dst_port"] = dst_port.strip()
    if src_port and src_port.strip():
        result["src_port"] = src_port.strip()
    return result


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
    uuid = validate_path_param(uuid, "uuid")

    state = "1" if enabled else "0"
    client = _get_client()
    try:
        write_result = await client.write(
            "firewall",
            "filter",
            f"toggleRule/{uuid}/{state}",
        )

        if not is_action_success(write_result):
            raise APIError(
                f"Failed to toggle firewall rule {uuid}: "
                f"{write_result.get('result', 'unknown error')}",
                status_code=400,
                endpoint=f"/api/firewall/filter/toggleRule/{uuid}/{state}",
                response_body=truncate_response_body(str(write_result)),
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
        "uuid": uuid,
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
                response_body=truncate_response_body(str(write_result)),
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


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__firewall__create_rule(
    interface: str,
    action: str,
    source_net: str,
    destination_net: str,
    protocol: str = "any",
    direction: str = "in",
    ipprotocol: str = "inet",
    enabled: bool = True,
    quick: bool = True,
    sequence: int | None = None,
    description: str = "",
    log: bool = False,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Create a new firewall filter rule.

    Creates the rule and applies it to the live pf ruleset via the
    OPNsense savepoint/apply/cancelRollback workflow.

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        interface: Interface to apply the rule on (e.g. 'lan', 'wan', 'opt1').
        action: Rule action: 'pass', 'block', or 'reject'.
        source_net: Source address, CIDR, alias name, or 'any'.
        destination_net: Destination address, CIDR, alias name, or 'any'.
        protocol: IP protocol (e.g. 'TCP', 'UDP', 'ICMP', 'any').
        direction: Traffic direction: 'in' or 'out'.
        ipprotocol: IP version: 'inet' (IPv4), 'inet6' (IPv6), 'inet46' (both).
        enabled: Whether the rule is enabled (default True).
        quick: First-match mode (default True). False for last-match-wins.
        sequence: Optional rule position in the filter chain.
        description: Human-readable rule description.
        log: Whether to log matching packets.
        apply: Must be True to execute (write gate).

    Returns:
        Dict with the new rule UUID and creation details.

    API endpoint: POST /api/firewall/filter/addRule
    """
    valid_actions = {"pass", "block", "reject"}
    if action.lower() not in valid_actions:
        raise ValidationError(
            f"Action must be one of {valid_actions}, got '{action}'",
            details={"field": "action", "value": action},
        )

    valid_directions = {"in", "out"}
    if direction.lower() not in valid_directions:
        raise ValidationError(
            f"Direction must be one of {valid_directions}, got '{direction}'",
            details={"field": "direction", "value": direction},
        )

    valid_ipprotocols = {"inet", "inet6", "inet46"}
    if ipprotocol.lower() not in valid_ipprotocols:
        raise ValidationError(
            f"IP protocol must be one of {valid_ipprotocols}, got '{ipprotocol}'",
            details={"field": "ipprotocol", "value": ipprotocol},
        )

    if not interface or not interface.strip():
        raise ValidationError(
            "Interface must not be empty.",
            details={"field": "interface"},
        )

    rule_payload: dict[str, str] = {
        "enabled": "1" if enabled else "0",
        "action": action.lower(),
        "quick": "1" if quick else "0",
        "interface": interface.strip(),
        "direction": direction.lower(),
        "ipprotocol": ipprotocol.lower(),
        "protocol": protocol,
        "source_net": source_net,
        "destination_net": destination_net,
        "description": description,
        "log": "1" if log else "0",
    }
    if sequence is not None:
        rule_payload["sequence"] = str(sequence)

    client = _get_client()
    try:
        write_result = await client.write(
            "firewall",
            "filter",
            "addRule",
            data={"rule": rule_payload},
        )

        if not is_action_success(write_result):
            validations = write_result.get("validations", {})
            detail = (
                f"validations={validations}" if validations else f"response={write_result}"
            )
            raise APIError(
                f"Failed to create firewall rule: "
                f"{write_result.get('result', 'unknown error')} -- {detail}",
                status_code=400,
                endpoint="/api/firewall/filter/addRule",
                response_body=truncate_response_body(str(write_result)),
            )

        uuid = write_result.get("uuid", "")

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
        "Created firewall rule: %s %s -> %s on %s (protocol=%s)",
        action,
        source_net,
        destination_net,
        interface,
        protocol,
        extra={"component": "firewall"},
    )

    return {
        "uuid": uuid,
        "status": "created",
        "action": action.lower(),
        "interface": interface.strip(),
        "source": source_net,
        "destination": destination_net,
        "protocol": protocol,
        "description": description,
        "applied": True,
    }


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__firewall__update_rule(
    uuid: str,
    action: str | None = None,
    interface: str | None = None,
    source_net: str | None = None,
    destination_net: str | None = None,
    protocol: str | None = None,
    direction: str | None = None,
    ipprotocol: str | None = None,
    enabled: bool | None = None,
    quick: bool | None = None,
    description: str | None = None,
    sequence: int | None = None,
    log: bool | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Update an existing firewall rule by UUID. Only specified fields are changed.

    Applies the update to the live pf ruleset via the OPNsense
    savepoint/apply/cancelRollback workflow.

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        uuid: The UUID of the firewall rule to update.
        action: Rule action: 'pass', 'block', or 'reject'.
        interface: Interface (e.g. 'lan', 'wan', 'opt1').
        source_net: Source address, CIDR, alias name, or 'any'.
        destination_net: Destination address, CIDR, alias name, or 'any'.
        protocol: IP protocol (e.g. 'TCP', 'UDP', 'ICMP', 'any').
        direction: Traffic direction: 'in' or 'out'.
        ipprotocol: IP version: 'inet', 'inet6', or 'inet46'.
        enabled: Whether the rule is enabled.
        quick: First-match mode.
        description: Human-readable rule description.
        sequence: Rule position in the filter chain.
        log: Whether to log matching packets.
        apply: Must be True to execute (write gate).

    Returns:
        Dict with the updated rule UUID and list of changed fields.

    API endpoint: POST /api/firewall/filter/setRule/{uuid}
    """
    uuid = validate_path_param(uuid, "uuid")

    # Validate provided fields
    if action is not None:
        valid_actions = {"pass", "block", "reject"}
        if action.lower() not in valid_actions:
            raise ValidationError(
                f"Action must be one of {valid_actions}, got '{action}'",
                details={"field": "action", "value": action},
            )

    if direction is not None:
        valid_directions = {"in", "out"}
        if direction.lower() not in valid_directions:
            raise ValidationError(
                f"Direction must be one of {valid_directions}, got '{direction}'",
                details={"field": "direction", "value": direction},
            )

    if ipprotocol is not None:
        valid_ipprotocols = {"inet", "inet6", "inet46"}
        if ipprotocol.lower() not in valid_ipprotocols:
            raise ValidationError(
                f"IP protocol must be one of {valid_ipprotocols}, got '{ipprotocol}'",
                details={"field": "ipprotocol", "value": ipprotocol},
            )

    # Build partial update payload -- only include specified fields
    rule_payload: dict[str, str] = {}
    if action is not None:
        rule_payload["action"] = action.lower()
    if interface is not None:
        rule_payload["interface"] = interface.strip()
    if source_net is not None:
        rule_payload["source_net"] = source_net
    if destination_net is not None:
        rule_payload["destination_net"] = destination_net
    if protocol is not None:
        rule_payload["protocol"] = protocol
    if direction is not None:
        rule_payload["direction"] = direction.lower()
    if ipprotocol is not None:
        rule_payload["ipprotocol"] = ipprotocol.lower()
    if enabled is not None:
        rule_payload["enabled"] = "1" if enabled else "0"
    if quick is not None:
        rule_payload["quick"] = "1" if quick else "0"
    if description is not None:
        rule_payload["description"] = description
    if sequence is not None:
        rule_payload["sequence"] = str(sequence)
    if log is not None:
        rule_payload["log"] = "1" if log else "0"

    if not rule_payload:
        raise ValidationError(
            "No fields specified to update.",
            details={"field": "rule_payload"},
        )

    client = _get_client()
    try:
        write_result = await client.write(
            "firewall",
            "filter",
            f"setRule/{uuid}",
            data={"rule": rule_payload},
        )

        if not is_action_success(write_result):
            validations = write_result.get("validations", {})
            detail = (
                f"validations={validations}" if validations else f"response={write_result}"
            )
            raise APIError(
                f"Failed to update firewall rule {uuid}: "
                f"{write_result.get('result', 'unknown error')} -- {detail}",
                status_code=400,
                endpoint=f"/api/firewall/filter/setRule/{uuid}",
                response_body=truncate_response_body(str(write_result)),
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
        "Updated firewall rule %s: fields=%s",
        uuid,
        list(rule_payload.keys()),
        extra={"component": "firewall"},
    )

    return {
        "uuid": uuid,
        "status": "updated",
        "updated_fields": list(rule_payload.keys()),
        "applied": True,
    }


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__firewall__delete_rule(
    uuid: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Delete a firewall rule by UUID.

    Removes the rule and applies the change to the live pf ruleset
    via the OPNsense savepoint/apply/cancelRollback workflow.

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        uuid: The UUID of the firewall rule to delete.
        apply: Must be True to execute (write gate).

    Returns:
        Dict with the deleted rule UUID and description.

    API endpoint: POST /api/firewall/filter/delRule/{uuid}
    """
    uuid = validate_path_param(uuid, "uuid")

    client = _get_client()
    try:
        # Fetch rule info before deletion for confirmation
        description = "Unknown"
        try:
            rule_info = await client.get("firewall", "filter", f"getRule/{uuid}")
            description = rule_info.get("rule", {}).get("description", "Unknown")
        except (APIError, KeyError, TypeError):
            logger.warning(
                "Could not fetch rule info before deletion: %s",
                uuid,
                exc_info=True,
            )

        write_result = await client.write(
            "firewall",
            "filter",
            f"delRule/{uuid}",
        )

        if not is_action_success(write_result):
            raise APIError(
                f"Failed to delete firewall rule {uuid}: "
                f"{write_result.get('result', 'unknown error')}",
                status_code=400,
                endpoint=f"/api/firewall/filter/delRule/{uuid}",
                response_body=truncate_response_body(str(write_result)),
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
        "Deleted firewall rule: uuid=%s, description='%s'",
        uuid,
        description,
        extra={"component": "firewall"},
    )

    return {
        "uuid": uuid,
        "description": description,
        "status": "deleted",
        "applied": True,
    }


# ---------------------------------------------------------------------------
# DNAT Port Forward write tools
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__firewall__add_port_forward(
    interface: str,
    protocol: str,
    destination_port: str,
    target: str,
    local_port: str,
    destination_net: str = "wanip",
    source_net: str = "any",
    ipprotocol: str = "inet",
    description: str = "",
    log: bool = False,
    enabled: bool = True,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Create a DNAT port forward rule.

    Forwards external traffic matching the destination port on the
    specified interface to an internal host and port.

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        interface: Incoming interface (typically 'wan').
        protocol: IP protocol: 'TCP', 'UDP', or 'TCP/UDP'.
        destination_port: External port to forward.
        target: Internal IP address to forward traffic to.
        local_port: Internal port on the target host.
        destination_net: External destination address to match
            (default 'wanip' = the WAN interface IP).
        source_net: Restrict source address (default 'any').
        ipprotocol: IP version: 'inet', 'inet6', or 'inet46'.
        description: Human-readable rule description.
        log: Whether to log matching packets.
        enabled: Whether the rule is enabled (default True).
        apply: Must be True to execute (write gate).

    API endpoint: POST /api/firewall/d_nat/addRule
    """
    valid_protocols = {"TCP", "UDP", "TCP/UDP"}
    if protocol.upper() not in valid_protocols:
        raise ValidationError(
            f"Protocol must be one of {valid_protocols}, got '{protocol}'",
            details={"field": "protocol", "value": protocol},
        )

    valid_ipprotocols = {"inet", "inet6", "inet46"}
    if ipprotocol.lower() not in valid_ipprotocols:
        raise ValidationError(
            f"IP protocol must be one of {valid_ipprotocols}, got '{ipprotocol}'",
            details={"field": "ipprotocol", "value": ipprotocol},
        )

    if not interface or not interface.strip():
        raise ValidationError(
            "Interface must not be empty.",
            details={"field": "interface"},
        )

    if not target or not target.strip():
        raise ValidationError(
            "Target (internal IP) must not be empty.",
            details={"field": "target"},
        )

    if not destination_port or not destination_port.strip():
        raise ValidationError(
            "Destination port must not be empty.",
            details={"field": "destination_port"},
        )

    if not local_port or not local_port.strip():
        raise ValidationError(
            "Local port must not be empty.",
            details={"field": "local_port"},
        )

    rule_payload: dict[str, Any] = {
        "interface": interface.strip(),
        "ipprotocol": ipprotocol.lower(),
        "protocol": protocol.upper(),
        "src_network": source_net,
        "dst_network": destination_net,
        "dst_port": destination_port.strip(),
        "target": target.strip(),
        "local_port": local_port.strip(),
        "descr": description,
        "log": "1" if log else "0",
        "enabled": "1" if enabled else "0",
    }

    client = _get_client()
    try:
        write_result = await client.write(
            "firewall",
            "d_nat",
            "addRule",
            data={"rule": rule_payload},
        )

        if not is_action_success(write_result):
            validations = write_result.get("validations", {})
            detail = (
                f"validations={validations}"
                if validations
                else f"response={write_result}"
            )
            raise APIError(
                f"Failed to add DNAT port forward rule: "
                f"{write_result.get('result', 'unknown error')} -- {detail}",
                status_code=400,
                endpoint="/api/firewall/d_nat/addRule",
                response_body=truncate_response_body(str(write_result)),
            )

        uuid = write_result.get("uuid", "")

        # Apply the DNAT configuration to make it live.
        await client.post("firewall", "d_nat", "apply")

        # Flush cache so subsequent reads pick up the new rule.
        await client.cache.flush_by_prefix("firewall:")

    finally:
        await client.close()

    logger.info(
        "Added DNAT port forward: %s:%s -> %s:%s on %s (protocol=%s)",
        destination_net,
        destination_port,
        target,
        local_port,
        interface,
        protocol,
        extra={"component": "firewall"},
    )

    return {
        "status": "created",
        "uuid": uuid,
        "interface": interface.strip(),
        "protocol": protocol.upper(),
        "external_port": destination_port.strip(),
        "target": target.strip(),
        "internal_port": local_port.strip(),
        "description": description,
        "applied": True,
    }


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__firewall__delete_port_forward(
    uuid: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Delete a DNAT port forward rule by UUID.

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        uuid: The UUID of the port forward rule to delete.
        apply: Must be True to execute (write gate).

    API endpoint: POST /api/firewall/d_nat/delRule/{uuid}
    """
    uuid = validate_path_param(uuid, "uuid")

    client = _get_client()
    try:
        write_result = await client.write(
            "firewall",
            "d_nat",
            f"delRule/{uuid}",
        )

        if not is_action_success(write_result):
            raise APIError(
                f"Failed to delete DNAT port forward rule {uuid}: "
                f"{write_result.get('result', 'unknown error')}",
                status_code=400,
                endpoint=f"/api/firewall/d_nat/delRule/{uuid}",
                response_body=truncate_response_body(str(write_result)),
            )

        # Apply the DNAT configuration to make the deletion live.
        await client.post("firewall", "d_nat", "apply")

        # Flush cache so subsequent reads reflect the deleted rule.
        await client.cache.flush_by_prefix("firewall:")

    finally:
        await client.close()

    logger.info(
        "Deleted DNAT port forward rule: %s",
        uuid,
        extra={"component": "firewall"},
    )

    return {
        "status": "deleted",
        "uuid": uuid,
        "applied": True,
    }
