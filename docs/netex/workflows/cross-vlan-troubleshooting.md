# Cross-VLAN Troubleshooting

> **Difficulty:** Advanced | **Time:** 15-30 minutes | **Risk:** Read-only (diagnosis), Write (fix)

## Problem Statement

A device on one VLAN cannot reach a service on another VLAN, or cross-VLAN traffic that should be blocked is getting through. This is the most common issue in segmented networks and requires checking both the gateway (routing + firewall) and the edge (VLAN tagging + trunking).

## Prerequisites

- Netex umbrella plugin installed
- OPNsense and UniFi plugins installed and authenticated
- Knowledge of the source and destination VLANs

## Workflow

### Step 1: Identify the Problem

```
"A device on the trusted VLAN (10.20.0.50) cannot reach the NAS
on the lab VLAN (10.60.0.10)"
```

### Step 2: Check Both Ends Exist

```
"netex vlan audit"
```

Verify both VLANs exist on both layers. If the lab VLAN (60) is missing from the gateway, there is no route between VLANs.

### Step 3: Trace the Path -- Gateway Layer

```
"Show me the routing table for 10.60.0.0/24"
```

Check:
- Is there a route for the destination subnet?
- Does the route point to the correct gateway IP?
- Is the VLAN interface for VLAN 60 in UP state?

```
"Show me firewall rules on the trusted VLAN interface"
```

Check:
- Is there an explicit allow rule for trusted -> lab traffic?
- Is there a deny rule that blocks this traffic before the allow rule? (Order matters)
- Is there any NAT rule that interferes?

### Step 4: Trace the Path -- Edge Layer

```
"What VLAN is the device at 10.20.0.50 on?"
"What port is 10.60.0.10 connected to, and what is its VLAN assignment?"
```

Check:
- Is the source device actually on VLAN 20? (Wrong VLAN = wrong subnet)
- Is the NAS port assigned to VLAN 60 (native) or is VLAN 60 tagged on a trunk?
- Is the trunk between the switch and the gateway carrying both VLANs?

### Step 5: Check ARP and DHCP

```
"Show me ARP entries for 10.60.0.10 on the gateway"
"Show me DHCP leases for VLAN 60"
```

If the gateway cannot ARP-resolve the destination, the issue is at Layer 2:
- VLAN trunk not carrying VLAN 60
- Port profile mismatch on the switch
- Physical link issue

### Step 6: Test the Reverse Path

```
"Check if 10.60.0.10 can reach 10.20.0.50"
```

Cross-VLAN issues can be asymmetric -- traffic may flow in one direction but not the other if firewall rules are not bidirectional.

### Step 7: Diagnose "Traffic Getting Through" Issues

If the problem is that traffic is NOT being blocked when it should be:

```
"netex verify-policy --vlan 50"
```

This runs the expected-block tests from the manifest access policy. A failed expected-block test means a firewall rule gap.

Common causes:
- Missing deny rule on the source VLAN interface
- Deny rule exists but is positioned after a broader allow rule
- Default allow rule on the interface (OPNsense anti-lockout rule)

## Decision Tree

```
Can source ping gateway (.1 of its own VLAN)?
  No  -> Layer 2 issue: check port VLAN, trunk, physical link
  Yes -> Can source ping destination gateway (.1 of dest VLAN)?
    No  -> Firewall blocking: check inter-VLAN rules on gateway
    Yes -> Can source ping destination host?
      No  -> Destination issue: check dest host firewall, ARP, VLAN assignment
      Yes -> Application-level issue: check service ports, host firewall
```

## Working Safely

The troubleshooting workflow is entirely read-only. If you identify a fix (e.g., adding a firewall rule), use the appropriate write command with `--apply`.

## Related Workflows

- [VLAN Audit](vlan-audit.md)
- [Guest WiFi Isolation](guest-wifi-isolation.md)
- [Post-Change Policy Sync](post-change-policy-sync.md)
