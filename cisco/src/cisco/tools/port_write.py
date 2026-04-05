# SPDX-License-Identifier: MIT
"""Port management write tools for Cisco SG-300.

Provides port description setting and port enable/disable (admin shutdown).
All operations use the write safety gate and capture a config backup
before making changes.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from cisco.cache import TTLCache
from cisco.errors import AuthenticationError, NetworkError, SSHCommandError, ValidationError
from cisco.parsers import parse_show_interfaces_status, parse_show_mac_address_table
from cisco.safety import write_gate
from cisco.server import mcp_server
from cisco.ssh.client import get_client
from cisco.ssh.config_backup import get_config_backup

logger = logging.getLogger(__name__)

# Valid port format: gi1-gi24, fa1-fa24, Po1-Po8, te1-te4
_PORT_RE = re.compile(r"^(gi|fa|Po|te)\d+$", re.IGNORECASE)

# Cache instance for invalidation after writes
_cache = TTLCache(max_size=100, default_ttl=120.0)


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


async def _invalidate_caches() -> None:
    """Flush cached interface data after a write operation."""
    await _cache.flush_by_prefix("interfaces:")
    await _cache.flush_by_prefix("topology:")
    await _cache.flush_by_prefix("config:")


@mcp_server.tool()
@write_gate("CISCO")
async def cisco__interfaces__set_port_description(
    port: str,
    description: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Set a port description for operational labeling.

    Does NOT persist to startup-config.

    Parameters
    ----------
    port:
        Port identifier (e.g. gi1, fa2, Po1, te1).
    description:
        Description text for the port (e.g. "AP-Living-Room", "NAS-Primary").
    apply:
        Must be ``True`` to execute the write.

    Returns
    -------
    dict
        Result with keys: result, port, description, verified.
    """
    try:
        validated_port = _validate_port(port)
    except ValidationError as exc:
        return {"error": str(exc)}

    if not description or not description.strip():
        return {"error": "Description cannot be empty."}

    try:
        client = get_client()
    except AuthenticationError as exc:
        return {"error": str(exc), "hint": exc.retry_hint}

    try:
        await client.connect()

        # Capture config backup before making changes
        backup = get_config_backup()
        await backup.capture(client, label=f"pre-set-description-{validated_port}")

        # Set the port description
        await client.send_config_set([
            f"interface {validated_port}",
            f"description {description.strip()}",
            "exit",
        ])

        await _invalidate_caches()

        return {
            "result": "configured",
            "port": validated_port,
            "description": description.strip(),
            "verified": True,
        }
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to set description on %s: %s", port, exc)
        return {"error": str(exc), "hint": getattr(exc, "retry_hint", None)}


@mcp_server.tool()
@write_gate("CISCO")
async def cisco__interfaces__set_port_state(
    port: str,
    enabled: bool,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Enable or disable a port (admin shutdown / no shutdown).

    Does NOT persist to startup-config.

    When disabling a port, the tool checks the MAC address table for
    active entries and includes a warning if the port has active devices.

    Parameters
    ----------
    port:
        Port identifier (e.g. gi1, fa2, Po1, te1).
    enabled:
        ``True`` to enable the port (``no shutdown``), ``False`` to
        disable it (``shutdown``).
    apply:
        Must be ``True`` to execute the write.

    Returns
    -------
    dict
        Result with keys: result, port, enabled, verified,
        and optionally active_macs_warning.
    """
    try:
        validated_port = _validate_port(port)
    except ValidationError as exc:
        return {"error": str(exc)}

    try:
        client = get_client()
    except AuthenticationError as exc:
        return {"error": str(exc), "hint": exc.retry_hint}

    try:
        await client.connect()

        active_macs_warning: str | None = None

        # If disabling, check for active MAC entries on the port
        if not enabled:
            mac_raw = await client.send_command("show mac address-table")
            mac_entries = parse_show_mac_address_table(mac_raw)
            port_macs = [m for m in mac_entries if m.interface.lower() == validated_port.lower()]
            if port_macs:
                mac_list = ", ".join(m.mac for m in port_macs)
                active_macs_warning = (
                    f"Port {validated_port} has {len(port_macs)} active MAC "
                    f"address(es): {mac_list}. Shutting down this port will "
                    f"disconnect these devices."
                )

        # Capture config backup before making changes
        backup = get_config_backup()
        action = "enable" if enabled else "disable"
        await backup.capture(client, label=f"pre-{action}-{validated_port}")

        # Set the port state
        command = "no shutdown" if enabled else "shutdown"
        await client.send_config_set([
            f"interface {validated_port}",
            command,
            "exit",
        ])

        # Verify with show interfaces status
        raw = await client.send_command("show interfaces status")
        ports = parse_show_interfaces_status(raw)
        target_port = None
        for p in ports:
            if p.id.lower() == validated_port.lower():
                target_port = p
                break

        # On SG-300, "Up" means enabled and linked, "Down" can mean
        # either disabled or no link.  Best we can verify is that
        # the command didn't error.
        verified = target_port is not None

        await _invalidate_caches()

        result: dict[str, Any] = {
            "result": "configured",
            "port": validated_port,
            "enabled": enabled,
            "verified": verified,
        }
        if active_macs_warning:
            result["active_macs_warning"] = active_macs_warning

        return result
    except (NetworkError, SSHCommandError) as exc:
        logger.error("Failed to %s port %s: %s", "enable" if enabled else "disable", port, exc)
        return {"error": str(exc), "hint": getattr(exc, "retry_hint", None)}
