"""Security models for OPNsense IDS/IPS and certificate data.

Maps from OPNsense API responses for Suricata IDS alerts and TLS
certificates to normalized Python representations.
"""

from pydantic import BaseModel, ConfigDict, Field


class IDSAlert(BaseModel):
    """An OPNsense Suricata IDS alert.

    Returned by ``opnsense__security__get_ids_alerts()``.

    API field mapping (``/api/ids/service/queryAlerts``):
        ``timestamp``   -> ``timestamp``
        ``alert``       -> ``signature``  (nested: alert.signature)
        ``alert_cat``   -> ``category``   (nested: alert.category)
        ``alert_sev``   -> ``severity``   (nested: alert.severity)
        ``src_ip``      -> ``src_ip``
        ``dest_ip``     -> ``dst_ip``
        ``proto``       -> ``proto``
        ``action``      -> ``action``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    timestamp: str = Field(
        description="Alert timestamp in ISO 8601 format",
    )
    signature: str = Field(
        default="",
        alias="alert",
        description="IDS rule signature that triggered this alert",
    )
    category: str = Field(
        default="",
        alias="alert_cat",
        description="Alert category (e.g. 'Attempted Information Leak')",
    )
    severity: int = Field(
        default=3,
        alias="alert_sev",
        description="Alert severity level (1=high, 2=medium, 3=low)",
    )
    src_ip: str = Field(
        default="",
        description="Source IP address that triggered the alert",
    )
    dst_ip: str = Field(
        default="",
        alias="dest_ip",
        description="Destination IP address",
    )
    proto: str = Field(
        default="",
        description="Network protocol (e.g. 'TCP', 'UDP', 'ICMP')",
    )
    action: str = Field(
        default="alert",
        description="Action taken: 'alert' (logged only) or 'drop' (blocked)",
    )


class Certificate(BaseModel):
    """An OPNsense TLS certificate from the trust store.

    Returned by ``opnsense__security__get_certificates()``.

    API field mapping (``/api/trust/cert/search``):
        ``cn``              -> ``cn``
        ``san``             -> ``san``
        ``issuer``          -> ``issuer``
        ``valid_from``      -> ``not_before``
        ``valid_to``        -> ``not_after``
        ``days_left``       -> ``days_until_expiry``
        ``in_use``          -> ``in_use_for``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    cn: str = Field(
        description="Common Name of the certificate",
    )
    san: list[str] = Field(
        default_factory=list,
        description="Subject Alternative Names (domains, IPs)",
    )
    issuer: str = Field(
        default="",
        description="Certificate issuer (CA) common name",
    )
    not_before: str = Field(
        default="",
        alias="valid_from",
        description="Certificate validity start date",
    )
    not_after: str = Field(
        default="",
        alias="valid_to",
        description="Certificate validity end date",
    )
    days_until_expiry: int | None = Field(
        default=None,
        alias="days_left",
        description="Days remaining until certificate expires (negative = expired)",
    )
    in_use_for: list[str] = Field(
        default_factory=list,
        alias="in_use",
        description="Services currently using this certificate (e.g. ['webgui', 'openvpn'])",
    )
