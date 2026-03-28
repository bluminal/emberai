# NextDNS Commands Reference

Commands are the user-facing entry points to the nextdns plugin. Each command orchestrates multiple tools from the [Skills Reference](skills.md) to produce a complete, severity-ranked report or formatted dashboard.

All read commands work with only `NEXTDNS_API_KEY` configured. Write commands additionally require `NEXTDNS_WRITE_ENABLED=true`.

---

## `nextdns profiles`

Discover all NextDNS profiles and their configuration summary.

### What It Does

Lists every profile associated with the NextDNS account, showing key metrics for each:

1. Profile name and ID
2. Security toggle coverage (e.g., 10/12 enabled)
3. Number of active blocklists
4. Whether parental controls are configured
5. Denylist and allowlist entry counts
6. Logging status

With a profile ID argument, returns full details for a single profile including all security, privacy, parental control, and general settings.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | `null` | Optional: inspect a single profile in full detail |

### Example (All Profiles)

```
You: Show me my NextDNS profiles

EmberAI:

## NextDNS Profiles
| Metric   | Value |
|----------|-------|
| Profiles | 3     |

## Profile Inventory
| Name       | ID      | Security  | Blocklists | Parental | Denylist | Allowlist | Logging |
|------------|---------|-----------|------------|----------|----------|-----------|---------|
| Home       | abc123  | 11/12     | 3          | No       | 2        | 1         | Yes     |
| Kids       | def456  | 12/12     | 4          | Yes      | 5        | 0         | Yes     |
| Guest      | ghi789  | 8/12     | 1          | No       | 0        | 0         | No      |
```

### Example (Single Profile)

```
You: Show me details for profile abc123

EmberAI:

## Profile: Home (abc123)

### Security Settings
| Feature                      | Status  |
|------------------------------|---------|
| Threat Intelligence Feeds    | Enabled |
| AI Threat Detection          | Enabled |
| Google Safe Browsing         | Enabled |
| Cryptojacking Protection     | Enabled |
| DNS Rebinding Protection     | Enabled |
| IDN Homograph Protection     | Enabled |
| Typosquatting Protection     | Enabled |
| DGA Protection               | Enabled |
| Newly Registered Domains     | Enabled |
| Dynamic DNS                  | Enabled |
| Parked Domains               | Enabled |
| CSAM                         | Disabled |

### Privacy Settings
| Blocklist                    | Active |
|------------------------------|--------|
| nextdns-recommended          | Yes    |
| oisd                         | Yes    |
| 1hosts-lite                  | Yes    |

Native tracking protection: Apple, Windows, Xiaomi
Disguised tracker detection: Enabled
Allow affiliate links: No

### General Settings
Logging: Enabled (30 day retention)
Block page: Enabled
ECS: Enabled
Cache boost: Enabled
Web3: Disabled
```

### Tools Called

- `nextdns__profiles__list_profiles` -- profile inventory with summaries
- `nextdns__profiles__get_profile` -- full profile details (when profile ID provided)

---

## `nextdns analytics`

Usage dashboard with query volume, block rates, top domains, and device activity.

### What It Does

Gathers analytics data from multiple endpoints and presents a comprehensive DNS usage dashboard:

1. Query status breakdown (total queries, blocked, allowed)
2. Top queried domains (with block status)
3. Top blocked domains and block reasons
4. Device activity (query counts per device)
5. Protocol breakdown (DoH, DoT, UDP, etc.)
6. Encryption status with warning if unencrypted traffic detected
7. DNSSEC validation status
8. IP version breakdown (IPv4 vs IPv6)

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `from_time` | string | `null` | Start of date range (ISO 8601 or relative like `"-24h"`, `"-7d"`) |
| `to_time` | string | `null` | End of date range |
| `device` | string | `null` | Filter analytics to a specific device ID |

### Example

```
You: Show me DNS analytics for profile abc123

EmberAI:

## DNS Analytics: Home (abc123)

### Query Status (last 24 hours)
| Metric          | Value  |
|-----------------|--------|
| Total Queries   | 14,823 |
| Blocked         | 2,341  |
| Allowed         | 12,482 |
| Block Rate      | 15.8%  |

### Top Queried Domains
| Domain                    | Queries | Status  |
|---------------------------|---------|---------|
| connectivity.apple.com    | 1,204   | Allowed |
| dns.google                | 892     | Allowed |
| graph.facebook.com        | 445     | Blocked |
| ads.doubleclick.net       | 312     | Blocked |
| api.spotify.com           | 287     | Allowed |

### Top Block Reasons
| Reason                    | Queries |
|---------------------------|---------|
| nextdns-recommended       | 1,102   |
| oisd                      | 834     |
| Native tracking (Apple)   | 312     |
| Denylist                  | 93      |

### Device Activity
| Device           | Queries |
|------------------|---------|
| macbook-pro      | 5,234   |
| iphone-14        | 3,891   |
| pixel-8          | 2,102   |
| ring-doorbell    | 1,547   |

### Protocol Breakdown
| Protocol             | Queries |
|----------------------|---------|
| DNS-over-HTTPS       | 12,102  |
| DNS-over-TLS         | 2,534   |
| UDP                  | 187     |

WARNING: 187 queries used unencrypted DNS (UDP/TCP).

### Encryption Status
| Metric              | Value   |
|---------------------|---------|
| Encrypted           | 14,636  |
| Unencrypted         | 187     |
| Encrypted %         | 98.7%   |
```

### Tools Called

- `nextdns__analytics__get_status` -- query status breakdown
- `nextdns__analytics__get_top_domains` -- top queried and blocked domains
- `nextdns__analytics__get_block_reasons` -- block reasons with counts
- `nextdns__analytics__get_devices` -- device activity
- `nextdns__analytics__get_protocols` -- protocol breakdown
- `nextdns__analytics__get_encryption` -- encryption status
- `nextdns__analytics__get_dnssec` -- DNSSEC validation
- `nextdns__analytics__get_ip_versions` -- IP version breakdown

---

## `nextdns audit`

Security posture audit for one or all profiles.

### What It Does

Evaluates the security configuration of NextDNS profiles and produces severity-tiered findings:

1. Checks all 12 security toggles are enabled
2. Verifies recommended blocklist is active
3. Detects overly broad allowlist entries (known tracker domains)
4. Confirms logging is enabled for forensic capability
5. Checks block page is enabled for user visibility
6. Verifies CSAM protection is active (critical safety feature)
7. Reports parental control and performance settings status

With two profile IDs, performs a side-by-side comparison showing differences in security, privacy, parental control, and general settings.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | `null` | Audit a single profile. If omitted, audits all profiles. |
| `compare` | string | `null` | Second profile ID for side-by-side comparison |

### Severity Tiers

| Tier | Triggers |
|------|----------|
| Critical | CSAM protection disabled |
| High | Fewer than 8/12 security toggles enabled; no blocklists configured; logging disabled |
| Warning | Recommended blocklist missing; overly broad allowlist entries; block page disabled |
| Informational | No parental controls configured; performance optimizations disabled |

### Example (All Profiles)

```
You: Audit the security of my DNS profiles

EmberAI:

## Security Posture Audit

### Summary
| Profile | Security | Blocklists | Findings |
|---------|----------|------------|----------|
| Home    | 11/12    | 3          | 2        |
| Kids    | 12/12    | 4          | 0        |
| Guest   | 8/12     | 1          | 4        |

### Findings

#### Critical
- **[Guest] CSAM protection disabled**: Child Sexual Abuse Material
  (CSAM) blocking is not enabled. This is a critical safety feature
  that should always be active.
  Recommendation: Enable the 'csam' toggle in security settings.

#### High
- **[Guest] Low security coverage (8/12)**: Only 8 of 12 security
  toggles are enabled. Disabled: aiThreatDetection, dnsRebinding,
  nrd, ddns.
  Recommendation: Enable all security toggles for maximum protection.

- **[Guest] Logging disabled**: DNS query logging is turned off.
  Without logs, there is no forensic capability for incident
  investigation or threat hunting.
  Recommendation: Enable logging with an appropriate retention period.

#### Warning
- **[Home] Block page not enabled**: Users receive no visual feedback
  when a domain is blocked. They see a generic connection error
  instead of an explanatory block page.
  Recommendation: Enable the block page in profile settings.
```

### Example (Profile Comparison)

```
You: Compare the Kids and Home profiles

EmberAI:

## Profile Comparison: Kids vs Home

### Security Differences
| Setting         | Kids    | Home    |
|-----------------|---------|---------|
| csam            | true    | false   |

### Privacy Differences
| Setting         | Kids                         | Home                    |
|-----------------|------------------------------|-------------------------|
| blocklists      | nextdns-recommended, oisd,   | nextdns-recommended,    |
|                 | 1hosts-lite, notracking      | oisd, 1hosts-lite       |

### Parental Control Differences
| Setting                  | Kids                    | Home |
|--------------------------|-------------------------|------|
| safe_search              | true                    | false |
| youtube_restricted_mode  | true                    | false |
| services                 | tiktok, instagram       | (none) |

### Settings Differences
| Setting          | Kids | Home |
|------------------|------|------|
| block_page       | true | false |
```

### Tools Called

- `nextdns__security_posture__audit` -- security posture audit (single or all profiles)
- `nextdns__security_posture__compare` -- side-by-side profile comparison
- `nextdns__profiles__get_profile` -- full profile details (for audit context)

---

## `nextdns logs`

Search and display recent DNS query logs.

### What It Does

Provides access to DNS query logs with flexible filtering:

1. **Search** -- search logs by domain substring, status, device, or time range
2. **Stream** -- poll-based live monitoring that collects new entries over a specified duration
3. **Download** -- generate a URL for bulk log export
4. **Clear** -- permanently delete all logs (destructive, requires additional safety flags)

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `profile_id` | string | *required* | The NextDNS profile identifier |
| `domain` | string | `null` | Filter by domain substring (partial match) |
| `status` | string | `null` | Filter: `"default"`, `"blocked"`, `"allowed"`, or `"error"` |
| `device` | string | `null` | Filter by device ID |
| `from_time` | string | `null` | Start time (ISO 8601, Unix timestamp, or relative like `"-6h"`) |
| `to_time` | string | `null` | End time |
| `limit` | int | `100` | Max results (10-1000) |

### Example (Search)

```
You: Show me blocked DNS queries for profile abc123

EmberAI:

## DNS Query Logs: Home (abc123)
Filter: status=blocked | 47 entries

| Timestamp           | Domain                    | Device       | Status  | Reason              |
|---------------------|---------------------------|--------------|---------|---------------------|
| 2026-03-28 10:23:45 | graph.facebook.com        | iphone-14    | Blocked | nextdns-recommended |
| 2026-03-28 10:23:12 | ads.doubleclick.net       | macbook-pro  | Blocked | oisd                |
| 2026-03-28 10:22:58 | analytics.tiktok.com      | pixel-8      | Blocked | nextdns-recommended |
| 2026-03-28 10:22:31 | tracking.example.com      | ring-doorbell| Blocked | Denylist            |
| ...                 | ...                       | ...          | ...     | ...                 |
```

### Example (Domain Investigation)

```
You: Search logs for example.com on profile abc123

EmberAI:

## DNS Query Logs: Home (abc123)
Filter: domain=example.com | 12 entries

| Timestamp           | Domain                    | Device       | Status  | Reason   |
|---------------------|---------------------------|--------------|---------|----------|
| 2026-03-28 10:15:22 | api.example.com           | macbook-pro  | Allowed | --       |
| 2026-03-28 10:14:58 | tracking.example.com      | macbook-pro  | Blocked | Denylist |
| 2026-03-28 09:30:11 | www.example.com           | iphone-14    | Allowed | --       |
```

### Example (Live Stream)

```
You: Stream DNS activity for profile abc123 for 30 seconds

EmberAI:

## Live DNS Stream: Home (abc123)
Duration: 30.2s | Polls: 6 | Entries: 23

| Timestamp           | Domain                    | Device       | Status  |
|---------------------|---------------------------|--------------|---------|
| 2026-03-28 10:25:02 | api.spotify.com           | macbook-pro  | Allowed |
| 2026-03-28 10:25:01 | connectivity.apple.com    | iphone-14    | Allowed |
| 2026-03-28 10:24:58 | ads.example.net           | pixel-8      | Blocked |
| ...                 | ...                       | ...          | ...     |

Note: Live streaming via SSE is not feasible in the MCP context.
Used polling with 5-second intervals.
```

### Tools Called

- `nextdns__logs__search` -- search with filtering and pagination
- `nextdns__logs__stream` -- poll-based live log monitoring
- `nextdns__logs__download` -- bulk download URL generation
- `nextdns__logs__clear` -- log clearing (destructive, requires `--apply` and `--clear-logs`)

---

## `nextdns manage`

Profile configuration management -- create, update, delete profiles and modify settings.

### What It Does

Provides write operations for managing NextDNS profiles:

1. **Create/rename/delete profiles** -- lifecycle management
2. **Update security settings** -- toggle any of the 12 security features
3. **Update privacy settings** -- manage blocklists, disguised tracker detection
4. **Update parental controls** -- SafeSearch, YouTube restricted mode, service/category blocking
5. **Manage deny/allow lists** -- add or remove individual domain entries
6. **Update general settings** -- logging, block page, performance, Web3
7. **Apply templates** -- bulk-apply security/privacy settings across multiple profiles

### Write Safety

All write operations follow the three-phase confirmation model:

- **Phase 1: Resolve assumptions** -- identify ambiguities and ask for clarification
- **Phase 2: Present the plan** -- show every change with current and proposed values
- **Phase 3: Single confirmation** -- one confirmation covers the entire plan

Requirements:
- **Env var gate:** `NEXTDNS_WRITE_ENABLED` must be set to `"true"`
- **Apply flag gate:** `--apply` must be present
- **Operator confirmation:** The change plan must be confirmed

Additional safety gates for destructive operations:
- **Profile deletion:** requires `--delete-profile` flag
- **Log clearing:** requires `--clear-logs` flag

### Parameters

Parameters vary by sub-operation. See the [Skills Reference](skills.md) for individual tool parameters.

### Example (Update Security)

```
You: Enable CSAM protection on the Guest profile

EmberAI:

## Change Plan: Guest (ghi789)

| Setting | Current | Proposed |
|---------|---------|----------|
| csam    | false   | true     |

This will enable CSAM (Child Sexual Abuse Material) blocking on the
Guest profile. This is a recommended security feature.

Apply this change? Requires --apply and NEXTDNS_WRITE_ENABLED=true.
```

### Example (Apply Template)

```
You: Apply the same security settings from Kids to all other profiles

EmberAI:

## Template Application Plan

Template source: Kids (def456)

### Profile: Home (abc123)
| Setting | Current | Template |
|---------|---------|----------|
| csam    | false   | true     |

### Profile: Guest (ghi789)
| Setting              | Current | Template |
|----------------------|---------|----------|
| aiThreatDetection    | false   | true     |
| dnsRebinding         | false   | true     |
| nrd                  | false   | true     |
| ddns                 | false   | true     |
| csam                 | false   | true     |

2 profiles will be updated. Apply? Requires --apply and
NEXTDNS_WRITE_ENABLED=true.
```

### Tools Called

- `nextdns__profiles__create_profile` -- create a new profile
- `nextdns__profiles__update_profile` -- rename a profile
- `nextdns__profiles__delete_profile` -- delete a profile (requires `--delete-profile`)
- `nextdns__profiles__update_security` -- update security toggles
- `nextdns__profiles__update_privacy` -- update blocklists and privacy settings
- `nextdns__profiles__update_parental_control` -- update parental controls
- `nextdns__profiles__add_denylist_entry` -- add a domain to the denylist
- `nextdns__profiles__remove_denylist_entry` -- remove a domain from the denylist
- `nextdns__profiles__add_allowlist_entry` -- add a domain to the allowlist
- `nextdns__profiles__remove_allowlist_entry` -- remove a domain from the allowlist
- `nextdns__profiles__update_settings` -- update general settings
- `nextdns__profiles__apply_template` -- bulk-apply settings across profiles
