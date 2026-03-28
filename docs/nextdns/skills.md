# NextDNS Skills Reference

Skills are groups of MCP tools that provide direct access to the NextDNS API. Each tool makes a single API call and returns normalized data. Tools are called by [commands](commands.md) through agent orchestrators, but can also be called individually.

All tools follow the naming convention: `nextdns__{skill}__{operation}`

---

## profiles

Manages NextDNS profile inventory and configuration. Eight read tools for listing and inspecting profiles and their sub-resources, plus twelve write tools for creating, updating, deleting, and configuring profiles.

### `nextdns__profiles__list_profiles`

List all NextDNS profiles with summary of key settings.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|

No parameters. Returns all profiles associated with the API key.

**Returns:** `list[dict]` -- profile inventory

Each profile includes:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Profile identifier |
| `name` | string | Profile display name |
| `security_enabled_count` | int | Number of enabled security toggles (out of 12) |
| `security_total` | int | Total security toggles (12) |
| `blocklist_count` | int | Number of active privacy blocklists |
| `parental_control_active` | bool | Whether any parental controls are configured |
| `denylist_count` | int | Number of custom denylist entries |
| `allowlist_count` | int | Number of custom allowlist entries |
| `logging_enabled` | bool | Whether DNS query logging is enabled |

**API:** `GET /profiles`

---

### `nextdns__profiles__get_profile`

Get full details of a NextDNS profile including all settings.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier (e.g. `"abc123"`) |

**Returns:** `dict` -- full profile details including security, privacy, parental control, denylist, allowlist, settings, and rewrites.

**API:** `GET /profiles/:id`

---

### `nextdns__profiles__get_security`

Get security settings for a NextDNS profile. Returns all 12 security toggles, blocked TLDs, and their states.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |

**Returns:** `dict` -- security settings

| Field | Type | Description |
|-------|------|-------------|
| `threatIntelligenceFeeds` | bool | Threat intelligence feed blocking |
| `aiThreatDetection` | bool | AI-driven threat detection |
| `googleSafeBrowsing` | bool | Google Safe Browsing integration |
| `cryptojacking` | bool | Cryptojacking protection |
| `dnsRebinding` | bool | DNS rebinding attack protection |
| `idnHomographs` | bool | IDN homograph attack protection |
| `typosquatting` | bool | Typosquatting domain protection |
| `dga` | bool | Domain generation algorithm detection |
| `nrd` | bool | Newly registered domain blocking |
| `ddns` | bool | Dynamic DNS blocking |
| `parking` | bool | Parked domain blocking |
| `csam` | bool | CSAM (child safety) blocking |
| `tlds` | list | Blocked top-level domains |

**API:** `GET /profiles/:id/security`

---

### `nextdns__profiles__get_privacy`

Get privacy settings for a NextDNS profile. Returns blocklists, native tracker blocking, disguised tracker detection, and affiliate link settings.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |

**Returns:** `dict` -- privacy settings

| Field | Type | Description |
|-------|------|-------------|
| `blocklists` | list | Active blocklists with IDs and names |
| `nativeTrackingProtection` | list | Active native tracking protections (Apple, Windows, etc.) |
| `disguisedTrackers` | bool | Whether disguised tracker detection is enabled |
| `allowAffiliate` | bool | Whether affiliate link passthrough is enabled |

**API:** `GET /profiles/:id/privacy`

---

### `nextdns__profiles__get_parental_control`

Get parental control settings for a NextDNS profile. Returns blocked services, blocked categories, SafeSearch, YouTube restricted mode, and bypass prevention settings.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |

**Returns:** `dict` -- parental control settings

| Field | Type | Description |
|-------|------|-------------|
| `categories` | list | Blocked content categories |
| `services` | list | Blocked services (e.g. TikTok, Instagram) |
| `safeSearch` | bool | SafeSearch enforcement |
| `youtubeRestrictedMode` | bool | YouTube restricted mode |
| `blockBypass` | bool | Bypass prevention (blocks DoH/DoT/VPN) |
| `recreation` | dict | Recreation time schedules |

**API:** `GET /profiles/:id/parentalControl`

---

### `nextdns__profiles__get_denylist`

Get the deny list for a NextDNS profile (custom blocked domains).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |

**Returns:** `list[dict]` -- denylist entries

Each entry includes:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Domain name |
| `active` | bool | Whether the entry is active |

**API:** `GET /profiles/:id/denylist`

---

### `nextdns__profiles__get_allowlist`

Get the allow list for a NextDNS profile (explicitly allowed domains).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |

**Returns:** `list[dict]` -- allowlist entries

Each entry includes:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Domain name |
| `active` | bool | Whether the entry is active |

**API:** `GET /profiles/:id/allowlist`

---

### `nextdns__profiles__get_settings`

Get general settings for a NextDNS profile. Returns logging configuration, block page, performance settings (ECS, cache boost, CNAME flattening), and Web3 toggle.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |

**Returns:** `dict` -- general settings

| Field | Type | Description |
|-------|------|-------------|
| `logs` | dict | Logging settings (`enabled`, `retention`, `location`, `drop`) |
| `blockPage` | dict | Block page settings (`enabled`) |
| `performance` | dict | Performance settings (`ecs`, `cacheBoost`, `cnameFlattening`) |
| `web3` | bool | Web3 domain resolution |

**API:** `GET /profiles/:id/settings`

---

### `nextdns__profiles__create_profile` (write)

Create a new NextDNS profile. Returns profile ID and DNS endpoint.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | string | *required* | Display name for the new profile |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict` -- created profile

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | New profile identifier |
| `name` | string | Profile display name |
| `dns_endpoint` | string | DNS endpoint URL |

**API:** `POST /profiles`

---

### `nextdns__profiles__update_profile` (write)

Update a NextDNS profile's name.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `name` | string | `null` | New display name |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true` and `apply=True`.

**API:** `PATCH /profiles/:id`

---

### `nextdns__profiles__delete_profile` (write, destructive)

Delete a NextDNS profile. This is irreversible.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `apply` | bool | `false` | Must be `true` to execute (write gate step 2) |
| `delete_profile` | bool | `false` | Must be `true` to confirm deletion (write gate step 3) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true`, `apply=True`, AND `delete_profile=True`.

**API:** `DELETE /profiles/:id`

---

### `nextdns__profiles__update_security` (write)

Update security settings for a profile. Only specified fields are changed.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `threat_intelligence_feeds` | bool | `null` | Enable/disable threat intelligence feeds |
| `ai_threat_detection` | bool | `null` | Enable/disable AI-driven threat detection |
| `google_safe_browsing` | bool | `null` | Enable/disable Google Safe Browsing |
| `cryptojacking` | bool | `null` | Enable/disable cryptojacking protection |
| `dns_rebinding` | bool | `null` | Enable/disable DNS rebinding protection |
| `idn_homographs` | bool | `null` | Enable/disable IDN homograph protection |
| `typosquatting` | bool | `null` | Enable/disable typosquatting protection |
| `dga` | bool | `null` | Enable/disable DGA detection |
| `nrd` | bool | `null` | Enable/disable newly registered domain blocking |
| `ddns` | bool | `null` | Enable/disable dynamic DNS blocking |
| `parking` | bool | `null` | Enable/disable parked domain blocking |
| `csam` | bool | `null` | Enable/disable CSAM blocking |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true` and `apply=True`.

**API:** `PATCH /profiles/:id/security`

---

### `nextdns__profiles__update_privacy` (write)

Update privacy settings. Blocklists replaces the entire blocklist set.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `blocklists` | list[string] | `null` | List of blocklist IDs (replaces all existing) |
| `disguised_trackers` | bool | `null` | Enable/disable disguised tracker detection |
| `allow_affiliate` | bool | `null` | Enable/disable affiliate link passthrough |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true` and `apply=True`.

**API:** `PATCH /profiles/:id/privacy`, `PUT /profiles/:id/privacy/blocklists`

---

### `nextdns__profiles__update_parental_control` (write)

Update parental control settings. Services and categories lists replace existing entries entirely.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `services` | list[string] | `null` | Service IDs to block (e.g. `["tiktok", "facebook"]`) |
| `categories` | list[string] | `null` | Category IDs to block (e.g. `["porn", "gambling"]`) |
| `safe_search` | bool | `null` | Enable/disable SafeSearch enforcement |
| `youtube_restricted_mode` | bool | `null` | Enable/disable YouTube restricted mode |
| `block_bypass` | bool | `null` | Enable/disable bypass prevention |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true` and `apply=True`.

**API:** `PATCH /profiles/:id/parentalControl`, `PUT /profiles/:id/parentalControl/services`, `PUT /profiles/:id/parentalControl/categories`

---

### `nextdns__profiles__add_denylist_entry` (write)

Add a domain to the profile's denylist (block list).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `domain` | string | *required* | Domain name to block |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true` and `apply=True`.

**API:** `POST /profiles/:id/denylist`

---

### `nextdns__profiles__remove_denylist_entry` (write)

Remove a domain from the profile's denylist.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `domain` | string | *required* | Domain name to unblock |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true` and `apply=True`.

**API:** `DELETE /profiles/:id/denylist/:domain`

---

### `nextdns__profiles__add_allowlist_entry` (write)

Add a domain to the profile's allowlist (permit list).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `domain` | string | *required* | Domain name to allow |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true` and `apply=True`.

**API:** `POST /profiles/:id/allowlist`

---

### `nextdns__profiles__remove_allowlist_entry` (write)

Remove a domain from the profile's allowlist.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `domain` | string | *required* | Domain name to remove from the allowlist |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true` and `apply=True`.

**API:** `DELETE /profiles/:id/allowlist/:domain`

---

### `nextdns__profiles__update_settings` (write)

Update general settings for a profile. Settings are organized into nested sub-resources.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `logs_enabled` | bool | `null` | Enable/disable DNS query logging |
| `logs_retention` | int | `null` | Log retention period in seconds |
| `block_page_enabled` | bool | `null` | Enable/disable the custom block page |
| `ecs` | bool | `null` | Enable/disable EDNS Client Subnet |
| `cache_boost` | bool | `null` | Enable/disable cache boosting |
| `cname_flattening` | bool | `null` | Enable/disable CNAME flattening |
| `web3` | bool | `null` | Enable/disable Web3 domain resolution |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true` and `apply=True`.

**API:** `PATCH /profiles/:id/settings/logs`, `PATCH /profiles/:id/settings/blockPage`, `PATCH /profiles/:id/settings/performance`, `PATCH /profiles/:id/settings`

---

### `nextdns__profiles__apply_template` (write)

Apply a security/privacy template across multiple profiles. Fetches each profile, computes a diff against the template, and applies only the changes needed.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_ids` | list[string] | *required* | List of profile IDs to apply the template to |
| `template_security` | dict | `null` | Security toggle overrides (camelCase keys) |
| `template_privacy_blocklists` | list[string] | `null` | Blocklist IDs the profile should have |
| `template_privacy_disguised_trackers` | bool | `null` | Whether disguised tracker detection should be enabled |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict` -- per-profile results

| Field | Type | Description |
|-------|------|-------------|
| `profiles_processed` | int | Total profiles processed |
| `profiles_updated` | int | Profiles that had changes applied |
| `results` | list | Per-profile details with changes and already-matching fields |

**API:** Multiple endpoints per profile (security, privacy, blocklists)

---

## analytics

Read-only analytics and usage dashboards. Eleven tools covering query status, top domains, block reasons, devices, protocols, encryption, destinations, IPs, query types, IP versions, and DNSSEC.

All analytics tools support optional date-range filtering via `from_time` and `to_time` parameters.

### `nextdns__analytics__get_status`

Get query status breakdown for a NextDNS profile. Returns counts of queries by resolution status: default (resolved normally), blocked, and allowed.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `from_time` | string | `null` | Start of the date range (ISO 8601 or relative like `"-7d"`) |
| `to_time` | string | `null` | End of the date range |
| `device` | string | `null` | Filter by device ID |

**Returns:** `list[dict]` -- status entries with `name` and `queries` fields

**API:** `GET /profiles/:id/analytics/status`

---

### `nextdns__analytics__get_top_domains`

Get top queried domains for a NextDNS profile. Uses cursor-based pagination.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `status` | string | `null` | Filter: `"default"`, `"blocked"`, or `"allowed"` |
| `from_time` | string | `null` | Start of the date range |
| `to_time` | string | `null` | End of the date range |
| `device` | string | `null` | Filter by device ID |
| `limit` | int | `null` | Maximum number of domains (1-500) |

**Returns:** `list[dict]` -- domains

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Domain name |
| `queries` | int | Query count |
| `root` | string or None | Root domain |

**API:** `GET /profiles/:id/analytics/domains`

---

### `nextdns__analytics__get_block_reasons`

Get block reasons for a NextDNS profile. Returns the reasons why queries were blocked, with query counts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `from_time` | string | `null` | Start of the date range |
| `to_time` | string | `null` | End of the date range |
| `device` | string | `null` | Filter by device ID |

**Returns:** `list[dict]` -- reasons with `name` and `queries` fields

**API:** `GET /profiles/:id/analytics/reasons`

---

### `nextdns__analytics__get_devices`

Get device activity for a NextDNS profile. Returns devices that have made DNS queries, with query counts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `from_time` | string | `null` | Start of the date range |
| `to_time` | string | `null` | End of the date range |

**Returns:** `list[dict]` -- devices

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Device identifier |
| `name` | string | Device name |
| `model` | string or None | Device model |
| `localIp` | string or None | Local IP address |
| `queries` | int | Query count |

**API:** `GET /profiles/:id/analytics/devices`

---

### `nextdns__analytics__get_protocols`

Get DNS protocol breakdown for a NextDNS profile. Returns protocol usage (DoH, DoT, UDP, TCP, etc.) with an unencrypted warning flag.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `from_time` | string | `null` | Start of the date range |
| `to_time` | string | `null` | End of the date range |

**Returns:** `dict` -- protocol breakdown

| Field | Type | Description |
|-------|------|-------------|
| `protocols` | list | Protocol entries with `name` and `queries` fields |
| `unencrypted_warning` | bool | True if any unencrypted protocol has queries |

**API:** `GET /profiles/:id/analytics/protocols`

---

### `nextdns__analytics__get_encryption`

Get encryption breakdown for a NextDNS profile. Returns encrypted vs unencrypted query counts with computed percentage and warning flag.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `from_time` | string | `null` | Start of the date range |
| `to_time` | string | `null` | End of the date range |

**Returns:** `dict` -- encryption stats

| Field | Type | Description |
|-------|------|-------------|
| `encrypted` | int | Number of encrypted queries |
| `unencrypted` | int | Number of unencrypted queries |
| `total` | int | Total queries |
| `unencrypted_percentage` | float | Percentage of unencrypted queries |
| `warning` | bool | True if unencrypted percentage exceeds 10% |

**API:** `GET /profiles/:id/analytics/encryption`

---

### `nextdns__analytics__get_destinations`

Get destination breakdown for a NextDNS profile. Returns query counts grouped by country or GAFAM provider.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `destination_type` | string | *required* | Either `"countries"` or `"gafam"` |
| `from_time` | string | `null` | Start of the date range |
| `to_time` | string | `null` | End of the date range |

**Returns:** `list[dict]` -- destinations with `name` and `queries` fields

**API:** `GET /profiles/:id/analytics/destinations`

---

### `nextdns__analytics__get_ips`

Get source IP addresses for a NextDNS profile. Returns IPs with geo/ISP metadata and query counts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `from_time` | string | `null` | Start of the date range |
| `to_time` | string | `null` | End of the date range |
| `device` | string | `null` | Filter by device ID |

**Returns:** `list[dict]` -- IP entries with address, geo, ISP, and query count

**API:** `GET /profiles/:id/analytics/ips`

---

### `nextdns__analytics__get_query_types`

Get DNS query type breakdown for a NextDNS profile. Returns counts by record type (A, AAAA, CNAME, MX, etc.).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `from_time` | string | `null` | Start of the date range |
| `to_time` | string | `null` | End of the date range |

**Returns:** `list[dict]` -- query types with `name` and `queries` fields

**API:** `GET /profiles/:id/analytics/queryTypes`

---

### `nextdns__analytics__get_ip_versions`

Get IP version breakdown for a NextDNS profile. Returns counts by IP version (IPv4, IPv6).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `from_time` | string | `null` | Start of the date range |
| `to_time` | string | `null` | End of the date range |

**Returns:** `list[dict]` -- IP versions with `name` and `queries` fields

**API:** `GET /profiles/:id/analytics/ipVersions`

---

### `nextdns__analytics__get_dnssec`

Get DNSSEC validation breakdown for a NextDNS profile. Returns counts by DNSSEC validation status.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `from_time` | string | `null` | Start of the date range |
| `to_time` | string | `null` | End of the date range |

**Returns:** `list[dict]` -- DNSSEC entries with validation status and counts

**API:** `GET /profiles/:id/analytics/dnssec`

---

## logs

Query log access, search, streaming, download, and clearing. Four tools covering the full lifecycle of DNS query logs.

### `nextdns__logs__search`

Search DNS query logs for a NextDNS profile. Returns matching log entries with pagination support.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `domain` | string | `null` | Filter by domain substring (partial match) |
| `status` | string | `null` | Filter: `"default"`, `"blocked"`, `"allowed"`, or `"error"` |
| `device` | string | `null` | Filter by device ID |
| `from_time` | string | `null` | Start time (ISO 8601, Unix timestamp, or relative like `"-6h"`) |
| `to_time` | string | `null` | End time |
| `limit` | int | `100` | Max results (10-1000) |

**Returns:** `dict` -- search results

| Field | Type | Description |
|-------|------|-------------|
| `entries` | list | Log entries |
| `count` | int | Number of entries returned |
| `next_cursor` | string or None | Pagination cursor for more results |
| `stream_id` | string or None | Stream ID for live streaming continuation |

Each log entry includes:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | Query timestamp |
| `domain` | string | Queried domain |
| `root` | string | Root domain |
| `type` | string | DNS record type (A, AAAA, etc.) |
| `protocol` | string | DNS protocol used |
| `clientIp` | string | Client IP address |
| `device` | dict or None | Device information |
| `status` | string | Resolution status |
| `answers` | list | DNS answers |
| `reasons` | list | Block reasons (if blocked) |

**API:** `GET /profiles/:id/logs`

---

### `nextdns__logs__stream`

Stream live DNS query logs via polling. Polls the logs endpoint at 5-second intervals for the specified duration, collecting new entries as they arrive.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `device` | string | `null` | Filter by device ID |
| `status` | string | `null` | Filter: `"default"`, `"blocked"`, `"allowed"`, or `"error"` |
| `domain` | string | `null` | Filter by domain substring |
| `duration_seconds` | int | `30` | How long to collect logs (5-120 seconds) |

**Returns:** `dict` -- streaming results

| Field | Type | Description |
|-------|------|-------------|
| `entries` | list | Collected log entries (most recent first) |
| `count` | int | Total entries collected |
| `duration_seconds` | float | Actual collection duration |
| `polls` | int | Number of poll cycles executed |

**API:** `GET /profiles/:id/logs` (polled)

---

### `nextdns__logs__download`

Get a download URL for bulk DNS query logs.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `from_time` | string | `null` | Start time (ISO 8601 or Unix timestamp) |
| `to_time` | string | `null` | End time |

**Returns:** `dict` -- download information

| Field | Type | Description |
|-------|------|-------------|
| `profile_id` | string | Profile identifier |
| `download_url` | string | URL for bulk download |
| `time_range` | dict or None | Specified time range |
| `warning` | string or None | Warning if no time range specified |

**API:** `GET /profiles/:id/logs/download`

---

### `nextdns__logs__clear` (write, destructive)

Clear all DNS query logs for a NextDNS profile. This is irreversible.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `apply` | bool | `false` | Must be `true` to execute (write gate step 2) |
| `clear_logs` | bool | `false` | Must be `true` to confirm clearing (write gate step 3) |

**Write safety:** Requires `NEXTDNS_WRITE_ENABLED=true`, `apply=True`, AND `clear_logs=True`.

**API:** `DELETE /profiles/:id/logs`

---

## security-posture

Security and privacy configuration auditing and profile comparison. Two tools for auditing profiles and comparing settings between profiles.

### `nextdns__security_posture__audit`

Audit security posture of one or all NextDNS profiles. Returns severity-tiered findings.

Checks performed:

- All 12 security toggles enabled
- CSAM protection active (critical)
- Recommended blocklist active
- No overly broad allowlist entries (known tracker domains)
- Logging enabled for forensic capability
- Block page enabled for user visibility
- Parental controls and performance settings status

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | `null` | Audit a single profile. If `null`, audits all profiles. |

**Returns:** `list[dict]` -- findings

Each finding includes:

| Field | Type | Description |
|-------|------|-------------|
| `severity` | string | `"CRITICAL"`, `"HIGH"`, `"WARNING"`, or `"INFORMATIONAL"` |
| `title` | string | Finding title with profile name prefix |
| `detail` | string | Detailed description of the finding |
| `recommendation` | string or None | Suggested remediation |

**API:** `GET /profiles` or `GET /profiles/:id` (then local analysis)

---

### `nextdns__security_posture__compare`

Compare two NextDNS profiles and highlight differences. Returns a structured diff organized by configuration section.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id_a` | string | *required* | First profile identifier |
| `profile_id_b` | string | *required* | Second profile identifier |

**Returns:** `dict` -- comparison results

| Field | Type | Description |
|-------|------|-------------|
| `profile_a_name` | string | First profile name |
| `profile_b_name` | string | Second profile name |
| `security_diff` | dict | Security setting differences (field -> [val_a, val_b]) |
| `privacy_diff` | dict | Privacy setting differences |
| `parental_diff` | dict | Parental control differences |
| `settings_diff` | dict | General settings differences |

**API:** `GET /profiles/:id` (for each profile, then local diff)

---

## Write Safety Model

All write operations across all skill groups follow the same safety model:

### Standard Write Gate

1. **Env var:** `NEXTDNS_WRITE_ENABLED` must be set to `"true"`
2. **Apply flag:** `apply=True` must be passed
3. **Operator confirmation:** The change plan must be confirmed

### Destructive Operation Gates

Two operations carry elevated risk and require additional flags beyond the standard write gate:

| Operation | Additional Flag | Reason |
|-----------|----------------|--------|
| Profile deletion | `delete_profile=True` | Irreversible loss of all profile configuration |
| Log clearing | `clear_logs=True` | Irreversible loss of all stored DNS query logs |

### Phase Model

Write commands follow the three-phase plan-level confirmation model:

1. **Phase 1 -- Resolve assumptions:** Identify ambiguities, batch all questions
2. **Phase 2 -- Present the plan:** Show every change with current and proposed values
3. **Phase 3 -- Single confirmation:** One confirmation covers the entire plan
