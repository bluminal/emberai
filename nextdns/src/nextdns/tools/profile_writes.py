# SPDX-License-Identifier: MIT
"""Profile write tools -- create, update, delete, and configure profiles.

Provides MCP tools for modifying NextDNS profile configurations including
creating/deleting profiles, updating security/privacy/parental control
settings, managing deny/allow lists, updating general settings, and
applying configuration templates across multiple profiles.

All write tools are gated by the write safety gate (NEXTDNS_WRITE_ENABLED
env var + --apply flag). Profile deletion has an additional safety gate
requiring the --delete-profile flag.
"""

from __future__ import annotations

import logging
from typing import Any

from nextdns.api.url_builder import sub_resource_url
from nextdns.safety import delete_profile_gate, write_gate
from nextdns.server import mcp_server
from nextdns.tools._client_factory import get_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Field mapping constants
# ---------------------------------------------------------------------------

# Maps Python snake_case parameter names to NextDNS API camelCase keys.
_SECURITY_FIELD_MAP: dict[str, str] = {
    "threat_intelligence_feeds": "threatIntelligenceFeeds",
    "ai_threat_detection": "aiThreatDetection",
    "google_safe_browsing": "googleSafeBrowsing",
    "cryptojacking": "cryptojacking",
    "dns_rebinding": "dnsRebinding",
    "idn_homographs": "idnHomographs",
    "typosquatting": "typosquatting",
    "dga": "dga",
    "nrd": "nrd",
    "ddns": "ddns",
    "parking": "parking",
    "csam": "csam",
}


# ---------------------------------------------------------------------------
# Task 236: Create profile
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("NEXTDNS")
async def nextdns__profiles__create_profile(
    name: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Create a new NextDNS profile. Returns profile ID and DNS endpoint.

    Args:
        name: Display name for the new profile.
        apply: Must be True to execute the write (safety gate).
    """
    client = get_client()
    raw = await client.post("/profiles", data={"name": name})
    data = raw.get("data", raw)
    profile_id = data.get("id", "")

    logger.info(
        "Created profile '%s' with ID %s",
        name,
        profile_id,
        extra={"component": "profile_writes"},
    )

    return {
        "id": profile_id,
        "name": name,
        "dns_endpoint": f"https://dns.nextdns.io/{profile_id}",
        "message": f"Profile '{name}' created successfully.",
    }


# ---------------------------------------------------------------------------
# Task 237: Update profile
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("NEXTDNS")
async def nextdns__profiles__update_profile(
    profile_id: str,
    name: str | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Update a NextDNS profile's name.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        name: New display name for the profile.
        apply: Must be True to execute the write (safety gate).
    """
    client = get_client()
    data: dict[str, Any] = {}
    if name is not None:
        data["name"] = name

    await client.patch(f"/profiles/{profile_id}", data=data)

    logger.info(
        "Updated profile %s: %s",
        profile_id,
        list(data.keys()),
        extra={"component": "profile_writes"},
    )

    return {
        "profile_id": profile_id,
        "updated_fields": list(data.keys()),
        "message": "Profile updated.",
    }


# ---------------------------------------------------------------------------
# Task 238: Delete profile (extra safeguard)
# ---------------------------------------------------------------------------


@mcp_server.tool()
@delete_profile_gate
async def nextdns__profiles__delete_profile(
    profile_id: str,
    *,
    apply: bool = False,
    delete_profile: bool = False,
) -> dict[str, Any]:
    """Delete a NextDNS profile. Requires --apply AND --delete-profile flags.

    WARNING: This is a destructive, irreversible operation. The profile and
    all its settings will be permanently deleted.

    Args:
        profile_id: The NextDNS profile identifier (e.g. "abc123").
        apply: Must be True to execute the write (safety gate step 2).
        delete_profile: Must be True to confirm deletion (safety gate step 3).
    """
    client = get_client()

    # Fetch profile info before deletion for confirmation message.
    profile_name = "Unknown"
    try:
        profile_raw = await client.get_profile(profile_id)
        profile_data = profile_raw.get("data", profile_raw)
        profile_name = profile_data.get("name", "Unknown")
    except Exception:
        pass

    await client.delete(f"/profiles/{profile_id}")

    logger.info(
        "Deleted profile '%s' (%s)",
        profile_name,
        profile_id,
        extra={"component": "profile_writes"},
    )

    return {
        "profile_id": profile_id,
        "profile_name": profile_name,
        "message": f"Profile '{profile_name}' ({profile_id}) has been permanently deleted.",
    }


# ---------------------------------------------------------------------------
# Task 239: Update security settings
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("NEXTDNS")
async def nextdns__profiles__update_security(
    profile_id: str,
    threat_intelligence_feeds: bool | None = None,
    ai_threat_detection: bool | None = None,
    google_safe_browsing: bool | None = None,
    cryptojacking: bool | None = None,
    dns_rebinding: bool | None = None,
    idn_homographs: bool | None = None,
    typosquatting: bool | None = None,
    dga: bool | None = None,
    nrd: bool | None = None,
    ddns: bool | None = None,
    parking: bool | None = None,
    csam: bool | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Update security settings for a profile. Only specified fields are changed.

    Args:
        profile_id: The NextDNS profile identifier.
        threat_intelligence_feeds: Enable/disable threat intelligence feeds.
        ai_threat_detection: Enable/disable AI-driven threat detection.
        google_safe_browsing: Enable/disable Google Safe Browsing.
        cryptojacking: Enable/disable cryptojacking protection.
        dns_rebinding: Enable/disable DNS rebinding protection.
        idn_homographs: Enable/disable IDN homograph attack protection.
        typosquatting: Enable/disable typosquatting protection.
        dga: Enable/disable domain generation algorithm detection.
        nrd: Enable/disable newly registered domain blocking.
        ddns: Enable/disable dynamic DNS blocking.
        parking: Enable/disable parked domain blocking.
        csam: Enable/disable CSAM (child sexual abuse material) blocking.
        apply: Must be True to execute the write (safety gate).
    """
    # Build patch data from non-None params -- explicitly check each parameter.
    params_map: dict[str, bool | None] = {
        "threat_intelligence_feeds": threat_intelligence_feeds,
        "ai_threat_detection": ai_threat_detection,
        "google_safe_browsing": google_safe_browsing,
        "cryptojacking": cryptojacking,
        "dns_rebinding": dns_rebinding,
        "idn_homographs": idn_homographs,
        "typosquatting": typosquatting,
        "dga": dga,
        "nrd": nrd,
        "ddns": ddns,
        "parking": parking,
        "csam": csam,
    }

    data: dict[str, bool] = {}
    for py_name, value in params_map.items():
        if value is not None:
            api_name = _SECURITY_FIELD_MAP[py_name]
            data[api_name] = value

    client = get_client()
    await client.patch_sub_resource(profile_id, "security", data)

    logger.info(
        "Updated security settings for profile %s: %s",
        profile_id,
        list(data.keys()),
        extra={"component": "profile_writes"},
    )

    return {
        "profile_id": profile_id,
        "updated_fields": list(data.keys()),
        "message": "Security settings updated.",
    }


# ---------------------------------------------------------------------------
# Task 240: Update privacy settings
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("NEXTDNS")
async def nextdns__profiles__update_privacy(
    profile_id: str,
    blocklists: list[str] | None = None,
    disguised_trackers: bool | None = None,
    allow_affiliate: bool | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Update privacy settings. Blocklists replaces the entire blocklist set.

    Args:
        profile_id: The NextDNS profile identifier.
        blocklists: List of blocklist IDs to set (replaces all existing).
        disguised_trackers: Enable/disable disguised tracker detection.
        allow_affiliate: Enable/disable affiliate link passthrough.
        apply: Must be True to execute the write (safety gate).
    """
    client = get_client()
    updated: list[str] = []

    if blocklists is not None:
        # PUT replaces all blocklists via the privacy.blocklists sub-resource.
        blocklist_data = [{"id": bl} for bl in blocklists]
        url = sub_resource_url(profile_id, "privacy.blocklists")
        await client.put(url, data=blocklist_data)
        updated.append("blocklists")

    patch_data: dict[str, Any] = {}
    if disguised_trackers is not None:
        patch_data["disguisedTrackers"] = disguised_trackers
        updated.append("disguisedTrackers")
    if allow_affiliate is not None:
        patch_data["allowAffiliate"] = allow_affiliate
        updated.append("allowAffiliate")

    if patch_data:
        await client.patch_sub_resource(profile_id, "privacy", patch_data)

    logger.info(
        "Updated privacy settings for profile %s: %s",
        profile_id,
        updated,
        extra={"component": "profile_writes"},
    )

    return {
        "profile_id": profile_id,
        "updated_fields": updated,
        "message": "Privacy settings updated.",
    }


# ---------------------------------------------------------------------------
# Task 241: Update parental control settings
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("NEXTDNS")
async def nextdns__profiles__update_parental_control(
    profile_id: str,
    services: list[str] | None = None,
    categories: list[str] | None = None,
    safe_search: bool | None = None,
    youtube_restricted_mode: bool | None = None,
    block_bypass: bool | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Update parental control settings for a profile.

    Services and categories lists replace existing entries entirely.

    Args:
        profile_id: The NextDNS profile identifier.
        services: List of service IDs to block (e.g. ["tiktok", "facebook"]).
        categories: List of category IDs to block (e.g. ["porn", "gambling"]).
        safe_search: Enable/disable SafeSearch enforcement.
        youtube_restricted_mode: Enable/disable YouTube restricted mode.
        block_bypass: Enable/disable bypass prevention (blocks DoH/DoT/VPN).
        apply: Must be True to execute the write (safety gate).
    """
    client = get_client()
    updated: list[str] = []

    if services is not None:
        services_data = [{"id": s, "active": True} for s in services]
        url = sub_resource_url(profile_id, "parentalControl.services")
        await client.put(url, data=services_data)
        updated.append("services")

    if categories is not None:
        categories_data = [{"id": c, "active": True} for c in categories]
        url = sub_resource_url(profile_id, "parentalControl.categories")
        await client.put(url, data=categories_data)
        updated.append("categories")

    patch_data: dict[str, Any] = {}
    if safe_search is not None:
        patch_data["safeSearch"] = safe_search
        updated.append("safeSearch")
    if youtube_restricted_mode is not None:
        patch_data["youtubeRestrictedMode"] = youtube_restricted_mode
        updated.append("youtubeRestrictedMode")
    if block_bypass is not None:
        patch_data["blockBypass"] = block_bypass
        updated.append("blockBypass")

    if patch_data:
        await client.patch_sub_resource(profile_id, "parentalControl", patch_data)

    logger.info(
        "Updated parental control settings for profile %s: %s",
        profile_id,
        updated,
        extra={"component": "profile_writes"},
    )

    return {
        "profile_id": profile_id,
        "updated_fields": updated,
        "message": "Parental control settings updated.",
    }


# ---------------------------------------------------------------------------
# Task 242: Add/remove denylist entries
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("NEXTDNS")
async def nextdns__profiles__add_denylist_entry(
    profile_id: str,
    domain: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Add a domain to the profile's denylist (block list).

    Args:
        profile_id: The NextDNS profile identifier.
        domain: Domain name to block (e.g. "ads.example.com").
        apply: Must be True to execute the write (safety gate).
    """
    client = get_client()
    await client.add_to_array(profile_id, "denylist", {"id": domain, "active": True})

    logger.info(
        "Added %s to denylist for profile %s",
        domain,
        profile_id,
        extra={"component": "profile_writes"},
    )

    return {
        "profile_id": profile_id,
        "domain": domain,
        "action": "added_to_denylist",
    }


@mcp_server.tool()
@write_gate("NEXTDNS")
async def nextdns__profiles__remove_denylist_entry(
    profile_id: str,
    domain: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Remove a domain from the profile's denylist (block list).

    Args:
        profile_id: The NextDNS profile identifier.
        domain: Domain name to unblock (e.g. "ads.example.com").
        apply: Must be True to execute the write (safety gate).
    """
    client = get_client()
    await client.delete_array_child(profile_id, "denylist", domain)

    logger.info(
        "Removed %s from denylist for profile %s",
        domain,
        profile_id,
        extra={"component": "profile_writes"},
    )

    return {
        "profile_id": profile_id,
        "domain": domain,
        "action": "removed_from_denylist",
    }


# ---------------------------------------------------------------------------
# Task 243: Add/remove allowlist entries
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("NEXTDNS")
async def nextdns__profiles__add_allowlist_entry(
    profile_id: str,
    domain: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Add a domain to the profile's allowlist (permit list).

    Args:
        profile_id: The NextDNS profile identifier.
        domain: Domain name to allow (e.g. "safe.example.com").
        apply: Must be True to execute the write (safety gate).
    """
    client = get_client()
    await client.add_to_array(profile_id, "allowlist", {"id": domain, "active": True})

    logger.info(
        "Added %s to allowlist for profile %s",
        domain,
        profile_id,
        extra={"component": "profile_writes"},
    )

    return {
        "profile_id": profile_id,
        "domain": domain,
        "action": "added_to_allowlist",
    }


@mcp_server.tool()
@write_gate("NEXTDNS")
async def nextdns__profiles__remove_allowlist_entry(
    profile_id: str,
    domain: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Remove a domain from the profile's allowlist (permit list).

    Args:
        profile_id: The NextDNS profile identifier.
        domain: Domain name to remove from the allowlist (e.g. "safe.example.com").
        apply: Must be True to execute the write (safety gate).
    """
    client = get_client()
    await client.delete_array_child(profile_id, "allowlist", domain)

    logger.info(
        "Removed %s from allowlist for profile %s",
        domain,
        profile_id,
        extra={"component": "profile_writes"},
    )

    return {
        "profile_id": profile_id,
        "domain": domain,
        "action": "removed_from_allowlist",
    }


# ---------------------------------------------------------------------------
# Task 244: Update general settings
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("NEXTDNS")
async def nextdns__profiles__update_settings(
    profile_id: str,
    logs_enabled: bool | None = None,
    logs_retention: int | None = None,
    block_page_enabled: bool | None = None,
    ecs: bool | None = None,
    cache_boost: bool | None = None,
    cname_flattening: bool | None = None,
    web3: bool | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Update general settings for a profile.

    Settings are organized into nested sub-resources (logs, blockPage,
    performance, web3). This tool patches only the specified fields.

    Args:
        profile_id: The NextDNS profile identifier.
        logs_enabled: Enable/disable DNS query logging.
        logs_retention: Log retention period in seconds (e.g. 2592000 for 30 days).
        block_page_enabled: Enable/disable the custom block page.
        ecs: Enable/disable EDNS Client Subnet.
        cache_boost: Enable/disable cache boosting.
        cname_flattening: Enable/disable CNAME flattening.
        web3: Enable/disable Web3 domain resolution.
        apply: Must be True to execute the write (safety gate).
    """
    client = get_client()
    updated: list[str] = []

    # Logs sub-resource
    logs_data: dict[str, Any] = {}
    if logs_enabled is not None:
        logs_data["enabled"] = logs_enabled
        updated.append("logs.enabled")
    if logs_retention is not None:
        logs_data["retention"] = logs_retention
        updated.append("logs.retention")
    if logs_data:
        await client.patch_sub_resource(profile_id, "settings.logs", logs_data)

    # Block page sub-resource
    if block_page_enabled is not None:
        await client.patch_sub_resource(
            profile_id, "settings.blockPage", {"enabled": block_page_enabled}
        )
        updated.append("blockPage.enabled")

    # Performance sub-resource
    perf_data: dict[str, Any] = {}
    if ecs is not None:
        perf_data["ecs"] = ecs
        updated.append("performance.ecs")
    if cache_boost is not None:
        perf_data["cacheBoost"] = cache_boost
        updated.append("performance.cacheBoost")
    if cname_flattening is not None:
        perf_data["cnameFlattening"] = cname_flattening
        updated.append("performance.cnameFlattening")
    if perf_data:
        await client.patch_sub_resource(profile_id, "settings.performance", perf_data)

    # Web3 (top-level settings field)
    if web3 is not None:
        await client.patch_sub_resource(profile_id, "settings", {"web3": web3})
        updated.append("web3")

    logger.info(
        "Updated settings for profile %s: %s",
        profile_id,
        updated,
        extra={"component": "profile_writes"},
    )

    return {
        "profile_id": profile_id,
        "updated_fields": updated,
        "message": "Settings updated.",
    }


# ---------------------------------------------------------------------------
# Task 246: Bulk template tool
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("NEXTDNS")
async def nextdns__profiles__apply_template(
    profile_ids: list[str],
    template_security: dict[str, bool] | None = None,
    template_privacy_blocklists: list[str] | None = None,
    template_privacy_disguised_trackers: bool | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Apply a security/privacy template across multiple profiles.

    Fetches each profile, computes a diff against the template, and applies
    only the changes needed. Returns per-profile results showing what was
    changed versus what already matched.

    Args:
        profile_ids: List of profile IDs to apply the template to.
        template_security: Security toggle overrides as camelCase keys
            (e.g. {"threatIntelligenceFeeds": true, "csam": true}).
        template_privacy_blocklists: List of blocklist IDs the profile should have.
        template_privacy_disguised_trackers: Whether disguised tracker detection
            should be enabled.
        apply: Must be True to execute the write (safety gate).
    """
    client = get_client()
    results: list[dict[str, Any]] = []

    for pid in profile_ids:
        profile_result: dict[str, Any] = {"profile_id": pid, "changes": [], "already_matching": []}

        try:
            raw = await client.get_profile(pid)
            profile_data = raw.get("data", raw)
            profile_result["profile_name"] = profile_data.get("name", "Unknown")

            # --- Security diff and apply ---
            if template_security is not None:
                current_security = profile_data.get("security", {})
                security_patch: dict[str, bool] = {}

                for key, desired in template_security.items():
                    current_val = current_security.get(key)
                    if current_val != desired:
                        security_patch[key] = desired
                        profile_result["changes"].append(
                            f"security.{key}: {current_val} -> {desired}"
                        )
                    else:
                        profile_result["already_matching"].append(f"security.{key}")

                if security_patch:
                    await client.patch_sub_resource(pid, "security", security_patch)

            # --- Privacy blocklists diff and apply ---
            if template_privacy_blocklists is not None:
                current_blocklists = [
                    bl.get("id", "") for bl in profile_data.get("privacy", {}).get("blocklists", [])
                ]
                desired_set = set(template_privacy_blocklists)
                current_set = set(current_blocklists)

                if desired_set != current_set:
                    blocklist_data = [{"id": bl} for bl in template_privacy_blocklists]
                    url = sub_resource_url(pid, "privacy.blocklists")
                    await client.put(url, data=blocklist_data)
                    added = desired_set - current_set
                    removed = current_set - desired_set
                    if added:
                        profile_result["changes"].append(f"blocklists added: {sorted(added)}")
                    if removed:
                        profile_result["changes"].append(f"blocklists removed: {sorted(removed)}")
                else:
                    profile_result["already_matching"].append("blocklists")

            # --- Privacy disguised trackers diff and apply ---
            if template_privacy_disguised_trackers is not None:
                current_dt = profile_data.get("privacy", {}).get("disguisedTrackers")
                if current_dt != template_privacy_disguised_trackers:
                    await client.patch_sub_resource(
                        pid, "privacy", {"disguisedTrackers": template_privacy_disguised_trackers}
                    )
                    profile_result["changes"].append(
                        f"disguisedTrackers: {current_dt} -> {template_privacy_disguised_trackers}"
                    )
                else:
                    profile_result["already_matching"].append("disguisedTrackers")

            profile_result["status"] = "updated" if profile_result["changes"] else "no_changes"

        except Exception as exc:
            profile_result["status"] = "error"
            profile_result["error"] = str(exc)[:200]

        results.append(profile_result)

    profiles_changed = sum(1 for r in results if r["status"] == "updated")

    logger.info(
        "Applied template to %d/%d profiles",
        profiles_changed,
        len(profile_ids),
        extra={"component": "profile_writes"},
    )

    return {
        "profiles_processed": len(results),
        "profiles_updated": profiles_changed,
        "results": results,
    }
