# Verify VLAN-to-NextDNS Profile Pinning

## Intent

"I want to confirm that devices on each VLAN are using the correct NextDNS profile for DNS filtering -- especially that Kids devices on VLAN 60 are going through the Kids profile, not the general Home profile."

## Prerequisites

- **Plugins:** netex umbrella, opnsense (gateway), nextdns (dns)
- **Optional:** unifi (edge) for additional VLAN discovery
- **API privileges:** Read access on all plugins
- **Environment variables:** `NEXTDNS_API_KEY`, `OPNSENSE_API_KEY`, `OPNSENSE_API_SECRET` configured
- **DNS forwarders:** OPNsense Unbound domain overrides configured with NextDNS profile endpoints

## Context

In a segmented home network, each VLAN should route DNS queries through a specific NextDNS profile. The Kids VLAN uses a profile with strict parental controls and a denylist for social media. The Guest VLAN uses a profile with basic security but no parental controls. If the forwarder is misconfigured -- or if devices are bypassing the forwarder entirely -- DNS filtering is not enforced.

This workflow verifies the full chain: VLAN subnet, OPNsense forwarder configuration, NextDNS profile identity, and analytics traffic confirmation. It is entirely read-only. If a mismatch is found, a separate write operation is needed to fix the OPNsense Unbound configuration.

## Commands

### Step 1: Run the VLAN-profile verification

```
You: Verify my VLAN-to-NextDNS profile mappings
```

Netex calls `netex__dns__verify_profiles`, which queries the gateway for all VLANs and DNS forwarder config, then cross-references with NextDNS profiles and analytics.

### Step 2: Review the verification report

```
EmberAI:

## VLAN-to-NextDNS Profile Verification

| VLAN        | ID | Subnet         | Forwarder Target            | Profile   | Analytics | Status       |
|-------------|----|----------------|-----------------------------|-----------|-----------|--------------|
| management  | 10 | 10.10.0.0/24   | dns.nextdns.io/abc123       | Home      | 847 hits  | Verified     |
| trusted     | 20 | 10.20.0.0/24   | dns.nextdns.io/abc123       | Home      | 2,341 hits| Verified     |
| iot         | 30 | 10.30.0.0/24   | dns.nextdns.io/jkl012       | IoT       | 532 hits  | Verified     |
| cameras     | 40 | 10.40.0.0/24   | (none)                      | —         | —         | No forwarder |
| guest       | 50 | 10.50.0.0/24   | dns.nextdns.io/ghi789       | Guest     | 0 hits    | No traffic   |
| kids        | 60 | 10.60.0.0/24   | dns.nextdns.io/def456       | Kids      | 1,204 hits| Verified     |
| quarantine  | 99 | 10.99.0.0/24   | (none)                      | —         | —         | No forwarder |

### Summary
Checked: 7 VLANs | Verified: 4 | No forwarder: 2 | No traffic: 1
```

The Kids VLAN (60) shows `Verified` -- the forwarder points to the Kids profile (`def456`) and NextDNS analytics confirm traffic from the 10.60.0.0/24 subnet is hitting that profile.

### Step 3: Investigate a mismatch by tracing a specific domain

If the Kids VLAN showed a mismatch or `no_traffic`, trace a known blocked domain to pinpoint the failure:

```
You: Trace DNS for tiktok.com from the Kids VLAN
```

```
EmberAI:

## DNS Trace: tiktok.com

### Path
| Step | Layer          | Detail                                                       | Status    |
|------|----------------|--------------------------------------------------------------|-----------|
| 1    | Source         | VLAN: Kids (ID 60, subnet 10.0.60.0/24)                     | Identified|
| 2    | Forwarder      | OPNsense Unbound -> dns.nextdns.io/def456 (Kids profile)    | Configured|
| 3    | NextDNS        | Profile: Kids (def456) — tiktok.com BLOCKED by denylist     | Blocked   |

### Summary
Domain is blocked at the NextDNS layer by the Kids profile denylist.
```

The trace confirms the full path is working: the Kids VLAN routes through the correct NextDNS profile, and TikTok is blocked by the Kids denylist.

### Step 4: View NextDNS analytics for the Kids profile

For a deeper look at what the Kids profile is blocking:

```
You: Show me DNS analytics for the Kids profile def456
```

```
EmberAI:

## DNS Analytics: Kids (def456)

### Query Summary (last 24 hours)
| Metric          | Value   |
|-----------------|---------|
| Total Queries   | 4,821   |
| Blocked         | 1,204   |
| Block Rate      | 25.0%   |
| Encrypted       | 99.9%   |

### Top Blocked Domains
| Domain              | Queries | Reason    |
|---------------------|---------|-----------|
| tiktok.com          | 312     | Denylist  |
| instagram.com       | 287     | Denylist  |
| ads.youtube.com     | 198     | oisd      |
| tracker.example.com | 107     | Blocklist |
```

### Step 5: Fix a forwarder misconfiguration (if needed)

If a VLAN is pointing to the wrong profile, fix the OPNsense Unbound domain override:

```
You: The guest VLAN forwarder is pointing to 1.1.1.1 instead of the
Guest NextDNS profile ghi789. Fix the Unbound forwarder.
```

This requires the `opnsense__services__configure_dns_forwarder` tool with `OPNSENSE_WRITE_ENABLED=true` and `--apply`.

## What to Look For

**Verified status:**
- The forwarder target contains a NextDNS profile ID, and analytics confirm traffic from the VLAN's subnet is hitting that profile. This is the healthy state.

**No forwarder:**
- Expected for isolated VLANs (cameras, quarantine) that should not have DNS access. A problem if the VLAN is supposed to have filtered DNS.

**No traffic:**
- The forwarder is configured but analytics show zero queries from the VLAN's subnet. Possible causes: no active clients on the VLAN, the forwarder URL is malformed, or devices are using hardcoded DNS servers (8.8.8.8, 1.1.1.1) that bypass Unbound.

**Non-NextDNS forwarder:**
- The forwarder target points to a non-NextDNS resolver (e.g., 1.1.1.1, 9.9.9.9). Analytics verification is not possible. This is only a problem if the VLAN was supposed to use a NextDNS profile.

**Wrong profile:**
- If the Kids VLAN is pointing to the Home profile instead of the Kids profile, parental controls and the Kids denylist are not enforced. Run `netex dns trace` with a domain that should be blocked on Kids but not Home (e.g., `tiktok.com`) to confirm.

## Working Safely

- The entire verification workflow is read-only. No network changes are made.
- Fixing a forwarder misconfiguration requires an OPNsense write operation. Follow the standard three-phase confirmation model.
- Changing a forwarder does not disrupt existing connections -- it only affects new DNS queries. Existing cached responses on client devices will expire based on their TTL.

## Next Steps

- [DNS Path Troubleshooting](dns-path-troubleshooting.md) -- if a device is bypassing DNS filtering
- [Network-Wide DNS Audit](network-wide-dns-audit.md) -- quarterly security audit of DNS filtering
- [Cross-VLAN Troubleshooting](cross-vlan-troubleshooting.md) -- if the issue is at the network layer, not DNS
- [VLAN Audit](vlan-audit.md) -- verify VLAN consistency between gateway and edge

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| All VLANs show "no forwarder" | No Unbound domain overrides configured | Configure domain overrides in OPNsense Unbound pointing to NextDNS profile endpoints |
| VLAN shows "verified" but devices are not filtered | Devices using hardcoded DNS (8.8.8.8) that bypasses Unbound | Add firewall rules to redirect port 53/853 traffic to the gateway |
| VLAN shows "no traffic" despite active clients | Forwarder URL is malformed or uses wrong protocol | Check the forwarder target in OPNsense; should be `dns.nextdns.io/{profile_id}` |
| "No gateway plugin installed" error | OPNsense plugin not installed or not authenticated | Install and configure the opnsense plugin |
| "No DNS plugin installed" warning | NextDNS plugin not installed | Install the nextdns plugin for full verification; basic forwarder checks still work without it |
