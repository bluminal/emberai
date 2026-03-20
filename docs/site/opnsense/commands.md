# OPNsense Commands Reference

Commands are the user-facing entry points to the opnsense plugin. Each command orchestrates multiple tools from the [Skills Reference](skills.md) to produce a complete, severity-ranked report.

All scan, health, and audit commands are **read-only**. Write commands (`--configure`, `--apply`) require `OPNSENSE_WRITE_ENABLED=true` and operator confirmation.

---

## `opnsense scan`

Full inventory of the OPNsense instance. The entry point for new deployments.

### What It Does

Calls tools across interfaces, routing, VPN, and firmware skills to build a complete inventory:

1. Lists all interfaces (physical, VLAN, loopback) with IP, status, and type
2. Lists all VLAN interfaces with tag, parent interface, and description
3. Lists all static routes and gateways with status and latency
4. Summarizes VPN tunnel status (IPSec, OpenVPN, WireGuard)
5. Reports firmware version and upgrade availability

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Scans the local OPNsense instance |

### Example

```
You: Scan my OPNsense firewall

EmberAI:

## OPNsense System Scan
| Metric       | Value |
|--------------|-------|
| Interfaces   | 6     |
| VLANs        | 4     |
| Routes       | 3     |
| VPN Tunnels  | 2     |
| Firmware     | 25.1  |

## Interfaces
| Name   | Description    | IP             | Type     | Status  |
|--------|----------------|----------------|----------|---------|
| igc0   | WAN            | 203.0.113.5/24 | physical | up      |
| igc1   | LAN            | 10.0.0.1/24    | physical | up      |
| igc2   | OPT1           | --             | physical | down    |
| igc3   | OPT2           | --             | physical | up      |
| lo0    | Loopback       | 127.0.0.1/8    | loopback | up      |
| ovpns1 | Site-to-Site   | 10.8.0.1/24    | openvpn  | up      |

## VLAN Interfaces
| Tag | Parent | Description | IP             |
|-----|--------|-------------|----------------|
| 10  | igc1   | Guest       | 10.10.0.1/24   |
| 20  | igc1   | IoT         | 10.20.0.1/24   |
| 30  | igc1   | Servers     | 10.30.0.1/24   |
| 99  | igc1   | Management  | 10.99.0.1/24   |

## Gateways
| Name       | Interface | Gateway       | Status | RTT    |
|------------|-----------|---------------|--------|--------|
| WAN_GW     | igc0      | 203.0.113.1   | online | 4ms    |
| VPN_GW     | ovpns1    | 10.8.0.2      | online | 12ms   |

## Routes
| Destination     | Gateway  | Description           |
|-----------------|----------|-----------------------|
| 0.0.0.0/0       | WAN_GW   | Default route         |
| 172.16.0.0/16   | VPN_GW   | Remote office network |
| 10.50.0.0/24    | VPN_GW   | Remote server VLAN    |

## VPN Status
| Type      | Name          | Status      | Peers/Clients |
|-----------|---------------|-------------|---------------|
| IPSec     | aws-tunnel-1  | established | 1 SA          |
| WireGuard | mobile-vpn    | active      | 3 peers       |

## Firmware
| Field           | Value |
|-----------------|-------|
| Current version | 25.1  |
| Latest version  | 25.1.3|
| Upgrade         | Available |
```

### Tools Called

- `opnsense__interfaces__list_interfaces` -- interface inventory
- `opnsense__interfaces__list_vlan_interfaces` -- VLAN interface listing
- `opnsense__routing__list_routes` -- static route table
- `opnsense__routing__list_gateways` -- gateway status
- `opnsense__vpn__get_vpn_status` -- VPN tunnel summary
- `opnsense__firmware__get_status` -- firmware version

---

## `opnsense health`

Run a comprehensive health check with severity-tiered findings.

### What It Does

Gathers health data from five sources and classifies findings into severity tiers:

- **Critical** -- gateway offline, WAN unreachable, high-severity IDS alerts
- **Warning** -- gateway packet loss, firmware upgrade available, certificates expiring within 30 days
- **Informational** -- gateway latency, IDS alert summary, firmware version

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Checks the local OPNsense instance |

### Example (Healthy)

```
You: Quick health check on the firewall

EmberAI:

## OPNsense Health Check
| Metric     | Value   |
|------------|---------|
| Gateways   | 2 / 2 online |
| WAN        | Reachable (4ms) |
| IDS Alerts | 0 (24h) |
| Firmware   | Up to date |
| Certs      | All valid |

All systems healthy -- 2 gateway(s) online, WAN reachable.

## Findings

### Informational
- **Gateway latency**: WAN_GW: 4ms, VPN_GW: 12ms. All gateways within
  normal latency range.
```

### Example (With Findings)

```
You: Health check

EmberAI:

## OPNsense Health Check
| Metric     | Value     |
|------------|-----------|
| Gateways   | 1 / 2 online |
| WAN        | Reachable (42ms) |
| IDS Alerts | 7 (24h)  |
| Firmware   | Update available |
| Certs      | 1 expiring |

## Findings

### Critical
- **Gateway offline**: VPN_GW (ovpns1) is not responding. Last seen
  RTT: 12ms. The IPSec tunnel and routes using this gateway are affected.
  Recommendation: Check VPN service status and remote endpoint reachability.

### Warning
- **Firmware upgrade available**: Current: 25.1, Available: 25.1.3.
  Recommendation: Review changelog and schedule upgrade during maintenance.
- **Certificate expiring**: "vpn-server-cert" expires in 14 days
  (2026-04-02). Used by: OpenVPN site-to-site.
  Recommendation: Renew the certificate before expiry.

### Informational
- **IDS alerts (24h)**: 7 alerts -- 2 high, 3 medium, 2 low severity.
  Top category: ET SCAN (4 alerts).
- **Gateway latency**: WAN_GW: 42ms (elevated).
```

### Severity Tiers

| Tier | Triggers |
|------|----------|
| Critical | Gateway offline; WAN unreachable (ping to 8.8.8.8 fails); high-severity IDS alerts |
| Warning | Firmware upgrade available; gateway packet loss > 0; certificates expiring within 30 days |
| Informational | Gateway latency summary; IDS alert count and categories; firmware version |

### Tools Called

- `opnsense__routing__list_gateways` -- gateway status and latency
- `opnsense__security__get_ids_alerts(hours=24)` -- recent IDS alerts
- `opnsense__firmware__get_status` -- firmware currency
- `opnsense__diagnostics__run_ping("8.8.8.8")` -- WAN reachability
- `opnsense__security__get_certificates` -- certificate expiry

---

## `opnsense diagnose`

Root-cause analysis for a specific host or interface.

### What It Does

For a **host**:

1. Pings the target to test basic reachability
2. Runs a traceroute to identify where packets are dropped
3. Performs a DNS lookup to verify name resolution
4. Checks firewall rules on the traversal path for blocking rules

For an **interface**:

1. Lists interface details (IP, status, type)
2. Checks gateway status for associated gateways
3. Runs host discovery on the interface to find connected devices
4. Lists DHCP leases for the interface

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | string | Yes | Hostname, IP address, or interface name |

### Example (Host Diagnosis)

```
You: Diagnose why I can't reach 10.30.0.50

EmberAI:

## Diagnosis: 10.30.0.50
| Metric     | Value       |
|------------|-------------|
| Type       | Host        |
| Reachable  | No          |

### Ping Result
| Field        | Value    |
|--------------|----------|
| Packets sent | 5        |
| Received     | 0        |
| Loss         | 100%     |

### Traceroute
| Hop | IP          | Hostname     | RTT    |
|-----|-------------|--------------|--------|
| 1   | 10.0.0.1    | fw.local     | 1ms    |
| 2   | 10.30.0.1   | --           | 2ms    |
| 3   | *           | --           | *      |

### Firewall Check
| Rule | Interface | Action | Source      | Destination | Match |
|------|-----------|--------|-------------|-------------|-------|
| 12   | SERVERS   | block  | SERVERS_net | !LAN_net    | Yes   |

### Diagnostic Findings

#### Warning
- **Firewall rule blocking traffic**: Rule 12 on SERVERS interface
  blocks traffic from SERVERS_net to destinations outside LAN_net.
  Host 10.30.0.50 is in SERVERS_net and the request source may be
  outside LAN_net.
  Recommendation: Verify the intended policy. If this traffic should
  be allowed, add a pass rule above rule 12.
```

### Tools Called

- `opnsense__diagnostics__run_ping` -- reachability test
- `opnsense__diagnostics__run_traceroute` -- path analysis
- `opnsense__diagnostics__dns_lookup` -- name resolution
- `opnsense__firewall__list_rules` -- firewall traversal check
- `opnsense__interfaces__list_interfaces` -- interface details (interface mode)
- `opnsense__routing__list_gateways` -- gateway status (interface mode)
- `opnsense__diagnostics__run_host_discovery` -- ARP/NDP discovery (interface mode)
- `opnsense__interfaces__get_dhcp_leases` -- DHCP leases (interface mode)

---

## `opnsense firewall`

Firewall rule listing and audit.

### What It Does

**Base mode**: Lists all firewall rules, aliases, and NAT rules with position, action, source, destination, and enabled status.

**With `--audit`**: Performs additional analysis:

1. Shadow analysis -- detects rules that never match because an earlier rule covers the same traffic
2. Overly-broad rule detection -- flags rules with `any/any` source or destination
3. Disabled rule count and listing
4. NAT exposure review -- identifies externally exposed services

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interface` | string | `null` | Filter rules by interface |
| `audit` | bool | `false` | Enable shadow analysis and broad rule detection |

### Example

```
You: Show me the firewall rules on the LAN interface

EmberAI:

## Firewall Rules: LAN
| # | Description              | Action | Direction | Source      | Destination | Protocol | Enabled |
|---|--------------------------|--------|-----------|-------------|-------------|----------|---------|
| 1 | Anti-lockout rule        | pass   | in        | LAN_net     | LAN_addr    | TCP      | Yes     |
| 2 | Allow LAN to WAN        | pass   | in        | LAN_net     | *           | *        | Yes     |
| 3 | Block IoT from LAN      | block  | in        | IoT_net     | LAN_net     | *        | No      |

## Aliases
| Name      | Type    | Content                          |
|-----------|---------|----------------------------------|
| LAN_net   | network | 10.0.0.0/24                      |
| IoT_net   | network | 10.20.0.0/24                     |
| RFC1918   | network | 10.0.0.0/8, 172.16.0.0/12, ...  |
```

### Example (With Audit)

```
You: Audit my firewall rules

EmberAI:

## Firewall Audit
| Metric          | Value |
|-----------------|-------|
| Total rules     | 24    |
| Enabled         | 21    |
| Disabled        | 3     |
| NAT rules       | 2     |
| Aliases         | 8     |

## Findings

### Warning
- **Overly-broad rule on IoT interface**: Rule 4 on IoT allows
  IoT_net to * (any destination) on all protocols. IoT devices
  should have restricted outbound access.
  Recommendation: Replace with specific destination aliases for
  required services (DNS, NTP, MQTT).

- **Shadowed rule detected**: Rule 8 on LAN (block LAN_net to
  Servers_net on TCP/443) is shadowed by Rule 2 (pass LAN_net
  to * on all protocols). Rule 8 will never match.
  Recommendation: Move Rule 8 above Rule 2 if the block is intended.

### Informational
- **3 disabled rules**: Rules 3, 15, 22 are disabled. Review
  whether these should be removed or re-enabled.
- **2 NAT port forwards active**: External ports 443 (-> 10.30.0.10)
  and 8443 (-> 10.99.0.5). Verify each forward is still needed.
```

### Tools Called

- `opnsense__firewall__list_rules` -- firewall rule listing
- `opnsense__firewall__list_aliases` -- alias definitions
- `opnsense__firewall__list_nat_rules` -- NAT/port forwarding rules

---

## `opnsense firewall policy-from-matrix`

Derive and apply a firewall ruleset from an inter-VLAN access matrix.

### What It Does

Accepts a YAML or CSV access matrix defining which VLANs may communicate with each other. Modes:

- **`--audit`**: Compares existing rules against the matrix; surfaces gaps (traffic allowed but matrix says block) and violations (traffic blocked but matrix says allow).
- **`--apply`**: Derives the minimum correct ruleset from the matrix -- creates needed aliases first, then adds rules in correct order, with a single reconfigure at the end.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `matrix` | string | Yes | Path to YAML or CSV matrix file |
| `audit` | bool | No | Compare existing rules against matrix |
| `apply` | bool | No | Generate and apply the derived ruleset (requires `OPNSENSE_WRITE_ENABLED=true`) |

### Write Safety

- **Env var gate:** `OPNSENSE_WRITE_ENABLED` must be set to `"true"`
- **Apply flag gate:** `--apply` must be present
- **NetworkSecurityAgent:** Reviews the derived ruleset before the plan is presented
- **Rule ordering:** The plan shows exactly where each rule will be inserted
- **Single reconfigure:** All rules are saved first, then one reconfigure applies them all

### Tools Called

- `opnsense__firewall__list_rules` -- current rule set
- `opnsense__firewall__list_aliases` -- existing aliases
- `opnsense__firewall__add_alias` -- create needed aliases
- `opnsense__firewall__add_rule` -- create derived rules

---

## `opnsense vlan`

VLAN interface listing, configuration, and audit.

### What It Does

**Base mode**: Lists all VLAN interfaces with tag, parent interface, IP address, and DHCP status.

**With `--configure`**: Three-phase write flow using the atomic `configure_vlan` tool. Creates a VLAN interface with static IP and DHCP scope in a single confirmed workflow with one reconfigure at the end.

**With `--audit`**: Checks each VLAN for a corresponding DHCP scope. Flags orphaned VLANs (VLAN interface exists but no DHCP). Understands intentional range offsets within larger subnets.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `configure` | bool | `false` | Enter VLAN creation workflow |
| `audit` | bool | `false` | Check VLAN-DHCP consistency |

### Write Safety

- **Env var gate:** `OPNSENSE_WRITE_ENABLED` must be set to `"true"`
- **Apply flag gate:** `--apply` must be present
- **Outage risk:** Interface changes carry the highest outage risk. If the operator's session traverses the interface being modified, the plan is classified as CRITICAL risk.

### Tools Called

- `opnsense__interfaces__list_vlan_interfaces` -- VLAN listing
- `opnsense__interfaces__list_interfaces` -- interface details
- `opnsense__interfaces__configure_vlan` -- atomic VLAN creation (write)

---

## `opnsense dhcp reserve-batch`

Create multiple static DHCP reservations in one confirmed workflow.

### What It Does

Accepts a device specification (inline or file) with one entry per line in `hostname:mac:ip` format. Verifies that the MACs are known from existing DHCP leases, then creates all reservations with a single reconfigure at the end.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `interface` | string | Yes | Interface for DHCP reservations |
| `devices` | string | Yes | Device spec (inline or file path), format: `hostname:mac:ip` per line |
| `apply` | bool | No | Execute the reservations (requires `OPNSENSE_WRITE_ENABLED=true`) |

### Write Safety

- **Env var gate:** `OPNSENSE_WRITE_ENABLED` must be set to `"true"`
- **Apply flag gate:** `--apply` must be present
- **Single reconfigure:** All reservations are saved first, then one Kea restart applies them all

### Tools Called

- `opnsense__interfaces__get_dhcp_leases` -- verify MACs are known
- `opnsense__interfaces__add_dhcp_reservation` -- create each reservation

---

## `opnsense vpn`

VPN tunnel status for IPSec, OpenVPN, and WireGuard.

### What It Does

Lists all VPN tunnels across all three protocols with status, peer information, and traffic counters. Flags sessions that are not established, WireGuard handshakes older than 3 minutes, and near-expiry certificates used by VPN.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tunnel` | string | `null` | Filter to a specific tunnel by name |

### Example

```
You: Check VPN tunnel status

EmberAI:

## VPN Status
| Metric         | Value |
|----------------|-------|
| IPSec SAs      | 1     |
| OpenVPN        | 1     |
| WireGuard      | 3     |

## IPSec Sessions
| Name          | Status      | Local Traffic  | Remote Traffic  | RX       | TX       |
|---------------|-------------|----------------|-----------------|----------|----------|
| aws-tunnel-1  | established | 10.0.0.0/24    | 172.31.0.0/16   | 1.2 GB   | 890 MB   |

## OpenVPN Instances
| Name           | Role   | Protocol | Port | Status  | Clients |
|----------------|--------|----------|------|---------|---------|
| site-to-site   | server | UDP      | 1194 | running | 1       |

## WireGuard Peers
| Name           | Endpoint          | Allowed IPs     | Last Handshake | RX      | TX      |
|----------------|-------------------|-----------------|----------------|---------|---------|
| mobile-phone   | 203.0.113.50:5182 | 10.8.0.2/32     | 45s ago        | 12 MB   | 89 MB   |
| laptop-remote  | 198.51.100.20:443 | 10.8.0.3/32     | 30s ago        | 450 MB  | 1.2 GB  |
| tablet         | --                | 10.8.0.4/32     | 4m 12s ago     | 1.2 MB  | 3.4 MB  |

## Findings

### Warning
- **WireGuard peer stale handshake**: "tablet" last handshake was 4m 12s
  ago (threshold: 3 minutes). The peer may be offline or unreachable.
  Recommendation: Verify the peer device is online and has network
  connectivity.
```

### Tools Called

- `opnsense__vpn__list_ipsec_sessions` -- IPSec SA status
- `opnsense__vpn__list_openvpn_instances` -- OpenVPN instance status
- `opnsense__vpn__list_wireguard_peers` -- WireGuard peer status
- `opnsense__vpn__get_vpn_status` -- aggregate VPN summary

---

## `opnsense dns`

DNS configuration and resolution testing.

### What It Does

Lists Unbound DNS configuration: host overrides, forwarders, and DNS-over-TLS status. Optionally resolves a hostname to verify Unbound is working correctly.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `hostname` | string | `null` | Optional hostname to resolve |

### Example

```
You: Check DNS configuration and resolve nas.home.local

EmberAI:

## DNS Configuration (Unbound)

### Host Overrides
| Hostname | Domain     | IP          | Description        |
|----------|------------|-------------|--------------------|
| nas      | home.local | 10.30.0.10  | Synology NAS       |
| printer  | home.local | 10.0.0.50   | Office printer     |
| plex     | home.local | 10.30.0.20  | Plex Media Server  |

### Forwarders
| Server        | Port | Domain | DoT    |
|---------------|------|--------|--------|
| 1.1.1.1       | 853  | --     | Yes    |
| 1.0.0.1       | 853  | --     | Yes    |

### Resolution Test: nas.home.local
| Field    | Value       |
|----------|-------------|
| Hostname | nas.home.local |
| IP       | 10.30.0.10  |
| TTL      | 3600        |
| Source   | Local override |

## Findings

### Informational
- **DNS-over-TLS enabled**: Both forwarders use DoT (port 853).
```

### Tools Called

- `opnsense__services__get_dns_overrides` -- host override listing
- `opnsense__services__get_dns_forwarders` -- forwarder configuration
- `opnsense__services__resolve_hostname` -- resolution test (when hostname provided)

---

## `opnsense secure`

Security posture audit.

### What It Does

Comprehensive security review across firewall rules, IDS/IPS, certificates, and NAT exposure:

1. Firewall shadow analysis -- redundant, shadowed, and overly permissive rules
2. IDS/IPS policy status -- whether Suricata is enabled, ruleset currency, interface coverage
3. IDS alerts (last 72 hours) -- summary by severity and category
4. Certificate expiry -- certificates expiring within 60 days
5. NAT exposure -- port forwards exposing management ports or sensitive services

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Audits the local OPNsense instance |

### Example

```
You: Run a security audit

EmberAI:

## Security Posture Audit

### Summary
| Metric          | Value |
|-----------------|-------|
| Firewall rules  | 24    |
| IDS status      | Enabled |
| IDS alerts (72h)| 14    |
| Certificates    | 5     |
| NAT forwards    | 2     |

### Findings

### Critical
- **IDS rulesets not updated**: Last ruleset update was 12 days ago.
  Rulesets should be updated at least weekly.
  Recommendation: Run ruleset update from Services > Intrusion Detection
  > Administration > Download.

### Warning
- **Certificate expiring**: "openvpn-server" expires in 22 days
  (2026-04-10). Used by: OpenVPN site-to-site instance.
  Recommendation: Renew the certificate and redeploy to VPN instances.
- **NAT forward exposes management port**: Port 8443 is forwarded to
  10.99.0.5:443 (Management VLAN). Management interfaces should not
  be directly exposed to the internet.
  Recommendation: Remove the port forward and use VPN for remote
  management access.

### Informational
- **IDS alert summary (72h)**: 14 alerts -- 3 high, 5 medium, 6 low.
  Top categories: ET SCAN (6), ET POLICY (4), ET INFO (4).
```

### Tools Called

- `opnsense__firewall__list_rules` -- shadow analysis
- `opnsense__security__get_ids_policy` -- IDS/IPS configuration
- `opnsense__security__get_ids_alerts(hours=72)` -- recent alerts
- `opnsense__security__get_certificates` -- certificate expiry
- `opnsense__firewall__list_nat_rules` -- NAT exposure review

---

## `opnsense firmware`

Firmware and package update status.

### What It Does

Reports the current OPNsense version, available upgrades, and installed packages with pending updates.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | Checks the local OPNsense instance |

### Example

```
You: Check firmware status

EmberAI:

## Firmware Status
| Field           | Value         |
|-----------------|---------------|
| Current version | 25.1          |
| Latest version  | 25.1.3        |
| Upgrade         | Available     |
| Last check      | 2026-03-18    |

## Packages with Updates
| Package              | Current    | Available  |
|----------------------|------------|------------|
| os-suricata          | 7.0.8      | 7.0.9      |
| os-wireguard         | 2.1        | 2.2        |

2 package(s) with available updates.

To upgrade: run `opnsense firmware --update` with OPNSENSE_WRITE_ENABLED=true.
This will restart the firewall. Confirm you have console access before proceeding.
```

### Write Safety (--update)

- **Env var gate:** `OPNSENSE_WRITE_ENABLED` must be set to `"true"`
- **Apply flag gate:** `--apply` must be present
- **Reboot warning:** Firmware updates require a firewall reboot. The plan always states: "This will restart the firewall. Confirm you have console access."
- **Never automatic:** The plugin never triggers a reboot without explicit operator confirmation

### Tools Called

- `opnsense__firmware__get_status` -- firmware version and upgrade availability
- `opnsense__firmware__list_packages` -- installed packages with update status
