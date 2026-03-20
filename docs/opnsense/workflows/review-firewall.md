# Review Firewall Rules

## Intent

"I want to list my firewall rules and identify any that are disabled or broadly permissive."

## Prerequisites

- **Plugin:** `opnsense` v0.2.0 or later
- **API privileges:** Read-only access to the Firewall section in Effective Privileges
- **Environment variables:** `OPNSENSE_HOST`, `OPNSENSE_API_KEY`, and `OPNSENSE_API_SECRET` must be configured

## Context

Run this workflow as a periodic review or before making firewall changes. It gives you a complete picture of all rules, aliases, and NAT entries across all interfaces. The `--audit` flag adds automated analysis for shadowed rules, overly-broad rules, and disabled rules that may be accumulating.

This workflow is read-only -- it does not modify any firewall rules. For a full security audit including IDS/IPS, certificate expiry, and NAT exposure review, see the `opnsense secure` command.

This workflow covers OPNsense firewall rules only. For UniFi ZBF policies and ACLs, use `unifi secure`. For a cross-vendor policy audit, use the netex umbrella.

## Commands

### Step 1: List rules on a specific interface

```
You: Show me the firewall rules on the LAN interface
```

EmberAI calls `opnsense firewall` with the interface filter to show rules for the LAN.

### Step 2: Review the listing

```
EmberAI:

## Firewall Rules: LAN
| # | Description              | Action | Direction | Source      | Destination | Protocol | Enabled |
|---|--------------------------|--------|-----------|-------------|-------------|----------|---------|
| 1 | Anti-lockout rule        | pass   | in        | LAN_net     | LAN_addr    | TCP      | Yes     |
| 2 | Allow LAN to WAN        | pass   | in        | LAN_net     | *           | *        | Yes     |
| 3 | Allow LAN to Servers     | pass   | in        | LAN_net     | Servers_net | *        | Yes     |
| 4 | Block inter-VLAN default | block  | in        | LAN_net     | RFC1918     | *        | No      |

## Aliases
| Name        | Type    | Content                              |
|-------------|---------|--------------------------------------|
| LAN_net     | network | 10.0.0.0/24                          |
| Servers_net | network | 10.30.0.0/24                         |
| RFC1918     | network | 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 |
```

### Step 3: Run the full audit

```
You: Audit all firewall rules
```

EmberAI calls `opnsense firewall --audit` which adds shadow analysis, broad rule detection, and disabled rule listing.

### Step 4: Review audit findings

```
EmberAI:

## Firewall Audit
| Metric          | Value |
|-----------------|-------|
| Total rules     | 28    |
| Enabled         | 24    |
| Disabled        | 4     |
| NAT rules       | 2     |
| Aliases         | 10    |

## Findings

### Warning
- **Overly-broad rule on IoT interface**: Rule 3 on IoT allows
  IoT_net to * (any destination) on all protocols. IoT devices
  should have restricted outbound access.
  Recommendation: Replace with specific destination aliases for
  required services (DNS, NTP, cloud endpoints).

- **Shadowed rule detected**: Rule 7 on LAN (block LAN_net to
  Servers_net on TCP/22) is shadowed by Rule 3 (pass LAN_net
  to Servers_net on all protocols). Rule 7 will never match.
  Recommendation: Move Rule 7 above Rule 3 if the SSH block
  is intended, or remove Rule 7 if it is obsolete.

### Informational
- **4 disabled rules**: Rules on interfaces LAN (1), Guest (1),
  IoT (2). Disabled rules may be intentional holdovers or
  forgotten experiments.
  Recommendation: Review each disabled rule and either re-enable
  or remove it to keep the ruleset clean.

- **2 NAT port forwards active**: External ports 443
  (-> 10.30.0.10:443) and 8443 (-> 10.99.0.5:443).
  Recommendation: Verify each forward is still needed and that
  the destination hosts are patched and hardened.
```

## What to Look For

**Rule listing:**
- **Position column (#)** -- rules are evaluated top-to-bottom. A broadly permissive rule high in the list will shadow more specific rules below it.
- **Action column** -- verify that `pass` and `block` rules are in the expected positions. The default OPNsense behavior is to block traffic that does not match any rule.
- **Source and Destination** -- rules using `*` (any) for both source and destination are overly permissive. Each rule should be as specific as possible.
- **Enabled column** -- disabled rules do not affect traffic but clutter the ruleset. Decide whether to remove or re-enable them.

**Audit findings:**
- **Shadowed rules** -- a rule that can never match because an earlier rule already matches all of its traffic. This usually indicates a rule ordering issue or an obsolete rule.
- **Overly-broad rules** -- rules that allow any source or any destination on any protocol. These are common on LAN interfaces but should not appear on IoT, Guest, or other restricted VLANs.
- **NAT forwards** -- every port forward is an entry point from the internet. Verify each one is needed, uses the minimum required protocol/port, and points to a hardened host.

**Aliases:**
- Verify alias contents match your network design. An alias with an incorrect CIDR can cause rules to match (or not match) unexpected traffic.

## Next Steps

- [Check VPN Health](check-vpn-health.md) -- verify VPN tunnels if your rules reference VPN traffic selectors
- [Troubleshoot DNS](troubleshoot-dns.md) -- if DNS rules are part of your policy, verify Unbound is resolving correctly
- [First-Time System Scan](first-time-scan.md) -- re-scan if you discover interfaces or VLANs that are missing from the rule analysis

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| 0 rules returned | Insufficient API privileges | The API key owner needs Effective Privileges for Firewall > Filter. Check System > Access > Users |
| Rules shown but aliases are empty | Alias API access missing | Add Firewall > Alias to Effective Privileges |
| Audit shows no findings | All rules are well-structured | This is the desired state -- no action needed |
| Rule position numbers are not sequential | Rules were reordered or deleted | OPNsense maintains internal ordering; gaps in position numbers are normal |
| NAT rules not shown | NAT API access missing | Add Firewall > Source NAT and Firewall > Destination NAT to Effective Privileges |
