"""Service models for OPNsense DHCP and DNS data.

Maps from OPNsense API responses for DHCP leases (Kea) and DNS overrides
(Unbound) to normalized Python representations.
"""

from pydantic import BaseModel, ConfigDict, Field


class DHCPLease(BaseModel):
    """An OPNsense DHCP lease from the Kea DHCP server.

    Returned by ``opnsense__services__get_dhcp_leases4()`` and
    ``opnsense__interfaces__get_dhcp_leases()``.

    API field mapping (``/api/kea/leases4/search``):
        ``hw_address``  -> ``mac``
        ``address``     -> ``ip``
        ``hostname``    -> ``hostname``
        ``expire``      -> ``expiry``
        ``state``       -> ``state``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    mac: str = Field(
        alias="hw_address",
        description="Client MAC address",
    )
    ip: str = Field(
        alias="address",
        description="Leased IPv4 address",
    )
    hostname: str = Field(
        default="",
        description="Client hostname (from DHCP request, may be empty)",
    )
    expiry: str = Field(
        default="",
        alias="expire",
        description="Lease expiration timestamp",
    )
    state: str = Field(
        default="",
        description="Lease state (e.g. 'active', 'expired', 'declined')",
    )
    interface: str = Field(
        default="",
        description="Interface the lease was granted on",
    )


class DNSOverride(BaseModel):
    """An OPNsense Unbound DNS host override.

    Returned by ``opnsense__services__get_dns_overrides()``.

    API field mapping (``/api/unbound/host/searchHost``):
        ``uuid``        -> ``uuid``
        ``hostname``    -> ``hostname``
        ``domain``      -> ``domain``
        ``server``      -> ``ip``
        ``description`` -> ``description``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    uuid: str = Field(
        description="Unique identifier for this DNS override",
    )
    hostname: str = Field(
        description="Hostname portion (e.g. 'nas' for nas.home.local)",
    )
    domain: str = Field(
        default="",
        description="Domain portion (e.g. 'home.local')",
    )
    ip: str = Field(
        default="",
        alias="server",
        description="IP address this hostname resolves to",
    )
    description: str = Field(
        default="",
        description="Human-readable description of this override",
    )
