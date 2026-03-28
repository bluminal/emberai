# First-Time Profile Scan

## Intent

"I want to discover all my NextDNS profiles and understand their configuration."

## Prerequisites

- **Plugin:** `nextdns` v0.1.0 or later
- **API privileges:** Read-only access to NextDNS API
- **Environment variables:** `NEXTDNS_API_KEY` must be configured
- **NextDNS account:** At least one profile configured at [my.nextdns.io](https://my.nextdns.io)

## Context

Run this workflow when you first connect the nextdns plugin, or when you want a full inventory of all profiles and their settings. The scan is entirely read-only -- it makes no changes to your DNS configuration.

This workflow gives you a complete picture of every profile: security toggle coverage, blocklist counts, parental control status, and logging configuration. Use it as a baseline before running a security posture audit.

This workflow does not cover DNS analytics or query logs -- see [DNS Analytics Review](dns-analytics-review.md) for usage data.

## Commands

### Step 1: List all profiles

```
You: Show me my NextDNS profiles
```

EmberAI calls `nextdns profiles` which fetches all profiles and computes summary metrics for each.

### Step 2: Review the inventory

```
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

### Step 3: Inspect a profile in detail

```
You: Show me details for the Kids profile
```

```
EmberAI:

## Profile: Kids (def456)

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
| CSAM                         | Enabled |

All 12/12 security toggles enabled.

### Parental Controls
| Setting                  | Value                   |
|--------------------------|-------------------------|
| SafeSearch               | Enabled                 |
| YouTube Restricted Mode  | Enabled                 |
| Blocked Services         | TikTok, Instagram       |
| Blocked Categories       | (none)                  |
| Bypass Prevention        | Enabled                 |
```

### Step 4: Run a security posture audit

```
You: Audit the security of my DNS profiles
```

```
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
- **[Guest] CSAM protection disabled**: CSAM blocking is not enabled.
  Recommendation: Enable the 'csam' toggle in security settings.

#### High
- **[Guest] Low security coverage (8/12)**: Disabled: aiThreatDetection,
  dnsRebinding, nrd, ddns.
  Recommendation: Enable all security toggles for maximum protection.

#### Warning
- **[Home] Block page not enabled**: Users see a generic error instead
  of an explanatory block page.
  Recommendation: Enable the block page in profile settings.
```

## What to Look For

**Security column:**
- All profiles should have 12/12 security toggles enabled. Any profile below 8/12 triggers a HIGH severity finding.
- CSAM protection should always be enabled. A disabled CSAM toggle is a CRITICAL finding.

**Blocklists column:**
- At minimum, the `nextdns-recommended` blocklist should be active. Profiles with zero blocklists have no ad/tracker blocking.

**Parental column:**
- Profiles intended for children should show parental controls active. Adult profiles may intentionally have this disabled.

**Logging column:**
- Profiles with logging disabled have no forensic capability. You cannot investigate blocked domains, troubleshoot resolution issues, or review device behavior without logs.

**Allowlist entries:**
- Excessive allowlist entries may undermine blocking. Check for known tracker domains in the allowlist.

## Next Steps

- [Security Posture Audit](security-posture-audit.md) -- deep dive into security findings and remediation
- [DNS Analytics Review](dns-analytics-review.md) -- review query volume, block rates, and device activity
- [Parental Control Setup](parental-control-setup.md) -- configure parental controls on profiles that need them

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "NEXTDNS_API_KEY is not set" | Missing environment variable | Set `NEXTDNS_API_KEY` from my.nextdns.io/account |
| 0 profiles returned | API key is invalid or expired | Verify the key at my.nextdns.io/account |
| 401 Unauthorized | API key is incorrect | Re-copy the key; check for trailing whitespace |
| 429 Too Many Requests | Rate limit exceeded | Wait and retry; the plugin handles backoff automatically |
| Profiles visible in UI but not via API | API key from a different account | Verify you are using the key from the correct NextDNS account |
