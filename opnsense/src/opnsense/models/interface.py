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
        description="Interface identifier (e.g. 'igb0', 'vtnet1', 'opt1')",
    )
    description: str = Field(
        default="",
        description="User-assigned interface description (e.g. 'LAN', 'WAN', 'DMZ')",
    )
    ip: str = Field(
        default="",
        alias="addr4",
        description="IPv4 address assigned to this interface",
    )
    subnet: str = Field(
        default="",
        alias="subnet4",
        description="IPv4 subnet mask or CIDR prefix length",
    )
    if_type: str = Field(
        default="",
        alias="type",
        description="Interface type (e.g. 'ethernet', 'vlan', 'bridge', 'lagg')",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the interface is administratively enabled",
    )
    vlan_id: int | None = Field(
        default=None,
        alias="vlan_tag",
        description="VLAN tag ID if this is a VLAN interface (e.g. 10, 20, 100)",
    )
