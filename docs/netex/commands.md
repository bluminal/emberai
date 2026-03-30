# Netex Command Reference

All netex commands are registered as MCP tools on the netex server. They coordinate vendor plugins via the Plugin Registry and follow the three-phase confirmation model for write operations.

## Read-Only Commands

### `netex topology`

**Tool:** `netex__topology__map`

Generate a unified network topology spanning all installed vendor plugins.

**Required plugins:** At least one with `topology` skill.

**Parameters:** None.

**Output:** Layered topology showing WAN, gateway, and edge layers with nodes, links, and VLAN assignments.

---

### `netex health [--site <site>]`

**Tool:** `netex__health__check`

Unified health report across all installed plugins. Findings are severity-tiered (CRITICAL, HIGH, Warning, Informational) regardless of source vendor.

**Required plugins:** At least one with `health` or `diagnostics` skill.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `site` | string | (all) | Filter to a specific site |

---

### `netex vlan audit [--vlan <id>]`

**Tool:** `netex__vlan__audit`

Cross-vendor VLAN consistency check. Compares VLAN definitions between gateway and edge plugins.

**Required plugins:** At least one `gateway` role + one `edge` role.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `vlan_id` | int | (all) | Filter to a specific VLAN ID |

---

### `netex dns trace <domain> [--source-vlan <name>] [--source-ip <ip>]`

**Tool:** `netex__dns__trace_enhanced`

Trace the full DNS resolution path for a domain across the entire stack: device/VLAN, OPNsense Unbound forwarder, and upstream resolver. When the NextDNS plugin is installed and the forwarder target points to NextDNS, the trace also shows profile-level resolution status (blocked, allowed, or no log entry).

Gracefully degrades when optional plugins are not installed. Without the gateway plugin, the forwarder lookup step is skipped. Without the NextDNS plugin, the NextDNS resolution step is skipped. The trace always reports which layers are available and which are missing.

**Required plugins:** Gateway with `services` skill (for forwarder config). Optionally dns plugin (NextDNS) for profile-level resolution. Optionally edge with `clients` skill (for VLAN identification).

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `domain` | string | (required) | Domain name to trace (e.g. `example.com`) |
| `source_vlan` | string | (none) | VLAN name or ID to identify the source subnet |
| `source_ip` | string | (none) | Source IP address for more precise tracing |

**Example:**

```
You: Trace DNS for tiktok.com from the Kids VLAN

EmberAI:

## DNS Trace: tiktok.com

### Path
| Step | Layer          | Detail                                                       | Status    |
|------|----------------|--------------------------------------------------------------|-----------|
| 1    | Source         | VLAN: Kids (ID 60, subnet 10.0.60.0/24)                     | Identified|
| 2    | Forwarder      | OPNsense Unbound -> dns.nextdns.io/def456 (Kids profile)    | Configured|
| 3    | NextDNS        | Profile: Kids (def456) — tiktok.com BLOCKED by denylist     | Blocked   |

### Summary
DNS trace for 'tiktok.com' across 2 layer(s): gateway (forwarder config),
dns (NextDNS analytics). Domain is blocked at the NextDNS layer by the
Kids profile denylist.
```

**Notes:**
- When `source_vlan` is provided, the trace looks up the forwarder rule matching that VLAN's subnet and extracts the NextDNS profile ID from the forwarder target URL.
- Without `source_vlan` or `source_ip`, the trace runs from the gateway's perspective using the catch-all forwarder.
- The NextDNS resolution step queries `nextdns__logs__search` for recent log entries matching the domain on the identified profile.

---

### `netex dns verify-profiles`

**Tool:** `netex__dns__verify_profiles`

Verify VLAN-to-NextDNS-profile mapping across the entire network. For each VLAN discovered from gateway and edge plugins, checks: (1) OPNsense Unbound DNS forwarder config for the VLAN's subnet, (2) extraction of the NextDNS profile ID from the forwarder target, (3) NextDNS analytics to confirm traffic from the VLAN's subnet is hitting the expected profile.

Reports each VLAN as `verified`, `no_forwarder`, `no_traffic`, or `non_nextdns`.

**Required plugins:** Gateway with `services` skill (required). DNS plugin (NextDNS) for analytics confirmation. Edge plugin for additional VLAN discovery.

**Parameters:** None (checks all VLANs).

**Example:**

```
You: Verify my VLAN-to-NextDNS profile mappings

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

### Mismatches
- **cameras (ID 40)**: No DNS forwarder configured for subnet.
  Cameras are internet-isolated so this is expected.
- **quarantine (ID 99)**: No DNS forwarder configured for subnet.
  Quarantine is fully isolated so this is expected.
- **guest (ID 50)**: Forwarder configured (profile ghi789) but no
  traffic from subnet in analytics. Guest WiFi may not have active
  clients, or the forwarder may be misconfigured.
```

**Common mismatches:**
- **No forwarder**: The VLAN has no Unbound domain override pointing to NextDNS. This is expected for isolated VLANs (cameras, quarantine) but is a problem for VLANs that should have DNS filtering.
- **No traffic**: The forwarder is configured but NextDNS analytics show no queries from the VLAN's subnet. This can mean: no active clients, the forwarder target URL is wrong, or DNS traffic is bypassing the forwarder (e.g., devices using hardcoded DNS like 8.8.8.8).
- **Non-NextDNS**: The forwarder target is not a NextDNS endpoint (e.g., it points to 1.1.1.1 or a local resolver). Analytics verification is not possible for non-NextDNS forwarders.

---

### `netex dns cross-profile-summary [--from <time>] [--to <time>]`

**Tool:** `netex__dns__get_cross_profile_summary`

Unified DNS analytics across all NextDNS profiles. Aggregates total queries, total blocked, per-profile breakdown with block rates, and an encryption audit showing the percentage of encrypted DNS queries per profile.

**Required plugins:** DNS plugin (NextDNS).

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `from_time` | string | (none) | Start of the date range (ISO 8601 or relative like `"-24h"`, `"-30d"`) |
| `to_time` | string | (none) | End of the date range |

**Example:**

```
You: Show me a DNS summary across all profiles for the last 30 days

EmberAI:

## Cross-Profile DNS Summary (last 30 days)

### Totals
| Metric          | Value      |
|-----------------|------------|
| Total Queries   | 1,247,832  |
| Total Blocked   | 198,450    |
| Block Rate      | 15.9%      |

### Per-Profile Breakdown
| Profile | ID      | Queries   | Blocked  | Block Rate | Encrypted |
|---------|---------|-----------|----------|------------|-----------|
| Home    | abc123  | 523,100   | 62,772   | 12.0%      | 99.8%     |
| Kids    | def456  | 412,560   | 103,140  | 25.0%      | 99.9%     |
| IoT     | jkl012  | 189,400   | 18,940   | 10.0%      | 98.2%     |
| Guest   | ghi789  | 122,772   | 13,598   | 11.1%      | 95.4%     |

### Encryption Audit
All profiles above 95% encrypted DNS. Guest profile has the lowest
encryption rate (95.4%) -- some guest devices may be using unencrypted
DNS resolvers directly. Consider firewall rules to redirect port 53
traffic to the gateway.
```

**Notes:**
- Queries `nextdns__analytics__get_status` and `nextdns__analytics__get_encryption` for each profile and aggregates.
- The encryption audit flags profiles where unencrypted DNS percentage is above a threshold, which may indicate DNS bypass by devices using hardcoded resolvers.

---

### `netex vpn status [--tunnel <name>]`

**Tool:** `netex__vpn__status`

VPN tunnel status across all installed plugins. Correlates with edge client data if available.

**Required plugins:** Gateway with `vpn` skill.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `tunnel_name` | string | (all) | Filter to a specific tunnel |

---

### `netex secure audit [--domain <d>]`

**Tool:** `netex__secure__audit`

On-demand security audit across 10 domains. Delegates to the NetworkSecurityAgent.

**Domains:** firewall-gw, firewall-edge, cross-layer, vlan-isolation, vpn-posture, dns-security, ids-ips, wireless, certs, firmware.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `domain` | string | all | Specific domain to audit |

---

### `netex verify-policy [--manifest <file>] [--vlan <id>]`

**Tool:** `netex__network__verify_policy`

Test connectivity against the intended policy. Runs expected-allow and expected-block tests derived from the manifest access_policy.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `manifest_yaml` | string | (none) | YAML manifest content |
| `vlan_id` | int | (all) | Filter to a specific VLAN |

**Output:** Pass/fail report grouped by category (VLAN existence, DHCP, connectivity, WiFi mapping, DNS profile mapping).

#### DNS Profile Checks

When a VLAN in the manifest includes a `dns_profile` field, `verify-policy` additionally checks that the OPNsense Unbound forwarder configuration routes that VLAN's DNS traffic to the specified NextDNS profile. This extends the existing DHCP, firewall, and WiFi checks.

**Manifest schema with `dns_profile`:**

```yaml
vlans:
  - vlan_id: 60
    name: kids
    subnet: 10.60.0.0/24
    gateway: 10.60.0.1
    dhcp_enabled: true
    dhcp_range_start: 10.60.0.100
    dhcp_range_end: 10.60.0.254
    purpose: kids
    dns_profile: def456        # NextDNS profile ID for this VLAN
```

**Example output with DNS checks:**

```
You: netex verify-policy --manifest site-network.yaml

EmberAI:

## Policy Verification Report

### VLAN Existence
| VLAN       | Gateway | Edge | Status |
|------------|---------|------|--------|
| kids (60)  | OK      | OK   | PASS   |
| ...        | ...     | ...  | ...    |

### DHCP
| VLAN       | Scope    | Status |
|------------|----------|--------|
| kids (60)  | Active   | PASS   |
| ...        | ...      | ...    |

### DNS Profile Mapping
| VLAN       | Expected Profile | Forwarder Target         | Status |
|------------|------------------|--------------------------|--------|
| kids (60)  | def456           | dns.nextdns.io/def456    | PASS   |
| iot (30)   | jkl012           | dns.nextdns.io/jkl012    | PASS   |
| guest (50) | ghi789           | 1.1.1.1                  | FAIL   |

FAIL: guest (50) — forwarder target does not match expected
NextDNS profile ghi789. Current target: 1.1.1.1.

### Connectivity
| ...        | ...      | ...    |
```

---

## Write Commands

> **Required safety notice:** Network changes can result in outages that disconnect you from your ability to correct them. Never make changes to a network you cannot reach through an out-of-band path (serial console, IPMI/iDRAC, a separate management VLAN on a different physical interface, or physical access). Netex will assess this risk for you, but it cannot guarantee your recovery path -- only you can verify that.

All write commands require:
1. `NETEX_WRITE_ENABLED=true` environment variable
2. `--apply` flag
3. Operator confirmation of the presented change plan

---

### `netex network provision-site --manifest <file> [--dry-run] [--apply]`

**Tool:** `netex__network__provision_site`

Full site bootstrap from a structured YAML manifest. The flagship orchestration command.

**Required plugins:** Gateway role + edge role.

**Manifest sections:** `vlans[]`, `access_policy[]`, `wifi[]`, `port_profiles[]`.

**Execution order:**
1. Gateway VLAN interfaces
2. DHCP scopes
3. DNS forwarders (from `dns_profile` fields in manifest)
4. Firewall aliases
5. Firewall rules (from access_policy)
6. Edge networks
7. WiFi SSIDs
8. Port profiles

#### DNS Forwarder Linkage

When a VLAN in the manifest includes a `dns_profile` field, `provision-site` configures an OPNsense Unbound domain override to forward DNS queries from that VLAN's subnet to the specified NextDNS profile endpoint. This step executes after DHCP scopes and before firewall aliases, ensuring DNS filtering is in place before the network is fully operational.

The forwarder target URL is derived from the profile ID: `dns.nextdns.io/{profile_id}`. The domain override description includes the VLAN name for traceability (used by `verify-profiles` to match forwarders to VLANs).

**Safety:** Single OutageRiskAgent assessment + single NSA review for the entire batch. Rollback plan presented before execution.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `manifest_yaml` | string | (required) | YAML manifest content |
| `dry_run` | bool | false | Generate plan without executing |
| `apply` | bool | false | Execute the plan (write gate step 2) |

---

### `netex vlan provision-batch --manifest <file> [--apply]`

**Tool:** `netex__vlan__provision_batch`

Batch-create multiple VLANs from a manifest. Lighter than `provision-site` -- only creates VLANs and DHCP, not firewall rules or WiFi.

**Required plugins:** Gateway role + edge role.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `manifest_yaml` | string | (required) | YAML manifest with `vlans[]` section |
| `apply` | bool | false | Execute the plan |

---

### `netex policy sync [--dry-run] [--apply]`

**Tool:** `netex__policy__sync`

Detect and reconcile configuration drift across installed vendor plugins.

**Required plugins:** At least two vendor plugins to compare.

**Check domains:** VLAN definitions, DNS search domains, firewall zone naming, firmware state.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `dry_run` | bool | true | Report drift without changes |
| `apply` | bool | false | Execute corrective changes |

---

## Site Manifest Format

The YAML manifest used by `provision-site`, `verify-policy`, and `provision-batch`:

```yaml
name: Site Name
description: Site description

vlans:
  - vlan_id: 10          # Required: 1-4094
    name: management      # Required: unique within manifest
    subnet: 10.10.0.0/24  # Required: CIDR notation
    gateway: 10.10.0.1    # Optional: defaults to .1
    dhcp_enabled: true     # Optional: defaults to true
    dhcp_range_start: 10.10.0.100
    dhcp_range_end: 10.10.0.254
    purpose: mgmt          # Optional: mgmt, general, iot, guest, etc.
    parent_interface: igc1  # Optional: parent for VLAN tagging
    dns_profile: abc123    # Optional: NextDNS profile ID for DNS filtering

access_policy:
  - source: trusted        # VLAN name or "wan"
    destination: wan        # VLAN name or "wan"
    action: allow           # "allow" or "block"
    protocol: any           # Optional: tcp, udp, icmp, any
    port: any               # Optional: port number or range
    description: "..."      # Optional

wifi:
  - ssid: Home-WiFi
    vlan_name: trusted      # VLAN name from vlans[] section
    security: wpa3          # open, wpa2, wpa3, wpa2-wpa3
    hidden: false           # Optional
    band: both              # Optional: 2.4, 5, both

port_profiles:
  - name: Trunk-All
    native_vlan: null       # Optional: VLAN name
    tagged_vlans: [mgmt, trusted, guest]
    poe_enabled: true       # Optional: defaults to true
```
