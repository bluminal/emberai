"""Interface model for OPNsense network interfaces.

Maps from OPNsense API responses
(GET ``/api/interfaces/overview/export``) to a normalized Python
representation.
"""

from pydantic import BaseModel, ConfigDict, Field


class Interface(BaseModel):
    """An OPNsense network interface.

    Returned by ``opnsense__interfaces__list_interfaces()``.

    API field mapping (``/api/interfaces/overview/export``):
        ``name``         -> ``name``
        ``description``  -> ``description``
        ``addr4``        -> ``ip``
        ``subnet4``      -> ``subnet``
        ``type``         -> ``if_type``
        ``status``       -> ``enabled``
        ``vlan_tag``     -> ``vlan_id``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    name: str = Field(
        default="",
        alias="device",
        description="Interface device name (e.g. 'igb0', 'vtnet1')",
    )
    description: str = Field(
        default="",
        description="User-assigned interface description (e.g. 'LAN', 'WAN', 'DMZ')",
    )
    identifier: str = Field(
        default="",
        description="OPNsense interface identifier (e.g. 'wan', 'lan', 'opt1')",
    )
    ip: str = Field(
        default="",
        alias="addr4",
        description="IPv4 address with CIDR (e.g. '10.10.10.1/24')",
    )
    subnet: str = Field(
        default="",
        alias="subnet4",
        description="IPv4 subnet mask or CIDR prefix length",
    )
    if_type: str = Field(
        default="",
        alias="type",
        description="Link type (e.g. 'dhcp', 'static', 'none')",
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
