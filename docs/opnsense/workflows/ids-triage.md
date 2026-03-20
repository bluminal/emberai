# IDS/IPS Alert Triage

> **Difficulty:** Advanced | **Time:** 15-30 minutes | **Risk:** Read-only (triage), Write (blocking)

## Problem Statement

Your OPNsense IDS (Suricata) is generating alerts and you need to determine which are genuine threats requiring action, which are false positives to suppress, and whether any active compromises are in progress.

## Prerequisites

- OPNsense plugin installed and authenticated
- Suricata IDS enabled on OPNsense (at minimum in IDS mode, optionally IPS)
- Read access to security and diagnostics tools
- Write access needed only if you want to add block rules

## Workflow

### Step 1: Review Recent Alerts

```
"Show me IDS alerts from the last 24 hours, sorted by severity"
```

The plugin calls `opnsense__security__list_ids_alerts` with a time filter. The output is severity-tiered:

- **Critical/High**: Active exploit attempts, C2 beacons, known malware signatures
- **Medium**: Port scans, protocol anomalies, policy violations
- **Low/Informational**: DNS queries to known tracking domains, TLS version warnings

### Step 2: Identify Top Talkers

```
"Group the IDS alerts by source IP and show the top 10"
```

This reveals which internal or external hosts are generating the most alerts. An internal host with many outbound alerts may indicate a compromised device.

### Step 3: Correlate with Client Data

```
"For the top alerting internal IPs, look up which devices they are
on the UniFi network"
```

If the unifi plugin is installed, the plugin calls `unifi__clients__list_clients` to identify:
- Device name and type
- Connected VLAN
- Switch port and AP
- Connection duration

This transforms a raw IP into an actionable device identity: "The Roku on the IoT VLAN (port 12, AP-Living-Room) is triggering ET MALWARE alerts."

### Step 4: Classify Each Alert Cluster

For each top-alerting source, classify the alerts:

| Classification | Action |
|---|---|
| **True positive -- active threat** | Block the source, investigate the device |
| **True positive -- policy violation** | Address the root cause (e.g., device on wrong VLAN) |
| **False positive -- benign traffic** | Suppress the rule SID for this source |
| **Noise -- informational only** | No action, optionally disable the rule |

### Step 5: Take Action

**For active threats:**
```
"Block IP 10.40.0.15 on the IoT VLAN interface"
```

The plugin creates a firewall block rule on the specific interface. The OutageRiskAgent assesses whether blocking this IP could affect your management session.

**For false positives:**
```
"Suppress Suricata rule SID 2024897 for source 10.20.0.50"
```

The plugin adds a suppress entry to the Suricata configuration, preventing future alerts from this specific source/rule combination.

### Step 6: Verify

```
"Show me IDS alerts from the last hour -- are the suppressed rules still firing?"
```

Confirm that:
- Blocked IPs are no longer generating new connection alerts
- Suppressed rules are no longer producing false positive alerts
- No new high-severity alerts have appeared from other sources

## Alert Severity Reference

| Suricata Severity | Typical Signatures | Priority |
|---|---|---|
| 1 (Critical) | ET MALWARE, ET TROJAN, ET EXPLOIT | Immediate triage |
| 2 (High) | ET SCAN, ET POLICY, ET WEB_SERVER | Same-day triage |
| 3 (Medium) | ET INFO, ET DNS, protocol anomalies | Weekly review |
| 4 (Low) | ET GAMES, ET CHAT, informational | Monthly review or suppress |

## Working Safely

The triage workflow is read-only. Write operations occur only when you explicitly:
- Add firewall block rules (firewall subsystem -- assessed by OutageRiskAgent)
- Suppress IDS rules (services subsystem -- LOW risk)

> **Required safety notice:** Network changes can result in outages that disconnect you from your ability to correct them. Never make changes to a network you cannot reach through an out-of-band path (serial console, IPMI/iDRAC, a separate management VLAN on a different physical interface, or physical access). Netex will assess this risk for you, but it cannot guarantee your recovery path -- only you can verify that.

## Related Workflows

- [Full Firewall Audit](full-firewall-audit.md)
- [Review Firewall Rules](review-firewall.md)
- [Check VPN Health](check-vpn-health.md)
