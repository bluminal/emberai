# Full Firewall Posture Audit

## Intent

"I want to enumerate ZBF, ACLs, port forwarding and surface exposure and shadowed rules."

## Prerequisites

- **Plugin:** `unifi` v0.2.0 or later
- **API privileges:** Read-only access to the Local Gateway API
- **Environment variables:** `UNIFI_LOCAL_HOST` and `UNIFI_LOCAL_KEY` must be configured

## Context

Run this workflow before a security review, after a network change, or as part of a periodic compliance check. The audit enumerates all firewall configuration across zone-based firewall (ZBF) policies, access control lists (ACLs), and port forwarding rules. It identifies exposure risks (overly permissive rules, unnecessary port forwards), shadowed rules (rules that never match because an earlier rule already handles the traffic), and configuration inconsistencies.

This workflow is entirely read-only. No changes are made to the firewall configuration. For cross-vendor auditing that includes OPNsense gateway-side rules, use `netex firewall audit` from the umbrella plugin.

This workflow does not cover IDS/IPS alert triage -- the IDS trend summary is included for context, but detailed alert investigation requires the `opnsense` plugin.

## Commands

### Step 1: Run the security posture audit

```
You: Audit our firewall posture
```

```
EmberAI:

## Security Posture Audit

### Summary
| Metric            | Value |
|-------------------|-------|
| ZBF Policies      | 8     |
| ACL Rules         | 5     |
| Port Forwards     | 3     |
| IDS Alerts (24h)  | 12    |
| Findings          | 4     |

### Zone-Based Firewall Policies
| # | Source Zone | Dest Zone  | Action | Description              | Enabled |
|---|------------|------------|--------|--------------------------|---------|
| 1 | LAN        | WAN        | Allow  | Default outbound         | Yes     |
| 2 | LAN        | LAN        | Allow  | Intra-VLAN traffic       | Yes     |
| 3 | Guest      | WAN        | Allow  | Guest internet access    | Yes     |
| 4 | Guest      | LAN        | Block  | Guest isolation          | Yes     |
| 5 | Guest      | IoT        | Block  | Guest to IoT isolation   | Yes     |
| 6 | IoT        | WAN        | Allow  | IoT internet access      | Yes     |
| 7 | IoT        | LAN        | Block  | IoT isolation            | Yes     |
| 8 | WAN        | LAN        | Block  | Default inbound deny     | Yes     |

### Access Control Lists
| # | Action | Source           | Destination      | Protocol | Port   | Enabled | Log |
|---|--------|-----------------|------------------|----------|--------|---------|-----|
| 1 | Pass   | 192.168.1.0/24  | any              | any      | any    | Yes     | No  |
| 2 | Pass   | 192.168.30.0/24 | 192.168.1.50     | TCP      | 445    | Yes     | Yes |
| 3 | Pass   | any             | any              | any      | any    | Yes     | No  |
| 4 | Block  | 192.168.30.0/24 | 192.168.1.0/24   | any      | any    | Yes     | Yes |
| 5 | Pass   | 192.168.10.0/24 | 192.168.10.1     | UDP      | 53     | Yes     | No  |

### Port Forwarding Rules
| # | External Port | Internal IP     | Internal Port | Protocol | Description            | Enabled |
|---|---------------|-----------------|---------------|----------|------------------------|---------|
| 1 | 443           | 192.168.1.50    | 443           | TCP      | NAS HTTPS              | Yes     |
| 2 | 8080          | 192.168.1.75    | 80            | TCP      | Dev server             | Yes     |
| 3 | 32400         | 192.168.30.60   | 32400         | TCP      | Media server           | Yes     |

### IDS/IPS Summary (last 24 hours)
| Severity | Count | Top Category                      |
|----------|-------|-----------------------------------|
| High     | 1     | Misc Attack                       |
| Medium   | 3     | Attempted Information Leak        |
| Low      | 8     | Not Suspicious Traffic            |

### Findings

#### Critical
- **Shadowed rule detected**: ACL rule #4 (Block IoT to LAN) is shadowed
  by ACL rule #3 (Pass any to any). Rule #3 matches all traffic before
  rule #4 is evaluated, making the IoT block ineffective.
  Recommendation: Review rule #3. An unrestricted "pass any any" ACL is
  almost certainly a misconfiguration. Remove or restrict it, then verify
  the IoT block takes effect.

#### Warning
- **Overly permissive ACL**: ACL rule #3 permits all traffic from any
  source to any destination on all protocols. This bypasses all
  zone-based isolation policies.
  Recommendation: Remove this rule or restrict it to specific source
  networks and protocols. Audit who created it and why.

- **Port forward to IoT VLAN**: Port 32400 is forwarded to 192.168.30.60
  (IoT VLAN). IoT devices are typically less hardened than LAN devices.
  Exposing an IoT device directly to the internet increases attack surface.
  Recommendation: Evaluate whether this service can be moved to the LAN
  VLAN, or add IDS rules to monitor traffic to this port forward.

#### Informational
- **3 port forwards active**: External ports 443, 8080, and 32400 are
  exposed to the internet. This is the expected attack surface.
  Recommendation: Periodically verify each port forward is still needed
  and that the internal services are patched.
```

### Step 2: Drill into specific findings

```
You: Show me more detail on the shadowed rule
```

```
EmberAI:

## Shadow Analysis: ACL Rule #4

### The Shadowed Rule
| Field       | Value              |
|-------------|--------------------|
| Position    | 4                  |
| Action      | Block              |
| Source      | 192.168.30.0/24    |
| Destination | 192.168.1.0/24     |
| Protocol    | any                |
| Log         | Yes                |

### The Shadowing Rule
| Field       | Value              |
|-------------|--------------------|
| Position    | 3                  |
| Action      | Pass               |
| Source      | any                |
| Destination | any                |
| Protocol    | any                |
| Log         | No                 |

### Explanation

Rule #3 matches **all** traffic (any source, any destination, any
protocol) with action **pass**. Since it is evaluated before rule #4
in the chain, traffic from 192.168.30.0/24 to 192.168.1.0/24 matches
rule #3 first and is permitted -- rule #4 never fires.

This means IoT devices on 192.168.30.0/24 can reach LAN resources on
192.168.1.0/24, which contradicts the zone-based firewall policy
(IoT -> LAN: Block) at position #7.

### Impact

- IoT devices have unrestricted access to all LAN resources.
- The log flag on rule #4 will never produce entries, making this
  invisible in log analysis.
- The ZBF policy "IoT isolation" is effectively bypassed.
```

## What to Look For

**Zone-based firewall (ZBF) policies:**
- Every zone pair should have an explicit policy. Missing pairs default to the controller's global policy (usually deny).
- Guest and IoT zones should block access to LAN. If they do not, this is a critical finding.
- Verify the WAN-to-LAN direction is blocked (except via port forwards).

**Access control lists (ACLs):**
- Rules are evaluated top-to-bottom. A broad "pass any any" rule early in the chain nullifies all subsequent blocks.
- Look for "pass" rules with source "any" -- these are almost always overly permissive.
- Shadowed rules (blocks after broader passes) indicate either a misconfiguration or a rule that was once effective but was bypassed by a later change.

**Port forwarding:**
- Each port forward is an entry point from the internet. Minimize these.
- Port forwards to IoT or Guest VLANs are higher risk than LAN forwards.
- Verify each forward maps to a service that is actively maintained and patched.

**IDS/IPS trend:**
- High-severity alerts correlating with a specific port forward may indicate active exploitation.
- A sudden increase in alerts after a rule change suggests the change exposed new attack surface.

## Next Steps

- [Diagnose Client Complaint](diagnose-client-complaint.md) -- if a firewall rule is blocking legitimate traffic
- [Config Drift Detection](config-drift-detection.md) -- save a baseline after fixing findings and detect future rule changes
- [MSP Fleet Digest](msp-fleet-digest.md) -- audit firewall posture across all managed sites

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| No firewall rules returned | Security skill group not available | Verify the plugin version supports the security skill group (v0.2.0+) |
| ZBF policies show empty | ZBF not configured on the controller | Some UniFi deployments use ACLs only without ZBF; the audit will still analyze ACLs |
| Port forwards show empty | No port forwards configured | This is a good security posture; no action needed |
| IDS data unavailable | IDS/IPS not enabled on the controller | Enable IDS in UniFi Network settings, or use the `opnsense` plugin for Suricata-based IDS |
| Shadow analysis misses a rule | Complex rule with protocol/port qualifiers | Shadow analysis compares source/destination/protocol; highly specific rules may not be flagged as shadows of broader rules |
