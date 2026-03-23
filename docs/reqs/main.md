# Netex — Three-Plugin Network Intelligence Suite

**Product Requirements Document**
`unifi · opnsense · netex (umbrella)`

| Field | Value |
|---|---|
| Version | 0.8.0 — Ridgeline validation & new commands |
| Date | March 2026 |
| Owner | A.J. · Bluminal Labs LLC |
| Supersedes | Netex PRD v0.7.0 (SKILL.md manifests) |
| Status | Draft — pending stakeholder review |
| Marketplace | EmberAI · bluminal/emberai |

---

## Revision History

| Version | Date | Author | Summary |
|---|---|---|---|
| 0.1.0 | March 2026 | A.J. | Initial draft — single Netex plugin targeting UniFi APIs only. |
| 0.2.0 | March 2026 | A.J. | Restructured to three-plugin architecture: unifi plugin (edge layer), opnsense plugin (gateway layer), and netex umbrella (cross-vendor orchestration). Added OPNsense API surface, 8 opnsense skill groups, umbrella command set, abstract data model, and updated roadmap. |
| 0.3.0 | March 2026 | A.J. | Added §9 Documentation Requirements: documentation-as-code principles, GitHub Pages publishing pipeline with MkDocs Material, workflow example standard (7-section template), full workflow example catalog for all three plugins, docs delivery schedule aligned to implementation phases. |
| 0.4.0 | March 2026 | A.J. | Added §10 Human-in-the-Loop Interaction Model NFR: assistant vs. autonomous agent design contrast with Synthex, plan-level confirmation model, OutageRiskAgent pre-change gate with four-tier risk classification, AskUserQuestion implementation patterns. |
| 0.5.0 | March 2026 | A.J. | Added §5.2 NetworkSecurityAgent: read-only umbrella agent with two roles — automatic security review of all change plans, and on-demand cross-vendor security audit across 10 domains. Updated §2.1, §7, §8, and §10.3. |
| 0.6.0 | March 2026 | A.J. | Formalized multi-vendor extensibility: §2.1 reframed as open-ended Plugin Layer Model; §2.3 Future Vendor Plugin Candidates; new §2.4 Vendor Plugin Contract; §5.1 abstract model extended with future-vendor column; Open Questions expanded with items 8–10. |
| 0.7.0 | March 2026 | A.J. | Added Appendices A, B, C: complete SKILL.md manifests for unifi, opnsense, and netex plugins. Each manifest includes YAML frontmatter, full Claude instruction content, skill groups with tool signatures, commands, and usage examples. These are the literal files the development team implements first. |
| 0.8.0 | March 2026 | A.J. | Ridgeline real-world validation update. Added 6 new tools (`add_alias`, `add_dhcp_reservation`, `configure_vlan` atomic, `create_port_profile`, `assign_port_profile`, `get_lldp_neighbors`) and 5 new commands (`netex network provision-site`, `netex verify-policy`, `netex vlan provision-batch`, `opnsense firewall policy-from-matrix`, `opnsense dhcp reserve-batch`) identified through analysis of a complete 7-VLAN home network buildout. Updated §3, §4, §5, §8 roadmap, §9 workflow catalog, and all three SKILL.md appendices. |

---

## 1. Executive Summary

Netex is a suite of three complementary plugins in the EmberAI marketplace — Bluminal Labs's operational intelligence platform for infrastructure teams. The suite spans the full network stack of a typical self-hosted or SMB environment: the gateway layer running OPNsense and the edge layer running UniFi hardware.

The three plugins are designed to be used independently or together:

- **unifi** — an intelligent Claude plugin for UniFi networks. Covers device topology, wireless health, client management, traffic analysis, security posture, and multi-site operations across UniFi's three API tiers.
- **opnsense** — an intelligent Claude plugin for OPNsense firewalls. Covers interface and VLAN management, firewall rules, routing, VPN tunnels, DNS, IDS/IPS, and system diagnostics via the OPNsense REST API.
- **netex** — the umbrella orchestrator. Understands both systems as two halves of the same network. Provides cross-vendor commands that require coordinated operations on both platforms — VLAN provisioning, policy auditing, end-to-end topology mapping, and configuration drift detection.

The guiding principle behind all three is unchanged: **keep the light on**. Netex gives operators intelligence and actionable insight, not raw API responses.

---

## 2. Architecture Overview

### 2.1 Plugin Layer Model

The Netex suite is organized into two fixed layers and an open-ended vendor plugin layer. The umbrella (netex) and the vendor plugin pattern are stable architectural contracts — the vendor layer is intentionally unbounded. UniFi and OPNsense are the first two vendor plugins, not the complete set.

| Layer | Plugin(s) | Role | Designed for |
|---|---|---|---|
| 3 — Umbrella (fixed) | netex | Cross-vendor orchestration. Owns the abstract network model and maps it to whichever vendor plugins are configured. Houses the NetworkSecurityAgent and OutageRiskAgent, both vendor-agnostic by design. | One instance, always present |
| 2 — Vendor plugins (open) | unifi, opnsense, [future vendors…] | Each vendor plugin implements the Vendor Plugin Contract (§2.4): standard skill groups, consistent tool naming, and a SKILL.md manifest. Netex orchestrates any conforming vendor plugin without modification. | One plugin per vendor ecosystem; any number may be installed |

> **Design principle:** Vendor plugins are fully independent of each other. A user running only OPNsense without UniFi gets a complete, useful plugin. Netex orchestrates whatever vendor plugins are present — it does not require a specific set and degrades gracefully when a vendor plugin is absent.

### 2.2 Current Vendor Plugin Summary

| Property | unifi plugin | opnsense plugin |
|---|---|---|
| Base URL(s) | `api.ui.com/v1/` · `api.ui.com/ea/` · `{gw-ip}/proxy/network/` | `{opnsense-ip}/api/{module}/{controller}/{command}` |
| Authentication | X-API-KEY header | HTTP Basic Auth — API key as username, secret as password |
| HTTP verbs | GET (read) · POST (write) · PUT (update) | GET (read) · POST (write and actions) |
| Response format | Cloud V1: `{data, httpStatusCode, traceId}` · Site Manager EA: unwrapped · Local: `{data, count, totalCount}` | Flat JSON or `{result, changed}` for actions |
| Rate limits | Site Manager: 100 req/min · Cloud V1: 10,000 req/min · Local: none | No published rate limit |
| Write safety | Opt-in via `UNIFI_WRITE_ENABLED` + `--apply` flag | Opt-in via `OPNSENSE_WRITE_ENABLED` + `--apply`; reconfigure always explicit |
| API scope | Account-level (cloud) or site-level (local) | Single OPNsense instance |

### 2.3 Future Vendor Plugin Candidates

| Vendor ecosystem | Likely network role | Target skills | Notes |
|---|---|---|---|
| Cisco (IOS-XE / Meraki) | Enterprise switching, routing, wireless | topology, health, security, routing, wifi | Two distinct APIs — likely two separate plugins. |
| MikroTik (RouterOS) | Routing, firewall, switching | interfaces, firewall, routing, vpn, diagnostics | RouterOS REST API (v7+). Strong overlap with opnsense skill set. |
| Proxmox VE | Hypervisor networking — VMs, SDN, bridges | topology, health, vlan, config | Proxmox REST API. Relevant for homelab environments. |
| Aruba (ClearPass / AOS-CX) | Enterprise WiFi, NAC, switching | wifi, clients, security, topology | AOS-CX REST API; ClearPass API for NAC policy. |
| pfSense (via REST plugin) | Gateway, firewall, routing | interfaces, firewall, routing, vpn, services | Requires community pfSense-pkg-API plugin. High skill reuse from opnsense. |
| Tailscale | Overlay VPN / zero-trust networking | vpn, topology, clients | Tailscale API at `api.tailscale.com`. Lightweight plugin. |

### 2.4 Vendor Plugin Contract

Any plugin that conforms to the Vendor Plugin Contract can be orchestrated by netex. The contract covers three areas: skill groups, tool naming conventions, and the SKILL.md manifest.

#### Skill Group Contract

A conforming vendor plugin declares which standard skill groups it implements. Partial implementation is valid.

| Standard skill group | What it covers | Required? |
|---|---|---|
| topology | Device discovery, network map, uplink relationships, VLAN assignments | Recommended |
| health | Device uptime, status, firmware currency, event log | Recommended |
| interfaces | Layer-3 interfaces, VLAN interfaces, IP addressing | Optional — gateway plugins typically |
| firewall | Firewall rules, ACLs, NAT, policy objects | Optional — NetworkSecurityAgent uses this |
| routing | Static routes, gateways, dynamic routing | Optional — gateway plugins only |
| vpn | VPN tunnel/peer CRUD and status | Optional |
| wifi | SSIDs, APs, channel utilization, RF environment | Optional — wireless vendors only |
| clients | Connected client inventory, signal, traffic | Optional — OutageRiskAgent uses this |
| security | IDS alerts, cert state, open ports | Optional — NetworkSecurityAgent uses this |
| services | DNS, DHCP, NTP, traffic shaping | Optional |
| diagnostics | Ping, traceroute, packet capture, host discovery | Optional — OutageRiskAgent uses this |
| config | Configuration snapshot, drift detection, backup state | Optional |
| firmware | Firmware/update check, package management | Optional |

#### Tool Naming Convention

All tools follow the pattern: **`{plugin_name}__{skill_group}__{operation}`**

```
unifi__topology__list_devices(site_id)
unifi__health__get_device_health(device_id)
opnsense__firewall__list_rules(interface?)
opnsense__vpn__list_ipsec_sessions()
```

This allows the netex Plugin Registry to query all tools for a skill group across all vendors:

```python
registry.tools_for_skill("security")  →  [unifi__security__*, opnsense__security__*, ...]
```

#### SKILL.md Manifest Requirements

| Field | Type | Description |
|---|---|---|
| `netex_vendor` | string | Machine-readable vendor identifier used as tool name prefix. Lowercase alphanumeric with underscores. E.g., `unifi`, `opnsense`, `meraki`. |
| `netex_role` | string[] | One or more of: `gateway`, `edge`, `wireless`, `overlay`, `hypervisor`. Informs workflow sequencing. |
| `netex_skills` | string[] | Standard skill groups this plugin implements. |
| `netex_write_flag` | string | Environment variable enabling write operations. Convention: `{VENDOR}_WRITE_ENABLED`. |
| `netex_contract_version` | string | Vendor Plugin Contract version this plugin targets. |

> **Contract stability:** Breaking changes to the contract require a major version bump and a migration guide. Skill group names and tool naming convention are stable after v1.0.0 of the contract.

### 2.5 Repository Structure

**Repository:** `bluminal/emberai` (mirrors bluminal/lumenai conventions)

```
emberai/
  unifi/                   # Vendor plugin: UniFi edge layer
    src/
      agents/              # topology, health, wifi, clients, traffic, security, config, multisite
      api/                 # site_manager_client, cloud_v1_client, local_gateway_client
      tools/               # MCP tools (named: unifi__<skill>__<op>)
      models/
    SKILL.md               # netex_vendor=unifi; netex_role=[edge,wireless]
    pyproject.toml

  opnsense/                # Vendor plugin: OPNsense gateway layer
    src/
      agents/              # interfaces, firewall, routing, vpn, security, services, diagnostics, firmware
      api/                 # opnsense_client.py (Basic auth, module/controller/command routing)
      tools/               # MCP tools (named: opnsense__<skill>__<op>)
      models/
    SKILL.md               # netex_vendor=opnsense; netex_role=[gateway]
    pyproject.toml

  [future-vendor]/         # Any future vendor plugin follows the same structure
    src/
      agents/
      api/
      tools/               # MCP tools (named: {vendor}__<skill>__<op>)
      models/
    SKILL.md               # Must declare all netex_* contract fields (§2.4)
    pyproject.toml

  netex/                   # Umbrella orchestrator
    src/
      agents/
        orchestrator.py          # Intent routing, vendor discovery, rollback coordination
        network_security_agent.py  # Read-only: plan review + audit across all vendor plugins
        outage_risk_agent.py       # Read-only: pre-change outage risk assessment
      registry/
        plugin_registry.py        # Discovers installed vendor plugins; indexes tools by skill group
        contract_validator.py     # Validates SKILL.md compliance with current contract version
      models/
        abstract.py               # Vendor-neutral: VLAN, FirewallPolicy, VPNTunnel, DNSRecord…
        security_finding.py       # SecurityFinding(severity, category, description, recommendation)
      workflows/                  # Multi-step cross-vendor playbooks
        vlan_configure.py         # Uses registry to find gateway + edge plugins dynamically
        vlan_audit.py
        policy_sync.py
        firewall_audit.py
        dns_trace.py
        vpn_status.py
        security_audit.py
      tools/                      # Umbrella MCP tools
    SKILL.md                      # netex_contract_version=1.0.0; depends=[any conforming vendor plugins]
    pyproject.toml

  docs/                    # GitHub Pages site (MkDocs Material)
  contract/                # Vendor Plugin Contract specification and changelog
    v1.0.0/
      VENDOR_PLUGIN_CONTRACT.md
      skill_groups.md
      tool_naming.md
      skill_md_reference.md
```

---

## 3. unifi Plugin

The unifi plugin is the edge intelligence layer. It is a standalone EmberAI plugin — useful with or without the netex umbrella.

### 3.1 API Tiers

| Tier | Base URL | Auth | Rate limit | Scope |
|---|---|---|---|---|
| Site Manager EA | `api.ui.com/ea/` | X-API-KEY | 100 req/min | All sites — aggregate health |
| Cloud V1 | `api.ui.com/v1/` | X-API-KEY | 10,000 req/min | Per-account — hosts, sites, devices |
| Local Gateway | `{gw-ip}/proxy/network/` | X-API-KEY | Unlimited | Per-site — full CRUD |

> **Response normalization:** Each API tier returns a different response envelope. The plugin normalizes all three into a consistent internal schema. Callers never see `httpStatusCode` wrappers or `totalCount` fields.

### 3.2 Skill Groups

| Skill | Capability summary | Key tools | API tier(s) |
|---|---|---|---|
| topology | Site/host/device discovery, uplink graph, VLAN layout, port table, port profile assignment (write) | `list_sites`, `list_devices`, `get_vlans`, `get_uplinks`, `assign_port_profile` | Cloud V1 · Local |
| health | Device status, uptime, CPU/mem, firmware, ISP metrics, event log | `get_site_health`, `get_device_health`, `get_isp_metrics`, `get_events` | Site Manager · Cloud V1 · Local |
| wifi | SSID config, channel utilization, RF scan, roaming, band steering | `get_wlans`, `get_aps`, `get_channel_utilization`, `get_rf_scan` | Local |
| clients | Connected client inventory, signal, data rate, roaming, traffic | `list_clients`, `get_client`, `get_client_traffic`, `search_clients` | Cloud V1 · Local |
| traffic | WAN/LAN throughput, DPI stats, per-port bandwidth, QoS | `get_bandwidth`, `get_dpi_stats`, `get_port_stats`, `get_wan_usage` | Local |
| security | Firewall rules, ZBF policies, ACLs, port forwarding, IDS/IPS | `get_firewall_rules`, `get_zbf_policies`, `get_acls`, `get_ids_alerts` | Local |
| config | Config snapshots, drift vs. baseline, firmware readiness, RADIUS audit, port profile creation (write) | `get_config_snapshot`, `diff_baseline`, `get_backup_state`, `create_port_profile` | Cloud V1 · Local |
| multisite | Cross-site health aggregation, vantage point metrics, site comparison | `list_all_sites`, `compare_sites`, `get_vantage_points` | Site Manager |

### 3.3 Commands

| Command | Description |
|---|---|
| `unifi scan [site?]` | Discover and map the full network topology. |
| `unifi health [site\|device?]` | Tiered health report (Critical / Warning / Informational). |
| `unifi diagnose [device\|client]` | Root-cause analysis: event correlation, signal, config, connectivity. |
| `unifi wifi [site\|ssid?]` | Wireless environment — channel util, RF scan, roaming, band steering. |
| `unifi optimize [site?]` | Prioritized recommendations; `--apply` queues confirmed changes. |
| `unifi clients [site?]` | Inventory all clients with signal, rate, VLAN, AP/port, traffic. |
| `unifi secure [site?]` | Firewall audit, ZBF, ACL review, port forwarding, IDS trend. |
| `unifi compare [site1] [site2]` | Side-by-side cross-site comparison. |
| `unifi config [site?] [--drift]` | Config state review; `--drift` diffs against stored baseline. |
| `unifi port-profile create <n> [--native <vlan>] [--tagged <vlans>] [--apply]` | Create a named switch port profile in UniFi. Specify native VLAN and tagged VLANs. Required before port assignment. |
| `unifi port-profile assign <switch> <port> <profile> [--apply]` | Assign a named port profile to a specific port on a UniFi switch. OutageRiskAgent assesses whether the port carries the operator's management session. |

---

## 4. opnsense Plugin

The opnsense plugin is the gateway intelligence layer for OPNsense firewall/router deployments.

### 4.1 API Architecture

| Property | Detail |
|---|---|
| Base URL pattern | `{opnsense-ip}/api/{module}/{controller}/{command}/[{param1}/...]` |
| Authentication | HTTP Basic Auth — API key as username, secret as password |
| Read operations | HTTP GET |
| Write operations | HTTP POST — body is `application/json` |
| **Reconfigure pattern** | Most writes require a separate POST to `{module}/{controller}/reconfigure` to apply to the running system. The plugin always calls `reconfigure` explicitly after confirmed writes. |
| API key scope | Scoped by Effective Privileges on the user in System > Access > Users. |

> **Reconfigure pattern (critical):** OPNsense separates saving a configuration change from applying it. A write stores the change in the config file but does NOT activate it. A separate `reconfigure` call is the point of no return. Dry-run mode skips `reconfigure` entirely.

### 4.2 Core API Modules

| Module | Controllers | Capability |
|---|---|---|
| firewall | alias, alias_util, category, d_nat, filter, s_nat | Firewall rules, NAT/DNAT, aliases, filter categories |
| interfaces | assignments, loopback, vlan, vxlan, overview | Interface assignments, VLAN interface CRUD |
| routes | routes | Static route CRUD |
| routing | bgp, ospf, general | Dynamic routing via Quagga plugin |
| diagnostics | dns, interface, network_insight, packet_capture, ping, traceroute | Live diagnostics |
| ids | policy, rule, ruleset, service, settings | Suricata IDS/IPS management |
| ipsec | connections, key_pairs, pool, sessions | IPSec tunnel CRUD and session status |
| openvpn | clients, export, instances, service | OpenVPN instances and client management |
| wireguard | client, general, server, service | WireGuard peer/server CRUD |
| unbound | alias, dot, forward, host, general, dnsbl, acl | Unbound DNS resolver |
| kea | ctrl_agent, dhcpv4, dhcpv6, leases4, leases6 | Modern DHCP server |
| core/firmware | firmware | Firmware updates, package management |
| hostdiscovery | scan | ARP/NDP-based host discovery |
| trafficshaper | pipe, queue, rule | Traffic shaping |

### 4.3 Skill Groups

| Skill | Capability summary | Key tools | Core API modules |
|---|---|---|---|
| interfaces | Interface assignments, VLAN interface CRUD (atomic: create+IP+DHCP in one step), DHCP scope and static reservation management, physical topology via LLDP | `list_interfaces`, `list_vlan_interfaces`, `configure_vlan`, `add_dhcp_reservation`, `get_lldp_neighbors` | interfaces · kea |
| firewall | Rule CRUD, alias create/manage, NAT/DNAT, filter categories, shadow analysis, policy-from-matrix derivation | `list_rules`, `get_aliases`, `add_alias`, `add_rule`, `reconfigure_firewall` | firewall |
| routing | Static routes, gateway status, dynamic routing | `list_routes`, `list_gateways`, `add_route` | routes · routing |
| vpn | IPSec session CRUD, OpenVPN instances, WireGuard peers | `list_ipsec_sessions`, `list_openvpn_instances`, `list_wireguard_peers` | ipsec · openvpn · wireguard |
| security | IDS/IPS alerts, rule management, certificate trust | `get_ids_alerts`, `get_ids_rules`, `get_ids_policy`, `get_certificates` | ids · trust |
| services | Unbound DNS, DHCP leases, traffic shaping, NTP | `get_dns_overrides`, `get_dhcp_leases4`, `get_traffic_shaper`, `resolve_hostname` | unbound · kea · trafficshaper |
| diagnostics | Ping, traceroute, packet capture, LLDP neighbor discovery, host discovery, DNS lookup | `run_ping`, `run_traceroute`, `get_lldp_neighbors`, `run_host_discovery`, `dns_lookup` | diagnostics · hostdiscovery |
| firmware | Update check, packages, changelog, reboot scheduling | `get_firmware_status`, `list_packages` | core/firmware |

### 4.4 Commands

| Command | Description |
|---|---|
| `opnsense scan` | Full inventory — interfaces, VLANs, routes, VPN tunnels, firmware state. |
| `opnsense health` | Gateway uptime, interface state, VPN health, IDS alerts, firmware, WAN reachability. |
| `opnsense diagnose [interface?\|host?]` | Root-cause analysis through routing, firewall, NAT layers. |
| `opnsense firewall [--audit]` | List/summarize rules. `--audit` adds shadow analysis and over-broad rule detection. |
| `opnsense firewall policy-from-matrix --matrix <file> [--audit] [--apply]` | Derive and apply a firewall ruleset from an inter-VLAN access matrix. `--audit` surfaces gaps vs. existing rules; `--apply` generates the minimum correct ruleset, creates aliases, applies in correct order. |
| `opnsense dhcp reserve-batch <interface> --devices <spec> [--apply]` | Create multiple static DHCP reservations in one confirmed workflow. Accepts `hostname:mac:ip` per line. More efficient than individual reservations for initial provisioning. |
| `opnsense firewall policy-from-matrix --matrix <file> [--audit] [--apply]` | Derive and apply a firewall ruleset from an inter-VLAN access matrix. `--audit` surfaces gaps; `--apply` generates the minimum correct ruleset, creates aliases, applies in order. |
| `opnsense dhcp reserve-batch <interface> --devices <spec> [--apply]` | Create multiple static DHCP reservations in one confirmed workflow. Accepts `hostname:mac:ip` per line. |
| `opnsense vlan [--configure] [--audit]` | List VLAN interfaces. `--configure` adds a new VLAN atomically (interface + IP + DHCP scope using `configure_vlan`). `--audit` checks consistency, understands intentional range offsets. |
| `opnsense vpn [--tunnel name]` | VPN status: IPSec SA state, OpenVPN sessions, WireGuard handshakes. |
| `opnsense dns [hostname?]` | Unbound config — overrides, forwarders, blocklists, optional resolution test. |
| `opnsense secure` | IDS/IPS state, ruleset currency, firewall exposure, certificate expiry, open ports. |
| `opnsense firmware` | Available updates, installed packages, changelog, reboot scheduling. |

---

## 5. netex Umbrella Plugin

The netex umbrella is the cross-vendor orchestration layer. It treats the network as a system composed of whatever vendor plugins are installed. Netex does not hardcode vendor knowledge — it discovers installed vendor plugins at startup via the Plugin Registry and routes operations by role (`gateway`, `edge`, `wireless`, `overlay`).

### 5.1 Abstract Data Model

Vendor-neutral abstractions in `models/abstract.py`. Each concept maps to vendor-specific API representations at execution time.

| Abstract concept | OPNsense | UniFi | Future vendors |
|---|---|---|---|
| `VLAN(id, name, subnet)` | VLAN interface + Kea DHCP subnet | Network object + switch port profiles | MikroTik: `/ip/vlan`; Cisco: vlan RESTCONF; Proxmox: SDN VLAN |
| `FirewallPolicy(src, dst, action)` | Rule in `/api/firewall/filter` | ZBF zone policy or ACL rule | MikroTik: `/ip/firewall/filter`; Meraki: L3 firewall rules |
| `Route(destination, gateway)` | `/api/routes/routes` | N/A — UniFi does not manage routing | MikroTik: `/ip/route`; Cisco IOS-XE: static routes RESTCONF |
| `VPNTunnel(type, peer, status)` | `/api/ipsec`, `/api/openvpn`, `/api/wireguard` | N/A | Tailscale: device peers; pfSense: ipsec API |
| `DNSRecord(hostname, ip)` | Host override in `/api/unbound/host` | N/A | MikroTik: `/ip/dns/static` |
| `DHCPLease(mac, ip, hostname)` | Kea lease from `/api/kea/leases4` | Client record from `/api-v2/stat/alluser` | MikroTik: `/ip/dhcp-server/lease` |
| `NetworkTopology(nodes, links)` | Interface list + route table + VPN tunnels | Device graph + uplinks + VLAN assignments | Additive — each plugin contributes its layer |

### 5.2 NetworkSecurityAgent

The NetworkSecurityAgent is a permanent, read-only member of the netex umbrella. It never makes changes.

> **Hard constraint:** The NetworkSecurityAgent has no write capability. It calls only read-only tools across all installed vendor plugins. Enforced at the tool registry level.

#### 5.2.1 Role 1 — Change Plan Security Review

Every change plan passes through the NetworkSecurityAgent before being presented to the operator. This review is automatic and non-optional.

| Finding category | What the agent looks for | Output |
|---|---|---|
| VLAN isolation gap | New VLANs without corresponding inter-VLAN firewall deny rules | Flags the gap; recommends the specific deny rules to add |
| Overly broad firewall rule | `any/any` source or destination, or port ranges wider than intent | Proposes a narrower rule achieving the same access |
| Firewall rule ordering risk | Rules shadowed by existing rules, or that shadow existing denies | Shows effective rule order; recommends correct insertion position |
| VPN split-tunnel exposure | Tunnel scope wider/narrower than stated intent | Recommends config matching the stated intent |
| Unencrypted VLAN for sensitive traffic | IoT/management/camera SSIDs without WPA3 or open auth | Recommends appropriate security profile for the use case |
| Management plane exposure | Changes routing mgmt interfaces onto untrusted segments | Flags exposure; recommends dedicated management VLAN |
| DNS security posture | DNSSEC disabled, open recursion, forwarders without DoT | Recommends specific Unbound settings to harden the resolver |

If no concerns are found, the agent appends: *"Security review: no issues identified."* — confirming the review was performed.

#### 5.2.2 Role 2 — On-Demand Security Audit (`netex secure audit`)

| Audit domain | Data sources | What is assessed |
|---|---|---|
| Firewall policy (gateway) | opnsense: firewall skill | Rule shadowing, default-deny coverage, NAT exposure |
| Firewall policy (edge) | unifi: security skill | ZBF completeness, ACL coverage, port forwarding exposure |
| Cross-layer firewall consistency | Both | Gaps that appear correct on each system individually but create exposure together |
| VLAN isolation | opnsense: interfaces; unifi: topology | VLANs defined but lacking firewall rules enforcing isolation |
| VPN security posture | opnsense: vpn skill | Weak cipher suites, expired certs, WireGuard `/0` allowed IPs |
| DNS security | opnsense: services skill | DNSSEC, open recursion, DoT forwarder config |
| IDS/IPS coverage | opnsense: security skill | Suricata enabled state, ruleset currency, interfaces covered |
| Wireless security | unifi: wifi + security skills | WPA2/WPA3, SSID-to-VLAN isolation, rogue AP detections |
| Certificate and trust | opnsense: security skill | Expiry timeline, self-signed cert usage on externally-reachable services |
| Firmware and patch state | opnsense: firmware; unifi: health | Devices with known CVEs in installed versions |

Remediation commands are always provided without `--apply`. Remediation is always operator-initiated.

#### 5.2.3 Invoking the NetworkSecurityAgent

| Invocation | Trigger | Description |
|---|---|---|
| Automatic (plan review) | Every change plan before confirmation | Called internally by the Orchestrator. Always visible in the plan. |
| `netex secure audit [--domain <d>]` | Operator-initiated | Full audit or scoped: `firewall`, `vlan`, `vpn`, `dns`, `wireless`, `ids`, `certs`, `firmware`. |
| `netex secure review <plan-description>` | Operator-initiated | Review a previously described plan for security issues without executing it. |

> **Extensibility:** When additional vendor plugins are added, the NetworkSecurityAgent queries their security and configuration skills using the same finding categories and severity taxonomy. No changes to the core agent are required.

### 5.3 Cross-Vendor Commands

All netex commands coordinate calls across installed vendor plugins using the Plugin Registry — not hardcoded vendor names.

#### `netex vlan configure <name> <id> [--subnet <cidr>] [--dhcp] [--ssid <name>]`

Provisions a VLAN end-to-end across gateway and edge plugins.

| Property | Detail |
|---|---|
| Plugins required | gateway role + edge role |
| Execution order | 1. [gateway] add VLAN interface → 2. [gateway] add DHCP subnet (if `--dhcp`) → 3. [gateway] add inter-VLAN isolation rule → 4. [gateway] reconfigure → 5. [edge] create network object → 6. [edge] update switch port profiles → 7. [edge] bind SSID (if `--ssid`) |
| Rollback | If step 5+ fails, gateway changes are reverted. If rollback fails, report clearly and stop. |
| Write gate | Requires write flag enabled + `--apply` + single plan confirmation |

#### `netex vlan audit [--id <vlan-id>]`

Compares VLAN definitions between all installed gateway and edge plugins. Surfaces: VLANs defined in gateway but missing in edge; VLANs in edge but missing in gateway; VLANs present in both but with mismatched subnets or DHCP ranges.

#### `netex topology [--site <site>]`

Builds a unified network map: WAN → gateway interfaces → VLAN boundaries → edge device graph → APs → clients. Calls `registry.tools_for_skill("topology")` across all plugins.

#### `netex health [--site <site>]`

Combined health report across all installed plugins in a single severity-tiered view. Critical and High findings appear first regardless of plugin source.

#### `netex firewall audit [--vlan <id>]`

Full security posture review spanning all vendor plugin firewall layers. Delegates cross-layer consistency analysis to the NetworkSecurityAgent.

#### `netex dns trace <hostname> [--client <mac>]`

Traces DNS resolution through OPNsense Unbound. If `--client` is provided, correlates with the client's VLAN assignment to catch VLAN-scoped DNS reachability issues.

#### `netex vpn status [--tunnel <name>]`

Reports VPN health from gateway plugins. Correlates VPN client IPs against edge plugin client records to confirm reachability through the full stack.

#### `netex policy sync [--dry-run]`

Identifies configuration drift between all installed plugins. With `--dry-run`, presents findings without entering Phase 3. Without it, queues a confirmed change plan with the safety gate.

---

## 6. Authentication & Security

### 6.1 Environment Variables

| Variable | Plugin | Purpose | Required |
|---|---|---|---|
| `UNIFI_API_KEY` | unifi | Cloud V1 and Site Manager API access | Yes (cloud) |
| `UNIFI_LOCAL_HOST` | unifi | IP/hostname of UniFi local gateway | Yes (local) |
| `UNIFI_LOCAL_KEY` | unifi | API key for local gateway | Yes (local) |
| `OPNSENSE_HOST` | opnsense | IP/hostname of OPNsense instance (include scheme) | Yes |
| `OPNSENSE_API_KEY` | opnsense | API key (Basic Auth username) | Yes |
| `OPNSENSE_API_SECRET` | opnsense | API secret (Basic Auth password) | Yes |
| `NETEX_WRITE_ENABLED` | netex | Enable writes across both plugins | No (default: false) |
| `UNIFI_WRITE_ENABLED` | unifi | Enable writes for unifi plugin only | No (default: false) |
| `OPNSENSE_WRITE_ENABLED` | opnsense | Enable writes for opnsense plugin only | No (default: false) |
| `NETEX_CACHE_TTL` | all | Override default TTL in seconds | No (default: 300) |

### 6.2 Write Safety Gate

Write operations in all three plugins follow the same three-step gate:

1. The relevant write-enable environment variable must be explicitly set to `true`.
2. The command must include an `--apply` flag. Without it, all commands run in plan (read-only) mode.
3. The orchestrator presents a full change plan and waits for affirmative confirmation in the Claude conversation.

For netex umbrella commands, the change plan is presented as a single cross-vendor summary before any writes are initiated. The user confirms once; the orchestrator executes the sequence and triggers rollback on failure.

### 6.3 Caching Strategy

| Plugin | Data type | Default TTL | Invalidation |
|---|---|---|---|
| unifi | Site list / device list | 5 min | TTL + manual flush |
| unifi | Client list | 30 sec | TTL only |
| unifi | Site Manager health | 2 min | TTL + manual flush |
| opnsense | Interface / route list | 5 min | TTL + post-write flush |
| opnsense | Firewall rule list | 2 min | TTL + post-write flush |
| opnsense | DHCP lease list | 1 min | TTL only |
| netex | Abstract VLAN model | 5 min | Invalidated when either vendor source changes |

---

## 7. Cross-Plugin Skill Alignment

The unifi and opnsense plugins are deliberately structured with parallel skill group names where domains overlap. The NetworkSecurityAgent operates at the umbrella layer and draws from all vendor plugins rather than being owned by either.

| Skill group | unifi plugin | opnsense plugin |
|---|---|---|
| topology / interfaces | Device graph, uplinks, VLANs on ports | Interface assignments, VLAN interfaces, routing table |
| health / diagnostics | Device uptime, firmware, ISP metrics, event log | Interface UP/DOWN, gateway latency, ping/traceroute, packet capture |
| security / security | ZBF, ACLs, UniFi firewall, IDS alerts | Firewall rules, NAT, aliases, Suricata IDS/IPS, cert trust |
| config / firmware | Config snapshots, drift detection, RADIUS, backup | Firmware check, package management, changelog, reboot |
| traffic / services | DPI stats, per-port bandwidth, QoS policy | Traffic shaper, Unbound DNS, DHCP scopes |
| clients / (diagnostics) | Connected clients, signal, roam history, traffic | Host discovery, DHCP leases — client IP/MAC resolution |
| wifi / — | SSIDs, APs, channel util, RF scan, roaming | N/A — OPNsense has no wireless management |
| multisite / — | Cross-site aggregation via Site Manager API | N/A — OPNsense manages a single instance |
| — / vpn | N/A — UniFi does not manage VPN | IPSec, OpenVPN, WireGuard tunnel CRUD and status |
| — / routing | N/A — UniFi does not manage routing | Static routes, gateways, BGP/OSPF via Quagga |
| — / — (umbrella) | NetworkSecurityAgent (read-only, cross-vendor) | NetworkSecurityAgent (read-only, cross-vendor) |

---

## 8. Implementation Roadmap

| Phase | Version | Target | Key deliverables |
|---|---|---|---|
| Phase 1 | v0.1.0 | Weeks 1–6 | unifi plugin: scaffold, Cloud V1 + Local API clients, topology/health/clients skills, scan/health/diagnose/clients commands, TTL cache, SKILL.md, EmberAI marketplace listing. |
| Phase 2 | v0.2.0 | Weeks 7–12 | opnsense plugin: scaffold, OPNsense REST client, all skill groups, all base commands + 3 new commands (`policy-from-matrix`, `dhcp reserve-batch`, atomic `vlan --configure`). New tools: `add_alias`, `add_dhcp_reservation`, `configure_vlan`, `get_lldp_neighbors`. |
| Phase 3 | v0.3.0 | Weeks 13–18 | netex umbrella: abstract data model, Orchestrator, OutageRiskAgent, NetworkSecurityAgent, vlan configure/audit, topology/health/firewall audit + 3 new commands (`network provision-site`, `verify-policy`, `vlan provision-batch`). unifi: port profile create/assign tools and commands. |
| Phase 4 | v0.4.0 | Weeks 19–24 | netex: dns trace, vpn status, policy sync. unifi: wifi/optimize skills. opnsense: services (Unbound, traffic shaper). Redis caching for all three plugins. |
| Phase 5 | v0.5.0 | Weeks 25–32 | unifi: Site Manager OAuth, multi-site full support. opnsense: Quagga dynamic routing, IDS policy CRUD. netex: scheduled health digests, MSP multi-tenant credential isolation. |

### 8.1 Phase 1 Milestones (unifi plugin, v0.1)

- Week 1–2: Scaffold `emberai/unifi` — pyproject.toml, directory structure, SKILL.md, CI pipeline.
- Week 2–3: Cloud V1 API client — hosts, sites, devices with response normalization and TTL cache.
- Week 3–4: Local Gateway API client — device, client, event, VLAN, uplink endpoints.
- Week 4–5: Topology and Health agents — `list_sites`, `list_devices`, `get_device_health`, `get_events`.
- Week 5–6: Clients agent, scan/health/diagnose/clients commands, Orchestrator routing, marketplace packaging.

### 8.2 Phase 2 Milestones (opnsense plugin, v0.2)

- Week 7–8: Scaffold `emberai/opnsense` — pyproject.toml, directory structure, SKILL.md.
- Week 8–9: OPNsense REST client — module/controller/command router, Basic auth, response normalization, reconfigure pattern.
- Week 9–10: Interfaces, firewall, routing agents — core read operations plus new write tools: `add_alias`, `add_dhcp_reservation`, `configure_vlan` (atomic VLAN+IP+DHCP), `get_lldp_neighbors`.
- Week 10–11: VPN, diagnostics, firmware agents — IPSec/OpenVPN/WireGuard status, ping/traceroute, firmware check.
- Week 11–12: New commands: `policy-from-matrix`, `dhcp reserve-batch`. All commands wired.

### 8.3 Phase 3 Milestones (netex umbrella, v0.3)

- Week 13–14: Abstract data model — VLAN, FirewallPolicy, VPNTunnel, SecurityFinding. Plugin Registry integration.
- Week 14–15: OutageRiskAgent — session path resolution, risk tier classification, single-pass batch assessment (one assessment per batch, not per operation).
- Week 15–16: NetworkSecurityAgent — plan review pipeline, SecurityFinding taxonomy, 10 audit domains.
- Week 16–17: Core umbrella commands: vlan configure/audit, topology, health, firewall audit, secure audit.
- Week 16–17: Core umbrella commands: vlan configure/audit, topology, health, firewall audit, secure audit.
- Week 17–18: New commands: `network provision-site`, `verify-policy`, `vlan provision-batch`. unifi port-profile commands.
- Week 18: Umbrella SKILL.md, Ridgeline workflow docs, marketplace listing.

---

## 9. Documentation Requirements

Documentation is a first-class deliverable. A plugin feature that exists without a workflow example is considered incomplete.

### 9.1 Documentation-as-Code Principles

- All documentation lives in `bluminal/emberai` repository in a top-level `/docs` directory. Docs and code are versioned together.
- Every PR that adds or modifies a command, skill, or agent must include corresponding documentation updates. PRs without docs updates are not mergeable.
- Workflow examples are the primary documentation artifact — not API reference tables.
- Documentation is written from the operator's perspective: *"I want to provision a new VLAN"* rather than *"the vlan configure command accepts the following parameters."*
- Code samples in documentation are tested against a reference environment as part of CI. Broken examples fail the build.

### 9.2 Publishing: GitHub Pages

| Property | Detail |
|---|---|
| Source repository | `bluminal/emberai` — `docs/` directory at repo root |
| Publishing URL | `https://bluminal.github.io/emberai` (custom domain: `docs.emberai.dev`, pending DNS) |
| Build tool | MkDocs with Material for MkDocs theme |
| API reference | Auto-generated from Python docstrings using `mkdocstrings` plugin |
| Deployment trigger | GitHub Actions on push to main; preview builds on PRs |
| Versioning | `mike` plugin — maintains `/latest` and `/vX.Y.Z` paths |
| Search | MkDocs Material built-in client-side search |

**Site navigation structure:**

```
docs/
  index.md                      # Landing page
  getting-started/
    installation.md
    authentication.md           # UniFi API keys, OPNsense key+secret setup
    connectivity.md             # Local vs. remote MCP server deployment
    quick-start.md
  unifi/
    overview.md
    commands.md
    skills.md
    workflows/
      basic/                    # 5 basic workflow examples
      advanced/                 # 5 advanced workflow examples
    api-reference/
  opnsense/
    overview.md
    commands.md
    skills.md
    workflows/
      basic/
      advanced/
    api-reference/
  netex/
    overview.md
    abstract-model.md
    commands.md
    workflows/
      basic/
      advanced/
  reference/
    environment-variables.md
    write-safety.md
    caching.md
    changelog.md
```

### 9.3 Workflow Example Standard

Every workflow example follows this 7-section structure — mandatory for all contributions:

| Section | Required content |
|---|---|
| Intent | One sentence in first person: what the operator is trying to accomplish. |
| Prerequisites | Which plugins must be installed; minimum API privileges; any optional OPNsense plugins required. |
| Context | 2–4 sentences on when this applies and what it doesn't cover. Links to related workflows. |
| Commands | Exact Claude conversation turns with representative output using realistic but anonymized data. |
| What to look for | How to interpret the output: actionable vs. informational findings, healthy vs. degraded states. |
| Next steps | Links to 1–3 follow-on workflows. Builds the mental model of a workflow chain. |
| Troubleshooting | Common failure modes specific to this workflow: API auth errors, missing privileges, partial results. |

### 9.4 Required Workflow Examples — unifi Plugin

**Basic workflows (ship with v0.1.0):**

| Workflow | Intent | Commands involved |
|---|---|---|
| First-time site scan | Discover everything on a UniFi network for the first time. | `unifi scan` |
| Daily health check | Confirm all devices are up, no firmware alerts, ISP metrics clean. | `unifi health` |
| Locate a specific client | Find a device by hostname/IP/MAC; see AP, VLAN, signal, traffic. | `unifi clients` → `unifi diagnose [client]` |
| Check WiFi channel utilization | See which channels are congested across all APs. | `unifi wifi` |
| Firmware update status | List all devices with pending updates before a maintenance window. | `unifi health` |

**Advanced workflows (ship with v0.2.0):**

| Workflow | Intent | Commands involved |
|---|---|---|
| Diagnose a client connectivity complaint | Trace why a client cannot reach a destination through all layers. | `unifi diagnose [client]` → `unifi secure` → `unifi health` |
| Optimize a congested WiFi environment | RF scan + roaming analysis → prioritized channel/power recommendations. | `unifi wifi` → `unifi optimize` |
| Full firewall posture audit | Enumerate ZBF, ACLs, port forwarding; surface exposure and shadowed rules. | `unifi secure` |
| Detect configuration drift post-change | Compare current config against pre-change baseline. | `unifi config --drift` |
| MSP fleet health digest | Cross-site health summary across all managed sites, sorted by severity. | `unifi compare` → `unifi health [site]` |

### 9.5 Required Workflow Examples — opnsense Plugin

**Basic workflows (ship with v0.2.0):**

| Workflow | Intent | Commands involved |
|---|---|---|
| First-time system scan | Inventory all interfaces, VLANs, routes, VPN tunnels. | `opnsense scan` |
| Review firewall rules | List rules on an interface; identify disabled or broadly permissive rules. | `opnsense firewall` |
| Check VPN tunnel health | Verify IPSec SAs and WireGuard peers; byte counters. | `opnsense vpn` |
| Troubleshoot DNS resolution | Confirm Unbound resolves correctly; check overrides and blocklists. | `opnsense dns [hostname]` |
| DHCP lease audit | See all active Kea leases — IP, MAC, hostname, expiry. | `opnsense scan` → `opnsense diagnose` |

**Advanced workflows (ship with v0.3.0):**

| Workflow | Intent | Commands involved |
|---|---|---|
| Diagnose a routing black hole | Trace why traffic to a destination is dropped — packet capture, traceroute, NAT. | `opnsense diagnose [host]` → `opnsense firewall --audit` |
| Full firewall audit with shadow analysis | Find redundant, shadowed, and overly permissive rules before a security review. | `opnsense firewall --audit` |
| Add and validate a new WireGuard peer | Create peer, generate keys, apply, verify handshake, test reachability. | `opnsense vpn` → `opnsense diagnose` |
| Traffic shaping policy review | Identify active pipes/queues, utilization, policy effectiveness. | `opnsense health` → `opnsense diagnose` |
| IDS/IPS alert triage and rule tuning | Review Suricata alerts, suppress false positives, validate coverage. | `opnsense secure` |

### 9.6 Required Workflow Examples — netex Umbrella

**Basic workflows (ship with v0.3.0):**

| Workflow | Intent | Commands involved |
|---|---|---|
| Unified health dashboard | Health of both OPNsense and UniFi in one severity-ranked report. | `netex health` |
| VLAN consistency audit | Compare VLAN IDs and subnets between both systems for mismatches. | `netex vlan audit` |
| End-to-end topology map | Unified view from WAN through gateway to edge to clients. | `netex topology` |

**Advanced workflows (ship with v0.3.0–v0.4.0):**

| Workflow | Intent | Commands involved |
|---|---|---|
| **Ridgeline: provision a segmented home network** | **FLAGSHIP:** provision a complete 7-VLAN home network with firewall policy, WiFi SSIDs, and port profiles from a manifest. Full walkthrough at `docs/netex/workflows/advanced/site-provision.md`. | `netex network provision-site` → `netex verify-policy` |
| Guest WiFi isolation setup | Guest VLAN + SSID + inter-VLAN isolation rules across both systems. | `netex vlan configure` → `netex firewall audit` |
| Troubleshoot cross-VLAN connectivity | Diagnose why VLAN 30 can reach VLAN 10 through both firewall layers. | `netex firewall audit` → `opnsense diagnose` |
| Post-change policy sync and validation | Detect drift and reconcile after a maintenance window. | `netex policy sync --dry-run` → `netex vlan audit` → `netex firewall audit` |
| New site onboarding checklist | Validate a newly deployed site: scan, VLAN audit, firewall posture, VPN, DNS. | `netex topology` → `netex vlan audit` → `netex firewall audit` → `opnsense vpn` → `opnsense dns` |

### 9.7 Documentation Delivery Schedule

| Phase | Plugin | Docs deliverables |
|---|---|---|
| Phase 1 — v0.1.0 | unifi | Getting Started; unifi overview, commands, skills reference; 5 basic workflow examples; GitHub Pages site scaffolded and live. |
| Phase 2 — v0.2.0 | opnsense | opnsense overview, commands, skills reference; 5 basic workflow examples; API reference auto-generation. |
| Phase 3 — v0.3.0 | netex | netex overview, abstract model, commands; 3 basic + 5 advanced umbrella workflow examples; unifi + opnsense advanced workflows. |
| Phase 4 — v0.4.0 | all | Versioned docs with `mike`; changelog; troubleshooting guide; connectivity deployment guide; CI doc testing. |
| Phase 5 — v0.5.0 | all | MSP deployment guide; multi-instance OPNsense; Protect API workflows; Plausible analytics. |

---

## 10. Human-in-the-Loop Interaction Model

Netex is explicitly designed as an **assistant**, not an autonomous agent. This is a deliberate architectural decision driven by the blast radius of network changes: a misconfigured firewall rule or VLAN reconfigure can disconnect the operator from the very system they are trying to manage.

### 10.1 Contrast with Synthex

| Dimension | Synthex (LumenAI) | Netex (EmberAI) |
|---|---|---|
| Operational model | Full asynchronous agentic — executes multi-step workflows autonomously | Assistant model — human gates every step that touches the live network |
| Ambiguity handling | Resolves ambiguity through inference; proceeds and reports | Stops and asks. Never infers a network intent that could cause disruption. |
| Write operations | Agentic write chains are a first-class use case | Write operations are the exception. Every write plan is individually confirmed. |
| Blast radius | Low — code and file operations are easily undone | High — a bad firewall rule or VLAN change can cause an outage |
| Rollback | Undo via version control or file restore | Rollback requires network access that may have been severed by the change itself |
| User supervision | Operator can step away; agent completes the task | Operator must remain present and attentive throughout any write workflow |

### 10.2 Plan-Level Confirmation Model

Netex does not ask for confirmation before every individual API call. Instead it follows three phases:

| Phase | What happens | AskUserQuestion usage |
|---|---|---|
| 1 — Gather & resolve assumptions | Before building the plan, identify genuine ambiguities — values not determinable from the API. Run OutageRiskAgent and NetworkSecurityAgent in parallel. | Ask only questions that would change the plan if answered differently. Batch related questions into a single call. Frame each with its implication: *"If X, the plan will do A; if Y, it will do B."* |
| 2 — Build & present the plan | Construct the full ordered change plan. Structure: `[OUTAGE RISK]` → `[SECURITY]` → `[CHANGE PLAN]` → `[ROLLBACK]`. Present in full before any write is initiated. | No question here — informational only. |
| 3 — Single confirmation | Operator reviews the complete plan and confirms or cancels. | One AskUserQuestion: *"N steps across [systems]. Confirm to proceed, or tell me what to change."* |

**What qualifies as an assumption worth asking about:**
- Any value not explicitly stated that has more than one plausible answer.
- Any inference about intent where, if wrong, the plan would be materially different.
- Any case where the agent must choose between two options with different risk profiles.

**What does not warrant a question:**
- Facts determinable by reading current system state via read-only API calls.
- Standard defaults already implied by the chosen command.
- Progress confirmations mid-execution (the exception is a failure — see §10.4).

**Pre-plan checks, not questions (never assume):**
- Check for VLAN ID conflicts via API before including the VLAN in the plan. Surface conflicts as blockers, not questions.
- Resolve interface-to-description mapping from the API and state the resolution explicitly in the plan.
- Check for subnet overlap before including a DHCP scope in the plan.
- Determine whether OPNsense `reconfigure` affects only the target module or reloads the full firewall state, and include that in the outage risk assessment.

### 10.3 Pre-Change Gate: OutageRiskAgent and NetworkSecurityAgent

Both agents run in parallel before every change plan. Neither can be skipped.

| Agent | Question it answers | Output in the plan |
|---|---|---|
| OutageRiskAgent | Will making these changes cut off the operator's ability to reach the network? | Risk tier (CRITICAL / HIGH / MEDIUM / LOW) with the specific interface or path at risk named explicitly. |
| NetworkSecurityAgent | Does this plan introduce or worsen security vulnerabilities? | Severity-ranked security findings with concrete alternative approaches. |

**OutageRiskAgent assessment steps:**
1. Determine the operator's session source IP.
2. Use `diagnostics` tools to map the path from source IP to the management interface.
3. Use `topology` and `clients` tools to identify the switch port and VLAN carrying the session.
4. Check whether the plan modifies the interface, VLAN, route, firewall rule, or DHCP scope the session depends on.
5. Classify and output a risk tier.

**Risk tiers and required actions:**

| Risk tier | Criteria | Required action |
|---|---|---|
| CRITICAL | Change directly modifies the interface, VLAN, or route the operator's session traverses. | Require the operator to explicitly state they have out-of-band access. A generic "yes" is not sufficient. |
| HIGH | Change is in the same subsystem; partial disruption is possible. | Present the risk; ask the operator to confirm they are prepared for potential brief disruption. |
| MEDIUM | Change could cause indirect disruption (DNS, DHCP, routing loop). | Present as informational callout in the change plan; single standard confirmation. |
| LOW | Change does not touch any infrastructure in the operator's session path. | Standard write-gate confirmation only. |

If the session path cannot be determined, default to HIGH and state the reason.

### 10.4 AskUserQuestion Implementation Patterns

| Scenario | Required question content |
|---|---|
| Assumption resolution (Phase 1) | Group all unresolvable ambiguities into a single question block. State what was already determined from the API. Frame each question with its implication. |
| Plan presentation with single confirmation (Phase 2→3) | Full ordered plan as a numbered list. OutageRiskAgent assessment at the top. Single confirmation prompt at the end. |
| Outage risk — CRITICAL or HIGH | Risk assessment at the top of the plan, before the step list. CRITICAL requires explicit out-of-band confirmation — a generic "yes" is not sufficient. |
| Mid-execution failure | Stop immediately. Report exactly which steps completed and which failed. Ask: *"Should I attempt rollback, or leave the current state for you to assess manually?"* |
| Operator modifies the plan | Re-run Phase 1 only for the affected steps; rebuild and present for a fresh confirmation. Do not re-ask about unchanged steps. |

### 10.5 Documentation Requirements for this NFR

- A dedicated **"Safety & Human Supervision"** page in Getting Started — linked from every workflow example's Prerequisites section.
- A prominent warning callout at the top of every write-capable command's documentation page.
- A **"Working Safely"** section in every advanced workflow example: which steps are writes, what outage risk the OutageRiskAgent will assess, what out-of-band access the operator should have.
- A **top-level warning banner** on the docs home page: *"Netex is an assistant, not an autonomous agent. It will always ask before changing anything on your network."*
- A **"Netex vs. Autonomous Network Automation"** explainer page.

#### `netex network provision-site --manifest <file> [--dry-run] [--apply]`

The site bootstrap command. Accepts a complete network manifest (VLANs, DHCP, access matrix, WiFi SSIDs, port profiles) and orchestrates the entire provisioning sequence in dependency order across all installed vendor plugins. Runs a **single** OutageRiskAgent pass and NSA review for the entire batch — not one per operation. Presents one unified ordered plan and executes with one confirmation. `--dry-run` produces the full plan without executing. Validated against the Ridgeline 7-VLAN home network buildout. See [Provisioning the Ridgeline network](netex/workflows/advanced/site-provision.md).

| Property | Detail |
|---|---|
| Plugins required | gateway role + edge role |
| Execution order | Gateway interfaces → DHCP → firewall aliases → rules (from access matrix) → edge networks → WiFi → port profiles |
| Write gate | `NETEX_WRITE_ENABLED=true` + `--apply` + single operator confirmation |
| Rollback | Presented before execution. On failure: stop, report, ask operator. |

#### `netex verify-policy [--manifest <file>] [--vlan <id>]`

Runs a structured test suite against a provisioned network — derived from the manifest `access_policy`. Tests every expected-allow and expected-block path, verifies DHCP ranges, DNS resolution, and WiFi SSID-to-VLAN mapping. Returns a pass/fail report per test. Run immediately after `provision-site` to confirm the network matches intent. A failed expected-block test indicates a firewall rule gap — follow with `opnsense firewall --audit`.

#### `netex vlan provision-batch --manifest <file> [--apply]`

Creates multiple VLANs across gateway and edge plugins in a single confirmed workflow. Accepts a `vlans[]` list. Runs one OutageRiskAgent assessment for the entire batch (new VLANs on a clean trunk all share the same LOW risk profile). Single NSA review and one confirmation. Use when adding a VLAN scheme to an existing network without the full `provision-site` workflow.

---

> ⚠️ **Required verbatim on all write workflow pages:** Network changes can result in outages that disconnect you from your ability to correct them. Never make changes to a network you cannot reach through an out-of-band path (serial console, IPMI/iDRAC, a separate management VLAN on a different physical interface, or physical access). Netex will assess this risk for you, but it cannot guarantee your recovery path — only you can verify that.

---

## 11. Open Questions

| # | Question | Owner | Target |
|---|---|---|---|
| 1 | Site Manager EA graduation: will Ubiquiti promote EA endpoints to stable v1 before Phase 5? Monitor `developer.ui.com`. | A.J. | Phase 5 kickoff |
| 2 | OPNsense multi-instance: should the opnsense plugin support multiple OPNsense instances (HA pair, multiple sites)? v0.1 targets single-instance only. | A.J. | Phase 2 design |
| 3 | Local connectivity: when the MCP server runs remotely, how does it reach the UniFi local gateway and OPNsense? Options: VPN, Site Magic, reverse proxy. Needs a deployment guide. | A.J. | Phase 1 Week 2 |
| 4 | EmberAI tool registry dependency declaration: how does the netex SKILL.md declare dependencies on vendor plugins at runtime? Directory scan, env var list, or registry manifest? | A.J. | Phase 3 kickoff |
| 5 | Rollback atomicity: if `vlan configure` partially succeeds and rollback itself fails, what happens? Need a persistent workflow state model. | A.J. | Phase 3 design |
| 6 | OPNsense Quagga plugin dependency: the routing skill uses Quagga for BGP/OSPF, an optional plugin. The skill must degrade gracefully if not installed. | A.J. | Phase 2 Week 9 |
| 7 | UniFi Protect integration: Protect API not publicly documented at the same level. Defer to Phase 5. | A.J. | Phase 5 kickoff |
| 8 | Vendor Plugin Contract versioning: how are breaking changes communicated to third-party plugin authors? Need a deprecation policy and contract changelog. | A.J. | Phase 3 kickoff |
| 9 | Plugin Registry discovery mechanism: how does the registry detect installed vendor plugins at runtime? | A.J. | Phase 3 design |
| 10 | Cross-vendor workflow with 3+ vendors: when gateway + edge + hypervisor plugins are all present, how does `vlan configure` determine sequencing? Need a role-based dependency graph. | A.J. | Phase 3 design |

---

## Appendix A: unifi SKILL.md

This is the complete SKILL.md manifest for the unifi vendor plugin. It is the first file the development team creates in Phase 1. It serves as both the plugin's contract declaration to the netex Plugin Registry and the Claude instruction set governing plugin behavior.

### A.1 YAML Frontmatter

```yaml
---
name: unifi
version: 0.1.0
description: >
  UniFi network intelligence plugin for EmberAI. Provides topology discovery,
  health monitoring, WiFi analysis, client management, traffic inspection,
  security audit, configuration drift detection, and multi-site operations
  across UniFi Site Manager, Cloud V1, and Local Gateway APIs.
author: Bluminal Labs
license: MIT
repository: https://github.com/bluminal/emberai/tree/main/unifi
docs: https://bluminal.github.io/emberai/unifi/

# Vendor Plugin Contract fields (netex v1.0.0)
netex_vendor: unifi
netex_role:
  - edge
  - wireless
netex_skills:
  - topology
  - health
  - wifi
  - clients
  - traffic
  - security
  - config
  - multisite
netex_write_flag: UNIFI_WRITE_ENABLED
netex_contract_version: "1.0.0"
---
```

### A.2 Overview Instructions

```
# unifi — UniFi Network Intelligence Plugin

You are operating the unifi plugin for the EmberAI marketplace. This plugin
gives you read and (when explicitly enabled) write access to UniFi network
deployments via three API tiers.

This plugin covers the EDGE layer of the network: switches, access points,
wireless SSIDs, client associations, VLANs on switch ports, and site-level
health. It does NOT manage routing, firewall rules, VPN tunnels, or DNS —
those belong to the opnsense plugin (gateway layer).

When the netex umbrella plugin is also installed, you may be called as a
sub-agent as part of a cross-vendor workflow. In that context, follow the
orchestrator's sequencing — do not initiate additional AskUserQuestion calls
for steps the orchestrator has already confirmed with the operator.

## API Tiers
  Site Manager EA : api.ui.com/ea/         auth: X-API-KEY   limit: 100 req/min
  Cloud V1        : api.ui.com/v1/         auth: X-API-KEY   limit: 10,000 req/min
  Local Gateway   : {UNIFI_LOCAL_HOST}/proxy/network/  auth: X-API-KEY  limit: none

Response envelopes differ by tier. The plugin normalizes all three into a
consistent internal schema. Never expose raw envelope fields (httpStatusCode,
traceId, totalCount) to the operator.
```

### A.3 Authentication Instructions

```
## Authentication

Required environment variables:
  UNIFI_API_KEY      : API key for Cloud V1 and Site Manager EA
  UNIFI_LOCAL_HOST   : IP or hostname of the UniFi Local Gateway
                       (e.g., 192.168.1.1 or unifi.local)
  UNIFI_LOCAL_KEY    : API key for the Local Gateway (may differ from
                       UNIFI_API_KEY if keys are scoped separately)

Optional:
  UNIFI_WRITE_ENABLED : Set to "true" to enable write operations.
                        Default: false. Without this, all POST calls
                        are blocked and the plugin operates read-only.
  NETEX_CACHE_TTL     : Override TTL for all cached responses (seconds).
                        Default: 300.

On startup, verify all required variables are set. If any are missing,
inform the operator which variable is absent and what it is used for.
Do not attempt to call any API endpoint with an incomplete configuration.
```

### A.4 Interaction Model

```
## Interaction Model

This plugin is an ASSISTANT, not an autonomous agent. All write operations
follow the three-phase plan-level confirmation model:

Phase 1 — Resolve assumptions
  Before building a change plan, identify values you cannot determine from
  the API. Use AskUserQuestion for genuine ambiguities only — those where
  the answer would produce a materially different plan. Batch all questions
  into a single call. Facts checkable via read-only API calls (e.g., whether
  a VLAN ID is already in use) must be checked, not asked.

Phase 2 — Present the complete plan
  Show the full ordered change plan: every step, every API call, in sequence.
  State what will change, on which system, and the expected outcome of each
  step. Include a rollback plan for reversible changes. This phase has no
  AskUserQuestion — it is informational only.

Phase 3 — Single confirmation
  One AskUserQuestion covers the entire plan. Begin execution only after
  an affirmative response. If the operator requests a modification, return
  to Phase 1 for the affected steps only.

UNIFI_WRITE_ENABLED must be "true" AND the operator must have confirmed the
plan before any POST call is made. If UNIFI_WRITE_ENABLED is false, you may
still describe what a write operation would do (plan mode), but you must
state clearly that write operations are currently disabled.
```

### A.5 Skill Groups and Tool Signatures

```
### topology
# Discovers and models the network graph.

unifi__topology__list_sites()
  -> [{site_id, name, description, device_count, client_count}]
  API: GET api.ui.com/v1/sites

unifi__topology__list_hosts()
  -> [{host_id, name, ip, type, is_owner, firmware_version}]
  API: GET api.ui.com/v1/hosts

unifi__topology__list_devices(site_id)
  -> [{device_id, name, model, mac, ip, status, uptime, firmware,
       product_line, is_console}]
  API: GET {local}/api/s/{site}/stat/device

unifi__topology__get_device(device_id)
  -> {device_id, name, model, port_table, uplink, vlan_assignments,
       radio_table?, config_network}
  API: GET {local}/api/s/{site}/stat/device/{mac}

unifi__topology__get_vlans(site_id)
  -> [{vlan_id, name, subnet, purpose, dhcp_enabled, domain_name}]
  API: GET {local}/api/s/{site}/rest/networkconf

unifi__topology__get_uplinks(site_id)
  -> [{device_id, uplink_device_id, uplink_port, uplink_type, speed}]
  API: Derived from device port_table and uplink fields


### health
# Device and site health monitoring.

unifi__health__get_site_health(site_id?)
  -> {wan_status, lan_status, wlan_status, www_status,
       device_count, adopted_count, offline_count, client_count}
  API: GET {local}/api/s/{site}/stat/health

unifi__health__get_device_health(device_id)
  -> {device_id, uptime, cpu_pct, mem_pct, temperature?,
       tx_bytes, rx_bytes, satisfaction?, firmware_upgrade_available}
  API: GET {local}/api/s/{site}/stat/device/{mac}

unifi__health__get_isp_metrics(site_id)
  -> {wan_ip, latency_ms, packet_loss_pct, uptime_pct,
       download_mbps, upload_mbps, isp_name}
  API: GET {local}/api/s/{site}/stat/sta (gateway-reported WAN stats)

unifi__health__get_events(site_id, hours?=24, severity?="all")
  -> [{timestamp, type, severity, device_id?, client_mac?,
       message, subsystem}]
  API: GET {local}/api/s/{site}/stat/event
  severity values: critical, warning, info, all

unifi__health__get_firmware_status(site_id?)
  -> [{device_id, model, current_version, latest_version,
       upgrade_available, product_line}]
  API: GET api.ui.com/v1/devices (cloud-reported firmware state)


### wifi
# Wireless environment analysis. All tools are read-only.
# Never trigger an active RF scan — passive data only.

unifi__wifi__get_wlans(site_id)
  -> [{wlan_id, name, ssid, security, band, vlan_id, enabled,
       client_count, satisfaction}]
  API: GET {local}/api/s/{site}/rest/wlanconf

unifi__wifi__get_aps(site_id)
  -> [{ap_id, name, mac, model, channel_2g?, channel_5g?, channel_6g?,
       tx_power_2g?, tx_power_5g?, client_count, satisfaction}]
  API: GET {local}/api/s/{site}/stat/device (filtered to APs)

unifi__wifi__get_channel_utilization(ap_id)
  -> {ap_id, radio_2g?: {channel, utilization_pct, interference_pct},
              radio_5g?: {channel, utilization_pct, interference_pct},
              radio_6g?: {channel, utilization_pct, interference_pct}}
  API: GET {local}/api/s/{site}/stat/device/{mac} (radio_table field)

unifi__wifi__get_rf_scan(ap_id)
  -> [{ssid, bssid, channel, band, rssi, security, is_own}]
  API: GET {local}/api/s/{site}/stat/rogueap
  Note: Returns cached scan data. Does not trigger a new scan.

unifi__wifi__get_roaming_events(site_id, hours?=24)
  -> [{timestamp, client_mac, from_ap_id, to_ap_id,
       rssi_before, rssi_after, roam_reason}]
  API: GET {local}/api/s/{site}/stat/event (filtered to roam events)

unifi__wifi__get_client_rf(client_mac, site_id)
  -> {client_mac, ap_id, ssid, rssi, noise, snr, tx_rate_mbps,
       rx_rate_mbps, tx_retries_pct, channel, band}
  API: GET {local}/api/s/{site}/stat/sta/{mac}


### clients
# Connected client inventory and profiling.

unifi__clients__list_clients(site_id, vlan_id?)
  -> [{client_mac, hostname?, ip, vlan_id, ap_id?, port_id?,
       connection_type, is_wired, is_guest, uptime}]
  API: GET {local}/api/s/{site}/stat/sta

unifi__clients__get_client(client_mac, site_id)
  -> {client_mac, hostname, ip, vlan_id, ap_id, ssid?,
       rssi?, tx_bytes, rx_bytes, uptime, first_seen, last_seen,
       os_name?, device_vendor?, is_blocked}
  API: GET {local}/api/s/{site}/stat/sta/{mac}

unifi__clients__get_client_traffic(client_mac, site_id)
  -> {client_mac, tx_bytes, rx_bytes, tx_packets, rx_packets,
       dpi?: [{application, category, tx_bytes, rx_bytes}]}
  API: GET {local}/api/s/{site}/stat/user/{mac}

unifi__clients__search_clients(query, site_id?)
  -> [{client_mac, hostname, ip, vlan_id, connection_type, site_id}]
  query: any of mac, hostname, IP address, or alias (partial match)
  API: GET {local}/api/s/{site}/stat/sta (client-side filter)


### traffic
unifi__traffic__get_bandwidth(site_id, hours?=24)
  -> {wan: {rx_mbps, tx_mbps, history[]}, lan: {rx_mbps, tx_mbps}}
unifi__traffic__get_dpi_stats(site_id)
  -> [{application, category, tx_bytes, rx_bytes, session_count}]
unifi__traffic__get_port_stats(device_id)
  -> [{port_idx, name, tx_bytes, rx_bytes, tx_errors, rx_errors,
        is_uplink, poe_power_w?}]
unifi__traffic__get_wan_usage(site_id, days?=30)
  -> [{date, download_gb, upload_gb}]


### security
unifi__security__get_firewall_rules(site_id)
  -> [{rule_id, name, action, enabled, src, dst, protocol, position}]
unifi__security__get_zbf_policies(site_id)
  -> [{policy_id, from_zone, to_zone, action, match_all}]
unifi__security__get_acls(site_id)
  -> [{acl_id, name, entries[], applied_to[]}]
unifi__security__get_port_forwards(site_id)
  -> [{rule_id, name, proto, wan_port, lan_host, lan_port, enabled}]
unifi__security__get_ids_alerts(site_id, hours?=24)
  -> [{timestamp, signature, severity, src_ip, dst_ip, action_taken}]


### config
unifi__config__get_config_snapshot(site_id)
  -> {site_id, timestamp, network_count, wlan_count, rule_count,
       raw_config: {networks[], wlans[], firewall_rules[], ...}}
unifi__config__diff_baseline(site_id, baseline_id)
  -> {added[], removed[], modified[]}  # structural diff vs stored baseline
unifi__config__get_backup_state(site_id)
  -> {last_backup_time, backup_type, size_mb, cloud_enabled}
unifi__config__save_baseline(site_id)  # WRITE — requires UNIFI_WRITE_ENABLED
  -> {baseline_id, timestamp}
unifi__config__create_port_profile(name, native_vlan, tagged_vlans[],
                                    poe?)  # WRITE
  Creates a named switch port profile.
  -> {profile_id, name}
  API: POST /api/s/{site}/rest/portconf

unifi__topology__assign_port_profile(device_id, port_idx,
                                      profile_name)  # WRITE
  Assigns a named port profile to a specific switch port.
  OutageRiskAgent assesses whether port carries operator session.
  -> {device_id, port_idx, profile_applied}
  API: PUT /api/s/{site}/rest/device/{device_id}  (port_overrides)

### multisite  (Site Manager EA API only)
unifi__multisite__list_all_sites(include_health?=true)
  -> [{site_id, name, device_count, client_count, health_status}]
unifi__multisite__get_site_health(site_id)
  -> {site_id, wan_status, device_count, offline_count, alert_count}
unifi__multisite__compare_sites(site_ids[], metrics[])
  -> {site_id: {metric: value}, ...}
unifi__multisite__search_across_sites(query, resource_type?="all")
  -> [{site_id, resource_type, resource_id, match_field, match_value}]
unifi__topology__assign_port_profile(device_id, port_idx,
                                      profile_name)  # WRITE
  Assigns a named port profile to a specific switch port.
  OutageRiskAgent assesses whether port carries operator session.
  -> {device_id, port_idx, profile_applied}
  API: PUT /api/s/{site}/rest/device/{device_id}  (port_overrides)
  Use get_device first to identify port_idx from port description.

unifi__multisite__get_vantage_points(site_id)
  -> [{location, latency_ms, packet_loss_pct, jitter_ms, measured_at}]
```

### A.6 Command Definitions

```
## Commands

### unifi scan [site?]
Intent: Discover the full network topology for one or all accessible sites.
Calls: topology.list_sites → topology.list_hosts → topology.list_devices
       → topology.get_vlans → topology.get_uplinks
Behavior: If no site is specified, list all sites and ask the operator to
  select one, or run a fleet-level summary if multisite skill is available.
  Never assume which site to use when multiple exist.

### unifi health [site?] [device?]
Intent: Tiered health report — Critical / Warning / Informational.
Calls: health.get_site_health → health.get_device_health (all devices)
       → health.get_isp_metrics → health.get_firmware_status
       → health.get_events(hours=24)
Output: Summary table of findings by severity. Never bury Critical findings.

### unifi diagnose [target]
Intent: Root-cause analysis for a device (by ID/name/IP) or client (by
  MAC/hostname/IP/alias).
Calls: topology.get_device OR clients.get_client → health.get_device_health
       → health.get_events → wifi.get_client_rf (if wireless)
       → clients.get_client_traffic → security.get_firewall_rules
Output: Ranked findings with probable causes and remediation steps.

### unifi wifi [site?] [ssid?]
Intent: Analyze the wireless RF environment.
Calls: wifi.get_wlans → wifi.get_aps → wifi.get_channel_utilization (all APs)
       → wifi.get_rf_scan (all APs) → wifi.get_roaming_events
Output: Per-AP channel summary, neighboring SSID interference, roaming stats.

### unifi optimize [site?] [--apply]
Intent: Generate prioritized improvement recommendations. With --apply,
  follow the three-phase confirmation model before making any changes.
Read phase: Calls wifi, traffic, security, config skills.
Write gate: UNIFI_WRITE_ENABLED must be true and --apply must be present.
  Without these, produce the recommendation plan only (no writes).

### unifi clients [site?] [--vlan <id>] [--ap <id>]
Intent: Inventory all connected clients, optionally filtered.
Calls: clients.list_clients → clients.get_client_traffic (top-N only)

### unifi secure [site?]
Intent: Security posture audit. Read-only.
Calls: security.get_firewall_rules → security.get_zbf_policies
       → security.get_acls → security.get_port_forwards
       → security.get_ids_alerts → wifi.get_rf_scan (rogue AP detection)
Output: Risk-ranked findings with severity and remediation guidance.

### unifi compare <site1> <site2>
Intent: Side-by-side comparison of two sites.
Calls: multisite.compare_sites → multisite.get_site_health (both)
       → health.get_firmware_status (both)

### unifi config [site?] [--drift]
Intent: Review config state. With --drift, diff against stored baseline.
Calls: config.get_config_snapshot → [config.diff_baseline if --drift]
       → config.get_backup_state
Write (--save): config.save_baseline — requires UNIFI_WRITE_ENABLED.

### unifi port-profile create <n> [--native <vlan>] [--tagged <vlans>]
                               [--poe] [--apply]
Intent: Create a named switch port profile in UniFi.
Calls: topology.get_vlans (verify named VLANs exist)
       → config.create_port_profile → confirm
Example: unifi port-profile create Trunk-AP --native 10 --tagged 30,50,60

### unifi port-profile assign <switch> <port> <profile> [--apply]
Intent: Assign a named profile to a specific port on a UniFi switch.
Phase 1: topology.get_device(switch) to identify port from description/index.
         OutageRiskAgent: assess if port carries operator management session.
Phase 2: present plan showing current profile → new profile for that port.
Write: topology.assign_port_profile → confirm.
CAUTION: Never assign to the port connected to OPNsense until all VLAN
  configuration on OPNsense is complete and verified.
```

### A.7 Usage Examples

```
## Examples

# Basic: First-time scan of a single-site deployment
User: "Scan my UniFi network"
-> call unifi__topology__list_sites()
-> if one site: proceed directly
-> if multiple: AskUserQuestion "Which site would you like to scan?"
-> call list_devices, get_vlans, get_uplinks
-> present: device count by type, VLAN summary, uplink graph, offline devices

# Basic: Morning health check
User: "Quick health check"
-> call get_site_health, get_firmware_status, get_events(hours=12)
-> if no critical findings: "All clear — N devices online, no alerts."
-> if findings: present by severity, Critical first

# Advanced: Diagnose a client complaint
User: "Sarah's laptop can't reach the file server"
-> search_clients("Sarah") or ask for MAC/hostname if ambiguous
-> get_client → get_client_rf → get_client_traffic
-> get_firewall_rules (check VLAN isolation)
-> present: signal quality, VLAN membership, firewall rules affecting path

# Write: Apply optimization (with UNIFI_WRITE_ENABLED=true)
User: "Optimize the office WiFi and apply changes"
-> Phase 1: gather wifi + traffic data, resolve any ambiguities
-> Phase 2: present full recommendation plan
-> Phase 3: AskUserQuestion "3 changes planned. Confirm to proceed?"
-> on confirm: execute each write, report result
```

---

## Appendix B: opnsense SKILL.md

This is the complete SKILL.md manifest for the opnsense vendor plugin, built in Phase 2. The reconfigure pattern — where a write and a separate apply step are always distinct — is a first-class concept throughout.

### B.1 YAML Frontmatter

```yaml
---
name: opnsense
version: 0.2.0
description: >
  OPNsense gateway intelligence plugin for EmberAI. Provides interface and
  VLAN management, firewall rule analysis, static routing, VPN tunnel status
  and configuration, DNS (Unbound), DHCP (Kea), IDS/IPS (Suricata), traffic
  shaping, live diagnostics, and firmware management via the OPNsense REST API.
author: Bluminal Labs
license: MIT
repository: https://github.com/bluminal/emberai/tree/main/opnsense
docs: https://bluminal.github.io/emberai/opnsense/

# Vendor Plugin Contract fields (netex v1.0.0)
netex_vendor: opnsense
netex_role:
  - gateway
netex_skills:
  - interfaces
  - firewall
  - routing
  - vpn
  - security
  - services
  - diagnostics
  - firmware
netex_write_flag: OPNSENSE_WRITE_ENABLED
netex_contract_version: "1.0.0"
---
```

### B.2 Overview Instructions

```
# opnsense — OPNsense Gateway Intelligence Plugin

You are operating the opnsense plugin for EmberAI. This plugin provides
read and (when explicitly enabled) write access to an OPNsense firewall
and router via its local REST API.

This plugin covers the GATEWAY layer: interfaces, VLAN interfaces, routing
table, firewall rules and aliases, NAT, VPN tunnels, DNS resolver (Unbound),
DHCP server (Kea), IDS/IPS (Suricata), traffic shaping, and system diagnostics.
It does NOT manage switching, wireless SSIDs, or client WiFi associations —
those belong to the unifi plugin (edge layer).

## API Pattern
All endpoints follow: {OPNSENSE_HOST}/api/{module}/{controller}/{command}
Authentication: HTTP Basic Auth — OPNSENSE_API_KEY as username,
                                  OPNSENSE_API_SECRET as password.
GET  = read operations (safe, always permitted)
POST = write and action operations (gated by OPNSENSE_WRITE_ENABLED)

## The Reconfigure Pattern (CRITICAL)
OPNsense separates saving a configuration change from applying it to the
running system. A write (POST to add/modify a rule, interface, alias, etc.)
stores the change in the config file but does NOT activate it. A separate
POST to {module}/{controller}/reconfigure pushes the config to the live
system. This is the point of no return for any configuration change.

Always model this explicitly in write workflows:
  Step N:   POST /api/{module}/{controller}/set_item  (saves config)
  Step N+1: POST /api/{module}/{controller}/reconfigure  (applies to live)

Dry-run mode: show both steps in the plan but skip Step N+1 entirely.
Never call reconfigure without explicit operator confirmation.
```

### B.3 Authentication Instructions

```
## Authentication

Required environment variables:
  OPNSENSE_HOST       : IP or hostname of the OPNsense instance
                        (e.g., https://192.168.1.1 or https://fw.local)
  OPNSENSE_API_KEY    : API key (Basic Auth username). Created in
                        OPNsense: System > Access > Users > Edit > API keys.
  OPNSENSE_API_SECRET : API secret (Basic Auth password).

Optional:
  OPNSENSE_WRITE_ENABLED : "true" to enable write/POST operations.
                           Default: false.
  OPNSENSE_VERIFY_SSL    : "false" to skip TLS certificate verification
                           for self-signed certs. Default: true.
                           Warn the operator if set to false.

Privilege note: The API key owner must have Effective Privileges covering
the resources you intend to access. Insufficient privileges return 403.
When a 403 is received, tell the operator which resource requires access
and where to grant it (System > Access > Users > Effective Privileges).
```

### B.4 Interaction Model

```
## Interaction Model

Same three-phase plan-level confirmation model as the unifi plugin.
Additional OPNsense-specific rules:

1. Always include the reconfigure step explicitly in any write plan.
   Label it clearly: "Step N: Apply config to live system (reconfigure)."
   This step is never implied — the operator must see it and confirm.

2. Before any firewall rule change, check the current rule list and show
   where the new rule will be inserted in the rule order. Rule position
   affects effective policy — never add a rule without stating its position.

3. Interface and VLAN changes carry the highest outage risk of any
   OPNsense operation. If the operator's session traverses the interface
   being modified, classify as CRITICAL risk and require out-of-band
   confirmation before showing the plan.

4. For Suricata (IDS/IPS), any rule or policy change that triggers a
   service restart may cause a brief interruption to IDS inspection.
   State this explicitly in the plan.

OPNSENSE_WRITE_ENABLED must be "true" AND the operator must have confirmed
the full plan before any POST call is made.
```

### B.5 Skill Groups and Tool Signatures

```
### interfaces skill
opnsense__interfaces__list_interfaces()
  -> [{name, description, ip, subnet, type, enabled, vlan_id?}]
  API: GET /api/interfaces/overview/export

opnsense__interfaces__list_vlan_interfaces()
  -> [{uuid, tag, if, description, parent_if, pcp?}]
  API: GET /api/interfaces/vlan/searchItem

opnsense__interfaces__configure_vlan(tag, parent_if, ip, subnet,
                                     dhcp_range_from?, dhcp_range_to?,
                                     description?)  # WRITE — atomic
  Combines: add VLAN interface + assign + static IP + DHCP scope in one
  confirmed workflow with a single reconfigure at the end.
  -> {vlan_uuid, interface_name, dhcp_uuid?}
  Use this instead of add_vlan_interface for all new workflows.

opnsense__interfaces__add_vlan_interface(tag, parent_if, description)  # WRITE
  -> {uuid}  then reconfigure: POST /api/interfaces/vlan/reconfigure
  Note: Retained for cases where only the VLAN definition is needed.

opnsense__interfaces__add_dhcp_reservation(interface, mac, ip,
                                            hostname?)  # WRITE
  -> {uuid}  then reconfigure: POST /api/kea/ctrl_agent/restart
  API: POST /api/kea/dhcpv4/addReservation

opnsense__interfaces__get_dhcp_leases(interface?)
  -> [{mac, ip, hostname, expiry, state, interface}]
  API: GET /api/kea/leases4/search

opnsense__interfaces__add_dhcp_subnet(interface, subnet, range_from,
                                       range_to, dns_servers[])  # WRITE
  -> {uuid}  then reconfigure: POST /api/kea/ctrl_agent/restart


### firewall skill
opnsense__firewall__list_rules(interface?)
  -> [{uuid, description, action, enabled, direction, protocol,
        source, destination, log, position}]
  API: GET /api/firewall/filter/searchRule

opnsense__firewall__get_rule(uuid)
  -> full rule object including all fields and metadata

opnsense__firewall__list_aliases()
  -> [{uuid, name, type, description, content}]
  API: GET /api/firewall/alias/searchItem

opnsense__firewall__list_nat_rules()
  -> [{uuid, description, interface, protocol, src, dst,
        target, target_port, enabled}]
  API: GET /api/firewall/s_nat/searchRule

opnsense__firewall__add_rule(interface, action, src, dst, protocol,
                              description, position?)  # WRITE
  -> {uuid}  then reconfigure: POST /api/firewall/filter/apply

opnsense__firewall__toggle_rule(uuid, enabled)  # WRITE
  -> {changed}  then reconfigure: POST /api/firewall/filter/apply

opnsense__firewall__add_alias(name, type, content[], description?)  # WRITE
  type: host | network | port | url
  content: list of values (CIDRs, IPs, port ranges, URLs)
  -> {uuid}  then reconfigure: POST /api/firewall/alias/reconfigure
  API: POST /api/firewall/alias/addItem
  Required before any rule that references a named alias.

### routing skill
opnsense__routing__list_routes()
  -> [{uuid, network, gateway, description, disabled}]
  API: GET /api/routes/routes/searchRoute

opnsense__routing__list_gateways()
  -> [{name, interface, gateway, monitor, status, priority, rtt_ms?}]
  API: GET /api/routes/gateway/status

opnsense__routing__add_route(network, gateway, description)  # WRITE
  -> {uuid}  then reconfigure: POST /api/routes/routes/reconfigure


### vpn skill
opnsense__vpn__list_ipsec_sessions()
  -> [{id, description, status, local_ts, remote_ts,
        rx_bytes, tx_bytes, established_at?}]
  API: GET /api/ipsec/sessions/search

opnsense__vpn__list_openvpn_instances()
  -> [{uuid, description, role, dev_type, protocol, port,
        enabled, connected_clients?}]
  API: GET /api/openvpn/instances/search

opnsense__vpn__list_wireguard_peers()
  -> [{uuid, name, public_key, endpoint?, allowed_ips[],
        last_handshake?, rx_bytes?, tx_bytes?}]
  API: GET /api/wireguard/client/search

opnsense__vpn__get_vpn_status()
  -> {ipsec: {up, down}, openvpn: {instances[]}, wireguard: {peers[]}}


### security skill (IDS/IPS — Suricata)
opnsense__security__get_ids_alerts(hours?=24, severity?="all")
  -> [{timestamp, signature, category, severity, src_ip,
        dst_ip, proto, action}]
  API: GET /api/ids/service/queryAlerts

opnsense__security__get_ids_rules(filter?)
  -> [{sid, msg, category, enabled, action}]
  API: GET /api/ids/rule/searchRule

opnsense__security__get_ids_policy()
  -> {enabled, interfaces[], block_mode, alert_only_mode,
       ruleset_count, last_update}
  API: GET /api/ids/settings/getSettings

opnsense__security__get_certificates()
  -> [{cn, san[], issuer, not_before, not_after, days_until_expiry,
        in_use_for[]}]
  API: GET /api/trust/cert/search


### services skill
opnsense__services__get_dns_overrides()
  -> [{uuid, hostname, domain, ip, description}]
  API: GET /api/unbound/host/searchHost

opnsense__services__get_dns_forwarders()
  -> [{uuid, server, port, domain?, dot_enabled}]
  API: GET /api/unbound/forward/searchForward

opnsense__services__resolve_hostname(hostname)
  -> {hostname, ip, ttl, source}
  API: GET /api/unbound/diagnostics/lookup/{hostname}

opnsense__services__add_dns_override(hostname, domain, ip,
                                      description?)  # WRITE
  -> {uuid}  then reconfigure: POST /api/unbound/service/reconfigure

opnsense__services__get_dhcp_leases4(interface?)
  -> [{mac, ip, hostname, expiry, state}]
  API: GET /api/kea/leases4/search

opnsense__services__get_traffic_shaper()
  -> {pipes: [{uuid, bandwidth, burst, delay, description}],
       queues: [{uuid, pipe, weight, mask, description}]}
  API: GET /api/trafficshaper/settings/getSettings


### diagnostics skill
opnsense__diagnostics__run_ping(host, count?=5, source_ip?)
  -> {host, packets_sent, packets_recv, loss_pct, rtt_avg_ms, output}
  API: POST /api/diagnostics/interface/getPing

opnsense__diagnostics__run_traceroute(host, max_hops?=30)
  -> {host, hops: [{hop, ip, hostname?, rtt_ms}]}
  API: POST /api/diagnostics/interface/getTrace

opnsense__diagnostics__run_host_discovery(interface)
  -> [{ip, mac, hostname?, last_seen}]
  API: POST /api/hostdiscovery/scan/start + GET .../result
  Note: Discovery scan runs asynchronously. Poll for results.

opnsense__diagnostics__get_lldp_neighbors(interface?)
  -> [{local_port, neighbor_system, neighbor_port, neighbor_ip?,
        neighbor_capabilities, ttl}]
  API: GET /api/diagnostics/interface/getLldpNeighbors
  Returns LLDP neighbor table — what device is connected to each port.
  Essential for physical topology verification and port assignment workflows.
  Read-only.

opnsense__diagnostics__dns_lookup(hostname, record_type?="A")
  -> [{name, type, value, ttl}]
  API: GET /api/diagnostics/dns/reverseResolve


### firmware skill
opnsense__firmware__get_status()
  -> {current_version, latest_version, upgrade_available,
       last_check, changelog_url?}
  API: GET /api/core/firmware/status

opnsense__firmware__list_packages()
  -> [{name, version, latest_version, needs_update, description}]
  API: GET /api/core/firmware/info
```

### B.6 Command Definitions

```
## Commands

### opnsense scan
Intent: Full inventory of the OPNsense instance. Entry point for new deployments.
Calls: interfaces.list_interfaces → interfaces.list_vlan_interfaces
       → routing.list_routes → routing.list_gateways
       → vpn.get_vpn_status → firmware.get_status
Output: Interface summary, VLAN count, active routes, VPN tunnel count,
  firmware status. Flag any interfaces that are down or gateways with loss.

### opnsense health
Calls: routing.list_gateways (latency/loss) → security.get_ids_alerts(hours=24)
       → firmware.get_status → diagnostics.run_ping(8.8.8.8) [WAN reachability]
       → security.get_certificates [flag certs expiring within 30 days]

### opnsense diagnose [interface?|host?]
For host: diagnostics.run_ping → run_traceroute → dns_lookup
          → firewall.list_rules (check traversal path)
For interface: interfaces.list_interfaces → routing.list_gateways
               → run_host_discovery → get_dhcp_leases4

### opnsense firewall [--audit]
Base: firewall.list_rules → list_aliases → list_nat_rules
--audit adds: shadow analysis (compare rules in order for redundancy/conflict),
  overly-broad rule detection (any/any src or dst), disabled rule count.

### opnsense firewall policy-from-matrix --matrix <file> [--audit] [--apply]
Accepts an inter-VLAN access matrix (source, destination, allow|block).
--audit: compare existing rules to the matrix; surface gaps and violations.
--apply: derive the minimum correct ruleset — creates needed aliases first,
  adds rules in correct order, single reconfigure at the end.
Matrix format: YAML or CSV. Source/destination accept VLAN IDs, names, or
  special values (inet, *, self).
The NSA reviews the derived ruleset before plan presentation.

### opnsense vlan [--configure] [--audit]
Base: interfaces.list_vlan_interfaces → interfaces.list_interfaces
--configure: Three-phase write flow using configure_vlan (atomic):
  single step creates VLAN interface + static IP + DHCP scope.
  Understands intentional range offsets within larger subnets (e.g.
  Homelab /21 with DHCP starting at .1.100 — not a misconfiguration).
--audit: Check each VLAN has a corresponding DHCP scope; flag orphans.

### opnsense dhcp reserve-batch <interface> --devices <spec> [--apply]
Create multiple static DHCP reservations in one confirmed workflow.
Device spec: inline or file, one entry per line: hostname:mac:ip
Single reconfigure at the end covers all reservations.
Calls: get_dhcp_leases (verify MACs known) → add_dhcp_reservation (×N)
       → reconfigure.

### opnsense vpn [--tunnel <n>]
Calls: vpn.list_ipsec_sessions → list_openvpn_instances
       → list_wireguard_peers
Filter to named tunnel if --tunnel is specified.
Flag: sessions not established, handshakes older than 3 minutes (WireGuard),
  near-expiry certificates used by VPN.

### opnsense dns [hostname?]
Calls: services.get_dns_overrides → get_dns_forwarders
       → [resolve_hostname(hostname) if hostname specified]
Flag: resolvers without DNS-over-TLS, open recursion enabled.

### opnsense secure
Calls: firewall.list_rules (shadow analysis) → security.get_ids_policy
       → security.get_ids_alerts(hours=72) → security.get_certificates
       → firewall.list_nat_rules (exposure review)
Flag: IDS disabled, rulesets not updated in >7 days, certs expiring in <60 days,
  NAT rules exposing management ports.

### opnsense firmware
Calls: firmware.get_status → firmware.list_packages
Flag: available upgrades, packages with pending updates.
Write (--update): Three-phase confirmation. Never trigger reboot automatically.
  Always state: "This will restart the firewall. Confirm you have console access."
```

---

## Appendix C: netex SKILL.md

This is the complete SKILL.md manifest for the netex umbrella plugin, built in Phase 3. Unlike the vendor plugins, netex does not declare `netex_vendor` or `netex_role` — it is the orchestrator. It discovers installed vendor plugins at startup via the Plugin Registry.

### C.1 YAML Frontmatter

```yaml
---
name: netex
version: 0.3.0
description: >
  Cross-vendor network orchestration umbrella for EmberAI. Coordinates
  installed vendor plugins (unifi, opnsense, and future vendors) to perform
  operations that span multiple network systems. Provides unified topology,
  health, VLAN provisioning, cross-vendor security audits, and policy
  synchronization. Requires at least one conforming vendor plugin.
author: Bluminal Labs
license: MIT
repository: https://github.com/bluminal/emberai/tree/main/netex
docs: https://bluminal.github.io/emberai/netex/

# netex is the orchestrator — it enforces the contract but is not a vendor plugin.
# It does not declare netex_vendor, netex_role, or netex_skills.
# It discovers and orchestrates any plugin that conforms to the contract below.
netex_contract_version: "1.0.0"
---
```

### C.2 Overview and Plugin Discovery

```
# netex — Cross-Vendor Network Orchestration Umbrella

You are operating the netex umbrella plugin for EmberAI. Your role is to
orchestrate operations that require coordinating two or more vendor plugins.

## Plugin Discovery
On startup, query the Plugin Registry to discover installed vendor plugins:
  registry.list_plugins()  -> [{name, vendor, roles[], skills[], write_flag}]

Use this registry — not hardcoded vendor names — for all routing decisions.
Example queries:
  registry.plugins_with_role("gateway")   -> plugins that manage routing/firewall
  registry.plugins_with_role("edge")      -> plugins that manage switching/ports
  registry.plugins_with_skill("firewall") -> all plugins with firewall audit tools
  registry.tools_for_skill("topology")    -> all topology tools across all plugins

When a required plugin is not installed, tell the operator clearly which
plugin is missing and what capability it provides. Do not silently degrade.

## Scope
netex handles CROSS-VENDOR operations only. If an operator asks something
that a single vendor plugin can answer alone (e.g., "show my UniFi clients"),
route it to that plugin directly rather than running it through the umbrella.
Reserve netex commands for operations that genuinely require data or actions
across two or more vendor plugins.
```

### C.3 Human-in-the-Loop Interaction Model

```
## Interaction Model

netex is an ASSISTANT, not an autonomous agent. This principle is more
critical here than in any individual vendor plugin: a cross-vendor operation
can touch the gateway AND the edge in the same workflow, compounding the
blast radius of any mistake.

All write workflows follow the three-phase model:

PHASE 1 — Resolve assumptions
  Gather state from all relevant vendor plugins using read-only tools.
  Identify genuine ambiguities (values not determinable from the API).
  Run the OutageRiskAgent and NetworkSecurityAgent in parallel.
  Batch all questions into a single AskUserQuestion call. Include the
  implication of each answer: "If X, the plan will do A; if Y, it will do B."

PHASE 2 — Present the complete cross-vendor plan
  Structure the plan as follows (in this order):
    [OUTAGE RISK]   OutageRiskAgent finding — risk tier + specific path at risk
    [SECURITY]      NetworkSecurityAgent findings — severity-ranked
    [CHANGE PLAN]   Numbered steps: step #, system (plugin name), API call,
                    what changes, expected outcome
    [ROLLBACK]      How completed steps will be reversed if a later step fails
  This phase has no AskUserQuestion.

PHASE 3 — Single confirmation
  One AskUserQuestion: "N steps across [plugin names]. Confirm to proceed,
  or describe a change you'd like to make to the plan."
  On confirm: execute steps in order. On failure: stop, report, ask about rollback.

CRITICAL RISK override: if OutageRiskAgent returns CRITICAL, require the
operator to explicitly state they have out-of-band access before showing
the plan. A generic "yes" is not sufficient — ask for the specific access
method (serial console, IPMI, physical access, management VLAN).
```

### C.4 OutageRiskAgent

```
## OutageRiskAgent

The OutageRiskAgent is a read-only sub-agent that runs before every write
plan. It determines whether the proposed changes could sever the operator's
access to the network.

Assessment steps:
1. Determine the operator's session source IP (from connection context or
   ask if not determinable).
2. Call registry.tools_for_skill("diagnostics") to find reachable
   diagnostic tools across installed plugins.
3. Use opnsense__diagnostics__run_traceroute (if available) to map the
   path from source IP to the OPNsense management interface.
4. Use unifi__topology__get_device and get_vlans to identify the switch port
   and VLAN carrying the operator's session (if unifi is installed).
5. Check whether any step in the change plan modifies:
   - The interface, VLAN, or route the operator's session traverses
   - A firewall rule that permits the operator's session
   - The DHCP scope serving the operator's IP

Risk tier output:
  CRITICAL : Change directly modifies the operator's session path.
             Require explicit out-of-band confirmation.
  HIGH     : Change is in the same subsystem; disruption is possible.
             State what could be affected; confirm once.
  MEDIUM   : Change could cause indirect disruption (DNS, DHCP, routing).
             Include as callout in plan; single standard confirmation.
  LOW      : Change does not intersect the operator's session path.
             Standard plan confirmation only.

If the session path cannot be determined (no diagnostic tools available,
source IP unknown), default to HIGH and state the reason.
```

### C.5 NetworkSecurityAgent

```
## NetworkSecurityAgent

The NetworkSecurityAgent is a read-only sub-agent that runs before every
write plan (automatic) and on demand via netex secure audit (manual).
It never makes changes. It never calls any POST endpoint.

### Automatic plan review
For every change plan, assess the following before Phase 2:

1. VLAN isolation gap: new VLANs without corresponding firewall deny rules?
2. Overly broad rule: any/any source or destination in proposed rules?
3. Rule ordering risk: does the new rule shadow existing denies, or get
   shadowed by existing allows?
4. VPN split-tunnel mismatch: tunnel scope wider or narrower than stated?
5. Unencrypted VLAN for sensitive use: IoT/cameras/management on open auth?
6. Management plane exposure: OPNsense UI or UniFi controller reachable from
   untrusted segment after the change?
7. DNS security weakened: forwarder without DoT, DNSSEC disabled?

Output format per finding:
  Severity: CRITICAL | HIGH | MEDIUM | LOW
  Issue: one sentence description
  Why it matters here: specific to this plan, not generic
  Alternative: concrete option achieving the same goal more securely

If no findings: output exactly "Security review: no issues identified."
Do not omit the security review section from the plan — its presence
confirms to the operator that the review was performed.

### On-demand audit (netex secure audit)
Query all installed plugins for their security-relevant data using
registry.tools_for_skill("security") and registry.tools_for_skill("config").
Audit domains: firewall policy (gateway), firewall policy (edge),
  cross-layer consistency, VLAN isolation, VPN posture, DNS security,
  IDS/IPS coverage, wireless security, certificates, firmware/patch state.
Group findings by domain and severity. Each finding includes the specific
configuration element, the security implication, and the remediation command
(never including --apply).
```

### C.6 Abstract Data Model

```
## Abstract Data Model

When working across vendor plugins, use these vendor-neutral concepts.
Each concept maps to vendor-specific data at query time via the registry.

VLAN(id, name, subnet, dhcp_enabled)
  gateway plugin  : VLAN interface + DHCP scope
  edge plugin     : Network object + switch port profiles + SSID bindings

FirewallPolicy(src_zone, dst_zone, protocol, action)
  gateway plugin  : Firewall filter rule with interface scope
  edge plugin     : ZBF zone policy or ACL rule

Route(destination, gateway, metric)
  gateway plugin  : Static route entry
  edge plugin     : Not applicable (UniFi does not manage routing)

VPNTunnel(type, peer, status, rx_bytes, tx_bytes)
  gateway plugin  : IPSec SA / OpenVPN instance / WireGuard peer
  overlay plugin  : Tailscale device peer (future)

DNSRecord(hostname, domain, ip, ttl)
  gateway plugin  : Unbound host override
  edge plugin     : Not applicable

DHCPLease(mac, ip, hostname, expiry, interface)
  gateway plugin  : Kea lease record
  edge plugin     : Client station record (IP/MAC correlation)

NetworkTopology(nodes[], links[], vlans[])
  Assembled from all installed plugins. Each plugin contributes its layer.
  gateway layer adds: interfaces, routes, VPN tunnels, firewall zones
  edge layer adds: device graph, uplink relationships, wireless APs, clients
```

### C.7 Cross-Vendor Command Definitions

```
## Commands

### netex vlan configure <n> <id> [--subnet <cidr>] [--dhcp] [--ssid <n>]
Requires plugins with roles: gateway, edge
Phase 1: query list_vlan_interfaces + get_vlans to check VLAN ID conflicts
  on both systems. Check subnet overlap. Ask if any inference is needed.
  Run OutageRiskAgent and NetworkSecurityAgent.
Phase 2 plan (in order):
  1. [gateway] add_vlan_interface(id, name)
  2. [gateway] add_dhcp_subnet(...)  (if --dhcp)
  3. [gateway] add_rule(inter-VLAN isolation deny)  (recommend always)
  4. [gateway] reconfigure
  5. [edge]    create network object (VLAN id, name, subnet)
  6. [edge]    update switch port profiles (if applicable)
  7. [edge]    bind SSID (if --ssid)
Rollback: if step 5+ fails, delete items created in steps 1–4.
  If rollback itself fails, report clearly and stop. Do not retry silently.

### netex vlan audit [--id <vlan-id>]
Requires plugins with roles: gateway, edge
Read-only. Collect VLANs from all installed gateway and edge plugins.
Find: (a) defined in gateway but missing in edge, (b) defined in edge
  but missing in gateway, (c) present in both but with mismatched subnets
  or DHCP ranges. Report findings grouped by category.

### netex topology [--site <site>]
Requires: at least one installed plugin
Call registry.tools_for_skill("topology") across all plugins.
Merge results into a unified NetworkTopology object: WAN → gateway
  interfaces → VLAN boundaries → edge device graph → APs → clients.

### netex health [--site <site>]
Requires: at least one installed plugin
Call registry.tools_for_skill("health") and "diagnostics" across all plugins.
Merge into unified report. Normalize severity tiers across vendors.
Critical and High findings always appear first regardless of plugin source.

### netex firewall audit [--vlan <id>]
Requires plugins with skill: firewall (gateway and edge if available)
Call registry.tools_for_skill("firewall") + "security".
Delegate to NetworkSecurityAgent for cross-layer consistency analysis.
Output: unified risk-ranked findings across all vendor firewall layers.

### netex dns trace <hostname> [--client <mac>]
Requires: gateway plugin with services skill + (optionally) edge clients skill
Call: services.resolve_hostname(hostname) → services.get_dns_overrides
  → services.get_dns_forwarders
If --client: clients.get_client(mac) to find VLAN, then verify DNS is
  reachable from that VLAN via firewall rules.

### netex vpn status [--tunnel <n>]
Requires: gateway plugin with vpn skill
Call: vpn.get_vpn_status [filtered if --tunnel]
If edge plugin installed: correlate VPN client IPs against clients.list_clients
  to confirm reachability through the switching layer.

### netex policy sync [--dry-run]
Requires plugins with roles: gateway, edge
Compare VLAN definitions (vlan audit), DNS search domains, firewall zone
  naming conventions, and firmware state across all installed plugins.
Without --dry-run: three-phase confirmation for any corrective changes.
With --dry-run: present all drift findings and the proposed corrections,
  but do not enter Phase 3. Operator must re-run without --dry-run to apply.

### netex secure audit [--domain <d>]
Delegates entirely to NetworkSecurityAgent.
Domains: firewall, vlan, vpn, dns, wireless, ids, certs, firmware, all
Default (no --domain): all domains assessed.

### netex secure review <plan-description>
Accepts a previously described plan and passes it to NetworkSecurityAgent
for a standalone security review. Read-only.

### netex network provision-site --manifest <file> [--dry-run] [--apply]
Requires plugins with roles: gateway, edge
Full site bootstrap from a structured YAML manifest:
  vlans[], access_policy[], wifi[], port_profiles[]
Single OutageRiskAgent pass for the entire batch.
Single NSA review — derives missing rules from access_policy automatically.
Execution order: gateway interfaces → DHCP → aliases → rules
  → edge networks → WiFi → port profiles.
Single operator confirmation. Rollback plan presented before execution.
--dry-run: full plan without executing.
See: docs/netex/workflows/advanced/site-provision.md

### netex verify-policy [--manifest <file>] [--vlan <id>]
Runs expected-allow and expected-block connectivity tests derived from
the manifest access_policy. Also verifies DHCP, DNS, and WiFi mappings.
Run immediately after provision-site to confirm network matches intent.
A failed expected-block test = firewall gap → run opnsense firewall --audit.

### netex vlan provision-batch --manifest <file> [--apply]
Requires plugins with roles: gateway, edge
Creates multiple VLANs in one confirmed workflow from a vlans[] manifest.
Single OutageRiskAgent pass for the batch.
Use when adding a VLAN scheme to an existing network without the full
provision-site workflow.


## Examples

# Provision a complete segmented home network (Ridgeline)
User: "Provision my home network from this plan" [attaches site-network.yaml]
-> Phase 1:
     Validate manifest — check all 7 VLAN IDs against both systems
     OutageRiskAgent: single batch assessment → LOW (new trunk, clean state)
     NetworkSecurityAgent: detects missing guest block-to-firewall rule,
       adds it to the derived ruleset automatically
-> Phase 2: present 38-step plan across OPNsense + UniFi with rollback
-> Phase 3: operator types CONFIRM → execute all 38 steps
-> suggest: netex verify-policy --manifest site-network.yaml

# Provision a guest WiFi VLAN end-to-end
User: "Set up a guest WiFi VLAN — ID 50, 10.50.0.0/24, bind to Guest-WiFi SSID,
       and isolate it from the rest of the network."
-> Phase 1:
     opnsense__interfaces__list_vlan_interfaces() — confirm VLAN 50 is free
     unifi__topology__get_vlans() — confirm VLAN 50 is free in UniFi
     opnsense__interfaces__list_interfaces() — identify parent interface
     OutageRiskAgent: classify risk (LOW — new VLAN, no existing path)
     NetworkSecurityAgent: note guest isolation requires deny rules
     No ambiguities → no AskUserQuestion in Phase 1
-> Phase 2: present 7-step plan with security note about isolation rules
-> Phase 3: single confirmation
-> execute in order, report each step result

# Cross-vendor security audit
User: "Run a full security audit of my network"
-> netex secure audit (no --domain = all)
-> NetworkSecurityAgent calls security + firewall + config skills
   on all installed plugins
-> Groups findings by domain and severity
-> For each finding: what, why it matters, remediation command
-> Never calls --apply on any remediation suggestion

# Identify why VLAN 30 can reach VLAN 10
User: "Traffic from my IoT VLAN (30) is somehow reaching the main LAN (10)"
-> netex firewall audit --vlan 30
-> opnsense__firewall__list_rules() filtered to VLAN 30 source
-> unifi__security__get_zbf_policies() for zones covering VLAN 30
-> NetworkSecurityAgent cross-layer analysis: find where the gap exists
-> Output: specific rule (or missing rule) allowing the traffic, on which system
```

---

*Netex Suite PRD v0.8.0 · EmberAI Marketplace · Bluminal Labs LLC · March 2026*