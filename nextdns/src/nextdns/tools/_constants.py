# SPDX-License-Identifier: MIT
"""Shared constants and helpers for NextDNS tool modules.

Extracted to avoid circular imports between profiles.py and
security_posture.py (both imported by server.py at startup).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nextdns.models.profile import SecuritySettings

# The 12 boolean security toggles on a SecuritySettings model.
SECURITY_TOGGLE_FIELDS: list[str] = [
    "threat_intelligence_feeds",
    "ai_threat_detection",
    "google_safe_browsing",
    "cryptojacking",
    "dns_rebinding",
    "idn_homographs",
    "typosquatting",
    "dga",
    "nrd",
    "ddns",
    "parking",
    "csam",
]

SECURITY_TOGGLE_COUNT: int = len(SECURITY_TOGGLE_FIELDS)


def count_security_enabled(sec: SecuritySettings) -> int:
    """Count how many of the 12 boolean security toggles are enabled."""
    return sum(1 for field in SECURITY_TOGGLE_FIELDS if getattr(sec, field))
