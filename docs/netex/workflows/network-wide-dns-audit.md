# Network-Wide DNS Security Audit

## Intent

"I want to perform a quarterly security audit of DNS filtering across my entire network -- verify every VLAN is using the correct NextDNS profile, audit each profile's security configuration, and review aggregate analytics for anomalies."

## Prerequisites

- **Plugins:** netex umbrella, opnsense (gateway), nextdns (dns)
- **Optional:** unifi (edge) for additional VLAN discovery
- **API privileges:** Read access on all plugins; write access on nextdns for remediation
- **Environment variables:** `NEXTDNS_API_KEY`, `OPNSENSE_API_KEY`, `OPNSENSE_API_SECRET` configured
- **For remediation:** `NEXTDNS_WRITE_ENABLED=true`
- **Recommended cadence:** Monthly or quarterly

## Context

A DNS security audit verifies that DNS filtering is correctly configured and operating effectively across the entire network. Over time, configuration drift can erode the security posture: new VLANs may be added without forwarder configuration, profiles may have security toggles disabled during debugging and never re-enabled, or allowlist entries may accumulate that undermine blocking.

This workflow combines four cross-vendor operations into a single audit session. Each step is read-only. Remediation (fixing weak profiles or mismatched forwarders) is a separate write operation at the end.

## Commands

### Step 1: Review cross-profile DNS analytics

Start with the big picture -- aggregate query volume, block rates, and encryption across all profiles:

```
You: Show me a DNS summary across all profiles for the last 30 days
```

```
EmberAI:

## Cross-Profile DNS Summary (last 30 days)

### Totals
| Metric          | Value      |
|-----------------|------------|
| Total Queries   | 1,247,832  |
| Total Blocked   | 198,450    |
| Block Rate      | 15.9%      |

### Per-Profile Breakdown
| Profile | ID      | Queries   | Blocked  | Block Rate | Encrypted |
|---------|---------|-----------|----------|------------|-----------|
| Home    | abc123  | 523,100   | 62,772   | 12.0%      | 99.8%     |
| Kids    | def456  | 412,560   | 103,140  | 25.0%      | 99.9%     |
| IoT     | jkl012  | 189,400   | 18,940   | 10.0%      | 98.2%     |
| Guest   | ghi789  | 122,772   | 13,598   | 11.1%      | 95.4%     |

### Encryption Audit
All profiles above 95% encrypted DNS. Guest profile has the lowest
encryption rate (95.4%) -- some guest devices may be using unencrypted
DNS resolvers directly.
```

Flag any profiles with unusually low block rates (may indicate missing blocklists) or low encryption percentages (may indicate DNS bypass).

### Step 2: Audit all NextDNS profiles for security weaknesses

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
| IoT     | 10/12    | 2          | 3        |
| Guest   | 8/12     | 1          | 4        |

Total: 9 findings across 4 profiles.

### Critical
- **[Guest] CSAM protection disabled**: CSAM blocking should always
  be active. Recommendation: enable the 'csam' toggle.

### High
- **[Guest] Low security coverage (8/12)**: Disabled: aiThreatDetection,
  dnsRebinding, nrd, ddns.
- **[IoT] Logging disabled**: No forensic capability for IoT devices.
- **[Guest] Logging disabled**: No forensic capability for guest devices.

### Warning
- **[Home] Block page not enabled**: Users see cryptic errors instead
  of an explanatory page when a domain is blocked.
- **[IoT] Recommended blocklist not active**: Missing 'nextdns-recommended'.
- **[Guest] Recommended blocklist not active**: Missing 'nextdns-recommended'.

### Informational
- **[IoT] No parental controls**: Expected for a device-only VLAN.
- **[Guest] No parental controls**: Expected for a guest network.
```

### Step 3: Verify VLAN-to-profile mapping

```
You: Verify my VLAN-to-NextDNS profile mappings
```

```
EmberAI:

## VLAN-to-NextDNS Profile Verification

| VLAN        | ID | Subnet         | Forwarder Target            | Profile   | Analytics | Status       |
|-------------|----|----------------|-----------------------------|-----------|-----------|--------------|
| management  | 10 | 10.10.0.0/24   | dns.nextdns.io/abc123       | Home      | 847 hits  | Verified     |
| trusted     | 20 | 10.20.0.0/24   | dns.nextdns.io/abc123       | Home      | 2,341 hits| Verified     |
| iot         | 30 | 10.30.0.0/24   | dns.nextdns.io/jkl012       | IoT       | 532 hits  | Verified     |
| cameras     | 40 | 10.40.0.0/24   | (none)                      | —         | —         | No forwarder |
| guest       | 50 | 10.50.0.0/24   | dns.nextdns.io/ghi789       | Guest     | 122 hits  | Verified     |
| kids        | 60 | 10.60.0.0/24   | dns.nextdns.io/def456       | Kids      | 1,204 hits| Verified     |
| quarantine  | 99 | 10.99.0.0/24   | (none)                      | —         | —         | No forwarder |

### Summary
Checked: 7 VLANs | Verified: 5 | No forwarder: 2 | Mismatches: 0
```

Confirm that isolated VLANs (cameras, quarantine) intentionally lack forwarders, and all other VLANs map to the expected profiles.

### Step 4: Run a full network security audit

```
You: netex secure audit
```

```
EmberAI:

## Network Security Audit

### DNS Security Domain
| Check                           | Status | Severity |
|---------------------------------|--------|----------|
| Unbound DNSSEC enabled          | PASS   | —        |
| All VLANs have DNS forwarding   | WARN   | Warning  |
| DNS query logging active        | FAIL   | High     |
| Encrypted DNS percentage > 95%  | PASS   | —        |
| No DNS rebinding vulnerabilities| PASS   | —        |

### Other Domains (summary)
| Domain           | Findings | Critical | High | Warning |
|------------------|----------|----------|------|---------|
| firewall-gw      | 1        | 0        | 0    | 1       |
| firewall-edge    | 0        | 0        | 0    | 0       |
| cross-layer      | 0        | 0        | 0    | 0       |
| vlan-isolation   | 0        | 0        | 0    | 0       |
| vpn-posture      | 2        | 0        | 1    | 1       |
| dns-security     | 3        | 0        | 2    | 1       |
| ids-ips          | 1        | 0        | 0    | 1       |
| wireless         | 0        | 0        | 0    | 0       |
| certs            | 1        | 0        | 0    | 1       |
| firmware         | 0        | 0        | 0    | 0       |
```

Review the dns-security domain findings from the NetworkSecurityAgent for issues that span the gateway and DNS layers.

### Step 5: Review DNS-layer findings

```
You: Show me details on the dns-security findings
```

```
EmberAI:

## DNS Security Findings

### High
- **DNS query logging disabled on 2 profiles**: IoT (jkl012) and
  Guest (ghi789) have logging disabled. Without logs, incident
  investigation is not possible for devices on these VLANs.

- **Guest profile security coverage below threshold**: Only 8 of 12
  security toggles enabled. AI threat detection, DNS rebinding
  protection, NRD blocking, and DDNS blocking are disabled.

### Warning
- **2 VLANs without DNS forwarder configuration**: cameras (40) and
  quarantine (99). These VLANs have no DNS filtering. Verify this is
  intentional (isolated VLANs should not have DNS access).
```

### Step 6: Remediate weak profiles

```
You: Apply the Kids profile security template to the Guest profile
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

```
You: Yes, apply

EmberAI: Security settings updated on Guest (ghi789). 5 settings
changed. Run the security audit again to verify the fix.
```

## What to Look For

**Cross-profile analytics anomalies:**
- A profile with a significantly lower block rate than others may have missing blocklists or an overly permissive allowlist.
- A profile with low encryption percentage suggests devices are using unencrypted DNS -- either hardcoded resolvers or misconfigured forwarders.
- A sudden spike in total queries on a profile may indicate a compromised device generating DNS traffic.

**Security audit findings:**
- CSAM protection should be enabled on every profile -- there is no legitimate reason to disable it.
- Logging should be enabled on every profile. Without logs, incident investigation is impossible.
- Security coverage below 10/12 indicates a profile that was likely created and never fully configured.

**VLAN-profile mapping:**
- Every non-isolated VLAN should map to a NextDNS profile. If a new VLAN was added without a forwarder, DNS queries from that VLAN use the catch-all forwarder (or the system resolver), which may not have appropriate filtering.
- Isolated VLANs (cameras, quarantine) should NOT have forwarders -- DNS access on these VLANs should be blocked at the firewall level.

**Network security audit DNS domain:**
- The NetworkSecurityAgent evaluates DNS from both the gateway (Unbound config, DNSSEC) and DNS service (NextDNS profiles) perspectives. Findings here may overlap with the NextDNS-specific audit but also cover gateway-level issues.

## Working Safely

- Steps 1-5 (analytics review, profile audit, VLAN verification, security audit) are entirely read-only.
- Remediation (Step 6) requires `NEXTDNS_WRITE_ENABLED=true` and `--apply`.
- Template application only changes security toggles. Blocklists, denylist/allowlist entries, and parental controls are separate.
- Review each finding before remediating. Some findings are intentional (e.g., no parental controls on a guest profile, no forwarder on an isolated VLAN).

## Next Steps

- [VLAN-to-Profile Pinning Verification](vlan-to-profile-pinning.md) -- deeper investigation of a specific VLAN mapping issue
- [DNS Path Troubleshooting](dns-path-troubleshooting.md) -- trace a specific domain if the audit reveals unexpected allows
- [Security Posture Audit](../../nextdns/workflows/security-posture-audit.md) -- NextDNS-specific audit with profile comparisons
- [Post-Change Policy Sync](post-change-policy-sync.md) -- verify no configuration drift after remediation changes

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Cross-profile summary shows 0 queries | NextDNS plugin not installed or API key misconfigured | Verify `NEXTDNS_API_KEY` is set and valid |
| Security audit returns no dns-security findings | NextDNS plugin not installed; audit only checks gateway-level DNS | Install the nextdns plugin for full DNS security auditing |
| VLAN verification shows all "no forwarder" | No Unbound domain overrides configured | Configure domain overrides in OPNsense Unbound for each VLAN |
| Template application fails | `NEXTDNS_WRITE_ENABLED` not set or `--apply` not included | Set `NEXTDNS_WRITE_ENABLED=true` and include `--apply` |
| Encryption percentage dropping over time | New devices using unencrypted DNS resolvers | Add firewall rules to redirect port 53 traffic from affected VLANs to the gateway |
| Profile shows high block rate but users report no blocking | DNS responses cached at device or intermediate resolver | Flush DNS caches; check if devices have a local caching resolver |
