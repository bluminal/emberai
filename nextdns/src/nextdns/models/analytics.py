"""Analytics models for NextDNS query statistics.

Maps from NextDNS Analytics API responses to normalized Python
representations. Covers query status breakdowns, top domains, devices,
source IPs, protocol/encryption stats, destinations, and block/allow
reasons.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsStatus(BaseModel):
    """Query counts by resolution status.

    Returned by ``nextdns__analytics__get_status(profile_id)``.

    API field mapping (``GET /profiles/:id/analytics/status``):
        ``default``  -> ``default``  (queries resolved normally)
        ``blocked``  -> ``blocked``
        ``allowed``  -> ``allowed``  (queries explicitly on allowlist)
    """

    model_config = ConfigDict(strict=True)

    default: int = 0
    blocked: int = 0
    allowed: int = 0


class AnalyticsDomain(BaseModel):
    """A top-queried domain entry from analytics.

    Returned by ``nextdns__analytics__get_domains(profile_id)``.
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    name: str
    queries: int
    root: str | None = None


class AnalyticsDevice(BaseModel):
    """A device entry from analytics with query count.

    Returned by ``nextdns__analytics__get_devices(profile_id)``.
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    id: str
    name: str | None = None
    model: str | None = None
    local_ip: str | None = Field(alias="localIp", default=None)
    queries: int = 0


class AnalyticsIP(BaseModel):
    """A source IP entry from analytics with geo and ISP metadata.

    Returned by ``nextdns__analytics__get_ips(profile_id)``.
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    ip: str
    queries: int = 0
    isp: str | None = None
    asn: int | None = None
    country: str | None = None
    city: str | None = None
    is_cellular: bool = Field(alias="isCellular", default=False)
    is_vpn: bool = Field(alias="isVpn", default=False)


class AnalyticsProtocol(BaseModel):
    """DNS protocol breakdown entry (e.g. DoH, DoT, UDP, TCP).

    Returned by ``nextdns__analytics__get_protocols(profile_id)``.
    """

    model_config = ConfigDict(strict=True)

    name: str
    queries: int = 0


class AnalyticsEncryption(BaseModel):
    """Encrypted vs unencrypted query breakdown.

    Returned by ``nextdns__analytics__get_encryption(profile_id)``.
    """

    model_config = ConfigDict(strict=True)

    encrypted: int = 0
    unencrypted: int = 0


class AnalyticsDestination(BaseModel):
    """Destination breakdown entry (countries or GAFAM providers).

    Returned by ``nextdns__analytics__get_destinations(profile_id)``.
    """

    model_config = ConfigDict(strict=True)

    name: str
    queries: int = 0


class AnalyticsReason(BaseModel):
    """Block or allow reason entry with query count.

    Returned by ``nextdns__analytics__get_reasons(profile_id)``.
    """

    model_config = ConfigDict(strict=True)

    name: str
    queries: int = 0
