"""Log entry models for NextDNS DNS query logs.

Maps from NextDNS Logs API responses (GET ``/profiles/:id/logs``)
to normalized Python representations. Each log entry represents a
single DNS query with its resolution status, device info, and
block/allow reasons.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LogDevice(BaseModel):
    """Device information within a DNS query log entry."""

    model_config = ConfigDict(strict=True)

    id: str | None = None
    name: str | None = None
    model: str | None = None


class LogReason(BaseModel):
    """Reason a DNS query was blocked or explicitly allowed.

    References either a blocklist ID (e.g. 'nextdns-recommended'),
    a parental control rule, or an allowlist entry.
    """

    model_config = ConfigDict(strict=True)

    id: str
    name: str | None = None


class LogEntry(BaseModel):
    """A single DNS query log entry.

    Returned by ``nextdns__logs__search(profile_id)``.

    API field mapping (``GET /profiles/:id/logs``):
        ``timestamp`` -> ``timestamp``  (ISO 8601)
        ``domain``    -> ``domain``
        ``root``      -> ``root``       (root domain if different)
        ``tracker``   -> ``tracker``    (tracker provider name)
        ``encrypted`` -> ``encrypted``
        ``protocol``  -> ``protocol``
        ``clientIp``  -> ``client_ip``
        ``client``    -> ``client``
        ``device``    -> ``device``
        ``status``    -> ``status``     ('default', 'blocked', 'allowed', 'error')
        ``reasons``   -> ``reasons``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    timestamp: str
    domain: str
    root: str | None = None
    tracker: str | None = None
    encrypted: bool = False
    protocol: str | None = None
    client_ip: str | None = Field(alias="clientIp", default=None)
    client: str | None = None
    device: LogDevice | None = None
    status: str = "default"
    reasons: list[LogReason] = Field(default_factory=list)
