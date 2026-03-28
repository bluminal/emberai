"""NextDNS data models.

Re-exports all Pydantic models used to normalize NextDNS API responses into
clean Python objects. Every model uses strict mode and field aliases so that
raw API payloads can be parsed directly while downstream code uses
Pythonic attribute names.

Usage::

    from nextdns.models import Profile, SecuritySettings, LogEntry
    from nextdns.models import AnalyticsStatus, AnalyticsDomain

    profile = Profile.model_validate(raw_api_response)
    print(profile.parental_control.safe_search)  # normalized field name
"""

from nextdns.models.analytics import (
    AnalyticsDestination,
    AnalyticsDevice,
    AnalyticsDomain,
    AnalyticsEncryption,
    AnalyticsIP,
    AnalyticsProtocol,
    AnalyticsReason,
    AnalyticsStatus,
)
from nextdns.models.logs import LogDevice, LogEntry, LogReason
from nextdns.models.profile import (
    AllowlistEntry,
    BlockedTLD,
    Blocklist,
    BlockPageSettings,
    DenylistEntry,
    LogDropSettings,
    LogSettings,
    NativeTracker,
    ParentalCategory,
    ParentalControlSettings,
    ParentalService,
    PerformanceSettings,
    PrivacySettings,
    Profile,
    ProfileSettings,
    SecuritySettings,
)

__all__ = [
    # Profile models
    "AllowlistEntry",
    "BlockPageSettings",
    "BlockedTLD",
    "Blocklist",
    "DenylistEntry",
    "LogDropSettings",
    "LogSettings",
    "NativeTracker",
    "ParentalCategory",
    "ParentalControlSettings",
    "ParentalService",
    "PerformanceSettings",
    "PrivacySettings",
    "Profile",
    "ProfileSettings",
    "SecuritySettings",
    # Analytics models
    "AnalyticsDestination",
    "AnalyticsDevice",
    "AnalyticsDomain",
    "AnalyticsEncryption",
    "AnalyticsIP",
    "AnalyticsProtocol",
    "AnalyticsReason",
    "AnalyticsStatus",
    # Log models
    "LogDevice",
    "LogEntry",
    "LogReason",
]
