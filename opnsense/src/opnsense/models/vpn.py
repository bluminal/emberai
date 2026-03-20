"""VPN models for OPNsense IPSec, WireGuard, and OpenVPN.

Maps from OPNsense API responses for VPN sessions and peers to normalized
Python representations.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IPSecSession(BaseModel):
    """An OPNsense IPSec tunnel session.

    Returned by ``opnsense__vpn__list_ipsec_sessions()``.

    API field mapping (``/api/ipsec/sessions/search``):
        ``id``              -> ``session_id``
        ``description``     -> ``description``
        ``connected``       -> ``status``
        ``local-ts``        -> ``local_ts``
        ``remote-ts``       -> ``remote_ts``
        ``bytes-in``        -> ``rx_bytes``
        ``bytes-out``       -> ``tx_bytes``
        ``established``     -> ``established_at``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    session_id: str = Field(
        alias="id",
        description="Unique session identifier",
    )
    description: str = Field(
        default="",
        description="Human-readable tunnel description",
    )
    status: str = Field(
        default="unknown",
        alias="connected",
        description="Tunnel status (e.g. 'connected', 'disconnected', 'connecting')",
    )
    local_ts: str = Field(
        default="",
        alias="local-ts",
        description="Local traffic selector (subnet/range)",
    )
    remote_ts: str = Field(
        default="",
        alias="remote-ts",
        description="Remote traffic selector (subnet/range)",
    )
    rx_bytes: int = Field(
        default=0,
        alias="bytes-in",
        description="Bytes received through this tunnel",
    )
    tx_bytes: int = Field(
        default=0,
        alias="bytes-out",
        description="Bytes transmitted through this tunnel",
    )
    established_at: datetime | None = Field(
        default=None,
        alias="established",
        description="Timestamp when the tunnel was established",
    )


class WireGuardPeer(BaseModel):
    """An OPNsense WireGuard peer.

    Returned by ``opnsense__vpn__list_wireguard_peers()``.

    API field mapping (``/api/wireguard/client/search``):
        ``uuid``            -> ``uuid``
        ``name``            -> ``name``
        ``pubkey``          -> ``public_key``
        ``endpoint``        -> ``endpoint``
        ``tunneladdress``   -> ``allowed_ips``
        ``lasthandshake``   -> ``last_handshake``
        ``transferrx``      -> ``rx_bytes``
        ``transfertx``      -> ``tx_bytes``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    uuid: str = Field(
        description="Unique identifier for this WireGuard peer",
    )
    name: str = Field(
        default="",
        description="Peer display name",
    )
    public_key: str = Field(
        default="",
        alias="pubkey",
        description="WireGuard public key of this peer",
    )
    endpoint: str | None = Field(
        default=None,
        description="Peer endpoint address:port (empty for roaming peers)",
    )
    allowed_ips: str = Field(
        default="",
        alias="tunneladdress",
        description="Comma-separated list of allowed IP ranges for this peer",
    )
    last_handshake: str | None = Field(
        default=None,
        alias="lasthandshake",
        description="Timestamp of last successful handshake",
    )
    rx_bytes: int | None = Field(
        default=None,
        alias="transferrx",
        description="Bytes received from this peer",
    )
    tx_bytes: int | None = Field(
        default=None,
        alias="transfertx",
        description="Bytes transmitted to this peer",
    )


class OpenVPNInstance(BaseModel):
    """An OPNsense OpenVPN instance (server or client).

    Returned by ``opnsense__vpn__list_openvpn_instances()``.

    API field mapping (``/api/openvpn/instances/search``):
        ``uuid``        -> ``uuid``
        ``description`` -> ``description``
        ``role``        -> ``role``
        ``dev_type``    -> ``dev_type``
        ``proto``       -> ``protocol``
        ``port``        -> ``port``
        ``enabled``     -> ``enabled``
        ``clients``     -> ``connected_clients``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    uuid: str = Field(
        description="Unique identifier for this OpenVPN instance",
    )
    description: str = Field(
        default="",
        description="Human-readable instance description",
    )
    role: str = Field(
        default="",
        description="Instance role: 'server' or 'client'",
    )
    dev_type: str = Field(
        default="tun",
        description="Virtual device type: 'tun' (routed) or 'tap' (bridged)",
    )
    protocol: str = Field(
        default="udp",
        alias="proto",
        description="Transport protocol: 'udp' or 'tcp'",
    )
    port: int | None = Field(
        default=None,
        description="Listening port number (servers) or connect port (clients)",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this instance is administratively enabled",
    )
    connected_clients: int | None = Field(
        default=None,
        alias="clients",
        description="Number of currently connected clients (servers only)",
    )
