"""VLAN model for UniFi network configuration data.

Maps from UniFi Local Gateway API responses
(GET ``{local}/api/s/{site}/rest/networkconf``) to a normalized Python
representation.
"""

from pydantic import BaseModel, ConfigDict, Field


class VLAN(BaseModel):
    """A VLAN / network configuration entry.

    Returned by ``unifi__topology__get_vlans(site_id)``.

    API field mapping (Local Gateway ``/rest/networkconf``):
        ``_id``              -> ``vlan_id``
        ``name``             -> ``name``
        ``ip_subnet``        -> ``subnet``
        ``purpose``          -> ``purpose``
        ``dhcpd_enabled``    -> ``dhcp_enabled``
        ``domain_name``      -> ``domain_name``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    vlan_id: str = Field(alias="_id", description="Unique network/VLAN identifier")
    name: str = Field(description="Human-readable network name")
    subnet: str = Field(
        default="",
        alias="ip_subnet",
        description="IP subnet in CIDR notation (e.g. '192.168.1.0/24')",
    )
    purpose: str = Field(
        default="corporate",
        description="Network purpose (e.g. 'corporate', 'guest', 'vlan-only')",
    )
    dhcp_enabled: bool = Field(
        default=False,
        alias="dhcpd_enabled",
        description="Whether the built-in DHCP server is enabled for this network",
    )
    domain_name: str | None = Field(
        default=None,
        description="DNS domain name assigned to this network",
    )
