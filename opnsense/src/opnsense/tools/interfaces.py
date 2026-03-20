# SPDX-License-Identifier: MIT
"""Interfaces skill MCP tools -- interface, VLAN, and DHCP operations.

Provides MCP tools for listing interfaces, VLANs, and DHCP leases on an
OPNsense firewall, as well as write-gated tools for VLAN configuration,
DHCP subnet management, and DHCP reservations.

Write tools follow the OPNsense two-step pattern: write (save config) then
reconfigure (apply to live system). All write tools are protected by the
``@write_gate("OPNSENSE")`` decorator.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.api.response import is_action_success, normalize_response
from opnsense.cache import CacheTTL
from opnsense.errors import APIError, ValidationError
from opnsense.models.interface import Interface
from opnsense.models.services import DHCPLease
from opnsense.models.vlan_interface import VLANInterface
from opnsense.safety import write_gate
from opnsense.server import mcp_server

logger = logging.getLogger(__name__)


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
async def opnsense__interfaces__list_interfaces() -> list[dict[str, Any]]:
    """List all network interfaces on the OPNsense firewall.

    Returns interface inventory with name, description, IP, subnet,
    type, enabled status, and VLAN tag (if applicable).

    API endpoint: GET /api/interfaces/overview/export
    """
    client = _get_client()
    try:
        raw = await client.get_cached(
            "interfaces", "overview", "export",
            cache_key="interfaces:list",
            ttl=CacheTTL.INTERFACES,
        )
    finally:
        await client.close()

    # The export endpoint returns a flat dict keyed by interface name,
    # or a search-style response with rows.
    normalized = normalize_response(raw)

    interfaces: list[dict[str, Any]] = []
    for row in normalized.data:
        # If the response is a flat dict (action-style), the rows contain
        # the full response which may be keyed by interface name.
        if "name" in row:
            try:
                iface = Interface.model_validate(row)
                interfaces.append(iface.model_dump(by_alias=False))
            except Exception:
                logger.warning(
                    "Skipping unparseable interface entry: %s",
                    row.get("name", "unknown"),
                    exc_info=True,
                )
        else:
            # Flat dict keyed by interface name -- iterate over values
            for key, value in row.items():
                if isinstance(value, dict) and "name" not in value:
                    value["name"] = key
                if isinstance(value, dict):
                    try:
                        iface = Interface.model_validate(value)
                        interfaces.append(iface.model_dump(by_alias=False))
                    except Exception:
                        logger.warning(
                            "Skipping unparseable interface entry: %s",
                            key,
                            exc_info=True,
                        )

    logger.info(
        "Listed %d interfaces",
        len(interfaces),
        extra={"component": "interfaces"},
    )

    return interfaces


@mcp_server.tool()
async def opnsense__interfaces__list_vlan_interfaces() -> list[dict[str, Any]]:
    """List all VLAN interface definitions on the OPNsense firewall.

    Returns VLAN inventory with UUID, tag, interface name, description,
    parent interface, and PCP priority.

    API endpoint: GET /api/interfaces/vlan/searchItem
    """
    client = _get_client()
    try:
        raw = await client.get_cached(
            "interfaces", "vlan", "searchItem",
            cache_key="interfaces:vlans",
            ttl=CacheTTL.VLAN_INTERFACES,
        )
    finally:
        await client.close()

    normalized = normalize_response(raw)

    vlans: list[dict[str, Any]] = []
    for row in normalized.data:
        try:
            vlan = VLANInterface.model_validate(row)
            vlans.append(vlan.model_dump(by_alias=False))
        except Exception:
            logger.warning(
                "Skipping unparseable VLAN entry: %s",
                row.get("uuid", row.get("tag", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Listed %d VLAN interfaces",
        len(vlans),
        extra={"component": "interfaces"},
    )

    return vlans


@mcp_server.tool()
async def opnsense__interfaces__get_dhcp_leases(
    interface: str | None = None,
) -> list[dict[str, Any]]:
    """List DHCP leases from the Kea DHCP server.

    Returns lease information with MAC address, IP, hostname,
    expiration, state, and interface.

    Args:
        interface: Optional interface name to filter leases
            (e.g. 'igb1', 'igb1_vlan10'). If not provided,
            returns all leases.

    API endpoint: GET /api/kea/leases4/search
    """
    client = _get_client()
    try:
        raw = await client.get_cached(
            "kea", "leases4", "search",
            cache_key="dhcp:leases",
            ttl=CacheTTL.DHCP_LEASES,
        )
    finally:
        await client.close()

    normalized = normalize_response(raw)

    leases: list[dict[str, Any]] = []
    for row in normalized.data:
        try:
            lease = DHCPLease.model_validate(row)
            lease_dict = lease.model_dump(by_alias=False)

            # Apply interface filter if specified
            if interface and lease_dict.get("interface") != interface:
                continue

            leases.append(lease_dict)
        except Exception:
            logger.warning(
                "Skipping unparseable DHCP lease: %s",
                row.get("address", row.get("hw_address", "unknown")),
                exc_info=True,
            )

    logger.info(
        "Listed %d DHCP leases%s",
        len(leases),
        f" for interface {interface}" if interface else "",
        extra={"component": "interfaces"},
    )

    return leases


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__interfaces__add_vlan_interface(
    tag: int,
    parent_if: str,
    description: str = "",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Add a new VLAN interface definition.

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Creates a new 802.1Q VLAN interface on the specified parent
    physical interface.

    Args:
        tag: 802.1Q VLAN tag (1-4094).
        parent_if: Parent physical interface (e.g. 'igb0', 'igb1').
        description: Human-readable description for this VLAN.
        apply: Must be True to execute (write gate).

    API endpoint: POST /api/interfaces/vlan/addItem
    """
    if not 1 <= tag <= 4094:
        raise ValidationError(
            f"VLAN tag must be between 1 and 4094, got {tag}",
            details={"field": "tag", "value": tag},
        )

    if not parent_if or not parent_if.strip():
        raise ValidationError(
            "Parent interface must not be empty.",
            details={"field": "parent_if"},
        )

    client = _get_client()
    try:
        # Write the VLAN definition
        write_result = await client.write(
            "interfaces", "vlan", "addItem",
            data={
                "vlan": {
                    "if": parent_if.strip(),
                    "tag": str(tag),
                    "descr": description,
                },
            },
        )

        if not is_action_success(write_result):
            raise APIError(
                f"Failed to add VLAN {tag} on {parent_if}: "
                f"{write_result.get('result', 'unknown error')}",
                status_code=400,
                endpoint="/api/interfaces/vlan/addItem",
                response_body=str(write_result),
            )

        # Reconfigure to apply
        await client.reconfigure("interfaces", "vlan")

    finally:
        await client.close()

    logger.info(
        "Added VLAN interface: tag=%d, parent=%s, description='%s'",
        tag, parent_if, description,
        extra={"component": "interfaces"},
    )

    return {
        "status": "created",
        "tag": tag,
        "parent_if": parent_if,
        "description": description,
        "uuid": write_result.get("uuid", ""),
    }


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__interfaces__add_dhcp_reservation(
    interface: str,
    mac: str,
    ip: str,
    hostname: str = "",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Add a DHCP static reservation (fixed IP for a MAC address).

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        interface: Interface name the reservation applies to (e.g. 'igb1').
        mac: Client MAC address (e.g. 'aa:bb:cc:dd:ee:ff').
        ip: IP address to assign to this client.
        hostname: Optional hostname for the reservation.
        apply: Must be True to execute (write gate).

    API endpoint: POST /api/kea/dhcpv4/addReservation
    """
    if not interface or not interface.strip():
        raise ValidationError(
            "Interface must not be empty.",
            details={"field": "interface"},
        )
    if not mac or not mac.strip():
        raise ValidationError(
            "MAC address must not be empty.",
            details={"field": "mac"},
        )
    if not ip or not ip.strip():
        raise ValidationError(
            "IP address must not be empty.",
            details={"field": "ip"},
        )

    client = _get_client()
    try:
        write_result = await client.write(
            "kea", "dhcpv4", "addReservation",
            data={
                "reservation": {
                    "hw_address": mac.strip(),
                    "ip_address": ip.strip(),
                    "hostname": hostname,
                },
            },
        )

        if not is_action_success(write_result):
            raise APIError(
                f"Failed to add DHCP reservation for {mac} -> {ip}: "
                f"{write_result.get('result', 'unknown error')}",
                status_code=400,
                endpoint="/api/kea/dhcpv4/addReservation",
                response_body=str(write_result),
            )

        await client.reconfigure("kea", "dhcpv4")

    finally:
        await client.close()

    logger.info(
        "Added DHCP reservation: %s -> %s on %s (hostname=%s)",
        mac, ip, interface, hostname,
        extra={"component": "interfaces"},
    )

    return {
        "status": "created",
        "interface": interface,
        "mac": mac.strip(),
        "ip": ip.strip(),
        "hostname": hostname,
        "uuid": write_result.get("uuid", ""),
    }


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__interfaces__add_dhcp_subnet(
    interface: str,
    subnet: str,
    range_from: str,
    range_to: str,
    dns_servers: str = "",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Add a DHCP subnet (pool) configuration for an interface.

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        interface: Interface name to configure DHCP on (e.g. 'igb1_vlan10').
        subnet: Subnet in CIDR notation (e.g. '192.168.10.0/24').
        range_from: Start of DHCP pool range (e.g. '192.168.10.100').
        range_to: End of DHCP pool range (e.g. '192.168.10.200').
        dns_servers: Comma-separated DNS server addresses.
        apply: Must be True to execute (write gate).

    API endpoint: POST /api/kea/dhcpv4/addSubnet
    """
    if not interface or not interface.strip():
        raise ValidationError(
            "Interface must not be empty.",
            details={"field": "interface"},
        )
    if not subnet or not subnet.strip():
        raise ValidationError(
            "Subnet must not be empty.",
            details={"field": "subnet"},
        )
    if not range_from or not range_from.strip():
        raise ValidationError(
            "Range start must not be empty.",
            details={"field": "range_from"},
        )
    if not range_to or not range_to.strip():
        raise ValidationError(
            "Range end must not be empty.",
            details={"field": "range_to"},
        )

    client = _get_client()
    try:
        subnet_data: dict[str, Any] = {
            "subnet4": {
                "interface": interface.strip(),
                "subnet": subnet.strip(),
                "pools": f"{range_from.strip()}-{range_to.strip()}",
            },
        }
        if dns_servers:
            subnet_data["subnet4"]["option_data_autocollect"] = "0"
            subnet_data["subnet4"]["option_data"] = dns_servers.strip()

        write_result = await client.write(
            "kea", "dhcpv4", "addSubnet",
            data=subnet_data,
        )

        if not is_action_success(write_result):
            raise APIError(
                f"Failed to add DHCP subnet {subnet} on {interface}: "
                f"{write_result.get('result', 'unknown error')}",
                status_code=400,
                endpoint="/api/kea/dhcpv4/addSubnet",
                response_body=str(write_result),
            )

        await client.reconfigure("kea", "dhcpv4")

    finally:
        await client.close()

    logger.info(
        "Added DHCP subnet: %s on %s (range %s-%s, dns=%s)",
        subnet, interface, range_from, range_to, dns_servers,
        extra={"component": "interfaces"},
    )

    return {
        "status": "created",
        "interface": interface.strip(),
        "subnet": subnet.strip(),
        "range_from": range_from.strip(),
        "range_to": range_to.strip(),
        "dns_servers": dns_servers.strip() if dns_servers else "",
        "uuid": write_result.get("uuid", ""),
    }


@mcp_server.tool()
@write_gate("OPNSENSE")
async def opnsense__interfaces__configure_vlan(
    tag: int,
    parent_if: str,
    ip: str,
    subnet: str,
    dhcp_range_from: str = "",
    dhcp_range_to: str = "",
    description: str = "",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Configure a complete VLAN: create VLAN interface, assign IP, and optionally set up DHCP.

    This is an atomic 4-step operation with rollback on failure:
    1. Create VLAN interface
    2. Assign the VLAN to an OPNsense interface
    3. Set IP address on the interface
    4. (Optional) Configure DHCP subnet if range is provided

    Write-gated: requires OPNSENSE_WRITE_ENABLED=true and apply=True.

    Args:
        tag: 802.1Q VLAN tag (1-4094).
        parent_if: Parent physical interface (e.g. 'igb1').
        ip: IP address to assign to this VLAN interface.
        subnet: Subnet mask in CIDR prefix length (e.g. '24').
        dhcp_range_from: Optional start of DHCP pool range.
        dhcp_range_to: Optional end of DHCP pool range.
        description: Human-readable description for this VLAN.
        apply: Must be True to execute (write gate).
    """
    if not 1 <= tag <= 4094:
        raise ValidationError(
            f"VLAN tag must be between 1 and 4094, got {tag}",
            details={"field": "tag", "value": tag},
        )
    if not parent_if or not parent_if.strip():
        raise ValidationError(
            "Parent interface must not be empty.",
            details={"field": "parent_if"},
        )
    if not ip or not ip.strip():
        raise ValidationError(
            "IP address must not be empty.",
            details={"field": "ip"},
        )
    if not subnet or not subnet.strip():
        raise ValidationError(
            "Subnet must not be empty.",
            details={"field": "subnet"},
        )

    # Validate DHCP range: both or neither
    has_dhcp = bool(dhcp_range_from and dhcp_range_to)
    if bool(dhcp_range_from) != bool(dhcp_range_to):
        raise ValidationError(
            "Both dhcp_range_from and dhcp_range_to must be provided together.",
            details={
                "dhcp_range_from": dhcp_range_from,
                "dhcp_range_to": dhcp_range_to,
            },
        )

    completed_steps: list[str] = []
    vlan_uuid: str = ""

    client = _get_client()
    try:
        # Step 1: Create VLAN interface
        vlan_result = await client.write(
            "interfaces", "vlan", "addItem",
            data={
                "vlan": {
                    "if": parent_if.strip(),
                    "tag": str(tag),
                    "descr": description,
                },
            },
        )

        if not is_action_success(vlan_result):
            raise APIError(
                f"Step 1 failed: Could not create VLAN {tag} on {parent_if}: "
                f"{vlan_result.get('result', 'unknown error')}",
                status_code=400,
                endpoint="/api/interfaces/vlan/addItem",
                response_body=str(vlan_result),
            )

        vlan_uuid = vlan_result.get("uuid", "")
        completed_steps.append("create_vlan")

        # Step 2: Reconfigure interfaces to register the new VLAN
        await client.reconfigure("interfaces", "vlan")
        completed_steps.append("reconfigure_vlan")

        # Step 3: Set IP address on the VLAN interface
        # OPNsense assigns interface names like igb1_vlan{tag}
        vlan_if_name = f"{parent_if.strip()}_vlan{tag}"
        ip_result = await client.write(
            "interfaces", "overview", "setItem",
            data={
                "interface": {
                    "if": vlan_if_name,
                    "ipaddr": ip.strip(),
                    "subnet": subnet.strip(),
                    "descr": description,
                    "enable": "1",
                },
            },
        )

        if not is_action_success(ip_result):
            # Rollback: delete the VLAN we just created
            logger.warning(
                "Step 3 failed, rolling back VLAN %d creation (uuid=%s)",
                tag, vlan_uuid,
            )
            if vlan_uuid:
                try:
                    await client.write(
                        "interfaces", "vlan", "delItem",
                        data={"uuid": vlan_uuid},
                    )
                    await client.reconfigure("interfaces", "vlan")
                except Exception:
                    logger.error(
                        "Rollback failed for VLAN %d (uuid=%s)",
                        tag, vlan_uuid,
                        exc_info=True,
                    )

            raise APIError(
                f"Step 3 failed: Could not set IP {ip}/{subnet} on {vlan_if_name}: "
                f"{ip_result.get('result', 'unknown error')}",
                status_code=400,
                endpoint="/api/interfaces/overview/setItem",
                response_body=str(ip_result),
            )

        completed_steps.append("set_ip")

        # Reconfigure to apply IP assignment
        await client.reconfigure("interfaces", "overview")
        completed_steps.append("reconfigure_ip")

        # Step 4 (optional): Configure DHCP
        dhcp_uuid: str = ""
        if has_dhcp:
            dhcp_result = await client.write(
                "kea", "dhcpv4", "addSubnet",
                data={
                    "subnet4": {
                        "interface": vlan_if_name,
                        "subnet": f"{ip.strip()}/{subnet.strip()}",
                        "pools": f"{dhcp_range_from.strip()}-{dhcp_range_to.strip()}",
                    },
                },
            )

            if not is_action_success(dhcp_result):
                logger.warning(
                    "Step 4 failed: DHCP configuration for VLAN %d failed. "
                    "VLAN and IP assignment are still in place.",
                    tag,
                )
                raise APIError(
                    f"Step 4 failed: Could not configure DHCP on {vlan_if_name}: "
                    f"{dhcp_result.get('result', 'unknown error')}. "
                    f"VLAN {tag} and IP {ip}/{subnet} were successfully configured.",
                    status_code=400,
                    endpoint="/api/kea/dhcpv4/addSubnet",
                    response_body=str(dhcp_result),
                )

            dhcp_uuid = dhcp_result.get("uuid", "")
            await client.reconfigure("kea", "dhcpv4")
            completed_steps.append("configure_dhcp")

    finally:
        await client.close()

    logger.info(
        "Configured VLAN %d on %s: ip=%s/%s, dhcp=%s",
        tag, parent_if, ip, subnet,
        f"{dhcp_range_from}-{dhcp_range_to}" if has_dhcp else "none",
        extra={"component": "interfaces"},
    )

    result: dict[str, Any] = {
        "status": "configured",
        "tag": tag,
        "parent_if": parent_if.strip(),
        "ip": ip.strip(),
        "subnet": subnet.strip(),
        "description": description,
        "vlan_uuid": vlan_uuid,
        "completed_steps": completed_steps,
    }

    if has_dhcp:
        result["dhcp_range_from"] = dhcp_range_from.strip()
        result["dhcp_range_to"] = dhcp_range_to.strip()
        result["dhcp_uuid"] = dhcp_uuid

    return result
