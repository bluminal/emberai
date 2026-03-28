# SPDX-License-Identifier: MIT
"""Profiles agent -- orchestrates profile tools for summary and detail views.

Composes MCP tool calls with OX formatters to produce operator-ready
markdown output for profile listing and detailed inspection.
"""

from __future__ import annotations

from nextdns.output import ProfileSummary, format_profile_detail, format_profile_summary
from nextdns.tools._constants import SECURITY_TOGGLE_COUNT
from nextdns.tools.profiles import (
    nextdns__profiles__get_profile,
    nextdns__profiles__list_profiles,
)


async def profile_list_summary() -> str:
    """Generate a formatted summary of all NextDNS profiles.

    Calls :func:`nextdns__profiles__list_profiles` and formats the
    results as a markdown table via the OX formatter.
    """
    profiles_raw = await nextdns__profiles__list_profiles()

    summaries = [
        ProfileSummary(
            name=p["name"],
            profile_id=p["id"],
            security_on=p["security_enabled_count"],
            security_off=SECURITY_TOGGLE_COUNT - p["security_enabled_count"],
            privacy_blocklists=p["blocklist_count"],
            parental_control=p["parental_control_active"],
        )
        for p in profiles_raw
    ]

    return format_profile_summary(summaries)


async def profile_detail(profile_id: str) -> str:
    """Generate a detailed view of a single NextDNS profile.

    Calls :func:`nextdns__profiles__get_profile` and formats the
    results as a structured key-value report via the OX formatter.

    Args:
        profile_id: The NextDNS profile identifier.
    """
    profile = await nextdns__profiles__get_profile(profile_id)
    return format_profile_detail(profile)
