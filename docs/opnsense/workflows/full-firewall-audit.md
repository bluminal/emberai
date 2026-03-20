# Full Firewall Audit

> **Difficulty:** Advanced | **Time:** 20-45 minutes | **Risk:** Read-only

## Problem Statement

You need a comprehensive security review of all OPNsense firewall rules across every interface. This could be triggered by a compliance review, a suspected breach, or routine security hygiene after accumulating rules over months of operation.

## Prerequisites

- OPNsense plugin installed and authenticated
- Read access to firewall, security, and interfaces tools
- Netex umbrella plugin recommended for cross-vendor audit via NetworkSecurityAgent

## Workflow

### Step 1: List All Rules by Interface

```
"Show me all firewall rules grouped by interface, including disabled rules"
```

The plugin calls `opnsense__firewall__list_rules` for each interface. The output includes rule count, any/any rules, and disabled rules that may be re-enabled accidentally.

### Step 2: Identify Overly Broad Rules

```
"Find any firewall rules that allow any/any traffic"
```

The plugin scans for rules where source, destination, port, and protocol are all set to `any`. These rules effectively bypass network segmentation.

Look for:
- `pass any from any to any` on non-WAN interfaces
- Rules with source `any` and destination `any` on VLAN interfaces
- Allow rules that predate more specific deny rules (order matters)

### Step 3: Check Rule Ordering

```
"Analyze rule ordering on the LAN interface -- are there any shadowed rules?"
```

OPNsense evaluates rules top-to-bottom, first match wins. A broad allow rule above a specific deny rule shadows the deny, making it ineffective.

### Step 4: Verify Inter-VLAN Isolation

```
"Check that guest and IoT VLANs cannot reach the management VLAN"
```

For each untrusted VLAN, verify:
- Explicit deny rule blocking traffic to management subnets
- Deny rule positioned before any broader allow rules
- No NAT rules that bypass the firewall intent

### Step 5: Review NAT Rules

```
"List all NAT rules and check for unusual port forwards"
```

The plugin calls `opnsense__firewall__list_nat_rules`. Look for:
- Port forwards from WAN to internal hosts (attack surface)
- 1:1 NAT mappings that expose entire hosts
- Outbound NAT rules that break intended isolation

### Step 6: Check Alias Definitions

```
"List all firewall aliases and their resolved values"
```

Aliases that reference stale IPs or overly broad networks weaken rules that depend on them.

### Step 7: Cross-Vendor Audit (if netex installed)

```
"netex secure audit --domain firewall-gw"
```

The NetworkSecurityAgent performs automated analysis across all seven finding categories, producing a severity-ranked report.

## Expected Output

A severity-tiered report:

- **CRITICAL**: Management plane exposed to untrusted segments
- **HIGH**: Any/any rules, missing inter-VLAN isolation, stale port forwards
- **MEDIUM**: Rule ordering risks, aliases with stale values
- **LOW**: Disabled rules, informational notes

## Working Safely

This workflow is entirely read-only. The NetworkSecurityAgent never makes changes -- it only reports findings. To remediate findings, use the specific write commands with `--apply`.

> **Required safety notice:** Network changes can result in outages that disconnect you from your ability to correct them. Never make changes to a network you cannot reach through an out-of-band path (serial console, IPMI/iDRAC, a separate management VLAN on a different physical interface, or physical access). Netex will assess this risk for you, but it cannot guarantee your recovery path -- only you can verify that.

## Related Workflows

- [Review Firewall Rules](review-firewall.md)
- [Routing Black Hole](routing-black-hole.md)
- [IDS Triage](ids-triage.md)
