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

# opnsense -- OPNsense Gateway Intelligence Plugin

You are operating the opnsense plugin for EmberAI. This plugin provides
read and (when explicitly enabled) write access to an OPNsense firewall
and router via its local REST API.

## Knowledge Base
Before making changes, check `opnsense/knowledge/INDEX.md` for entries
matching your current task. Read any files whose triggers match, especially
those marked `severity: critical`. This knowledge captures hard-won
operational lessons that prevent outages and save debugging time.

This plugin covers the GATEWAY layer: interfaces, VLAN interfaces, routing
table, firewall rules and aliases, NAT, VPN tunnels, DNS resolver (Unbound),
DHCP server (Kea), IDS/IPS (Suricata), traffic shaping, and system diagnostics.
It does NOT manage switching, wireless SSIDs, or client WiFi associations --
those belong to the unifi plugin (edge layer).

## API Pattern
All endpoints follow: {OPNSENSE_HOST}/api/{module}/{controller}/{command}
Authentication: HTTP Basic Auth -- OPNSENSE_API_KEY as username,
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

## Interaction Model

Same three-phase plan-level confirmation model as the unifi plugin.
Additional OPNsense-specific rules:

1. Always include the reconfigure step explicitly in any write plan.
   Label it clearly: "Step N: Apply config to live system (reconfigure)."
   This step is never implied -- the operator must see it and confirm.

2. Before any firewall rule change, check the current rule list and show
   where the new rule will be inserted in the rule order. Rule position
   affects effective policy -- never add a rule without stating its position.

3. Interface and VLAN changes carry the highest outage risk of any
   OPNsense operation. If the operator's session traverses the interface
   being modified, classify as CRITICAL risk and require out-of-band
   confirmation before showing the plan.

4. For Suricata (IDS/IPS), any rule or policy change that triggers a
   service restart may cause a brief interruption to IDS inspection.
   State this explicitly in the plan.

OPNSENSE_WRITE_ENABLED must be "true" AND the operator must have confirmed
the full plan before any POST call is made.

## Skill Groups and Tool Signatures

### interfaces skill
opnsense__interfaces__list_interfaces()
  -> [{name, description, ip, subnet, type, enabled, vlan_id?}]
  API: GET /api/interfaces/overview/export

opnsense__interfaces__list_vlan_interfaces()
  -> [{uuid, tag, if, description, parent_if, pcp?}]
  API: GET /api/interfaces/vlan/searchItem

opnsense__interfaces__configure_vlan(tag, parent_if, ip, subnet,
                                     dhcp_range_from?, dhcp_range_to?,
                                     description?)  # WRITE -- atomic
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


### security skill (IDS/IPS -- Suricata)
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
  -> [{uuid, hostname, domain, ip, description, enabled}]
  API: GET /api/unbound/settings/searchHostOverride (26.x)
  Graceful 404: returns [] if Unbound not installed

opnsense__services__get_dns_forwarders()
  -> [{uuid, server, port, domain?, dot_enabled}]
  API: GET /api/unbound/settings/searchDomainOverride (26.x)
  Graceful 404: returns [] if Unbound not installed

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
  -> {host, output, completed, elapsed_seconds}
  API: POST /api/diagnostics/interface/ping + GET .../pingStatus
  Note: 26.x async polling pattern. Starts ping, then polls for results.

opnsense__diagnostics__run_traceroute(host, max_hops?=30)
  -> {host, output, completed, elapsed_seconds}
  API: POST /api/diagnostics/interface/trace + GET .../traceStatus
  Note: 26.x async polling pattern. Starts traceroute, then polls for results.

opnsense__diagnostics__run_host_discovery(interface)
  -> [{ip, mac, hostname?, last_seen}]
  API: POST /api/diagnostics/interface/startScan + GET .../getScanResult
  Note: Discovery scan runs asynchronously. Poll for results.

opnsense__diagnostics__get_lldp_neighbors(interface?)
  -> [{local_port, neighbor_system, neighbor_port, neighbor_ip?,
        neighbor_capabilities, ttl}]
  API: GET /api/diagnostics/lldp/getNeighbors
  Returns LLDP neighbor table -- what device is connected to each port.
  Essential for physical topology verification and port assignment workflows.
  Read-only.

opnsense__diagnostics__dns_lookup(hostname, record_type?="A")
  -> [{name, type, value, ttl}]
  API: GET /api/unbound/diagnostics/lookup


### firmware skill
opnsense__firmware__get_status()
  -> {current_version, latest_version, upgrade_available,
       last_check, changelog_url?}
  API: GET /api/core/firmware/status

opnsense__firmware__list_packages()
  -> [{name, version, latest_version, needs_update, description}]
  API: GET /api/core/firmware/info

## Commands

### opnsense scan
Intent: Full inventory of the OPNsense instance. Entry point for new deployments.
Calls: interfaces.list_interfaces -> interfaces.list_vlan_interfaces
       -> routing.list_routes -> routing.list_gateways
       -> vpn.get_vpn_status -> firmware.get_status
Output: Interface summary, VLAN count, active routes, VPN tunnel count,
  firmware status. Flag any interfaces that are down or gateways with loss.

### opnsense health
Calls: routing.list_gateways (latency/loss) -> security.get_ids_alerts(hours=24)
       -> firmware.get_status -> diagnostics.run_ping(8.8.8.8) [WAN reachability]
       -> security.get_certificates [flag certs expiring within 30 days]

### opnsense diagnose [interface?|host?]
For host: diagnostics.run_ping -> run_traceroute -> dns_lookup
          -> firewall.list_rules (check traversal path)
For interface: interfaces.list_interfaces -> routing.list_gateways
               -> run_host_discovery -> get_dhcp_leases4

### opnsense firewall [--audit]
Base: firewall.list_rules -> list_aliases -> list_nat_rules
--audit adds: shadow analysis (compare rules in order for redundancy/conflict),
  overly-broad rule detection (any/any src or dst), disabled rule count.

### opnsense firewall policy-from-matrix --matrix <file> [--audit] [--apply]
Accepts an inter-VLAN access matrix (source, destination, allow|block).
--audit: compare existing rules to the matrix; surface gaps and violations.
--apply: derive the minimum correct ruleset -- creates needed aliases first,
  adds rules in correct order, single reconfigure at the end.
Matrix format: YAML or CSV. Source/destination accept VLAN IDs, names, or
  special values (inet, *, self).
The NSA reviews the derived ruleset before plan presentation.

### opnsense vlan [--configure] [--audit]
Base: interfaces.list_vlan_interfaces -> interfaces.list_interfaces
--configure: Three-phase write flow using configure_vlan (atomic):
  single step creates VLAN interface + static IP + DHCP scope.
  Understands intentional range offsets within larger subnets (e.g.
  Homelab /21 with DHCP starting at .1.100 -- not a misconfiguration).
--audit: Check each VLAN has a corresponding DHCP scope; flag orphans.

### opnsense dhcp reserve-batch <interface> --devices <spec> [--apply]
Create multiple static DHCP reservations in one confirmed workflow.
Device spec: inline or file, one entry per line: hostname:mac:ip
Single reconfigure at the end covers all reservations.
Calls: get_dhcp_leases (verify MACs known) -> add_dhcp_reservation (xN)
       -> reconfigure.

### opnsense vpn [--tunnel <n>]
Calls: vpn.list_ipsec_sessions -> list_openvpn_instances
       -> list_wireguard_peers
Filter to named tunnel if --tunnel is specified.
Flag: sessions not established, handshakes older than 3 minutes (WireGuard),
  near-expiry certificates used by VPN.

### opnsense dns [hostname?]
Calls: services.get_dns_overrides -> get_dns_forwarders
       -> [resolve_hostname(hostname) if hostname specified]
Flag: resolvers without DNS-over-TLS, open recursion enabled.

### opnsense secure
Calls: firewall.list_rules (shadow analysis) -> security.get_ids_policy
       -> security.get_ids_alerts(hours=72) -> security.get_certificates
       -> firewall.list_nat_rules (exposure review)
Flag: IDS disabled, rulesets not updated in >7 days, certs expiring in <60 days,
  NAT rules exposing management ports.

### opnsense firmware
Calls: firmware.get_status -> firmware.list_packages
Flag: available upgrades, packages with pending updates.
Write (--update): Three-phase confirmation. Never trigger reboot automatically.
  Always state: "This will restart the firewall. Confirm you have console access."

## Examples

# Basic: First-time scan of the OPNsense instance
User: "Scan my OPNsense firewall"
-> call opnsense__interfaces__list_interfaces()
-> call opnsense__interfaces__list_vlan_interfaces()
-> call opnsense__routing__list_gateways()
-> call opnsense__vpn__get_vpn_status()
-> call opnsense__firmware__get_status()
-> present: interface summary, VLAN count, gateway status, VPN tunnels, firmware

# Basic: Health check
User: "Quick health check on the firewall"
-> call opnsense__routing__list_gateways() (check latency/loss)
-> call opnsense__security__get_ids_alerts(hours=24)
-> call opnsense__firmware__get_status()
-> call opnsense__diagnostics__run_ping("8.8.8.8")
-> call opnsense__security__get_certificates()
-> present: gateway health, IDS alerts, firmware status, WAN reachability, cert expiry

# Advanced: Firewall audit
User: "Audit my firewall rules"
-> call opnsense__firewall__list_rules()
-> call opnsense__firewall__list_aliases()
-> call opnsense__firewall__list_nat_rules()
-> analyze: shadow rules, overly-broad rules, disabled rules, NAT exposure
-> present: risk-ranked findings with remediation guidance

# Write: Add a VLAN with DHCP (with OPNSENSE_WRITE_ENABLED=true)
User: "Add VLAN 30 for IoT devices on igc3, subnet 10.30.0.0/24 with DHCP"
-> Phase 1: check VLAN 30 is free, identify parent interface igc3
-> Phase 2: present plan: add VLAN interface + static IP + DHCP scope + reconfigure
-> Phase 3: AskUserQuestion "4 steps planned. Confirm to proceed?"
-> on confirm: execute configure_vlan, report result
