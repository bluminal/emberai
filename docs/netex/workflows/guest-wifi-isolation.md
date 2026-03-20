# Guest WiFi Isolation

> **Difficulty:** Advanced | **Time:** 15-25 minutes | **Risk:** Write operation

## Problem Statement

You need to set up a guest WiFi network that provides internet access but is completely isolated from your trusted network, management plane, and other internal VLANs. This is one of the most common network segmentation tasks.

## Prerequisites

- Netex umbrella plugin installed with `NETEX_WRITE_ENABLED=true`
- OPNsense and UniFi plugins installed and authenticated
- Write enabled on both vendor plugins
- Out-of-band access available

## Workflow

### Step 1: Describe the Intent

```
"Set up a guest WiFi VLAN -- ID 50, 10.50.0.0/24, bind to Guest-WiFi SSID,
and isolate it from the rest of the network."
```

### Step 2: Phase 1 -- Resolve

Netex automatically:
1. Calls `opnsense__interfaces__list_vlan_interfaces` -- confirms VLAN 50 is free
2. Calls `unifi__topology__get_vlans` -- confirms VLAN 50 is free on UniFi
3. Identifies the parent interface on OPNsense
4. OutageRiskAgent: LOW risk (new VLAN, no existing path)
5. NetworkSecurityAgent: notes that guest isolation requires deny rules

### Step 3: Phase 2 -- Review the Plan

Netex presents a 7-step plan:

```
## Change Plan

### [OUTAGE RISK]
**LOW** -- New VLAN on clean trunk, no intersection with session path.

### [SECURITY]
- [!] Guest VLAN requires explicit deny rules to prevent access to
  management and trusted VLANs.

### [CHANGE PLAN]
1. [gateway] Create VLAN interface guest (ID 50)
   Subnet: 10.50.0.0/24, Gateway: 10.50.0.1, Parent: igc1
2. [gateway] Configure DHCP for guest
   Range: 10.50.0.100-10.50.0.254
3. [gateway] Create firewall alias for guest_net
   Type: network, Value: 10.50.0.0/24
4. [gateway] Block guest -> trusted (any)
   Deny all traffic from guest to trusted VLAN
5. [gateway] Block guest -> management (any)
   Deny all traffic from guest to management VLAN
6. [gateway] Allow guest -> WAN (tcp/80,443)
   Allow web browsing only
7. [edge] Create network Guest (VLAN 50)
   Subnet: 10.50.0.0/24, Purpose: guest

### [ROLLBACK]
If execution fails:
1. Remove network 'Guest' from edge
2. Remove allow rule guest -> WAN
3. Remove block rule guest -> management
4. Remove block rule guest -> trusted
5. Remove alias 'guest_net'
6. Remove DHCP scope for 'guest'
7. Remove VLAN interface 'guest' from gateway
```

### Step 4: Confirm and Execute

```
"Looks good, apply it"
```

All 7 steps execute in order. Each step reports success/failure.

### Step 5: Create the WiFi SSID

```
"Create a WiFi SSID called Guest-WiFi, bound to the guest VLAN,
WPA2/WPA3 security, broadcast on both bands"
```

This creates the SSID on the UniFi controller with VLAN 50 binding.

### Step 6: Verify Isolation

```
"netex verify-policy --vlan 50"
```

The verification checks:
- VLAN 50 exists on both gateway and edge
- DHCP is active
- Deny rules are in place (guest cannot reach trusted/mgmt)
- Allow rule permits web traffic
- WiFi SSID is bound to the correct VLAN

## Working Safely

This workflow creates VLAN interfaces, DHCP scopes, and firewall rules. The key safety concern is the firewall rule ordering -- deny rules must be positioned correctly.

The OutageRiskAgent rates this as LOW risk because:
- New VLAN on a clean trunk
- No modification to existing interfaces or routes
- Your management session is not affected

> **Required safety notice:** Network changes can result in outages that disconnect you from your ability to correct them. Never make changes to a network you cannot reach through an out-of-band path (serial console, IPMI/iDRAC, a separate management VLAN on a different physical interface, or physical access). Netex will assess this risk for you, but it cannot guarantee your recovery path -- only you can verify that.

## Related Workflows

- [Neffroad Provisioning](neffroad-provision.md)
- [Cross-VLAN Troubleshooting](cross-vlan-troubleshooting.md)
- [VLAN Audit](vlan-audit.md)
