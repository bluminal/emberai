---
title: Multi-WAN Gateway Groups & Failover
triggers: [gateway, failover, multi-wan, wan2, policy routing, gateway group]
severity: critical
created: 2026-03-24
---

# Multi-WAN Gateway Groups & Failover on OPNsense

## Summary

Setting up gateway groups for WAN failover and policy-based routing requires several OPNsense settings beyond just creating the groups and assigning them to firewall rules. Without these settings, a WAN failure will cause a complete DNS outage for the entire network.

## Required Settings

### 1. Gateway Monitoring (System > Gateways > Configuration)

Each gateway **must** have a Monitor IP set, or dpinger cannot detect outages and the `trigger: "down"` failover condition never fires.

- WAN1 (e.g., WAN_DHCP): Monitor IP = `1.1.1.1` (or another reliable external IP)
- WAN2 (e.g., WAN2_DHCP): Monitor IP = `8.8.8.8` (use a different IP than WAN1)

Without monitor IPs, all gateways show `status: "none"` in the API and failover groups are inert.

### 2. Gateway Switching (System > Settings > General)

**"Allow default gateway switching"** must be checked. This lets OPNsense automatically switch the system default gateway when dpinger detects a WAN is down. Without it, the system default route stays pointed at a dead gateway.

### 3. DNS Server Gateway Binding (System > Settings > General)

The system DNS servers (listed under "DNS servers") should have their "Use gateway" dropdown set to a specific gateway (e.g., `WAN_DHCP`) rather than `none`. When set to `none`, DNS queries from the firewall itself use the system default route, which may point at a down WAN.

Note: This dropdown only shows individual gateways, not gateway groups. If you need DNS failover, rely on gateway switching (setting #2) combined with a pinned gateway here.

### 4. Disable Force Gateway (Firewall > Settings > Advanced) -- CRITICAL

**"Disable force gateway"** MUST be checked. When unchecked (the default), OPNsense forces local services (Unbound DNS, NTP, etc.) to use the gateway assigned in firewall rules AND omits the `pass out all` rule from the generated pf ruleset. This means the firewall itself cannot send any outbound traffic (DNS, dpinger health checks, etc.).

Without this setting, every firewall apply/reload strips the `pass out all` rule, which causes:
- dpinger can't ping monitor IPs → reports all gateways as down
- Unbound can't reach upstream DNS → network-wide DNS outage
- "Skip rules when gateway is down" then skips all gateway-group rules → total internet loss
- A cascading failure that requires SSH access to recover

### 5. Skip Rules on Down Gateway (Firewall > Settings > Advanced) -- DO NOT ENABLE

**"Skip rules when gateway is down"** MUST remain **unchecked**. Despite sounding helpful, this setting causes catastrophic cascading failures with gateway groups:

1. dpinger briefly reports a gateway as down (even a transient hiccup)
2. OPNsense disables ALL firewall rules referencing that gateway
3. Internet access rules for every VLAN using that gateway group are skipped
4. DNS breaks network-wide (Unbound can't reach upstream resolvers)
5. dpinger can't resolve/reach monitor IPs → reports gateways as permanently down
6. Death spiral — requires console access to recover

With this setting OFF, a down gateway in a gateway group simply means traffic uses the failover tier, which is the correct behavior.

### 6. Floating Rule Safety Net (Firewall > Rules > Floating)

Create an explicit floating rule as a permanent safety net:
- Direction: **Out**, Action: **Pass**, Interface: **All**, Protocol: **any**
- Source: **any**, Destination: **any**
- Description: "Allow firewall outbound traffic"

This ensures the firewall can always send outbound traffic (dpinger probes, DNS, NTP) regardless of how the pf ruleset is regenerated.

### 7. Socket Buffer Size (persistent sysctl)

Repeated Unbound restarts during outage recovery can exhaust socket buffers. Add to `/etc/sysctl.conf`:
```
kern.ipc.maxsockbuf=16777216
```

## What Goes Wrong Without These Settings

When a WAN goes down without proper configuration:

1. The gateway group detects nothing (no monitor IP = no health check)
2. The system default route may still point at the dead WAN
3. Unbound DNS tries to reach NextDNS (or other upstream resolvers) via the dead WAN
4. All DNS resolution fails network-wide
5. The OPNsense web UI/API may become unresponsive (it depends on DNS too)
6. The `pass out all` pf rule may disappear from the ruleset, blocking all firewall-originated outbound traffic

## Recovery Steps (if DNS is already broken)

If you're already in a DNS outage state:

1. SSH to OPNsense: `ssh root@<opnsense-ip>`
2. Kill hung Unbound: `killall -9 unbound`
3. Check if `pass out all` rule exists: `pfctl -sr | grep "pass out all"`
4. If missing, add it: `echo "pass out all keep state" | pfctl -m -f -`
5. Restart Unbound: `/usr/local/sbin/unbound -c /var/unbound/unbound.conf`
6. Verify: `drill amazon.com @<gateway-ip>`

## Gateway Groups API Notes

- OPNsense 26.x does **not** have an MVC API for gateway group CRUD. Gateway groups must be created via the legacy PHP form at `/system_gateway_groups_edit.php`.
- The gateway status API is at `GET /api/routes/gateway/status` and returns an `items` array.
- DHCP-based gateways (e.g., `WAN2_DHCP`) disappear entirely from the gateway list when the DHCP lease is lost. They are not shown as "offline" -- they simply vanish.
- Gateway group listing may be available at `GET /api/routes/gateway/searchgroup` on some 26.x versions (returns 404 on others).

## Starlink CGNAT Consideration

Starlink uses CGNAT addresses (100.64.0.0/10). The WAN interface will have an IP in this range (e.g., 100.94.200.2). This is important because:

- The bogon filter does NOT include 100.64.0.0/10 by default on OPNsense (verified)
- Anti-spoofing rules are generated automatically and include `block drop in log on ! igb0 inet from 100.64.0.0/10 to any` -- this is normal and expected
- If "Block bogon networks" is enabled on WAN, verify that 100.64.0.0/10 is not in the bogon table: `pfctl -t bogons -T show | grep 100.64`
