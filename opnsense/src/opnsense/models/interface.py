"""Interface model for OPNsense network interfaces.

Maps from the OPNsense 26.x ``/api/interfaces/overview/interfacesInfo``
response to a normalized Python representation.  This endpoint returns a flat
dict keyed by logical interface name (``wan``, ``lan``, ``opt1``, etc.)
with each value containing device, description, IP, and status fields.

Previous versions used ``/api/interfaces/overview/export`` which returned a
search-style ``rows`` array.  The model accepts both formats -- see the
``interface_from_info`` factory function for 26.x parsing.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Interface(BaseModel):
    """An OPNsense network interface.

    Returned by ``opnsense__interfaces__list_interfaces()``.

    Field mapping (``/api/interfaces/overview/interfacesInfo``):
        dict key     -> ``name``  (logical name: wan, lan, opt1, ...)
        ``device``   -> ``device`` (physical: igb0, igb1_vlan10, ...)
        ``description`` -> ``description``
        ``identifier``  -> ``identifier``
        ``addr4``    -> ``ip``
        ``subnet4``  -> ``subnet``
        ``type``     -> ``if_type``
        ``enabled``  -> ``enabled``
        ``status``   -> ``status``
        ``vlan_tag`` -> ``vlan_id``
    """

    model_config = ConfigDict(strict=False, populate_by_name=True)

    name: str = Field(
        default="",
        description=("Logical interface name assigned by OPNsense (e.g. 'wan', 'lan', 'opt1')"),
    )
    device: str = Field(
        default="",
        description="Physical/OS device name (e.g. 'igb0', 'igb1_vlan10')",
    )
    description: str = Field(
        default="",
        description="User-assigned interface description (e.g. 'LAN', 'WAN', 'DMZ')",
    )
    identifier: str = Field(
        default="",
        description=(
            "OPNsense interface identifier -- often same as name (e.g. 'wan', 'lan', 'opt1')"
        ),
    )
    ip: str = Field(
        default="",
        alias="addr4",
        description="IPv4 address (e.g. '192.168.1.1')",
    )
    subnet: str = Field(
        default="",
        alias="subnet4",
        description="IPv4 subnet mask or CIDR prefix length (e.g. '24')",
    )
    if_type: str = Field(
        default="",
        alias="type",
        description="Interface type (e.g. 'dhcp', 'static', 'none')",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the interface is administratively enabled",
    )
    status: str = Field(
        default="",
        description="Operational status (e.g. 'up', 'down', 'no carrier')",
    )
    vlan_id: int | None = Field(
        default=None,
        alias="vlan_tag",
        description="VLAN tag ID if this is a VLAN interface",
    )


def interface_from_info(logical_name: str, data: dict[str, Any]) -> Interface:
    """Create an Interface from a single entry in the interfacesInfo response.

    This is the factory function for the OPNsense 26.x
    ``/api/interfaces/overview/interfacesInfo`` endpoint.  The endpoint
    returns a flat dict keyed by logical interface name; each value is
    a dict with device details.

    Parameters
    ----------
    logical_name:
        The dict key from the interfacesInfo response (e.g. 'wan', 'opt3').
    data:
        The interface detail dict for this entry.

    Returns
    -------
    Interface
        A populated Interface model instance.
    """
    return Interface.model_validate(
        {
            "name": logical_name,
            "device": data.get("device", ""),
            "description": data.get("description", ""),
            "identifier": data.get("identifier", logical_name),
            "addr4": data.get("addr4", ""),
            "subnet4": data.get("subnet4", ""),
            "type": data.get("type", ""),
            "enabled": data.get("enabled", True),
            "status": data.get("status", ""),
            "vlan_tag": data.get("vlan_tag"),
        },
    )
