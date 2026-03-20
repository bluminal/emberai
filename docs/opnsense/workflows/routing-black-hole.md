# Diagnosing a Routing Black Hole

> **Difficulty:** Advanced | **Time:** 15-30 minutes | **Risk:** Read-only

## Problem Statement

Traffic destined for a specific subnet is silently dropped. Clients can reach some VLANs but not others. Traceroutes stop at the OPNsense gateway with no ICMP unreachable response -- a classic routing black hole.

## Prerequisites

- OPNsense plugin installed and authenticated
- Read access to routing, interfaces, and diagnostics tools
- Know the affected source and destination subnets

## Workflow

### Step 1: Verify the Symptom

```
"Show me the routing table and highlight any routes for 10.30.0.0/24"
```

The plugin calls `opnsense__routing__list_routes` and filters for the destination subnet. A missing route or a route pointing to a null/non-existent gateway confirms the black hole.

### Step 2: Check Interface State

```
"List all VLAN interfaces and their operational status"
```

The plugin calls `opnsense__interfaces__list_interfaces` and `opnsense__interfaces__list_vlan_interfaces`. Look for:

- Interface in `down` state
- VLAN interface missing entirely (gateway-side not created)
- IP address mismatch between interface and route gateway

### Step 3: Trace the Path

```
"Run a traceroute from OPNsense to 10.30.0.1"
```

The plugin calls `opnsense__diagnostics__run_traceroute`. If the trace stops at hop 1, the gateway itself cannot reach the destination -- the route is missing or the interface is down.

### Step 4: Check Firewall Rules

```
"Show me firewall rules on the interface for VLAN 30"
```

Even with a valid route, a deny-all rule on the destination interface silently drops traffic (OPNsense defaults to block on interfaces without explicit pass rules).

### Step 5: Verify ARP Resolution

```
"Show the ARP table for the 10.30.0.0/24 subnet"
```

If routes and firewall rules look correct, the issue may be at Layer 2 -- the gateway cannot ARP-resolve the next hop. This indicates a VLAN trunk misconfiguration on the switch side.

## Resolution Patterns

| Root Cause | Fix |
|---|---|
| Missing static route | `opnsense routing add-route --destination 10.30.0.0/24 --gateway <gw>` |
| Interface down | Check physical link, VLAN tag, parent interface |
| Missing VLAN interface | `opnsense interfaces configure-vlan --vlan-id 30 ...` |
| Firewall blocking | Add pass rule on the destination interface |
| ARP failure | Check VLAN trunk on switch (UniFi side) |

## Working Safely

This workflow is entirely read-only. No changes are made to the network. If you identify the fix and want to apply it, use the appropriate write command with `--apply` -- the OutageRiskAgent will assess whether the change affects your management session.

## Related Workflows

- [Review Firewall Rules](review-firewall.md)
- [Troubleshoot DNS](troubleshoot-dns.md)
- [Check VPN Health](check-vpn-health.md)
