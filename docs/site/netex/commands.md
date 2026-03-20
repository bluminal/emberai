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

### `netex dns trace <hostname> [--client <mac>]`

**Tool:** `netex__dns__trace`

Trace the DNS resolution path for a hostname. Checks local overrides, forwarder configuration, and upstream resolution. Optionally correlates with a specific client's VLAN.

**Required plugins:** Gateway with `services` skill. Optionally edge with `clients` skill.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `hostname` | string | (required) | Hostname to trace |
| `client_mac` | string | (none) | Client MAC for VLAN-aware tracing |

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

**Output:** Pass/fail report grouped by category (VLAN existence, DHCP, connectivity, WiFi mapping).

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
3. Firewall aliases
4. Firewall rules (from access_policy)
5. Edge networks
6. WiFi SSIDs
7. Port profiles

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
