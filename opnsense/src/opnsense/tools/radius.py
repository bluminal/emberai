# SPDX-License-Identifier: MIT
"""FreeRADIUS service tools for MAC-based VLAN assignment via OPNsense.

Provides tools for managing FreeRADIUS clients and users (MAC
Authentication Bypass / MAB) through the OPNsense ``os-freeradius``
plugin API.

Tools
-----
- ``opnsense__services__get_radius_status`` -- Service status overview
- ``opnsense__services__add_radius_client`` -- Add a RADIUS client (WRITE)
- ``opnsense__services__add_radius_mac_vlan`` -- Add MAC->VLAN mapping (WRITE)
- ``opnsense__services__remove_radius_mac_vlan`` -- Remove MAC mapping (WRITE)
- ``opnsense__services__list_radius_mac_vlans`` -- List MAC->VLAN mappings
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError as PydanticValidationError

from opnsense.models.radius import RadiusClient, RadiusUser
from opnsense.safety import reconfigure_gate, write_gate
from opnsense.server import mcp_server
from opnsense.validation import validate_path_param

if TYPE_CHECKING:
    from opnsense.api.opnsense_client import OPNsenseClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def _get_client() -> OPNsenseClient:
    """Get a configured OPNsenseClient from environment variables."""
    import os

    from opnsense.api.opnsense_client import OPNsenseClient

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
# MAC normalization helper
# ---------------------------------------------------------------------------

_MAC_PATTERN = re.compile(
    r"^[0-9a-fA-F]{2}([:\-]?)[0-9a-fA-F]{2}"
    r"(\1[0-9a-fA-F]{2}){4}$"
)


def normalize_mac(mac: str) -> str:
    """Normalize a MAC address to lowercase hex without separators.

    Accepts colon-separated (AA:BB:CC:DD:EE:FF), dash-separated
    (aa-bb-cc-dd-ee-ff), or plain (aabbccddeeff) formats.

    Parameters
    ----------
    mac:
        MAC address in any common format.

    Returns
    -------
    str
        12-character lowercase hex string (e.g. ``"aabbccddeeff"``).

    Raises
    ------
    ValueError
        If the input is not a valid MAC address.
    """
    stripped = mac.strip()
    if not _MAC_PATTERN.match(stripped):
        raise ValueError(
            f"Invalid MAC address: {mac!r}. "
            "Expected format: AA:BB:CC:DD:EE:FF, "
            "aa-bb-cc-dd-ee-ff, or aabbccddeeff."
        )
    return re.sub(r"[:\-]", "", stripped).lower()


# ---------------------------------------------------------------------------
# Internal write helpers (safety-gated)
# ---------------------------------------------------------------------------


@write_gate("OPNSENSE")
async def _add_client_write(
    client: OPNsenseClient,
    name: str,
    ip: str,
    secret: str,
    description: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Save a new RADIUS client to config (write-gated)."""
    data = {
        "client": {
            "name": name,
            "secret": secret,
            "ip": ip,
            "enabled": "1",
            "description": description,
        },
    }
    result = await client.write(
        "freeradius",
        "client",
        "addClient",
        data=data,
    )
    logger.info("Added RADIUS client: %s (%s)", name, ip)
    return result


@write_gate("OPNSENSE")
async def _add_user_write(
    client: OPNsenseClient,
    username: str,
    vlan: str,
    description: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Save a new RADIUS user (MAB entry) to config (write-gated)."""
    data = {
        "user": {
            "username": username,
            "password": username,
            "vlan": vlan,
            "enabled": "1",
            "description": description,
        },
    }
    result = await client.write(
        "freeradius",
        "user",
        "addUser",
        data=data,
    )
    logger.info("Added RADIUS MAB user: %s -> VLAN %s", username, vlan)
    return result


@write_gate("OPNSENSE")
async def _delete_user_write(
    client: OPNsenseClient,
    uuid: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Delete a RADIUS user by UUID (write-gated)."""
    uuid = validate_path_param(uuid, "uuid")
    result = await client.write(
        "freeradius",
        "user",
        f"delUser/{uuid}",
    )
    logger.info("Deleted RADIUS user: %s", uuid)
    return result


@reconfigure_gate("OPNSENSE")
async def _reconfigure_freeradius(
    client: OPNsenseClient,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Apply saved FreeRADIUS config to the live system."""
    result = await client.reconfigure("freeradius", "service")
    logger.info("FreeRADIUS reconfigure completed")
    return result


# ===========================================================================
# MCP tool: get_radius_status
# ===========================================================================


@mcp_server.tool()
async def opnsense__services__get_radius_status() -> dict[str, Any]:
    """Get FreeRADIUS service status, clients, and user count.

    Returns an overview of the FreeRADIUS service including whether
    it is enabled, the number of configured RADIUS clients (NAS
    devices), and the number of MAC->VLAN user entries.

    Returns:
        Dict with keys: enabled, client_count, user_count,
        clients, users.
    """
    client = _get_client()
    try:
        general = await client.get(
            "freeradius",
            "general",
            "get",
        )
        clients_raw = await client.get(
            "freeradius",
            "client",
            "searchClient",
        )
        users_raw = await client.get(
            "freeradius",
            "user",
            "searchUser",
        )
    finally:
        await client.close()

    # Parse enabled status from general settings
    general_settings = general.get("general", general)
    enabled = general_settings.get("enabled", "0")

    # Parse clients
    client_rows = clients_raw.get("rows", [])
    clients_list: list[dict[str, Any]] = []
    for row in client_rows:
        try:
            parsed = RadiusClient.model_validate(row)
            clients_list.append(parsed.model_dump())
        except (PydanticValidationError, KeyError, TypeError, ValueError):
            logger.warning(
                "Failed to parse RADIUS client: %s",
                row.get("name", "unknown"),
            )
            clients_list.append(row)

    # Parse users
    user_rows = users_raw.get("rows", [])
    users_list: list[dict[str, Any]] = []
    for row in user_rows:
        try:
            parsed = RadiusUser.model_validate(row)
            users_list.append(parsed.model_dump())
        except (PydanticValidationError, KeyError, TypeError, ValueError):
            logger.warning(
                "Failed to parse RADIUS user: %s",
                row.get("username", "unknown"),
            )
            users_list.append(row)

    logger.info(
        "RADIUS status: enabled=%s, clients=%d, users=%d",
        enabled,
        len(clients_list),
        len(users_list),
    )

    return {
        "enabled": enabled,
        "client_count": len(clients_list),
        "user_count": len(users_list),
        "clients": clients_list,
        "users": users_list,
    }


# ===========================================================================
# MCP tool: add_radius_client
# ===========================================================================


@mcp_server.tool()
async def opnsense__services__add_radius_client(
    name: str,
    ip: str,
    secret: str,
    description: str = "",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Add a RADIUS client (NAS device) to FreeRADIUS.

    A RADIUS client is a network device (e.g. UniFi controller, switch)
    that sends RADIUS authentication requests to FreeRADIUS.

    This is a WRITE operation. Requires OPNSENSE_WRITE_ENABLED=true
    and apply=True.

    Args:
        name: Client name (e.g. 'unifi-controller').
        ip: Client IP address (e.g. '10.10.10.168').
        secret: Shared secret for RADIUS communication.
        description: Optional human-readable description.
        apply: Must be True to execute. Without it, the write gate blocks.

    Returns:
        Dict with write_result, reconfigure_result, and client details.
    """
    client = _get_client()
    try:
        write_result = await _add_client_write(
            client,
            name,
            ip,
            secret,
            description,
            apply=apply,
        )
        reconfigure_result = await _reconfigure_freeradius(
            client,
            apply=apply,
        )
    finally:
        await client.close()

    return {
        "write_result": write_result,
        "reconfigure_result": reconfigure_result,
        "name": name,
        "ip": ip,
        "description": description,
    }


# ===========================================================================
# MCP tool: add_radius_mac_vlan
# ===========================================================================


@mcp_server.tool()
async def opnsense__services__add_radius_mac_vlan(
    mac: str,
    vlan_id: int,
    description: str = "",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Add a MAC-to-VLAN mapping via FreeRADIUS MAB.

    Creates a RADIUS user entry where both the username and password
    are the normalized MAC address (lowercase, no separators). The
    VLAN attribute controls which VLAN the device is assigned to.

    This is a WRITE operation. Requires OPNSENSE_WRITE_ENABLED=true
    and apply=True.

    Args:
        mac: Device MAC address (any format: AA:BB:CC:DD:EE:FF,
            aa-bb-cc-dd-ee-ff, or aabbccddeeff).
        vlan_id: Target VLAN ID (e.g. 70 for gaming VLAN).
        description: Optional description (e.g. 'Xbox One - Gaming').
        apply: Must be True to execute. Without it, the write gate blocks.

    Returns:
        Dict with write_result, reconfigure_result, and user details.
    """
    normalized = normalize_mac(mac)

    client = _get_client()
    try:
        write_result = await _add_user_write(
            client,
            normalized,
            str(vlan_id),
            description,
            apply=apply,
        )
        reconfigure_result = await _reconfigure_freeradius(
            client,
            apply=apply,
        )
    finally:
        await client.close()

    return {
        "write_result": write_result,
        "reconfigure_result": reconfigure_result,
        "mac": normalized,
        "vlan_id": vlan_id,
        "description": description,
    }


# ===========================================================================
# MCP tool: remove_radius_mac_vlan
# ===========================================================================


@mcp_server.tool()
async def opnsense__services__remove_radius_mac_vlan(
    mac: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Remove a MAC-to-VLAN mapping from FreeRADIUS.

    Searches for the RADIUS user entry matching the given MAC address
    (normalized to lowercase no-separator format), deletes it, and
    reconfigures FreeRADIUS.

    This is a WRITE operation. Requires OPNSENSE_WRITE_ENABLED=true
    and apply=True.

    Args:
        mac: Device MAC address (any format).
        apply: Must be True to execute. Without it, the write gate blocks.

    Returns:
        Dict with delete_result, reconfigure_result, and the MAC removed.

    Raises:
        ValueError: If no RADIUS user entry matches the given MAC.
    """
    normalized = normalize_mac(mac)

    client = _get_client()
    try:
        # Search for the user by MAC (username)
        users_raw = await client.get(
            "freeradius",
            "user",
            "searchUser",
        )
        rows = users_raw.get("rows", [])

        # Find the matching user
        target_uuid = None
        for row in rows:
            if row.get("username", "").lower() == normalized:
                target_uuid = row.get("uuid", "")
                break

        if not target_uuid:
            raise ValueError(f"No RADIUS user found for MAC {mac} (normalized: {normalized}).")

        delete_result = await _delete_user_write(
            client,
            target_uuid,
            apply=apply,
        )
        reconfigure_result = await _reconfigure_freeradius(
            client,
            apply=apply,
        )
    finally:
        await client.close()

    return {
        "delete_result": delete_result,
        "reconfigure_result": reconfigure_result,
        "mac": normalized,
        "uuid": target_uuid,
    }


# ===========================================================================
# MCP tool: list_radius_mac_vlans
# ===========================================================================


@mcp_server.tool()
async def opnsense__services__list_radius_mac_vlans() -> list[dict[str, Any]]:
    """List all MAC-to-VLAN mappings from FreeRADIUS.

    Returns all RADIUS user entries configured for MAC Authentication
    Bypass (MAB), showing the MAC address (username), assigned VLAN,
    enabled status, and description.

    Returns:
        List of dicts with uuid, username (MAC), vlan, enabled,
        and description fields.
    """
    client = _get_client()
    try:
        users_raw = await client.get(
            "freeradius",
            "user",
            "searchUser",
        )
    finally:
        await client.close()

    rows = users_raw.get("rows", [])
    users: list[dict[str, Any]] = []
    for row in rows:
        try:
            parsed = RadiusUser.model_validate(row)
            users.append(parsed.model_dump())
        except (PydanticValidationError, KeyError, TypeError, ValueError):
            logger.warning(
                "Failed to parse RADIUS user: %s",
                row.get("username", "unknown"),
            )
            users.append(row)

    logger.info("Listed %d RADIUS MAC->VLAN mappings", len(users))
    return users
