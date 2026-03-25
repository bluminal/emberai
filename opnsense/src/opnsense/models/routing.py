"""Routing models for OPNsense static routes and gateways.

Maps from OPNsense API responses for routes and gateways to normalized
Python representations.
"""

from pydantic import BaseModel, ConfigDict, Field


class Route(BaseModel):
    """An OPNsense static route entry.

    Returned by ``opnsense__routing__list_routes()``.

    API field mapping (``/api/routes/routes/searchRoute``):
        ``uuid``        -> ``uuid``
        ``network``     -> ``network``
        ``gateway``     -> ``gateway``
        ``descr``       -> ``description``
        ``disabled``    -> ``disabled``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    uuid: str = Field(
        description="Unique identifier for this route",
    )
    network: str = Field(
        description="Destination network in CIDR notation (e.g. '10.0.0.0/8')",
    )
    gateway: str = Field(
        description="Gateway name or address for this route",
    )
    description: str = Field(
        default="",
        alias="descr",
        description="Human-readable route description",
    )
    disabled: bool = Field(
        default=False,
        description="Whether the route is administratively disabled",
    )


class Gateway(BaseModel):
    """An OPNsense gateway (next-hop for routing).

    Returned by ``opnsense__routing__list_gateways()``.

    API field mapping (``/api/routes/gateway/status``):
        ``name``        -> ``name``
        ``address``     -> ``gateway``
        ``interface``   -> ``interface``
        ``monitor``     -> ``monitor``
        ``status``      -> ``status``
        ``priority``    -> ``priority``
        ``delay``       -> ``rtt_ms``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    name: str = Field(
        description="Gateway name (e.g. 'WAN_GW', 'LAN_GW')",
    )
    gateway: str = Field(
        default="",
        alias="address",
        description="Gateway IP address",
    )
    interface: str = Field(
        default="",
        description="Interface this gateway is bound to",
    )
    monitor: str = Field(
        default="",
        description="Monitor IP used for gateway health checks",
    )
    status: str = Field(
        default="",
        description="Gateway status (e.g. 'online', 'offline', 'unknown')",
    )
    priority: int = Field(
        default=255,
        description="Gateway priority (lower = preferred)",
    )
    rtt_ms: float | None = Field(
        default=None,
        alias="delay",
        description="Round-trip time to monitor IP in milliseconds",
    )


class GatewayGroupMember(BaseModel):
    """A single member entry within an OPNsense gateway group.

    Each member associates a gateway with a priority tier and weight
    for load balancing or failover within the group.
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    gateway: str = Field(
        description="Gateway name (e.g. 'WAN_DHCP', 'WAN2_DHCP')",
    )
    tier: int = Field(
        default=1,
        description="Priority tier (1 = highest priority, 5 = lowest). "
        "Gateways in the same tier are load-balanced; lower tiers are failover targets.",
    )
    weight: int = Field(
        default=1,
        description="Load-balancing weight within the same tier (1-5)",
    )


class GatewayGroup(BaseModel):
    """An OPNsense gateway group for failover or load balancing.

    Returned by ``opnsense__routing__list_gateway_groups()``.

    API field mapping (``/api/routes/gateway/searchgroup``):
        ``uuid``        -> ``uuid``
        ``name``        -> ``name``
        ``trigger``     -> ``trigger``
        ``members``     -> ``members``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    uuid: str = Field(
        description="Unique identifier for this gateway group",
    )
    name: str = Field(
        description="Gateway group name (e.g. 'WAN1_Failover')",
    )
    trigger: str = Field(
        default="down",
        description="Failover trigger: 'down', 'packet_loss', "
        "'high_latency', or 'packet_loss_high_latency'",
    )
    members: list[GatewayGroupMember] = Field(
        default_factory=list,
        description="Ordered list of gateway members with tier and weight",
    )
