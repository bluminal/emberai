# SPDX-License-Identifier: MIT
"""VLAN write tools for Cisco SG-300.

Provides VLAN creation, deletion, access port assignment, and trunk
port configuration.  All operations use the write safety gate and
capture a config backup before making changes.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from cisco.cache import TTLCache
from cisco.errors import AuthenticationError, NetworkError, SSHCommandError, ValidationError
from cisco.parsers import parse_show_switchport, parse_show_vlan
from cisco.safety import write_gate
from cisco.server import mcp_server
from cisco.ssh.client import get_client
from cisco.ssh.config_backup import get_config_backup

logger = logging.getLogger(__name__)

# Valid port format: gi1-gi24, fa1-fa24, Po1-Po8, te1-te4
_PORT_RE = re.compile(r"^(gi|fa|Po|te)\d+$", re.IGNORECASE)

# Cache instance shared with topology/interfaces read tools for invalidation
_cache = TTLCache(max_size=100, default_ttl=300.0)


def _validate_port(port: str) -> str:
    """Validate and normalize a port identifier.

    Raises :class:`ValidationError` if the format is invalid.
    """
    if not _PORT_RE.match(port):
        raise ValidationError(
            f"Invalid port format: {port!r}. "
            f"Expected formats: gi1-gi24, fa1-fa24, Po1-Po8, te1-te4",
            details={"port": port},
        )
    return port


def _validate_vlan_id(vlan_id: int, *, allow_one: bool = False) -> None:
    """Validate a VLAN ID is in the user-configurable range.

    Parameters
    ----------
    vlan_id:
        The VLAN ID to validate.
    allow_one:
        If ``True``, VLAN 1 is permitted (for read operations).
        If ``False``, VLAN 1 is rejected (for create/delete operations).
    """
    if not allow_one and vlan_id == 1:
        raise ValidationError(
            "VLAN 1 is the default VLAN and cannot be created or deleted.",
            details={"vlan_id": vlan_id},
        )
    if vlan_id < 1 or vlan_id > 4094:
        raise ValidationError(
            f"VLAN ID must be between 2 and 4094, got {vlan_id}",
            details={"vlan_id": vlan_id},
        )


async def _get_existing_vlans(client: Any) -> list[Any]:
    """Fetch and parse current VLANs from the switch."""
    raw = await client.send_command("show vlan")
    return parse_show_vlan(raw)


async def _invalidate_caches() -> None:
    """Flush cached VLAN and interface data after a write operation."""
    await _cache.flush_by_prefix("vlans:")
    await _cache.flush_by_prefix("topology:")
    await _cache.flush_by_prefix("interfaces:")
    await _cache.flush_by_prefix("config:")


@mcp_server.tool()
@write_gate("CISCO")
async def cisco__interfaces__create_vlan(
    vlan_id: int,
    name: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Create a VLAN on the switch. Does NOT persist to startup-config.

    Parameters
    ----------
    vlan_id:
        VLAN ID to create (2-4094).  VLAN 1 cannot be created.
    name:
        Name to assign to the VLAN (e.g. "Guest", "IoT").
    apply:
        Must be ``True`` to execute the write.  Without this flag the
        operation is blocked by the write safety gate.

    Returns
    -------
    dict
        Result with keys: result, vlan_id, name, verified.
    """
    try:
        _validate_vlan_id(vlan_id)
    except ValidationError as exc:
        return {"error": str(exc)}

    try:
        client = get_client()
    except AuthenticationError as exc:
        return {"error": str(exc), "hint": exc.retry_hint}

    try:
        await client.connect()

        # Check that the VLAN doesn't already exist
        existing = await _get_existing_vlans(client)
        for v in existing:
            if v.id == vlan_id:
                return {
                    "error": f"VLAN {vlan_id} already exists with name {v.name!r}",
                    "vlan_id": vlan_id,
                }

        # Capture config backup before making changes
        backup = get_config_backup()
        await backup.capture(client, label=f"pre-create-vlan-{vlan_id}")

        # Create the VLAN
        await client.send_config_set([
            f"vlan {vlan_id}",
            f"name {name}",
            "exit",
        ])

        # Verify the VLAN was created
        updated = await _get_existing_vlans(client)
        verified = any(v.id == vlan_id for v in updated)

        await _invalidate_caches()

        return {
            "result": "created",
            "vlan_id": vlan_id,
            "name": name,
            "verified": verified,
        }
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to create VLAN %d: %s", vlan_id, exc)
        return {"error": str(exc), "hint": getattr(exc, "retry_hint", None)}


@mcp_server.tool()
@write_gate("CISCO")
async def cisco__interfaces__delete_vlan(
    vlan_id: int,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Delete a VLAN from the switch. Refuses to delete VLAN 1 (default).

    Does NOT persist to startup-config.

    Parameters
    ----------
    vlan_id:
        VLAN ID to delete (2-4094).  VLAN 1 cannot be deleted.
    apply:
        Must be ``True`` to execute the write.

    Returns
    -------
    dict
        Result with keys: result, vlan_id, warning (if ports were assigned),
        verified.
    """
    try:
        _validate_vlan_id(vlan_id)
    except ValidationError as exc:
        return {"error": str(exc)}

    try:
        client = get_client()
    except AuthenticationError as exc:
        return {"error": str(exc), "hint": exc.retry_hint}

    try:
        await client.connect()

        # Check that the VLAN exists
        existing = await _get_existing_vlans(client)
        target = None
        for v in existing:
            if v.id == vlan_id:
                target = v
                break

        if target is None:
            return {
                "error": f"VLAN {vlan_id} does not exist",
                "vlan_id": vlan_id,
            }

        # Warn if ports are still assigned to this VLAN
        warning: str | None = None
        if target.ports:
            warning = (
                f"VLAN {vlan_id} has ports assigned: {', '.join(target.ports)}. "
                f"These ports will lose their VLAN assignment."
            )

        # Capture config backup before making changes
        backup = get_config_backup()
        await backup.capture(client, label=f"pre-delete-vlan-{vlan_id}")

        # Delete the VLAN
        await client.send_config_set([f"no vlan {vlan_id}"])

        # Verify the VLAN was removed
        updated = await _get_existing_vlans(client)
        verified = not any(v.id == vlan_id for v in updated)

        await _invalidate_caches()

        result: dict[str, Any] = {
            "result": "deleted",
            "vlan_id": vlan_id,
            "verified": verified,
        }
        if warning:
            result["warning"] = warning

        return result
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to delete VLAN %d: %s", vlan_id, exc)
        return {"error": str(exc), "hint": getattr(exc, "retry_hint", None)}


@mcp_server.tool()
@write_gate("CISCO")
async def cisco__interfaces__set_port_vlan(
    port: str,
    vlan_id: int,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Set a port to access mode on a specific VLAN.

    Does NOT persist to startup-config.

    Parameters
    ----------
    port:
        Port identifier (e.g. gi1, fa2, Po1, te1).
    vlan_id:
        VLAN ID to assign (1-4094).
    apply:
        Must be ``True`` to execute the write.

    Returns
    -------
    dict
        Result with keys: result, port, vlan_id, verified.
    """
    try:
        validated_port = _validate_port(port)
    except ValidationError as exc:
        return {"error": str(exc)}

    try:
        _validate_vlan_id(vlan_id, allow_one=True)
    except ValidationError as exc:
        return {"error": str(exc)}

    try:
        client = get_client()
    except AuthenticationError as exc:
        return {"error": str(exc), "hint": exc.retry_hint}

    try:
        await client.connect()

        # Verify the VLAN exists
        existing = await _get_existing_vlans(client)
        if not any(v.id == vlan_id for v in existing):
            return {
                "error": f"VLAN {vlan_id} does not exist. Create it first.",
                "vlan_id": vlan_id,
            }

        # Capture config backup before making changes
        backup = get_config_backup()
        await backup.capture(client, label=f"pre-set-port-vlan-{validated_port}-{vlan_id}")

        # Configure the port
        await client.send_config_set([
            f"interface {validated_port}",
            "switchport mode access",
            f"switchport access vlan {vlan_id}",
            "exit",
        ])

        # Verify with show interfaces switchport
        raw = await client.send_command(f"show interfaces switchport {validated_port}")
        detail = parse_show_switchport(raw)
        verified = detail.vlan_id == vlan_id and detail.mode.lower() == "access"

        await _invalidate_caches()

        return {
            "result": "configured",
            "port": validated_port,
            "vlan_id": vlan_id,
            "verified": verified,
        }
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to set port %s to VLAN %d: %s", port, vlan_id, exc)
        return {"error": str(exc), "hint": getattr(exc, "retry_hint", None)}
    except ValueError as exc:
        return {"error": f"Failed to verify switchport output for {port}: {exc}"}


@mcp_server.tool()
@write_gate("CISCO")
async def cisco__interfaces__set_trunk_port(
    port: str,
    allowed_vlans: str,
    operation: str = "add",
    native_vlan: int | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Configure a port as trunk with allowed VLANs.

    Does NOT persist to startup-config.

    Parameters
    ----------
    port:
        Port identifier (e.g. gi1, gi24, Po1).
    allowed_vlans:
        Comma-separated VLAN IDs (e.g. "10,20,30").
    operation:
        How to apply the allowed VLANs list:
        - ``"add"``: Add VLANs to the existing allowed list.
        - ``"remove"``: Remove VLANs from the existing allowed list.
        - ``"replace"``: Replace the entire allowed list with these VLANs.
    native_vlan:
        Optional native VLAN ID for untagged traffic.
    apply:
        Must be ``True`` to execute the write.

    Returns
    -------
    dict
        Result with keys: result, port, allowed_vlans, native_vlan, verified.
    """
    try:
        validated_port = _validate_port(port)
    except ValidationError as exc:
        return {"error": str(exc)}

    # Validate operation
    valid_operations = ("add", "remove", "replace")
    if operation not in valid_operations:
        choices = ", ".join(valid_operations)
        return {
            "error": f"Invalid operation: {operation!r}. Must be one of: {choices}",
        }

    # Validate VLAN IDs in the allowed list
    try:
        vlan_ids = [int(v.strip()) for v in allowed_vlans.split(",") if v.strip()]
    except ValueError:
        return {
            "error": (
                f"Invalid VLAN list: {allowed_vlans!r}. "
                f"Expected comma-separated integers."
            ),
        }

    for vid in vlan_ids:
        if vid < 1 or vid > 4094:
            return {"error": f"VLAN ID {vid} is out of range (1-4094)."}

    if not vlan_ids:
        return {"error": "At least one VLAN ID is required."}

    # Validate native VLAN if provided
    if native_vlan is not None and (native_vlan < 1 or native_vlan > 4094):
        return {"error": f"Native VLAN ID {native_vlan} is out of range (1-4094)."}

    try:
        client = get_client()
    except AuthenticationError as exc:
        return {"error": str(exc), "hint": exc.retry_hint}

    try:
        await client.connect()

        # Capture config backup before making changes
        backup = get_config_backup()
        await backup.capture(client, label=f"pre-set-trunk-{validated_port}")

        # Build CLI commands
        vlan_list_str = ",".join(str(v) for v in vlan_ids)
        commands: list[str] = [
            f"interface {validated_port}",
            "switchport mode trunk",
        ]

        if operation == "add":
            commands.append(f"switchport trunk allowed vlan add {vlan_list_str}")
        elif operation == "remove":
            commands.append(f"switchport trunk allowed vlan remove {vlan_list_str}")
        else:  # replace
            commands.append(f"switchport trunk allowed vlan {vlan_list_str}")

        if native_vlan is not None:
            commands.append(f"switchport trunk native vlan {native_vlan}")

        commands.append("exit")

        await client.send_config_set(commands)

        # Verify with show interfaces switchport
        raw = await client.send_command(f"show interfaces switchport {validated_port}")
        detail = parse_show_switchport(raw)
        verified = detail.mode.lower() == "trunk"

        await _invalidate_caches()

        result: dict[str, Any] = {
            "result": "configured",
            "port": validated_port,
            "allowed_vlans": vlan_list_str,
            "operation": operation,
            "native_vlan": native_vlan,
            "verified": verified,
        }

        return result
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to configure trunk on %s: %s", port, exc)
        return {"error": str(exc), "hint": getattr(exc, "retry_hint", None)}
    except ValueError as exc:
        return {"error": f"Failed to verify switchport output for {port}: {exc}"}
