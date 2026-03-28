# SPDX-License-Identifier: MIT
"""Profile read tools -- list, detail, and sub-resource access.

Provides MCP tools for reading NextDNS profile configurations including
security, privacy, parental control, deny/allow lists, and general
settings. All tools are read-only and do not require write gate approval.
"""

from __future__ import annotations

import logging
from typing import Any

from nextdns.models.profile import (
    AllowlistEntry,
    DenylistEntry,
    ParentalControlSettings,
    PrivacySettings,
    Profile,
    ProfileSettings,
    SecuritySettings,
)
from nextdns.server import mcp_server
from nextdns.tools._client_factory import get_client
from nextdns.tools._constants import SECURITY_TOGGLE_COUNT, count_security_enabled

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def nextdns__profiles__list_profiles() -> list[dict[str, Any]]:
    """List all NextDNS profiles with summary of key settings.

    Returns profile name, ID, and counts of enabled security/privacy
    features for each profile.
    """
    client = get_client()
    raw = await client.get("/profiles")
    profiles_data = raw.get("data", [])

    results: list[dict[str, Any]] = []
    for p in profiles_data:
        profile = Profile.model_validate(p)
        sec_enabled = count_security_enabled(profile.security)

        results.append(
            {
                "id": profile.id,
                "name": profile.name,
                "security_enabled_count": sec_enabled,
                "security_total": SECURITY_TOGGLE_COUNT,
                "blocklist_count": len(profile.privacy.blocklists),
                "parental_control_active": (
                    profile.parental_control.safe_search
                    or len(profile.parental_control.services) > 0
                    or len(profile.parental_control.categories) > 0
                ),
                "denylist_count": len(profile.denylist),
                "allowlist_count": len(profile.allowlist),
                "logging_enabled": profile.settings.logs.enabled,
            }
        )

    logger.info(
        "Listed %d profiles",
        len(results),
        extra={"component": "profiles"},
    )
    return results


@mcp_server.tool()
async def nextdns__profiles__get_profile(profile_id: str) -> dict[str, Any]:
    """Get full details of a NextDNS profile including all settings.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
    """
    client = get_client()
    raw = await client.get_profile(profile_id)
    data = raw.get("data", raw)
    profile = Profile.model_validate(data)

    logger.info(
        "Fetched profile %s (%s)",
        profile.id,
        profile.name,
        extra={"component": "profiles"},
    )
    return profile.model_dump(by_alias=True)


@mcp_server.tool()
async def nextdns__profiles__get_security(profile_id: str) -> dict[str, Any]:
    """Get security settings for a NextDNS profile.

    Returns all 12 security toggles, blocked TLDs, and their states.

    Args:
        profile_id: The NextDNS profile identifier.
    """
    client = get_client()
    raw = await client.get_sub_resource(profile_id, "security")
    data = raw.get("data", raw)
    settings = SecuritySettings.model_validate(data)
    return settings.model_dump(by_alias=True)


@mcp_server.tool()
async def nextdns__profiles__get_privacy(profile_id: str) -> dict[str, Any]:
    """Get privacy settings for a NextDNS profile.

    Returns blocklists, native tracker blocking, disguised tracker
    detection, and affiliate link settings.

    Args:
        profile_id: The NextDNS profile identifier.
    """
    client = get_client()
    raw = await client.get_sub_resource(profile_id, "privacy")
    data = raw.get("data", raw)
    settings = PrivacySettings.model_validate(data)
    return settings.model_dump(by_alias=True)


@mcp_server.tool()
async def nextdns__profiles__get_parental_control(profile_id: str) -> dict[str, Any]:
    """Get parental control settings for a NextDNS profile.

    Returns blocked services, blocked categories, SafeSearch,
    YouTube restricted mode, and bypass prevention settings.

    Args:
        profile_id: The NextDNS profile identifier.
    """
    client = get_client()
    raw = await client.get_sub_resource(profile_id, "parentalControl")
    data = raw.get("data", raw)
    settings = ParentalControlSettings.model_validate(data)
    return settings.model_dump(by_alias=True)


@mcp_server.tool()
async def nextdns__profiles__get_denylist(profile_id: str) -> list[dict[str, Any]]:
    """Get the deny list for a NextDNS profile (blocked domains).

    Args:
        profile_id: The NextDNS profile identifier.
    """
    client = get_client()
    raw = await client.get_array(profile_id, "denylist")
    return [DenylistEntry.model_validate(e).model_dump() for e in raw]


@mcp_server.tool()
async def nextdns__profiles__get_allowlist(profile_id: str) -> list[dict[str, Any]]:
    """Get the allow list for a NextDNS profile (explicitly allowed domains).

    Args:
        profile_id: The NextDNS profile identifier.
    """
    client = get_client()
    raw = await client.get_array(profile_id, "allowlist")
    return [AllowlistEntry.model_validate(e).model_dump() for e in raw]


@mcp_server.tool()
async def nextdns__profiles__get_settings(profile_id: str) -> dict[str, Any]:
    """Get general settings for a NextDNS profile.

    Returns logging configuration, block page, performance settings
    (ECS, cache boost, CNAME flattening), and Web3 toggle.

    Args:
        profile_id: The NextDNS profile identifier.
    """
    client = get_client()
    raw = await client.get_sub_resource(profile_id, "settings")
    data = raw.get("data", raw)
    settings = ProfileSettings.model_validate(data)
    return settings.model_dump(by_alias=True)
