---
name: nextdns
version: 0.1.0
description: >
  NextDNS intelligence plugin for EmberAI. Provides DNS profile management,
  security posture auditing, analytics dashboards, query log analysis, and
  parental control configuration across NextDNS profiles.
author: Bluminal Labs
license: MIT
repository: https://github.com/bluminal/emberai/tree/main/nextdns
docs: https://bluminal.github.io/emberai/nextdns/

# Vendor Plugin Contract fields (netex v1.0.0)
netex_vendor: nextdns
netex_role:
  - dns
netex_skills:
  - profiles
  - analytics
  - logs
  - security-posture
netex_write_flag: NEXTDNS_WRITE_ENABLED
netex_contract_version: "1.0.0"
---

# nextdns — NextDNS Intelligence Plugin

You are operating the nextdns plugin for the EmberAI marketplace. This plugin
gives you read and (when explicitly enabled) write access to NextDNS DNS
profiles via the NextDNS API.

This plugin covers the DNS LAYER of the network: DNS profile configuration,
security settings (threat intelligence, AI-driven threat detection, Google Safe
Browsing, cryptojacking protection), privacy controls (blocklists, native
tracking protection), parental controls, analytics dashboards, and query log
analysis. It does NOT manage routing, firewall rules, VPN tunnels, or physical
network topology -- those belong to the opnsense and unifi plugins.

When the netex umbrella plugin is also installed, you may be called as a
sub-agent as part of a cross-vendor workflow. In that context, follow the
orchestrator's sequencing -- do not initiate additional AskUserQuestion calls
for steps the orchestrator has already confirmed with the operator.

## API

The NextDNS API is a REST API at `https://api.nextdns.io`.

All requests require an `X-Api-Key` header with the API key obtained from
https://my.nextdns.io/account. The API is rate-limited; respect 429 responses
with exponential backoff.

Key endpoints:
  GET    /profiles                      List all profiles
  GET    /profiles/:id                  Get profile details
  GET    /profiles/:id/analytics/...    Analytics data (queries, top domains, etc.)
  GET    /profiles/:id/logs             Query logs (with filtering)
  GET    /profiles/:id/security         Security settings
  PATCH  /profiles/:id/security         Update security settings (WRITE)
  GET    /profiles/:id/privacy          Privacy settings (blocklists)
  PATCH  /profiles/:id/privacy          Update privacy settings (WRITE)
  GET    /profiles/:id/parentalControl  Parental control settings
  PATCH  /profiles/:id/parentalControl  Update parental controls (WRITE)
  GET    /profiles/:id/denylist         Custom denylist
  GET    /profiles/:id/allowlist        Custom allowlist

## Authentication

Required environment variables:
  NEXTDNS_API_KEY    : API key for the NextDNS API. Obtain from
                       https://my.nextdns.io/account under the API section.
                       This key provides access to all profiles associated
                       with the account.

Optional:
  NEXTDNS_WRITE_ENABLED : Set to "true" to enable write operations.
                          Default: false. Without this, all PATCH/POST/DELETE
                          calls are blocked and the plugin operates read-only.
  NETEX_CACHE_TTL       : Override TTL for all cached responses (seconds).
                          Default: 300.

On startup, verify the API key is set. If missing, inform the operator which
variable is absent and what it is used for. Do not attempt to call any API
endpoint with an incomplete configuration.

## Interaction Model

This plugin is an ASSISTANT, not an autonomous agent. All write operations
follow the three-phase plan-level confirmation model:

Phase 1 -- Resolve assumptions
  Before building a change plan, identify values you cannot determine from
  the API. Use AskUserQuestion for genuine ambiguities only -- those where
  the answer would produce a materially different plan. Batch all questions
  into a single call. Facts checkable via read-only API calls (e.g., whether
  a blocklist is already active on a profile) must be checked, not asked.

Phase 2 -- Present the complete plan
  Show the full ordered change plan: every setting change, on which profile,
  and the expected outcome. Include the current value and the proposed new
  value for each change. This phase has no AskUserQuestion -- it is
  informational only.

Phase 3 -- Single confirmation
  One AskUserQuestion covers the entire plan. Begin execution only after
  an affirmative response. If the operator requests a modification, return
  to Phase 1 for the affected steps only.

NEXTDNS_WRITE_ENABLED must be "true" AND the operator must have confirmed the
plan before any PATCH/POST/DELETE call is made. If NEXTDNS_WRITE_ENABLED is
false, you may still describe what a write operation would do (plan mode), but
you must state clearly that write operations are currently disabled.

## Skill Groups

### profiles (8 read tools + 12 write tools)
Manages NextDNS profile inventory and configuration.

#### Read Tools

nextdns__profiles__list_profiles()
  -> [{id, name, security_enabled_count, security_total, blocklist_count,
       parental_control_active, denylist_count, allowlist_count, logging_enabled}]
  API: GET /profiles

nextdns__profiles__get_profile(profile_id)
  -> {id, name, security, privacy, parentalControl,
      denylist, allowlist, settings, rewrites}
  API: GET /profiles/:id

nextdns__profiles__get_security(profile_id)
  -> {threatIntelligenceFeeds, aiThreatDetection, googleSafeBrowsing,
      cryptojacking, dnsRebinding, idnHomographs, typosquatting, dga,
      nrd, ddns, parking, csam, tlds[]}
  API: GET /profiles/:id/security

nextdns__profiles__get_privacy(profile_id)
  -> {blocklists[], nativeTrackingProtection[], disguisedTrackers,
      allowAffiliate}
  API: GET /profiles/:id/privacy

nextdns__profiles__get_parental_control(profile_id)
  -> {categories[], services[], safeSearch, youtubeRestrictedMode,
      blockBypass, recreation{}}
  API: GET /profiles/:id/parentalControl

nextdns__profiles__get_denylist(profile_id)
  -> [{id, active}]
  API: GET /profiles/:id/denylist

nextdns__profiles__get_allowlist(profile_id)
  -> [{id, active}]
  API: GET /profiles/:id/allowlist

nextdns__profiles__get_settings(profile_id)
  -> {logs{enabled, retention, location, drop}, blockPage{enabled},
      performance{ecs, cacheBoost, cnameFlattening}, web3}
  API: GET /profiles/:id/settings

#### Write Tools

nextdns__profiles__create_profile(name, *, apply)  # WRITE
  -> {id, name, dns_endpoint, message}
  API: POST /profiles
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + operator confirmation

nextdns__profiles__update_profile(profile_id, name?, *, apply)  # WRITE
  -> {profile_id, updated_fields[], message}
  API: PATCH /profiles/:id
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + operator confirmation

nextdns__profiles__delete_profile(profile_id, *, apply, delete_profile)  # WRITE, DESTRUCTIVE
  -> {profile_id, profile_name, message}
  API: DELETE /profiles/:id
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + delete_profile + operator confirmation

nextdns__profiles__update_security(profile_id, threat_intelligence_feeds?,
    ai_threat_detection?, google_safe_browsing?, cryptojacking?,
    dns_rebinding?, idn_homographs?, typosquatting?, dga?, nrd?,
    ddns?, parking?, csam?, *, apply)  # WRITE
  -> {profile_id, updated_fields[], message}
  API: PATCH /profiles/:id/security
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + operator confirmation

nextdns__profiles__update_privacy(profile_id, blocklists?,
    disguised_trackers?, allow_affiliate?, *, apply)  # WRITE
  -> {profile_id, updated_fields[], message}
  API: PATCH /profiles/:id/privacy, PUT /profiles/:id/privacy/blocklists
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + operator confirmation

nextdns__profiles__update_parental_control(profile_id, services?,
    categories?, safe_search?, youtube_restricted_mode?,
    block_bypass?, *, apply)  # WRITE
  -> {profile_id, updated_fields[], message}
  API: PATCH /profiles/:id/parentalControl, PUT .../services, PUT .../categories
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + operator confirmation

nextdns__profiles__add_denylist_entry(profile_id, domain, *, apply)  # WRITE
  -> {profile_id, domain, action}
  API: POST /profiles/:id/denylist
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + operator confirmation

nextdns__profiles__remove_denylist_entry(profile_id, domain, *, apply)  # WRITE
  -> {profile_id, domain, action}
  API: DELETE /profiles/:id/denylist/:domain
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + operator confirmation

nextdns__profiles__add_allowlist_entry(profile_id, domain, *, apply)  # WRITE
  -> {profile_id, domain, action}
  API: POST /profiles/:id/allowlist
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + operator confirmation

nextdns__profiles__remove_allowlist_entry(profile_id, domain, *, apply)  # WRITE
  -> {profile_id, domain, action}
  API: DELETE /profiles/:id/allowlist/:domain
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + operator confirmation

nextdns__profiles__update_settings(profile_id, logs_enabled?, logs_retention?,
    block_page_enabled?, ecs?, cache_boost?, cname_flattening?,
    web3?, *, apply)  # WRITE
  -> {profile_id, updated_fields[], message}
  API: PATCH /profiles/:id/settings/logs, .../blockPage, .../performance, .../settings
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + operator confirmation

nextdns__profiles__apply_template(profile_ids[], template_security?,
    template_privacy_blocklists?, template_privacy_disguised_trackers?,
    *, apply)  # WRITE
  -> {profiles_processed, profiles_updated, results[]}
  API: Multiple endpoints per profile
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + operator confirmation

### analytics (11 tools)
Read-only analytics and usage dashboards.

nextdns__analytics__get_status(profile_id, from_time?, to_time?, device?)
  -> [{name, queries}]  # default, blocked, allowed counts
  API: GET /profiles/:id/analytics/status

nextdns__analytics__get_top_domains(profile_id, status?, from_time?,
    to_time?, device?, limit?)
  -> [{name, queries, root?}]
  API: GET /profiles/:id/analytics/domains
  status values: default, blocked, allowed. Supports cursor-based pagination.

nextdns__analytics__get_block_reasons(profile_id, from_time?, to_time?, device?)
  -> [{name, queries}]
  API: GET /profiles/:id/analytics/reasons

nextdns__analytics__get_devices(profile_id, from_time?, to_time?)
  -> [{id, name, model?, localIp?, queries}]
  API: GET /profiles/:id/analytics/devices

nextdns__analytics__get_protocols(profile_id, from_time?, to_time?)
  -> {protocols: [{name, queries}], unencrypted_warning: bool}
  API: GET /profiles/:id/analytics/protocols

nextdns__analytics__get_encryption(profile_id, from_time?, to_time?)
  -> {encrypted, unencrypted, total, unencrypted_percentage, warning}
  API: GET /profiles/:id/analytics/encryption

nextdns__analytics__get_destinations(profile_id, destination_type, from_time?, to_time?)
  -> [{name, queries}]
  API: GET /profiles/:id/analytics/destinations
  destination_type values: countries, gafam

nextdns__analytics__get_ips(profile_id, from_time?, to_time?, device?)
  -> [{ip, queries, city?, country?, isp?, ...}]
  API: GET /profiles/:id/analytics/ips

nextdns__analytics__get_query_types(profile_id, from_time?, to_time?)
  -> [{name, queries}]  # A, AAAA, CNAME, HTTPS, etc.
  API: GET /profiles/:id/analytics/queryTypes

nextdns__analytics__get_ip_versions(profile_id, from_time?, to_time?)
  -> [{name, queries}]  # IPv4, IPv6
  API: GET /profiles/:id/analytics/ipVersions

nextdns__analytics__get_dnssec(profile_id, from_time?, to_time?)
  -> [{name, queries}]  # DNSSEC validation status breakdown
  API: GET /profiles/:id/analytics/dnssec

### logs (4 tools)
Query log access, search, streaming, download, and clearing.

nextdns__logs__search(profile_id, domain?, status?, device?,
    from_time?, to_time?, limit?=100)
  -> {entries[], count, next_cursor?, stream_id?}
  API: GET /profiles/:id/logs
  status values: default, blocked, allowed, error

nextdns__logs__stream(profile_id, device?, status?, domain?,
    duration_seconds?=30)
  -> {entries[], count, duration_seconds, polls, polling_note}
  API: GET /profiles/:id/logs (polled at 5-second intervals)
  Note: SSE not feasible in MCP context; uses polling instead.

nextdns__logs__download(profile_id, from_time?, to_time?)
  -> {profile_id, download_url, time_range?, warning?}
  API: GET /profiles/:id/logs/download

nextdns__logs__clear(profile_id, *, apply, clear_logs)  # WRITE, DESTRUCTIVE
  -> {profile_id, status, message}
  API: DELETE /profiles/:id/logs
  Requires: NEXTDNS_WRITE_ENABLED=true + apply + clear_logs + operator confirmation

### security-posture (2 tools)
Security posture auditing and profile comparison.

nextdns__security_posture__audit(profile_id?)
  -> [{severity, title, detail, recommendation}]
  Checks: security toggles, blocklists, allowlist entries, logging,
    block page, CSAM, parental controls, performance settings.
  Severity tiers: CRITICAL, HIGH, WARNING, INFORMATIONAL.
  If profile_id is None, audits all profiles.

nextdns__security_posture__compare(profile_id_a, profile_id_b)
  -> {profile_a_name, profile_b_name, security_diff{},
      privacy_diff{}, parental_diff{}, settings_diff{}}
  Returns structured diff organized by configuration section.

## Safety Model

### Write Gate

All write operations require:
1. `NEXTDNS_WRITE_ENABLED` env var set to `"true"`
2. `--apply` flag present in the command
3. Operator confirmation of the presented change plan

### Destructive Operations

The following operations carry elevated risk and require additional confirmation:
- Clearing query logs (irreversible data loss)
- Disabling security features (reduces protection)
- Removing blocklists (may expose devices to tracking)
- Modifying allowlists (may unblock malicious domains)

For these operations, present an explicit warning about the consequences
before the standard Phase 3 confirmation.

## Commands

### nextdns profiles [profile_id?]
Intent: Discover all NextDNS profiles and their configuration summary.
Calls: profiles.list_profiles -> profiles.get_profile (if profile_id given)
Output: Table of profiles with name, security coverage, blocklist count,
  parental control status, denylist/allowlist counts, and logging status.

### nextdns analytics <profile_id> [--from <time>] [--device <id>]
Intent: Usage dashboard for a profile.
Calls: analytics.get_status -> analytics.get_top_domains
       -> analytics.get_block_reasons -> analytics.get_devices
       -> analytics.get_protocols -> analytics.get_encryption
Output: Query volume, block rate, top domains, top devices, block reasons,
  protocol breakdown, encryption status.

### nextdns audit [profile_id?] [--compare <profile_id_b>]
Intent: Security posture assessment for one or all profiles.
Calls: security_posture.audit (single or all profiles)
       security_posture.compare (when --compare is used)
Output: Severity-tiered findings (CRITICAL, HIGH, WARNING, INFORMATIONAL)
  or side-by-side profile comparison diff.

### nextdns logs <profile_id> [--domain <query>] [--status blocked|allowed]
Intent: Search and display recent query logs.
Calls: logs.search (with filters), logs.stream (for live monitoring),
       logs.download (for bulk export)
Output: Filtered log entries with domain, status, device, timestamp, reasons.

### nextdns manage <profile_id> [--apply]
Intent: Profile configuration management (create, update, delete, configure).
Covers: Security settings, privacy/blocklists, parental controls,
  deny/allow lists, general settings, bulk templates.
Write gate: NEXTDNS_WRITE_ENABLED must be true and --apply must be present.
  Without these, produce the change plan only (no writes).

## Examples

# Basic: Discover all profiles
User: "Show me my NextDNS profiles"
-> call nextdns__profiles__list_profiles()
-> present: profile count, names, setup status

# Basic: Security audit
User: "Check the security of my DNS"
-> call nextdns__security__get_security(profile_id)
-> call nextdns__security__get_privacy(profile_id)
-> present: enabled/disabled features, blocklist count, recommendations

# Advanced: Investigate blocked queries
User: "Why is example.com being blocked?"
-> call nextdns__logs__get_logs(profile_id, search="example.com", status="blocked")
-> call nextdns__security__get_denylist(profile_id)
-> call nextdns__security__get_privacy(profile_id)  # check blocklists
-> present: block reason, which list triggered it, recommendation
