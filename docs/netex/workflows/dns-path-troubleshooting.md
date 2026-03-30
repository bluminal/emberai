# Troubleshoot DNS Resolution Path

## Intent

"A device on the IoT VLAN is accessing a domain that should be blocked. I need to trace the DNS path to find out why filtering is not working and fix it."

## Prerequisites

- **Plugins:** netex umbrella, opnsense (gateway), nextdns (dns), unifi (edge)
- **API privileges:** Read access on all plugins; write access on nextdns for denylist changes
- **Environment variables:** `NEXTDNS_API_KEY`, `OPNSENSE_API_KEY`, `OPNSENSE_API_SECRET`, `UNIFI_LOCAL_HOST`, `UNIFI_LOCAL_KEY` configured
- **For denylist changes:** `NEXTDNS_WRITE_ENABLED=true`
- **DNS logging:** Enabled on the relevant NextDNS profile

## Context

DNS filtering relies on a chain of correctly configured components: the device must use the gateway as its DNS resolver, the gateway's Unbound forwarder must route queries to the correct NextDNS profile, and the NextDNS profile must have the domain blocked. A failure at any point in this chain allows the domain to resolve.

This workflow traces the DNS resolution path step by step to identify where the filtering breakdown occurs. The investigation phase is read-only. Adding a domain to a denylist or fixing a forwarder configuration requires write access.

Common failure modes:
- The device uses a hardcoded DNS server (8.8.8.8), bypassing the gateway entirely
- The forwarder points to the wrong NextDNS profile (one without the blocklist)
- The domain is not on any active blocklist or denylist
- The forwarder is a catch-all and does not apply per-VLAN profile pinning

## Commands

### Step 1: Identify the device and its VLAN

```
You: Show me clients on the IoT VLAN
```

```
EmberAI:

## UniFi Clients: IoT VLAN (ID 30)

| Name            | MAC               | IP          | Last Seen  |
|-----------------|-------------------|-------------|------------|
| smart-tv        | aa:bb:cc:dd:ee:01 | 10.30.0.15  | 2 min ago  |
| thermostat      | aa:bb:cc:dd:ee:02 | 10.30.0.22  | 5 min ago  |
| ip-camera-01    | aa:bb:cc:dd:ee:03 | 10.30.0.31  | 1 min ago  |
| robot-vacuum    | aa:bb:cc:dd:ee:04 | 10.30.0.44  | 8 min ago  |

4 clients on IoT VLAN.
```

Identify which device is making the suspicious DNS query.

### Step 2: Trace the DNS path for the suspicious domain

```
You: Trace DNS for suspicious-tracker.com from the IoT VLAN
```

```
EmberAI:

## DNS Trace: suspicious-tracker.com

### Path
| Step | Layer          | Detail                                                       | Status    |
|------|----------------|--------------------------------------------------------------|-----------|
| 1    | Source         | VLAN: IoT (ID 30, subnet 10.30.0.0/24)                      | Identified|
| 2    | Forwarder      | OPNsense Unbound -> dns.nextdns.io/jkl012 (IoT profile)     | Configured|
| 3    | NextDNS        | Profile: IoT (jkl012) — suspicious-tracker.com ALLOWED       | Allowed   |

### Summary
DNS trace for 'suspicious-tracker.com' across 2 layer(s): gateway
(forwarder config), dns (NextDNS analytics). Domain is resolving
normally -- it is not on any active blocklist or denylist.
```

The trace reveals the domain is reaching NextDNS but is not blocked. The forwarder is correctly configured -- the issue is that the domain is not on the profile's blocklist or denylist.

### Step 3: Check if the forwarder is configured correctly

If step 2 showed a forwarder issue, check the configuration directly:

```
You: Show me the DNS forwarder configuration on OPNsense
```

```
EmberAI:

## OPNsense Unbound Domain Overrides

| Domain | Server                    | Description            |
|--------|---------------------------|------------------------|
| .      | dns.nextdns.io/abc123     | Home (catch-all)       |
| .      | dns.nextdns.io/jkl012     | IoT VLAN 10.30.0.0/24  |
| .      | dns.nextdns.io/def456     | Kids VLAN 10.60.0.0/24 |
| .      | dns.nextdns.io/ghi789     | Guest VLAN 10.50.0.0/24|
```

Verify the IoT VLAN override points to the correct profile.

### Step 4: Check NextDNS logs for the domain

```
You: Search NextDNS logs on profile jkl012 for suspicious-tracker.com
```

```
EmberAI:

## Log Search: IoT (jkl012)
Filter: domain=suspicious-tracker.com | 15 entries

| Timestamp           | Domain                 | Device IP   | Status  | Reason   |
|---------------------|------------------------|-------------|---------|----------|
| 2026-03-28 14:23:45 | suspicious-tracker.com | 10.30.0.15  | Allowed | default  |
| 2026-03-28 14:22:12 | suspicious-tracker.com | 10.30.0.15  | Allowed | default  |
| 2026-03-28 13:15:33 | suspicious-tracker.com | 10.30.0.15  | Allowed | default  |
| ...                 | ...                    | ...         | ...     | ...      |

Status "default" means the domain is not on any blocklist, denylist,
or security filter. It resolved normally.
```

The logs confirm the domain is resolving with status "default" -- it is not being filtered.

### Step 5: Add the domain to the denylist

```
You: Add suspicious-tracker.com to the denylist on IoT profile jkl012
```

```
EmberAI:

## Change Plan: IoT (jkl012)

| Action            | Domain                 |
|-------------------|------------------------|
| Add to denylist   | suspicious-tracker.com |

This will block all DNS queries for suspicious-tracker.com on the
IoT profile. All devices using this profile will be affected.

Apply this change? Requires --apply and NEXTDNS_WRITE_ENABLED=true.
```

```
You: Yes, apply

EmberAI: suspicious-tracker.com has been added to the denylist for
profile jkl012. DNS queries for this domain will now be blocked.
```

### Step 6: Verify the fix

```
You: Trace DNS for suspicious-tracker.com from the IoT VLAN
```

```
EmberAI:

## DNS Trace: suspicious-tracker.com

### Path
| Step | Layer          | Detail                                                       | Status    |
|------|----------------|--------------------------------------------------------------|-----------|
| 1    | Source         | VLAN: IoT (ID 30, subnet 10.30.0.0/24)                      | Identified|
| 2    | Forwarder      | OPNsense Unbound -> dns.nextdns.io/jkl012 (IoT profile)     | Configured|
| 3    | NextDNS        | Profile: IoT (jkl012) — suspicious-tracker.com BLOCKED       | Blocked   |

### Summary
Domain is now blocked at the NextDNS layer by the IoT profile denylist.
```

## What to Look For

**DNS trace shows "Allowed" with reason "default":**
- The domain is not on any blocklist or denylist. If it should be blocked, add it to the profile's denylist or activate a blocklist that covers it.

**DNS trace shows a different profile than expected:**
- The forwarder is misconfigured. The IoT VLAN may be using the catch-all forwarder (Home profile) instead of the IoT-specific override. Fix the Unbound domain override.

**No log entries for the domain:**
- The device may be using hardcoded DNS (8.8.8.8, 1.1.1.1) that bypasses Unbound entirely. Check the device's network settings. Consider adding firewall rules to redirect port 53 and 853 traffic from the IoT VLAN to the gateway.

**Forwarder not configured for the VLAN:**
- If there is no VLAN-specific domain override, IoT devices use the catch-all forwarder. The catch-all profile may have different filtering rules. Add a VLAN-specific override.

**Domain blocked but device still accessing it:**
- DNS cache on the device. The device cached the previous (allowed) DNS response. Wait for the TTL to expire (typically 5-60 minutes) or reboot the device.
- The device may use DNS-over-HTTPS to a non-NextDNS resolver, bypassing both Unbound and NextDNS.

## Working Safely

- Steps 1-4 (identification, tracing, log search) are entirely read-only.
- Adding a domain to the denylist (Step 5) is a write operation requiring `NEXTDNS_WRITE_ENABLED=true` and `--apply`.
- A denylist entry affects all devices using that profile. If you only want to block for a specific device, consider per-device rules in the NextDNS profile's parentalControl settings.
- Denylist changes take effect immediately for new DNS queries. Cached responses on devices must expire first.

## Next Steps

- [VLAN-to-Profile Pinning Verification](vlan-to-profile-pinning.md) -- verify all VLANs are using the correct profiles
- [Network-Wide DNS Audit](network-wide-dns-audit.md) -- comprehensive DNS security review
- [Investigate Blocked Domain](../../nextdns/workflows/investigate-blocked-domain.md) -- the reverse problem: a domain that is blocked but should not be
- [Cross-VLAN Troubleshooting](cross-vlan-troubleshooting.md) -- if the issue is at the network/firewall layer, not DNS

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Trace shows "No gateway plugin installed" | OPNsense plugin not installed | Install and configure the opnsense plugin |
| Trace shows "No DNS plugin installed" | NextDNS plugin not installed | Install the nextdns plugin for NextDNS-aware tracing |
| Domain blocked on NextDNS but device still resolves it | Device using hardcoded DNS (8.8.8.8) | Add firewall rules to redirect port 53/853 from the VLAN to the gateway |
| Denylist updated but domain still allowed | DNS cache on device or local resolver | Wait for TTL expiration or flush the device's DNS cache |
| Log search returns no entries | Logging disabled on the profile | Enable logging in the NextDNS profile settings |
| "NEXTDNS_WRITE_ENABLED is not set" error | Write operations not enabled | Set `NEXTDNS_WRITE_ENABLED=true` to modify the denylist |
| Trace shows catch-all profile instead of VLAN-specific | No VLAN-specific Unbound domain override | Add a domain override with the VLAN subnet in the description field |
