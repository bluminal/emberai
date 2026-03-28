# Security Posture Audit

## Intent

"I want to audit the security configuration of my DNS profiles and fix any weaknesses."

## Prerequisites

- **Plugin:** `nextdns` v0.1.0 or later
- **API privileges:** Read-only access for auditing; write access for remediation
- **Environment variables:** `NEXTDNS_API_KEY` must be configured
- **For remediation:** `NEXTDNS_WRITE_ENABLED=true` (optional, only needed to apply fixes)

## Context

Run this workflow during security reviews, after creating new profiles, or as a periodic compliance check. The audit evaluates all security toggles, blocklist coverage, allowlist entries, logging status, and parental control configuration across your profiles.

The audit phase is entirely read-only. Remediation (applying fixes) requires write access and follows the standard three-phase confirmation model.

This workflow does not cover DNS analytics or query investigation -- see [DNS Analytics Review](dns-analytics-review.md) for usage patterns.

## Commands

### Step 1: Run the audit across all profiles

```
You: Audit the security of my DNS profiles
```

EmberAI calls `nextdns audit` which fetches all profiles and runs nine security checks against each.

### Step 2: Review the findings

```
EmberAI:

## Security Posture Audit

### Summary
| Profile | Security | Blocklists | Findings |
|---------|----------|------------|----------|
| Home    | 11/12    | 3          | 2        |
| Kids    | 12/12    | 4          | 0        |
| Guest   | 8/12     | 1          | 4        |

Total: 6 findings across 3 profiles.

### Findings

#### Critical
- **[Guest] CSAM protection disabled**: CSAM blocking is not enabled.
  This is a critical safety feature that should always be active.
  Recommendation: Enable the 'csam' toggle in security settings.

#### High
- **[Guest] Low security coverage (8/12)**: Only 8 of 12 security
  toggles are enabled. Disabled: aiThreatDetection, dnsRebinding,
  nrd, ddns.
  Recommendation: Enable all security toggles for maximum protection.

- **[Guest] Logging disabled**: DNS query logging is turned off.
  Without logs, there is no forensic capability.
  Recommendation: Enable logging with an appropriate retention period.

#### Warning
- **[Home] Block page not enabled**: Users receive no visual feedback
  when a domain is blocked.
  Recommendation: Enable the block page in profile settings.

- **[Guest] Recommended blocklist not active**: The 'nextdns-recommended'
  blocklist is not in the active set.
  Recommendation: Add the 'nextdns-recommended' blocklist.

#### Informational
- **[Guest] No parental controls configured**: This may be intentional
  for an adult-facing profile.
```

### Step 3: Compare the weak profile against a strong one

```
You: Compare the Guest profile to the Kids profile
```

```
EmberAI:

## Profile Comparison: Guest vs Kids

### Security Differences
| Setting              | Guest  | Kids  |
|----------------------|--------|-------|
| aiThreatDetection    | false  | true  |
| dnsRebinding         | false  | true  |
| nrd                  | false  | true  |
| ddns                 | false  | true  |
| csam                 | false  | true  |

### Privacy Differences
| Setting              | Guest              | Kids                              |
|----------------------|--------------------|-----------------------------------|
| blocklists           | oisd               | nextdns-recommended, oisd,        |
|                      |                    | 1hosts-lite, notracking           |
| disguised_trackers   | false              | true                              |

### Parental Control Differences
| Setting                  | Guest  | Kids                 |
|--------------------------|--------|----------------------|
| safe_search              | false  | true                 |
| youtube_restricted_mode  | false  | true                 |
| services                 | (none) | tiktok, instagram    |
| block_bypass             | false  | true                 |

### Settings Differences
| Setting          | Guest | Kids |
|------------------|-------|------|
| logs_enabled     | false | true |
| block_page       | false | true |
```

### Step 4: Apply a template to fix the weak profile

```
You: Apply the Kids profile security settings to the Guest profile
```

```
EmberAI:

## Template Application Plan

Template source: Kids (def456)

### Profile: Guest (ghi789)
| Setting              | Current | Template |
|----------------------|---------|----------|
| aiThreatDetection    | false   | true     |
| dnsRebinding         | false   | true     |
| nrd                  | false   | true     |
| ddns                 | false   | true     |
| csam                 | false   | true     |

5 security settings will be updated on 1 profile.

Apply this change? Requires --apply and NEXTDNS_WRITE_ENABLED=true.
```

## What to Look For

**Critical findings:**
- CSAM protection should always be enabled on every profile. There is no legitimate reason to disable it.

**High findings:**
- Security coverage below 8/12 indicates a profile that was likely created and never fully configured.
- Missing blocklists mean no ad/tracker blocking -- DNS queries to known trackers resolve normally.
- Disabled logging eliminates forensic capability. You cannot investigate incidents without logs.

**Warning findings:**
- A missing `nextdns-recommended` blocklist means the baseline curated list is not active. This is the most commonly recommended starting blocklist.
- Overly broad allowlist entries (known tracker domains like `doubleclick.net` or `google-analytics.com`) undermine blocking.
- A disabled block page means users see cryptic connection errors instead of an explanatory page.

**Profile comparison:**
- The comparison helps identify which profiles have drifted from your security baseline. Use the template feature to bring weak profiles into alignment.

## Working Safely

- The audit itself is entirely read-only and safe to run at any time.
- Remediation via the `manage` command requires `NEXTDNS_WRITE_ENABLED=true` and `--apply`.
- Every write operation presents a change plan before executing.
- Template application shows per-profile diffs so you can verify what will change before confirming.
- Parental control changes on the Guest profile are distinct from the Kids profile -- the comparison only shows the difference, it does not imply you should add parental controls to Guest.

## Next Steps

- [First-Time Profile Scan](first-profile-scan.md) -- if you have not yet done a full profile inventory
- [DNS Analytics Review](dns-analytics-review.md) -- verify that blocking is working after remediation
- [Parental Control Setup](parental-control-setup.md) -- configure parental controls on profiles that need them

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "NEXTDNS_WRITE_ENABLED is not set" | Write operations not enabled | Set `NEXTDNS_WRITE_ENABLED=true` to apply remediation |
| Template applied but audit still shows findings | Template only covers security; blocklists/logging are separate | Address blocklists and logging separately via `nextdns manage` |
| Comparison shows no differences | Profiles are already in sync | No action needed; both profiles have the same configuration |
| "apply must be True" error | Missing `--apply` flag | Include `--apply` when running write operations |
