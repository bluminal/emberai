"""Profile models for NextDNS configuration data.

Maps from NextDNS API responses (GET ``https://api.nextdns.io/profiles/:id``)
to normalized Python representations. Covers the full profile configuration
including security, privacy, parental controls, deny/allow lists, and
performance settings.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Security settings
# ---------------------------------------------------------------------------


class BlockedTLD(BaseModel):
    """A blocked top-level domain entry (e.g. 'ru', 'cn')."""

    model_config = ConfigDict(strict=True)

    id: str


class SecuritySettings(BaseModel):
    """Security toggles and blocked TLDs for a NextDNS profile.

    Controls threat protection features such as AI threat detection,
    Google Safe Browsing, cryptojacking protection, and more.
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    threat_intelligence_feeds: bool = Field(
        alias="threatIntelligenceFeeds", default=False
    )
    ai_threat_detection: bool = Field(alias="aiThreatDetection", default=False)
    google_safe_browsing: bool = Field(alias="googleSafeBrowsing", default=False)
    cryptojacking: bool = False
    dns_rebinding: bool = Field(alias="dnsRebinding", default=False)
    idn_homographs: bool = Field(alias="idnHomographs", default=False)
    typosquatting: bool = False
    dga: bool = False
    nrd: bool = False
    ddns: bool = False
    parking: bool = False
    csam: bool = False
    tlds: list[BlockedTLD] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Privacy settings
# ---------------------------------------------------------------------------


class Blocklist(BaseModel):
    """A privacy blocklist entry (e.g. 'nextdns-recommended', 'oisd')."""

    model_config = ConfigDict(strict=True)

    id: str


class NativeTracker(BaseModel):
    """A native OS tracker entry (e.g. 'huawei', 'samsung')."""

    model_config = ConfigDict(strict=True)

    id: str


class PrivacySettings(BaseModel):
    """Privacy controls for a NextDNS profile.

    Manages ad/tracker blocklists, native OS tracker blocking,
    disguised tracker detection, and affiliate link handling.
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    blocklists: list[Blocklist] = Field(default_factory=list)
    natives: list[NativeTracker] = Field(default_factory=list)
    disguised_trackers: bool = Field(alias="disguisedTrackers", default=False)
    allow_affiliate: bool = Field(alias="allowAffiliate", default=False)


# ---------------------------------------------------------------------------
# Parental control settings
# ---------------------------------------------------------------------------


class ParentalService(BaseModel):
    """A parental control service entry (e.g. 'tiktok', 'facebook')."""

    model_config = ConfigDict(strict=True)

    id: str
    active: bool = True


class ParentalCategory(BaseModel):
    """A parental control category entry (e.g. 'porn', 'social-networks')."""

    model_config = ConfigDict(strict=True)

    id: str
    active: bool = True


class ParentalControlSettings(BaseModel):
    """Parental control configuration for a NextDNS profile.

    Controls blocked services, content categories, safe search,
    YouTube restricted mode, and bypass prevention.
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    services: list[ParentalService] = Field(default_factory=list)
    categories: list[ParentalCategory] = Field(default_factory=list)
    safe_search: bool = Field(alias="safeSearch", default=False)
    youtube_restricted_mode: bool = Field(
        alias="youtubeRestrictedMode", default=False
    )
    block_bypass: bool = Field(alias="blockBypass", default=False)


# ---------------------------------------------------------------------------
# Deny/allow list entries
# ---------------------------------------------------------------------------


class DenylistEntry(BaseModel):
    """An entry in the profile's denylist (blocked domain)."""

    model_config = ConfigDict(strict=True)

    id: str
    active: bool = True


class AllowlistEntry(BaseModel):
    """An entry in the profile's allowlist (explicitly permitted domain)."""

    model_config = ConfigDict(strict=True)

    id: str
    active: bool = True


# ---------------------------------------------------------------------------
# Profile settings (logs, block page, performance, web3)
# ---------------------------------------------------------------------------


class LogDropSettings(BaseModel):
    """Controls which fields are dropped from DNS query logs."""

    model_config = ConfigDict(strict=True)

    ip: bool = False
    domain: bool = False


class LogSettings(BaseModel):
    """DNS query logging configuration."""

    model_config = ConfigDict(strict=True)

    enabled: bool = True
    drop: LogDropSettings | None = None
    retention: int | None = None
    location: str | None = None


class BlockPageSettings(BaseModel):
    """Block page display configuration."""

    model_config = ConfigDict(strict=True)

    enabled: bool = False


class PerformanceSettings(BaseModel):
    """DNS performance optimization settings.

    Controls EDNS Client Subnet (ECS), cache boosting, and CNAME
    flattening features.
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    ecs: bool = False
    cache_boost: bool = Field(alias="cacheBoost", default=False)
    cname_flattening: bool = Field(alias="cnameFlattening", default=False)


class ProfileSettings(BaseModel):
    """Top-level settings block within a NextDNS profile."""

    model_config = ConfigDict(strict=True, populate_by_name=True)

    logs: LogSettings = Field(default_factory=LogSettings)
    block_page: BlockPageSettings = Field(
        alias="blockPage", default_factory=BlockPageSettings
    )
    performance: PerformanceSettings = Field(
        default_factory=PerformanceSettings
    )
    web3: bool = False


# ---------------------------------------------------------------------------
# Top-level profile model
# ---------------------------------------------------------------------------


class Profile(BaseModel):
    """A NextDNS configuration profile.

    Returned by ``nextdns__profiles__list_profiles()`` and
    ``nextdns__profiles__get_profile(profile_id)``.

    The profile is the top-level organizational unit in NextDNS. Each
    profile has its own security, privacy, parental control, deny/allow
    list, and performance settings.

    API field mapping (``GET /profiles`` / ``GET /profiles/:id``):
        ``id``              -> ``id``
        ``name``            -> ``name``
        ``security``        -> ``security``
        ``privacy``         -> ``privacy``
        ``parentalControl`` -> ``parental_control``
        ``denylist``        -> ``denylist``
        ``allowlist``       -> ``allowlist``
        ``settings``        -> ``settings``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    id: str
    name: str
    security: SecuritySettings
    privacy: PrivacySettings
    parental_control: ParentalControlSettings = Field(alias="parentalControl")
    denylist: list[DenylistEntry] = Field(default_factory=list)
    allowlist: list[AllowlistEntry] = Field(default_factory=list)
    settings: ProfileSettings
