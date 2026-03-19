"""Client model for UniFi client data.

Maps from UniFi Local Gateway API responses
(GET ``{local}/api/s/{site}/stat/sta``) to a normalized Python representation.
"""

from pydantic import BaseModel, ConfigDict, Field

from unifi.models._types import FlexibleDatetime


class Client(BaseModel):
    """A connected network client (wired or wireless).

    Returned by ``unifi__clients__list_clients(site_id)`` (summary fields)
    and ``unifi__clients__get_client(client_mac, site_id)`` (full detail
    including optional fields).

    API field mapping (Local Gateway ``/stat/sta``):
        ``mac``          -> ``client_mac``
        ``hostname``     -> ``hostname``
        ``ip``           -> ``ip``
        ``network_id``   -> ``vlan_id``
        ``ap_mac``       -> ``ap_id``
        ``sw_port``      -> ``port_id``
        ``is_wired``     -> ``is_wired``
        ``is_guest``     -> ``is_guest``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    # --- Core fields (always present in list responses) ---

    client_mac: str = Field(
        alias="mac",
        description="Client MAC address (unique identifier)",
    )
    hostname: str | None = Field(
        default=None,
        description="Client-reported hostname (may be absent)",
    )
    ip: str = Field(description="Assigned IP address")
    vlan_id: str = Field(
        alias="network_id",
        description="Network/VLAN identifier the client is connected to",
    )
    ap_id: str | None = Field(
        default=None,
        alias="ap_mac",
        description="MAC of the AP the client is associated with (wireless only)",
    )
    port_id: int | None = Field(
        default=None,
        alias="sw_port",
        description="Switch port index the client is connected to (wired only)",
    )
    connection_type: str = Field(
        default="",
        description="Connection type description (e.g. 'wifi', 'wired')",
    )
    is_wired: bool = Field(
        default=False,
        description="Whether the client is connected via Ethernet",
    )
    is_guest: bool = Field(
        default=False,
        description="Whether the client is on a guest network",
    )
    uptime: int = Field(
        default=0,
        description="Client session uptime in seconds",
    )

    # --- Detail fields (present in get_client responses) ---

    ssid: str | None = Field(
        default=None,
        description="SSID the wireless client is connected to",
    )
    rssi: int | None = Field(
        default=None,
        description="Received signal strength indicator (dBm)",
    )
    tx_bytes: int | None = Field(
        default=None,
        description="Total bytes transmitted by the client",
    )
    rx_bytes: int | None = Field(
        default=None,
        description="Total bytes received by the client",
    )
    first_seen: FlexibleDatetime | None = Field(
        default=None,
        description="Timestamp when the client was first seen on the network",
    )
    last_seen: FlexibleDatetime | None = Field(
        default=None,
        description="Timestamp when the client was last seen on the network",
    )
    os_name: str | None = Field(
        default=None,
        description="Detected operating system name",
    )
    device_vendor: str | None = Field(
        default=None,
        alias="oui",
        description="Device vendor derived from MAC OUI lookup",
    )
    is_blocked: bool | None = Field(
        default=None,
        alias="blocked",
        description="Whether the client is blocked from network access",
    )
