"""Event model for UniFi health/event data.

Maps from UniFi Local Gateway API responses
(GET ``{local}/api/s/{site}/stat/event``) to a normalized Python
representation.
"""

from pydantic import BaseModel, ConfigDict, Field

from unifi.models._types import FlexibleDatetime


class Event(BaseModel):
    """A network event (alarm, state change, notification).

    Returned by ``unifi__health__get_events(site_id, hours, severity)``.

    API field mapping (Local Gateway ``/stat/event``):
        ``datetime``     -> ``timestamp``  (ISO 8601 string -> datetime)
        ``key``          -> ``type``
        ``msg``          -> ``message``
        ``subsystem``    -> ``subsystem``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    timestamp: FlexibleDatetime = Field(
        alias="datetime",
        description="When the event occurred (UTC)",
    )
    type: str = Field(
        alias="key",
        description="Event type key (e.g. 'EVT_AP_Connected', 'EVT_SW_Lost_Contact')",
    )
    severity: str = Field(
        default="info",
        description="Event severity: 'critical', 'warning', or 'info'",
    )
    message: str = Field(
        alias="msg",
        description="Human-readable event message",
    )
    subsystem: str = Field(
        default="",
        description="Subsystem that generated the event (e.g. 'wlan', 'lan', 'www')",
    )

    # --- Optional context fields ---

    device_id: str | None = Field(
        default=None,
        alias="sw",
        description="Device identifier associated with this event (if applicable)",
    )
    client_mac: str | None = Field(
        default=None,
        alias="user",
        description="Client MAC address associated with this event (if applicable)",
    )
