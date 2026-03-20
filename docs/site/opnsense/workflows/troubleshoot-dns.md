# Troubleshoot DNS Resolution

## Intent

"I want to confirm that Unbound resolves hostnames correctly and check my DNS overrides and forwarder configuration."

## Prerequisites

- **Plugin:** `opnsense` v0.2.0 or later
- **API privileges:** Read-only access to the Unbound DNS section in Effective Privileges
- **Environment variables:** `OPNSENSE_HOST`, `OPNSENSE_API_KEY`, and `OPNSENSE_API_SECRET` must be configured
- **Unbound DNS enabled:** Unbound must be the active DNS resolver on the OPNsense instance

## Context

Run this workflow when clients report DNS resolution failures, when you have added or changed DNS host overrides, or as part of a routine check on your DNS infrastructure. The workflow covers Unbound DNS configuration -- host overrides, forwarders, DNS-over-TLS status, and live hostname resolution testing.

This workflow is entirely read-only. It verifies the DNS configuration and tests resolution but does not modify any DNS settings.

This workflow covers OPNsense's Unbound DNS resolver only. If you are using a separate DNS server (Pi-hole, AdGuard Home, etc.) as a downstream resolver, this workflow verifies that Unbound is forwarding correctly but does not inspect the downstream server configuration.

## Commands

### Step 1: Check DNS configuration

```
You: Check my DNS configuration
```

EmberAI calls `opnsense dns` to list host overrides, forwarders, and DNS-over-TLS status.

### Step 2: Review the configuration

```
EmberAI:

## DNS Configuration (Unbound)

### Host Overrides
| Hostname | Domain     | IP          | Description        |
|----------|------------|-------------|--------------------|
| nas      | home.local | 10.30.0.10  | Synology NAS       |
| printer  | home.local | 10.0.0.50   | Office printer     |
| plex     | home.local | 10.30.0.20  | Plex Media Server  |
| pihole   | home.local | 10.30.0.30  | Pi-hole DNS        |

### Forwarders
| Server        | Port | Domain | DoT    |
|---------------|------|--------|--------|
| 1.1.1.1       | 853  | --     | Yes    |
| 1.0.0.1       | 853  | --     | Yes    |

## Findings

### Informational
- **DNS-over-TLS enabled**: Both forwarders use DoT (port 853).
  DNS queries to upstream resolvers are encrypted.
- **4 host overrides configured**: Local hostnames resolve to
  internal IPs without querying upstream DNS.
```

### Step 3: Test resolution for a specific hostname

```
You: Can Unbound resolve nas.home.local?
```

EmberAI calls `opnsense dns nas.home.local` which adds a live resolution test.

### Step 4: Review the resolution test

```
EmberAI:

## DNS Configuration (Unbound)

### Host Overrides
| Hostname | Domain     | IP          | Description        |
|----------|------------|-------------|--------------------|
| nas      | home.local | 10.30.0.10  | Synology NAS       |
| printer  | home.local | 10.0.0.50   | Office printer     |
| plex     | home.local | 10.30.0.20  | Plex Media Server  |
| pihole   | home.local | 10.30.0.30  | Pi-hole DNS        |

### Forwarders
| Server        | Port | Domain | DoT    |
|---------------|------|--------|--------|
| 1.1.1.1       | 853  | --     | Yes    |
| 1.0.0.1       | 853  | --     | Yes    |

### Resolution Test: nas.home.local
| Field    | Value          |
|----------|----------------|
| Hostname | nas.home.local |
| IP       | 10.30.0.10     |
| TTL      | 3600           |
| Source   | Local override  |

DNS resolution successful -- nas.home.local resolves to 10.30.0.10
via local host override.
```

### Step 5: Test an external hostname (optional)

```
You: Can it resolve github.com?
```

```
EmberAI:

### Resolution Test: github.com
| Field    | Value          |
|----------|----------------|
| Hostname | github.com     |
| IP       | 140.82.121.4   |
| TTL      | 60             |
| Source   | Forwarded (1.1.1.1:853, DoT) |

DNS resolution successful -- github.com resolves to 140.82.121.4
via upstream forwarder with DNS-over-TLS.
```

## What to Look For

**Host overrides:**
- **IP addresses** -- verify each override points to the correct internal IP. A stale override (pointing to an old IP) will cause resolution failures for that hostname.
- **Domain consistency** -- all overrides should use the same local domain (e.g., `home.local`). Mixed domains may cause confusion.
- **Missing overrides** -- if a local service is not resolvable by hostname, check whether a host override exists for it.

**Forwarders:**
- **DNS-over-TLS (DoT)** -- forwarders using port 853 with DoT enabled encrypt DNS queries to upstream resolvers. Port 53 without DoT sends queries in plaintext.
- **Multiple forwarders** -- having at least two forwarders provides redundancy if one upstream resolver is unreachable.
- **Domain-specific forwarders** -- if you have a split-DNS setup (e.g., VPN traffic uses a different resolver), verify the domain restrictions are correct.

**Resolution tests:**
- **Source field** -- tells you where the answer came from. `Local override` means Unbound answered from its host override table. `Forwarded` means the query was sent to an upstream resolver. `Cached` means the answer was served from Unbound's cache.
- **TTL** -- time-to-live in seconds. Very low TTLs (< 30s) mean the record will be re-queried frequently. Very high TTLs (> 86400s / 24h) mean changes to the record will take a long time to propagate.

## Next Steps

- [First-Time System Scan](first-time-scan.md) -- verify interfaces and VLANs if DNS issues are VLAN-specific
- [Review Firewall Rules](review-firewall.md) -- check that firewall rules allow DNS traffic (UDP/TCP port 53) from client VLANs to the OPNsense interface
- [DHCP Lease Audit](dhcp-lease-audit.md) -- verify DHCP is handing out the correct DNS server address to clients

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Resolution test fails for local hostname | Host override missing or misspelled | Add or correct the host override in Services > Unbound DNS > Host Overrides |
| Resolution test fails for external hostname | Forwarder misconfigured or unreachable | Verify forwarder addresses; test connectivity with `opnsense diagnose 1.1.1.1` |
| DoT column shows "No" | DNS-over-TLS not configured | Edit the forwarder in Services > Unbound DNS > DNS over TLS and enable it on port 853 |
| 0 host overrides returned | API privileges missing | Add Unbound DNS to Effective Privileges |
| Resolution works from OPNsense but not from clients | Clients not using OPNsense as DNS server | Check DHCP settings -- the DNS server should be the OPNsense VLAN gateway IP (e.g., 10.0.0.1) |
| Slow resolution for external domains | Cache miss + high latency to forwarder | Check forwarder RTT; consider using a lower-latency upstream resolver or enabling prefetch in Unbound settings |
