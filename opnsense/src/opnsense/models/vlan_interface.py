"""VLAN interface model for OPNsense VLAN definitions.

Maps from OPNsense API responses
(GET ``/api/interfaces/vlan_settings/searchItem``) to a normalized Python
representation.

OPNsense 26.x field semantics
------------------------------
- ``if``     -- parent physical interface (e.g. ``"igb1"``)
- ``vlanif`` -- VLAN device name (e.g. ``"vlan0.10"``)
- ``tag``    -- 802.1Q tag, returned as a **string** (e.g. ``"10"``)
- ``pcp``    -- Priority Code Point, returned as a **string** (e.g. ``"0"``)
- ``descr``  -- user description
- ``proto``  -- protocol (typically empty string)
"""

from pydantic import BaseModel, ConfigDict, Field


class VLANInterface(BaseModel):
    """An OPNsense VLAN interface definition.

    Returned by ``opnsense__interfaces__list_vlan_interfaces()``.

    OPNsense 26.x API field mapping
    (``/api/interfaces/vlan_settings/searchItem``):

        ``uuid``    -> ``uuid``
        ``tag``     -> ``tag``       (coerced from str to int)
        ``if``      -> ``parent_if`` (parent physical interface)
        ``descr``   -> ``description``
        ``vlanif``  -> ``device``    (VLAN device name, e.g. ``vlan0.10``)
        ``pcp``     -> ``pcp``       (coerced from str to int)
        ``proto``   -> ``proto``     (optional, typically empty)
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    uuid: str = Field(
        description="Unique identifier for this VLAN interface definition",
    )
    tag: int = Field(
        description="802.1Q VLAN tag (1-4094)",
    )
    parent_if: str = Field(
        alias="if",
        description="Parent physical interface (e.g. 'igb0', 'igb1', 'vtnet0')",
    )
    description: str = Field(
        default="",
        alias="descr",
        description="User-assigned description for this VLAN",
    )
    device: str = Field(
        alias="vlanif",
        description="VLAN device name (e.g. 'vlan0.10', 'igb1_vlan10')",
    )
    pcp: int | None = Field(
        default=None,
        description="802.1Q Priority Code Point (0-7) for QoS tagging",
    )
    proto: str = Field(
        default="",
        description="Protocol field (typically empty on 26.x)",
    )
