"""VLAN interface model for OPNsense VLAN definitions.

Maps from OPNsense API responses
(GET ``/api/interfaces/vlan/searchItem``) to a normalized Python
representation.
"""

from pydantic import BaseModel, ConfigDict, Field


class VLANInterface(BaseModel):
    """An OPNsense VLAN interface definition.

    Returned by ``opnsense__interfaces__list_vlan_interfaces()``.

    API field mapping (``/api/interfaces/vlan/searchItem``):
        ``uuid``    -> ``uuid``
        ``tag``     -> ``tag``
        ``if``      -> ``if_``  (renamed to avoid Python keyword conflict)
        ``descr``   -> ``description``
        ``vlanif``  -> ``parent_if``
        ``pcp``     -> ``pcp``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    uuid: str = Field(
        description="Unique identifier for this VLAN interface definition",
    )
    tag: int = Field(
        description="802.1Q VLAN tag (1-4094)",
    )
    if_: str = Field(
        alias="if",
        description="Assigned interface name (e.g. 'vlan01', 'igb0_vlan10')",
    )
    description: str = Field(
        default="",
        alias="descr",
        description="User-assigned description for this VLAN",
    )
    parent_if: str = Field(
        alias="vlanif",
        description="Parent physical interface (e.g. 'igb0', 'vtnet0')",
    )
    pcp: int | None = Field(
        default=None,
        description="802.1Q Priority Code Point (0-7) for QoS tagging",
    )
