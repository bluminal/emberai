# Investigate Blocked Domain

## Intent

"A user reports that a website is blocked. I want to find out why and unblock it if legitimate."

## Prerequisites

- **Plugin:** `nextdns` v0.1.0 or later
- **API privileges:** Read access for investigation; write access for allowlisting
- **Environment variables:** `NEXTDNS_API_KEY` must be configured
- **For allowlisting:** `NEXTDNS_WRITE_ENABLED=true` (optional, only needed to modify the allowlist)
- **Logging:** DNS query logging must be enabled on the target profile

## Context

Run this workflow when a user reports that a website is not loading or is being blocked. The investigation traces the block through the query logs to identify which blocklist, denylist, or security feature caused the block. If the domain is legitimate, you can add it to the allowlist.

The investigation phase is entirely read-only. Modifying the allowlist requires write access and follows the standard confirmation model.

This workflow focuses on DNS-level blocking. If the domain resolves correctly but the site still does not load, the issue is likely at the network layer (firewall, proxy) -- check the opnsense or unifi plugins.

## Commands

### Step 1: Search logs for the blocked domain

```
You: Why is app.example.com being blocked on profile abc123?
```

EmberAI searches the query logs for the domain and filters for blocked entries.

### Step 2: Review the log entries

```
EmberAI:

## Log Search: Home (abc123)
Filter: domain=app.example.com, status=blocked | 8 entries

| Timestamp           | Domain           | Device      | Status  | Reason              |
|---------------------|------------------|-------------|---------|---------------------|
| 2026-03-28 10:23:45 | app.example.com  | macbook-pro | Blocked | oisd                |
| 2026-03-28 10:22:12 | app.example.com  | macbook-pro | Blocked | oisd                |
| 2026-03-28 09:15:33 | app.example.com  | iphone-14   | Blocked | oisd                |
| 2026-03-28 08:45:01 | app.example.com  | macbook-pro | Blocked | oisd                |
| ...                 | ...              | ...         | ...     | ...                 |

## Block Analysis

The domain `app.example.com` is being blocked by the **oisd** blocklist.
This is a third-party ad/tracker blocklist. The domain appears 8 times
in the last 24 hours across 2 devices.
```

### Step 3: Check the denylist and allowlist

```
You: Is app.example.com on the denylist or allowlist?
```

```
EmberAI:

## Denylist Check: Home (abc123)
app.example.com is NOT on the custom denylist.

## Allowlist Check: Home (abc123)
app.example.com is NOT on the custom allowlist.

## Conclusion
The block is caused by the **oisd** blocklist, not a custom denylist
entry. To unblock this domain while keeping the blocklist active, add
it to the allowlist. Allowlist entries override blocklist blocks.
```

### Step 4: Check the privacy settings for context

```
You: What blocklists are active on this profile?
```

```
EmberAI:

## Privacy Settings: Home (abc123)

### Active Blocklists
| Blocklist            | Description                        |
|----------------------|------------------------------------|
| nextdns-recommended  | NextDNS curated baseline list      |
| oisd                 | Open Internet Standards Database   |
| 1hosts-lite          | Lightweight ad/tracker blocking    |

### Other Privacy Settings
| Setting              | Value   |
|----------------------|---------|
| Disguised Trackers   | Enabled |
| Allow Affiliate      | No      |
```

### Step 5: Add the domain to the allowlist

```
You: Add app.example.com to the allowlist
```

```
EmberAI:

## Change Plan: Home (abc123)

| Action               | Domain          |
|----------------------|-----------------|
| Add to allowlist     | app.example.com |

This will override the **oisd** blocklist for this specific domain.
The domain will resolve normally for all devices using this profile.
All other domains blocked by oisd will remain blocked.

Apply this change? Requires --apply and NEXTDNS_WRITE_ENABLED=true.
```

```
You: Yes, apply

EmberAI: app.example.com has been added to the allowlist for profile
abc123. The domain should resolve normally within a few seconds
(subject to DNS cache TTL on the client device).
```

### Step 6: Verify the fix

```
You: Stream DNS logs for profile abc123 filtering on app.example.com
```

```
EmberAI:

## Live DNS Stream: Home (abc123)
Filter: domain=app.example.com
Duration: 15.2s | Polls: 3 | Entries: 2

| Timestamp           | Domain           | Device      | Status  |
|---------------------|------------------|-------------|---------|
| 2026-03-28 10:30:15 | app.example.com  | macbook-pro | Allowed |
| 2026-03-28 10:30:14 | app.example.com  | macbook-pro | Allowed |

Domain is now resolving normally.
```

## What to Look For

**Block reasons:**
- **Blocklist name** (e.g., `nextdns-recommended`, `oisd`): The domain is on a third-party blocklist. Allowlisting overrides it.
- **Denylist**: The domain was manually added to the profile's denylist. Remove it from the denylist instead of allowlisting.
- **Security feature** (e.g., `nrd`, `dga`, `typosquatting`): A security toggle flagged the domain. Investigate carefully before allowlisting -- it may be genuinely malicious.
- **Parental control**: A service or category block is active. Review whether unblocking is appropriate.

**Domain reputation:**
- Before allowlisting, consider whether the domain is legitimate. A domain blocked by a security feature (not a blocklist) may be malicious.
- Check the root domain. If `tracker.example.com` is blocked but `example.com` is needed, consider allowlisting only `example.com`.

**Multiple blocklists:**
- A domain may appear in multiple blocklists. Allowlisting overrides all blocklist blocks simultaneously.
- If a domain appears in many lists, it is more likely to be a genuine tracker.

## Working Safely

- The investigation phase (log search, denylist/allowlist check, privacy check) is entirely read-only.
- Allowlisting a domain overrides ALL blocklist blocks for that domain. Consider the security implications.
- Do not allowlist known tracker domains (doubleclick.net, google-analytics.com, etc.) unless you have a specific reason.
- If the domain was blocked by a security feature (not a blocklist), investigate further before allowlisting.
- After allowlisting, verify with the live stream that the domain now resolves.

## Next Steps

- [DNS Analytics Review](dns-analytics-review.md) -- review overall block rates after allowlisting
- [Security Posture Audit](security-posture-audit.md) -- verify the allowlist does not contain overly broad entries
- [First-Time Profile Scan](first-profile-scan.md) -- review the full profile configuration

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Domain still blocked after allowlisting | DNS cache on the device | Clear the device's DNS cache or wait for TTL expiration (typically 5 minutes) |
| No log entries found for the domain | Logging disabled on the profile | Enable logging, reproduce the block, then search again |
| Block reason is a security feature, not a blocklist | Domain flagged by threat intelligence, NRD, DGA, etc. | Investigate the domain carefully before allowlisting; it may be genuinely malicious |
| Domain resolves but site still does not load | Network-level block (firewall, proxy) | Check opnsense firewall rules and unifi ACLs |
| "NEXTDNS_WRITE_ENABLED is not set" | Write operations not enabled | Set `NEXTDNS_WRITE_ENABLED=true` to modify the allowlist |
