# Provisioning the Ridgeline Network

> **Difficulty:** Advanced | **Time:** 30-60 minutes | **Risk:** Write operation (full site provisioning)

## Problem Statement

You are building a complete segmented home network from scratch. The Ridgeline network is a 7-VLAN home deployment serving as the reference implementation for `netex network provision-site`. This workflow provisions the entire network from a single YAML manifest.

## Prerequisites

- Netex umbrella plugin installed with `NETEX_WRITE_ENABLED=true`
- OPNsense plugin installed with `OPNSENSE_WRITE_ENABLED=true`
- UniFi plugin installed with `UNIFI_WRITE_ENABLED=true`
- OPNsense gateway reachable and authenticated
- UniFi controller reachable and authenticated
- **Out-of-band access** available (serial console, IPMI, or physical access)

## The Ridgeline Manifest

```yaml
name: Ridgeline
description: 7-VLAN segmented home network

vlans:
  - vlan_id: 10
    name: management
    subnet: 10.10.0.0/24
    gateway: 10.10.0.1
    dhcp_enabled: true
    dhcp_range_start: 10.10.0.100
    dhcp_range_end: 10.10.0.254
    purpose: mgmt
    parent_interface: igc1

  - vlan_id: 20
    name: trusted
    subnet: 10.20.0.0/24
    gateway: 10.20.0.1
    dhcp_enabled: true
    dhcp_range_start: 10.20.0.100
    dhcp_range_end: 10.20.0.254
    purpose: general

  - vlan_id: 30
    name: iot
    subnet: 10.30.0.0/24
    gateway: 10.30.0.1
    dhcp_enabled: true
    dhcp_range_start: 10.30.0.100
    dhcp_range_end: 10.30.0.254
    purpose: iot

  - vlan_id: 40
    name: cameras
    subnet: 10.40.0.0/24
    gateway: 10.40.0.1
    dhcp_enabled: true
    dhcp_range_start: 10.40.0.100
    dhcp_range_end: 10.40.0.200
    purpose: cameras

  - vlan_id: 50
    name: guest
    subnet: 10.50.0.0/24
    gateway: 10.50.0.1
    dhcp_enabled: true
    dhcp_range_start: 10.50.0.100
    dhcp_range_end: 10.50.0.254
    purpose: guest

  - vlan_id: 60
    name: lab
    subnet: 10.60.0.0/24
    gateway: 10.60.0.1
    dhcp_enabled: true
    dhcp_range_start: 10.60.0.100
    dhcp_range_end: 10.60.0.254
    purpose: general

  - vlan_id: 99
    name: quarantine
    subnet: 10.99.0.0/24
    gateway: 10.99.0.1
    dhcp_enabled: true
    dhcp_range_start: 10.99.0.100
    dhcp_range_end: 10.99.0.254
    purpose: quarantine

access_policy:
  # Trusted can reach everything except quarantine
  - source: trusted
    destination: wan
    action: allow
    description: Trusted internet access
  - source: trusted
    destination: management
    action: allow
    description: Trusted can manage network
  - source: trusted
    destination: iot
    action: allow
    description: Trusted can control IoT devices
  - source: trusted
    destination: cameras
    action: allow
    description: Trusted can view cameras

  # Guest -- internet only
  - source: guest
    destination: wan
    action: allow
    protocol: tcp
    port: "80,443"
    description: Guest web browsing only
  - source: guest
    destination: trusted
    action: block
    description: Isolate guest from trusted
  - source: guest
    destination: management
    action: block
    description: Isolate guest from management

  # IoT -- restricted
  - source: iot
    destination: wan
    action: allow
    description: IoT cloud access
  - source: iot
    destination: trusted
    action: block
    description: IoT cannot reach trusted

  # Cameras -- no internet
  - source: cameras
    destination: wan
    action: block
    description: Cameras isolated from internet
  - source: cameras
    destination: trusted
    action: block
    description: Cameras cannot reach trusted

  # Quarantine -- nothing
  - source: quarantine
    destination: wan
    action: block
    description: Quarantine fully isolated
  - source: quarantine
    destination: trusted
    action: block
    description: Quarantine fully isolated

wifi:
  - ssid: Ridgeline-WiFi
    vlan_name: trusted
    security: wpa3
  - ssid: Ridgeline-Guest
    vlan_name: guest
    security: wpa2-wpa3
  - ssid: Ridgeline-IoT
    vlan_name: iot
    security: wpa2
    band: "2.4"
    hidden: true

port_profiles:
  - name: Trunk-All
    tagged_vlans: [management, trusted, iot, cameras, guest, lab, quarantine]
    poe_enabled: true
  - name: Access-Trusted
    native_vlan: trusted
    poe_enabled: true
  - name: Access-IoT
    native_vlan: iot
    poe_enabled: true
  - name: Access-Camera
    native_vlan: cameras
    poe_enabled: true
```

## Workflow

### Step 1: Provision the Site

```
"Provision my home network from this manifest"
```

Attach the YAML file or paste its contents. Netex executes three phases:

**Phase 1 -- Resolve and Assess:**
- Validates the manifest (7 VLANs, 14 policy rules, 3 SSIDs, 4 profiles)
- Checks all 7 VLAN IDs against both systems (gateway + edge)
- OutageRiskAgent: single batch assessment -- LOW (new trunk, clean state)
- NetworkSecurityAgent: checks for isolation gaps, detects any missing deny rules

**Phase 2 -- Present Plan:**
- ~38-step execution plan across OPNsense and UniFi
- Execution order: gateway interfaces, DHCP, aliases, rules, edge networks, WiFi, profiles
- Rollback plan for every step

**Phase 3 -- Execute:**
- Operator types CONFIRM
- Each step executes in dependency order
- Progress reported after each step

### Step 2: Verify the Deployment

```
"netex verify-policy --manifest site-network.yaml"
```

Runs the full test suite:
- All 7 VLANs exist on both gateway and edge
- DHCP is active on all 7 VLANs
- All 14 access policy rules are enforced (allow and block paths)
- All 3 WiFi SSIDs are bound to the correct VLANs
- All 4 port profiles are created

### Step 3: Run a Security Audit

```
"netex secure audit"
```

The NetworkSecurityAgent performs a full 10-domain security audit of the newly provisioned network.

## Working Safely

This is a **full site provisioning** operation. It creates interfaces, DHCP scopes, firewall rules, networks, WiFi SSIDs, and port profiles across two systems.

**Before executing:**
1. Ensure you have out-of-band access (serial console, IPMI, or physical access to OPNsense)
2. The OutageRiskAgent will assess risk -- for a clean-state deployment, risk is LOW
3. Review the full plan before confirming
4. The rollback plan is presented before execution

> **Required safety notice:** Network changes can result in outages that disconnect you from your ability to correct them. Never make changes to a network you cannot reach through an out-of-band path (serial console, IPMI/iDRAC, a separate management VLAN on a different physical interface, or physical access). Netex will assess this risk for you, but it cannot guarantee your recovery path -- only you can verify that.

## Related Workflows

- [Guest WiFi Isolation](guest-wifi-isolation.md)
- [Cross-VLAN Troubleshooting](cross-vlan-troubleshooting.md)
- [Post-Change Policy Sync](post-change-policy-sync.md)
