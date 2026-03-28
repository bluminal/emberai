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

### profiles
Manages NextDNS profile inventory and configuration.

nextdns__profiles__list_profiles()
  -> [{id, name, fingerprint, setup}]
  API: GET /profiles

nextdns__profiles__get_profile(profile_id)
  -> {id, name, fingerprint, security, privacy, parentalControl,
      denylist, allowlist, settings, rewrites}
  API: GET /profiles/:id

nextdns__profiles__get_setup(profile_id)
  -> {linkedIp, ddns, endpoints[]}
  API: GET /profiles/:id/setup

### analytics
Read-only analytics and usage dashboards.

nextdns__analytics__get_status(profile_id)
  -> {queries, blockedQueries, blockedQueriesRatio, protocols{}}
  API: GET /profiles/:id/analytics/status

nextdns__analytics__get_top_domains(profile_id, type?="queries")
  -> [{name, queries, blockedQueries?, root?}]
  API: GET /profiles/:id/analytics/domains
  type values: queries, blockedQueries

nextdns__analytics__get_top_devices(profile_id)
  -> [{id, name, model?, localIp?, queries}]
  API: GET /profiles/:id/analytics/devices

nextdns__analytics__get_query_types(profile_id)
  -> [{name, queries}]  # A, AAAA, CNAME, HTTPS, etc.
  API: GET /profiles/:id/analytics/queryTypes

nextdns__analytics__get_top_resolved(profile_id)
  -> [{name, queries}]
  API: GET /profiles/:id/analytics/dnssec

nextdns__analytics__get_top_blocked_reasons(profile_id)
  -> [{name, queries}]
  API: GET /profiles/:id/analytics/blockedReasons

nextdns__analytics__get_protocols(profile_id)
  -> [{name, queries}]
  API: GET /profiles/:id/analytics/protocols

nextdns__analytics__get_encryption(profile_id)
  -> [{name, queries}]
  API: GET /profiles/:id/analytics/encryption

nextdns__analytics__get_ip_versions(profile_id)
  -> [{name, queries}]
  API: GET /profiles/:id/analytics/ipVersions

### logs
Query log access and search.

nextdns__logs__get_logs(profile_id, limit?=100, before?, search?, status?)
  -> [{timestamp, domain, root, type, protocol, clientIp, device?,
       status, answers[], reasons[]}]
  API: GET /profiles/:id/logs
  status values: all, blocked, allowed, default

nextdns__logs__get_stream(profile_id)
  -> Server-Sent Events stream of real-time queries
  API: GET /profiles/:id/logs/stream
  Note: Returns streaming data. Use for real-time monitoring only.

### security-posture
Security and privacy configuration auditing and management.

nextdns__security__get_security(profile_id)
  -> {threatIntelligenceFeeds, aiThreatDetection, googleSafeBrowsing,
      cryptojacking, dnsRebinding, idnHomographs, typosquatting, dga,
      nrd, parkedDomains, csam, tlds[]}
  API: GET /profiles/:id/security

nextdns__security__get_privacy(profile_id)
  -> {blocklists[], nativeTrackingProtection[], disguisedTrackers,
      allowAffiliate}
  API: GET /profiles/:id/privacy

nextdns__security__get_parental_control(profile_id)
  -> {categories[], services[], recreation{}}
  API: GET /profiles/:id/parentalControl

nextdns__security__get_denylist(profile_id)
  -> [{id, active}]
  API: GET /profiles/:id/denylist

nextdns__security__get_allowlist(profile_id)
  -> [{id, active}]
  API: GET /profiles/:id/allowlist

nextdns__security__update_security(profile_id, settings)  # WRITE
  -> {updated_fields[]}
  API: PATCH /profiles/:id/security
  Requires: NEXTDNS_WRITE_ENABLED=true + operator confirmation

nextdns__security__update_privacy(profile_id, settings)  # WRITE
  -> {updated_fields[]}
  API: PATCH /profiles/:id/privacy
  Requires: NEXTDNS_WRITE_ENABLED=true + operator confirmation

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

### nextdns scan
Intent: Discover all NextDNS profiles and their configuration summary.
Calls: profiles.list_profiles -> profiles.get_profile (each)
Output: Table of profiles with name, query count, security features enabled,
  blocklist count, and setup method.

### nextdns health [profile?]
Intent: Security posture assessment for one or all profiles.
Calls: security.get_security -> security.get_privacy
       -> security.get_denylist -> security.get_allowlist
Output: Risk-ranked findings: disabled security features, missing blocklists,
  overly permissive allowlists. Severity: Critical / Warning / Info.

### nextdns analytics [profile?] [--hours 24]
Intent: Usage dashboard for a profile.
Calls: analytics.get_status -> analytics.get_top_domains
       -> analytics.get_top_devices -> analytics.get_top_blocked_reasons
Output: Query volume, block rate, top domains, top devices, block reasons.

### nextdns logs [profile?] [--search <query>] [--status blocked|allowed]
Intent: Search and display recent query logs.
Calls: logs.get_logs (with filters)
Output: Filtered log entries with domain, status, device, timestamp.

### nextdns secure [profile?] [--apply]
Intent: Apply security hardening recommendations.
Read phase: security.get_security -> identify disabled protections
Write gate: NEXTDNS_WRITE_ENABLED must be true and --apply must be present.
  Without these, produce the recommendation plan only (no writes).

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
