# Cross-Vendor Topology Map

> **Difficulty:** Basic | **Time:** 5-10 minutes | **Risk:** Read-only

## Problem Statement

You want to see the complete network topology spanning your gateway (OPNsense), switches, and access points (UniFi) in a single unified view. Vendor dashboards only show their own layer.

## Prerequisites

- Netex umbrella plugin installed
- At least one vendor plugin installed
- Both plugins recommended for full cross-vendor topology

## Workflow

### Step 1: Generate the Topology

```
"netex topology"
```

Netex queries all installed plugins:
- **Gateway layer:** `opnsense__interfaces__list_interfaces` -- physical and VLAN interfaces, WAN connections
- **Edge layer:** `unifi__topology__list_devices` -- switches, APs, uplink relationships, client counts

The results are merged into the unified `NetworkTopology` model with nodes, links, and VLANs.

### Step 2: Read the Topology

The topology is presented as a layered view:

```
## Network Topology

**Sources:** opnsense (gateway), unifi (edge)

### WAN
- WAN interface (igc0) -- ISP connection
  - IP: 203.0.113.42/24
  - Gateway: 203.0.113.1

### Gateway Layer (OPNsense)
- OPNsense Gateway
  - Interfaces: igc0 (WAN), igc1 (LAN trunk), igc2 (unused)
  - VLANs: 10 (mgmt), 20 (trusted), 30 (iot), 50 (guest)
  - VPN tunnels: wg0 (WireGuard, UP)

### Edge Layer (UniFi)
- USW-Pro-24 (Core Switch)
  - Uplink: igc1 @ 1 Gbps
  - Ports: 24 (18 used, 6 available)
  - Connected APs: 3

  - UAP-AC-Pro (Living Room)
    - Uplink: USW-Pro-24 port 1 @ 1 Gbps
    - Clients: 12 (5 on 5 GHz, 7 on 2.4 GHz)
    - SSIDs: Home-WiFi (trusted), Guest-WiFi (guest)

  - UAP-AC-Pro (Office)
    - Uplink: USW-Pro-24 port 2 @ 1 Gbps
    - Clients: 8
```

### Step 3: Drill Down

```
"Show me all clients connected to the Office AP"
"What VLANs are configured on USW-Pro-24 port 5?"
```

## Working Safely

This workflow is entirely read-only. No changes are made to the network.

## Related Workflows

- [Unified Health Check](unified-health.md)
- [VLAN Audit](vlan-audit.md)
