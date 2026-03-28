# Parental Control Setup

## Intent

"I want to configure parental controls on a NextDNS profile to protect children from inappropriate content."

## Prerequisites

- **Plugin:** `nextdns` v0.1.0 or later
- **API privileges:** Read and write access to NextDNS API
- **Environment variables:** `NEXTDNS_API_KEY` and `NEXTDNS_WRITE_ENABLED=true` must be configured
- **Target profile:** A NextDNS profile assigned to devices used by children

## Context

Run this workflow when setting up a new child profile or reviewing existing parental controls. The workflow walks through viewing current settings, enabling SafeSearch and YouTube restrictions, blocking specific services, and verifying the configuration with a security audit.

This workflow modifies profile settings. All changes require `NEXTDNS_WRITE_ENABLED=true`, the `--apply` flag, and operator confirmation before execution.

This workflow focuses on DNS-level parental controls. For network-level isolation (VLAN segmentation, firewall rules), use the unifi and opnsense plugins.

## Commands

### Step 1: View current parental controls

```
You: Show me parental controls for profile def456
```

```
EmberAI:

## Parental Controls: Kids (def456)

| Setting                  | Value    |
|--------------------------|----------|
| SafeSearch               | Disabled |
| YouTube Restricted Mode  | Disabled |
| Bypass Prevention        | Disabled |

### Blocked Services
(none)

### Blocked Categories
(none)
```

### Step 2: Enable SafeSearch and YouTube Restricted Mode

```
You: Enable SafeSearch and YouTube restricted mode on the Kids profile
```

```
EmberAI:

## Change Plan: Kids (def456)

| Setting                  | Current  | Proposed |
|--------------------------|----------|----------|
| safeSearch               | false    | true     |
| youtubeRestrictedMode    | false    | true     |

SafeSearch forces safe search results on Google, Bing, DuckDuckGo,
and YouTube. YouTube Restricted Mode hides potentially mature content.

Apply this change? Requires --apply and NEXTDNS_WRITE_ENABLED=true.
```

```
You: Apply it

EmberAI: Parental control settings updated. safeSearch and
youtubeRestrictedMode are now enabled on profile def456.
```

### Step 3: Block specific services

```
You: Block TikTok and Instagram on the Kids profile
```

```
EmberAI:

## Change Plan: Kids (def456)

| Setting  | Current | Proposed            |
|----------|---------|---------------------|
| services | (none)  | tiktok, instagram   |

This will block DNS resolution for TikTok and Instagram domains on
all devices using this profile. Users will see a block page (if
enabled) when attempting to access these services.

Note: Service blocking operates at the DNS level. Determined users
may bypass this by using alternative DNS resolvers unless bypass
prevention is also enabled.

Apply this change? Requires --apply and NEXTDNS_WRITE_ENABLED=true.
```

```
You: Yes, apply

EmberAI: Services updated. TikTok and Instagram are now blocked on
profile def456.
```

### Step 4: Enable bypass prevention

```
You: Also enable bypass prevention on the Kids profile
```

```
EmberAI:

## Change Plan: Kids (def456)

| Setting       | Current | Proposed |
|---------------|---------|----------|
| blockBypass   | false   | true     |

Bypass prevention blocks access to DNS-over-HTTPS (DoH) endpoints,
DNS-over-TLS (DoT) endpoints, VPN services, and anonymizing proxies
at the DNS level. This makes it harder to circumvent the parental
controls.

WARNING: This will also block legitimate VPN usage on devices using
this profile. If a child needs VPN access for school, consider
adding that VPN provider's domain to the allowlist.

Apply this change? Requires --apply and NEXTDNS_WRITE_ENABLED=true.
```

### Step 5: Verify with a security audit

```
You: Audit the Kids profile
```

```
EmberAI:

## Security Posture Audit: Kids (def456)

### Summary
| Metric          | Value |
|-----------------|-------|
| Security        | 12/12 |
| Blocklists      | 4     |
| Parental Active | Yes   |
| Findings        | 0     |

No findings. Profile is well-configured.

### Parental Controls Summary
| Setting                  | Value                |
|--------------------------|----------------------|
| SafeSearch               | Enabled              |
| YouTube Restricted Mode  | Enabled              |
| Blocked Services         | TikTok, Instagram    |
| Bypass Prevention        | Enabled              |
```

## What to Look For

**SafeSearch:**
- Forces safe results on major search engines. Works at the DNS level so it cannot be disabled in browser settings.
- Does not cover all search engines -- only Google, Bing, DuckDuckGo, YouTube, and a few others.

**YouTube Restricted Mode:**
- Hides potentially mature content and prevents viewing of comments on most videos.
- Works independently of YouTube's in-app settings.

**Service blocking:**
- Blocks DNS resolution for the entire service. There is no partial blocking (e.g., you cannot allow TikTok browsing but block uploads).
- Available services include: TikTok, Instagram, Facebook, Snapchat, Twitter/X, Discord, Twitch, Reddit, Pinterest, Tumblr, Steam, Roblox, Fortnite, Minecraft, and many more.

**Bypass prevention:**
- Critical for parental controls to be effective. Without it, a child can configure a device to use a different DNS resolver (8.8.8.8, 1.1.1.1) and bypass all NextDNS controls.
- Also blocks VPN services and proxies, which is the trade-off.

**Category blocking:**
- Categories provide broader content filtering (e.g., `porn`, `gambling`, `piracy`, `social-networks`).
- Categories are coarser than service blocking -- use services for specific apps and categories for broad content types.

## Working Safely

- All changes follow the three-phase confirmation model: resolve ambiguities, present the plan, single confirmation.
- Service and category lists are replacement operations -- specifying a new list replaces the existing one entirely. To add a service, include all existing services plus the new one.
- Bypass prevention blocks legitimate VPN usage. Consider the impact on schoolwork or work-from-home scenarios.
- Test changes by attempting to access a blocked service from a device on the profile.

## Next Steps

- [Security Posture Audit](security-posture-audit.md) -- verify the profile's overall security configuration
- [Investigate Blocked Domain](investigate-blocked-domain.md) -- if a child reports a legitimate site is blocked
- [DNS Analytics Review](dns-analytics-review.md) -- monitor what the child's devices are querying

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Service still accessible after blocking | DNS cache on the device | Clear the device's DNS cache or wait for TTL expiration |
| SafeSearch not working on a browser | Browser using its own DNS (DoH) | Enable bypass prevention to block alternative DNS resolvers |
| Blocked service accessible via mobile data | Mobile data bypasses home DNS | Configure NextDNS on the device directly (not just the router) |
| "services list is empty after update" | Replacement semantics | Include all desired services in the list, not just the new one |
| VPN needed for school | Bypass prevention blocks all VPNs | Add the specific VPN provider's domain to the allowlist |
