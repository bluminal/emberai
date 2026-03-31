# SPDX-License-Identifier: MIT
"""Security posture tools -- audit and compare NextDNS profiles.

Provides MCP tools for auditing the security configuration of NextDNS
profiles and comparing two profiles side-by-side. Findings are
severity-tiered (CRITICAL, HIGH, WARNING, INFORMATIONAL) to help
operators prioritise remediation.
"""

from __future__ import annotations

import logging
from typing import Any

from nextdns.models.profile import Profile
from nextdns.output import Finding, ProfileDiff, Severity
from nextdns.server import mcp_server
from nextdns.tools._client_factory import get_client
from nextdns.tools._constants import (
    SECURITY_TOGGLE_COUNT,
    SECURITY_TOGGLE_FIELDS,
    count_security_enabled,
)

logger = logging.getLogger(__name__)

# Threshold: fewer than this many security toggles triggers HIGH severity.
_SECURITY_TOGGLE_HIGH_THRESHOLD = 8

# Well-known tracker domains that should not appear in allowlists.
_KNOWN_TRACKER_DOMAINS: frozenset[str] = frozenset(
    {
        "doubleclick.net",
        "googlesyndication.com",
        "googleadservices.com",
        "facebook.net",
        "fbcdn.net",
        "analytics.google.com",
        "google-analytics.com",
        "ads.yahoo.com",
        "advertising.com",
    }
)


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------


def _audit_profile(profile: Profile) -> list[Finding]:
    """Run all security checks against a single profile and return findings."""
    findings: list[Finding] = []
    sec = profile.security

    # 1. CRITICAL: CSAM protection not enabled
    if not sec.csam:
        findings.append(
            Finding(
                severity=Severity.CRITICAL,
                title=f"[{profile.name}] CSAM protection disabled",
                detail=(
                    "Child Sexual Abuse Material (CSAM) blocking is not enabled. "
                    "This is a critical safety feature that should always be active."
                ),
                recommendation="Enable the 'csam' toggle in security settings.",
            )
        )

    # 2. HIGH: Fewer than 8 of 12 security toggles enabled
    sec_enabled = count_security_enabled(sec)
    if sec_enabled < _SECURITY_TOGGLE_HIGH_THRESHOLD:
        disabled = [f for f in SECURITY_TOGGLE_FIELDS if not getattr(sec, f)]
        findings.append(
            Finding(
                severity=Severity.HIGH,
                title=(
                    f"[{profile.name}] Low security coverage"
                    f" ({sec_enabled}/{SECURITY_TOGGLE_COUNT})"
                ),
                detail=(
                    f"Only {sec_enabled} of {SECURITY_TOGGLE_COUNT} security toggles are enabled. "
                    f"Disabled: {', '.join(disabled)}."
                ),
                recommendation="Enable all security toggles for maximum protection.",
            )
        )

    # 3. HIGH: No blocklists configured in privacy settings
    if len(profile.privacy.blocklists) == 0:
        findings.append(
            Finding(
                severity=Severity.HIGH,
                title=f"[{profile.name}] No privacy blocklists configured",
                detail=(
                    "No ad/tracker blocklists are active."
                    " DNS queries to known trackers will resolve normally."
                ),
                recommendation="Add at least 'nextdns-recommended' blocklist.",
            )
        )

    # 4. HIGH: Logging disabled (no forensic capability)
    if not profile.settings.logs.enabled:
        findings.append(
            Finding(
                severity=Severity.HIGH,
                title=f"[{profile.name}] Logging disabled",
                detail=(
                    "DNS query logging is turned off. Without logs, there is no "
                    "forensic capability for incident investigation or threat hunting."
                ),
                recommendation="Enable logging with an appropriate retention period.",
            )
        )

    # 5. WARNING: nextdns-recommended blocklist missing
    blocklist_ids = {bl.id for bl in profile.privacy.blocklists}
    if profile.privacy.blocklists and "nextdns-recommended" not in blocklist_ids:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"[{profile.name}] Recommended blocklist not active",
                detail=(
                    "The 'nextdns-recommended' blocklist is not in the active blocklist set. "
                    "This is the baseline blocklist curated by NextDNS."
                ),
                recommendation="Add the 'nextdns-recommended' blocklist to privacy settings.",
            )
        )

    # 6. WARNING: Overly broad allowlist entries
    broad_entries: list[str] = []
    for entry in profile.allowlist:
        domain = entry.id.lower()
        # Check against known tracker domains
        if domain in _KNOWN_TRACKER_DOMAINS or ("." not in domain and len(domain) > 0):
            broad_entries.append(domain)

    if broad_entries:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"[{profile.name}] Overly broad allowlist entries",
                detail=(
                    f"Allowlist contains entries that may undermine blocking: "
                    f"{', '.join(broad_entries)}."
                ),
                recommendation=(
                    "Review and remove tracker domains or overly broad entries from the allowlist."
                ),
            )
        )

    # 7. WARNING: Block page not enabled
    if not profile.settings.block_page.enabled:
        findings.append(
            Finding(
                severity=Severity.WARNING,
                title=f"[{profile.name}] Block page not enabled",
                detail=(
                    "Users receive no visual feedback when a domain is blocked. "
                    "They see a generic connection error instead of an explanatory block page."
                ),
                recommendation="Enable the block page in profile settings.",
            )
        )

    # 8. INFORMATIONAL: Parental controls not configured
    pc = profile.parental_control
    pc_active = pc.safe_search or len(pc.services) > 0 or len(pc.categories) > 0
    if not pc_active:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title=f"[{profile.name}] No parental controls configured",
                detail=(
                    "Parental controls (SafeSearch, service blocking, category blocking) "
                    "are not enabled. This may be intentional for adult profiles."
                ),
                recommendation=None,
            )
        )

    # 9. INFORMATIONAL: Performance settings not enabled
    perf = profile.settings.performance
    if not perf.ecs and not perf.cache_boost:
        findings.append(
            Finding(
                severity=Severity.INFORMATIONAL,
                title=f"[{profile.name}] Performance optimizations disabled",
                detail=(
                    "Neither ECS (EDNS Client Subnet) nor cache boost is enabled. "
                    "Enabling these can improve DNS resolution speed and CDN routing."
                ),
                recommendation="Consider enabling ECS and cache boost in performance settings.",
            )
        )

    return findings


async def _fetch_all_profiles() -> list[Profile]:
    """Fetch all profiles and parse them into Profile models."""
    client = get_client()
    raw = await client.get("/profiles")
    profiles_data = raw.get("data", [])
    return [Profile.model_validate(p) for p in profiles_data]


async def _fetch_single_profile(profile_id: str) -> Profile:
    """Fetch a single profile by ID."""
    client = get_client()
    raw = await client.get_profile(profile_id)
    data = raw.get("data", raw)
    return Profile.model_validate(data)


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def nextdns__security_posture__audit(
    profile_id: str | None = None,
) -> list[dict[str, Any]]:
    """Audit security posture of one or all NextDNS profiles.

    Checks:
    - All 12 security toggles enabled
    - Recommended blocklist active
    - No overly broad allowlist entries
    - Logging enabled for forensic capability
    - Block page enabled for user visibility
    - CSAM protection active (critical)

    Returns severity-tiered findings per profile. Each finding includes
    severity, title, detail, and optional recommendation.

    Args:
        profile_id: Audit a single profile. If None, audits all profiles.
    """
    if profile_id is not None:
        profiles = [await _fetch_single_profile(profile_id)]
    else:
        profiles = await _fetch_all_profiles()

    all_findings: list[Finding] = []
    for profile in profiles:
        all_findings.extend(_audit_profile(profile))

    logger.info(
        "Security audit completed: %d findings across %d profile(s)",
        len(all_findings),
        len(profiles),
        extra={"component": "security_posture"},
    )

    return [
        {
            "severity": f.severity.value,
            "title": f.title,
            "detail": f.detail,
            "recommendation": f.recommendation,
        }
        for f in all_findings
    ]


def _diff_security(a: Profile, b: Profile) -> dict[str, tuple[Any, Any]]:
    """Compare security settings between two profiles."""
    diff: dict[str, tuple[Any, Any]] = {}
    for field_name in SECURITY_TOGGLE_FIELDS:
        val_a = getattr(a.security, field_name)
        val_b = getattr(b.security, field_name)
        if val_a != val_b:
            diff[field_name] = (val_a, val_b)
    # Compare blocked TLDs
    tlds_a = sorted(t.id for t in a.security.tlds)
    tlds_b = sorted(t.id for t in b.security.tlds)
    if tlds_a != tlds_b:
        diff["blocked_tlds"] = (tlds_a, tlds_b)
    return diff


def _diff_privacy(a: Profile, b: Profile) -> dict[str, tuple[Any, Any]]:
    """Compare privacy settings between two profiles."""
    diff: dict[str, tuple[Any, Any]] = {}
    bls_a = sorted(bl.id for bl in a.privacy.blocklists)
    bls_b = sorted(bl.id for bl in b.privacy.blocklists)
    if bls_a != bls_b:
        diff["blocklists"] = (bls_a, bls_b)

    natives_a = sorted(n.id for n in a.privacy.natives)
    natives_b = sorted(n.id for n in b.privacy.natives)
    if natives_a != natives_b:
        diff["natives"] = (natives_a, natives_b)

    if a.privacy.disguised_trackers != b.privacy.disguised_trackers:
        diff["disguised_trackers"] = (a.privacy.disguised_trackers, b.privacy.disguised_trackers)
    if a.privacy.allow_affiliate != b.privacy.allow_affiliate:
        diff["allow_affiliate"] = (a.privacy.allow_affiliate, b.privacy.allow_affiliate)
    return diff


def _diff_parental(a: Profile, b: Profile) -> dict[str, tuple[Any, Any]]:
    """Compare parental control settings between two profiles."""
    diff: dict[str, tuple[Any, Any]] = {}
    svcs_a = sorted(s.id for s in a.parental_control.services)
    svcs_b = sorted(s.id for s in b.parental_control.services)
    if svcs_a != svcs_b:
        diff["services"] = (svcs_a, svcs_b)

    cats_a = sorted(c.id for c in a.parental_control.categories)
    cats_b = sorted(c.id for c in b.parental_control.categories)
    if cats_a != cats_b:
        diff["categories"] = (cats_a, cats_b)

    if a.parental_control.safe_search != b.parental_control.safe_search:
        diff["safe_search"] = (a.parental_control.safe_search, b.parental_control.safe_search)
    if a.parental_control.youtube_restricted_mode != b.parental_control.youtube_restricted_mode:
        diff["youtube_restricted_mode"] = (
            a.parental_control.youtube_restricted_mode,
            b.parental_control.youtube_restricted_mode,
        )
    if a.parental_control.block_bypass != b.parental_control.block_bypass:
        diff["block_bypass"] = (a.parental_control.block_bypass, b.parental_control.block_bypass)
    return diff


def _diff_settings(a: Profile, b: Profile) -> dict[str, tuple[Any, Any]]:
    """Compare general settings between two profiles."""
    diff: dict[str, tuple[Any, Any]] = {}
    if a.settings.logs.enabled != b.settings.logs.enabled:
        diff["logs_enabled"] = (a.settings.logs.enabled, b.settings.logs.enabled)
    if a.settings.block_page.enabled != b.settings.block_page.enabled:
        diff["block_page_enabled"] = (a.settings.block_page.enabled, b.settings.block_page.enabled)
    if a.settings.performance.ecs != b.settings.performance.ecs:
        diff["ecs"] = (a.settings.performance.ecs, b.settings.performance.ecs)
    if a.settings.performance.cache_boost != b.settings.performance.cache_boost:
        diff["cache_boost"] = (
            a.settings.performance.cache_boost,
            b.settings.performance.cache_boost,
        )
    if a.settings.performance.cname_flattening != b.settings.performance.cname_flattening:
        diff["cname_flattening"] = (
            a.settings.performance.cname_flattening,
            b.settings.performance.cname_flattening,
        )
    if a.settings.web3 != b.settings.web3:
        diff["web3"] = (a.settings.web3, b.settings.web3)
    return diff


@mcp_server.tool()
async def nextdns__security_posture__compare(
    profile_id_a: str,
    profile_id_b: str,
) -> dict[str, Any]:
    """Compare two NextDNS profiles and highlight differences.

    Returns a structured diff with setting name, profile A value,
    profile B value for each section (security, privacy, parental
    control, settings).

    Args:
        profile_id_a: First profile identifier.
        profile_id_b: Second profile identifier.
    """
    profile_a = await _fetch_single_profile(profile_id_a)
    profile_b = await _fetch_single_profile(profile_id_b)

    diff = ProfileDiff(
        profile_a_name=profile_a.name,
        profile_b_name=profile_b.name,
        security_diff=_diff_security(profile_a, profile_b),
        privacy_diff=_diff_privacy(profile_a, profile_b),
        parental_diff=_diff_parental(profile_a, profile_b),
        settings_diff=_diff_settings(profile_a, profile_b),
    )

    logger.info(
        "Compared profiles %s (%s) vs %s (%s): %d differences",
        profile_a.id,
        profile_a.name,
        profile_b.id,
        profile_b.name,
        (
            len(diff.security_diff)
            + len(diff.privacy_diff)
            + len(diff.parental_diff)
            + len(diff.settings_diff)
        ),
        extra={"component": "security_posture"},
    )

    return {
        "profile_a_name": diff.profile_a_name,
        "profile_b_name": diff.profile_b_name,
        "security_diff": {k: list(v) for k, v in diff.security_diff.items()},
        "privacy_diff": {k: list(v) for k, v in diff.privacy_diff.items()},
        "parental_diff": {k: list(v) for k, v in diff.parental_diff.items()},
        "settings_diff": {k: list(v) for k, v in diff.settings_diff.items()},
    }
