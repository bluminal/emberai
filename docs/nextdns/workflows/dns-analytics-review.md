# DNS Analytics Review

## Intent

"I want to understand my DNS usage: query volume, block rates, top domains, and device activity."

## Prerequisites

- **Plugin:** `nextdns` v0.1.0 or later
- **API privileges:** Read-only access to NextDNS API
- **Environment variables:** `NEXTDNS_API_KEY` must be configured
- **Logging:** DNS query logging must be enabled on the target profile (analytics require log data)

## Context

Run this workflow to review DNS activity over a time period. Use it for routine monitoring, investigating unusual traffic patterns, or verifying that blocking is working as expected. The workflow is entirely read-only.

This workflow covers analytics dashboards -- query counts, top domains, block reasons, and device activity. For investigating a specific blocked domain, see [Investigate Blocked Domain](investigate-blocked-domain.md). For security configuration review, see [Security Posture Audit](security-posture-audit.md).

## Commands

### Step 1: View the analytics dashboard

```
You: Show me DNS analytics for profile abc123
```

EmberAI calls `nextdns analytics` which gathers data from multiple analytics endpoints and produces a consolidated dashboard.

### Step 2: Review the dashboard

```
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
```

### Step 3: Drill into blocked domains

```
You: Show me the top blocked domains for the last 24 hours
```

```
EmberAI:

## Top Blocked Domains: Home (abc123)
| Domain                         | Queries | Reason              |
|--------------------------------|---------|---------------------|
| graph.facebook.com             | 445     | nextdns-recommended |
| ads.doubleclick.net            | 312     | oisd                |
| analytics.tiktok.com           | 187     | nextdns-recommended |
| metrics.icloud.com             | 156     | Native (Apple)      |
| app-measurement.com            | 134     | nextdns-recommended |
| mobile.events.data.microsoft.. | 98      | Native (Windows)    |
```

### Step 4: Check device activity

```
You: Show me which devices are making the most queries
```

```
EmberAI:

## Device Activity: Home (abc123)
| Device           | Model        | Local IP       | Queries |
|------------------|--------------|----------------|---------|
| macbook-pro      | MacBook Pro  | 192.168.1.101  | 5,234   |
| iphone-14        | iPhone       | 192.168.1.142  | 3,891   |
| pixel-8          | Pixel        | 192.168.1.155  | 2,102   |
| ring-doorbell    |              | 192.168.30.25  | 1,547   |
| sonos-one        |              | 192.168.30.12  | 1,023   |
| smart-tv         |              | 192.168.30.40  | 826     |
```

### Step 5: Review encryption status

```
You: What percentage of my DNS queries are encrypted?
```

```
EmberAI:

## Encryption Status: Home (abc123)
| Metric              | Value   |
|---------------------|---------|
| Encrypted           | 14,636  |
| Unencrypted         | 187     |
| Encrypted %         | 98.7%   |

### Protocol Breakdown
| Protocol             | Queries |
|----------------------|---------|
| DNS-over-HTTPS       | 12,102  |
| DNS-over-TLS         | 2,534   |
| UDP (unencrypted)    | 187     |

WARNING: 187 queries used unencrypted DNS (UDP). These queries are
visible to network intermediaries. The unencrypted queries likely
originate from IoT devices that do not support encrypted DNS.
```

## What to Look For

**Block rate:**
- A typical block rate for a well-configured profile is 10-25%. Below 5% may indicate insufficient blocklists. Above 40% may indicate an overly aggressive configuration.

**Top domains:**
- Look for unexpected high-volume domains. An IoT device querying an unknown domain thousands of times per day warrants investigation.
- Known tracker domains appearing as "Allowed" may indicate they are on the allowlist.

**Device activity:**
- Devices with unusually high query counts may be compromised, misbehaving, or have noisy firmware. Compare IoT device query counts to their expected behavior.
- Devices making queries you do not recognize should be investigated.

**Encryption:**
- Ideally 100% of queries should be encrypted (DoH or DoT). Unencrypted queries (UDP, TCP) are visible to network intermediaries.
- IoT devices often cannot use encrypted DNS -- this is expected. Consider routing them through a local DNS resolver that forwards over DoH.

**Block reasons:**
- The `nextdns-recommended` list should typically be the top reason. If `Denylist` is the top reason, you may have many custom blocks.
- A single blocklist producing the vast majority of blocks may indicate the other lists are redundant.

## Next Steps

- [Investigate Blocked Domain](investigate-blocked-domain.md) -- drill into a specific blocked domain to understand why
- [Security Posture Audit](security-posture-audit.md) -- review security configuration based on analytics findings
- [Parental Control Setup](parental-control-setup.md) -- block specific services for child profiles

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| 0 queries in analytics | Logging disabled on the profile | Enable logging: `nextdns manage --logs-enabled true` |
| 0 queries in analytics | Profile not actively used | Verify devices are configured to use this profile's DNS endpoint |
| Missing devices | Devices not using this profile | Check that devices point to the correct NextDNS DNS endpoint |
| All queries show "Allowed" | No blocklists configured | Add blocklists via `nextdns manage` or the NextDNS dashboard |
| No encryption data | Profile is new or has very few queries | Wait for sufficient query volume to generate encryption stats |
