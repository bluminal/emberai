# Adding a WireGuard Peer

> **Difficulty:** Advanced | **Time:** 10-20 minutes | **Risk:** Write operation

## Problem Statement

You need to add a new WireGuard peer to an existing WireGuard VPN server on OPNsense. This involves creating the peer configuration, assigning an IP from the tunnel subnet, configuring allowed IPs, and adding a firewall rule to permit tunnel traffic.

## Prerequisites

- OPNsense plugin installed with `OPNSENSE_WRITE_ENABLED=true`
- An existing WireGuard server instance configured on OPNsense
- The new peer's public key
- Knowledge of the tunnel subnet and desired allowed IPs

## Workflow

### Step 1: Check Existing WireGuard Configuration

```
"Show me the current WireGuard server configuration and all peers"
```

The plugin calls `opnsense__vpn__get_vpn_status` filtered to WireGuard tunnels. Note:
- Server public key and listen port
- Tunnel subnet (e.g., 10.200.0.0/24)
- Existing peer IPs to avoid conflicts

### Step 2: Plan the Peer Configuration

```
"Add a WireGuard peer named 'laptop-remote' with public key 'abc123...',
assign it 10.200.0.3/32, and allow it to reach the trusted and management VLANs"
```

The plugin builds a change plan:

1. **[OPNsense]** Create WireGuard peer endpoint
   - Name: laptop-remote
   - Public key: abc123...
   - Tunnel address: 10.200.0.3/32
   - Allowed IPs: 10.10.0.0/24, 10.20.0.0/24

2. **[OPNsense]** Add firewall rule on WireGuard interface
   - Pass traffic from 10.200.0.3 to 10.10.0.0/24 and 10.20.0.0/24

3. **[OPNsense]** Reconfigure WireGuard service (applies changes)

### Step 3: Review Risk Assessment

The OutageRiskAgent assesses:
- **VPN subsystem change** -- rated HIGH if your current session traverses the WireGuard tunnel, LOW if you are on a local management connection
- The NetworkSecurityAgent checks:
  - Are the allowed IPs appropriate? (not too broad)
  - Is the tunnel split or full? (0.0.0.0/0 vs specific subnets)

### Step 4: Confirm and Execute

```
"Looks good, apply it"
```

With `--apply`, the plugin executes the three steps in order, reporting each result. The reconfigure step applies the new peer to the live WireGuard instance.

### Step 5: Verify

```
"Show me the WireGuard peer status for laptop-remote"
```

The peer will appear in the status output. The `latest handshake` field will show `never` until the remote client connects and completes a handshake.

## Generating the Client Configuration

After the peer is added, generate the client-side WireGuard config:

```ini
[Interface]
PrivateKey = <client-private-key>
Address = 10.200.0.3/32
DNS = 10.10.0.1

[Peer]
PublicKey = <server-public-key>
Endpoint = <your-public-ip>:<listen-port>
AllowedIPs = 10.10.0.0/24, 10.20.0.0/24
PersistentKeepalive = 25
```

## Working Safely

This workflow includes write operations. The steps that modify the network are:
- Creating the WireGuard peer (VPN subsystem)
- Adding the firewall rule (firewall subsystem)
- Reconfiguring the WireGuard service (applies changes live)

The OutageRiskAgent will assess whether these changes could affect your current session. If you are connected via the same WireGuard tunnel being modified, the risk is HIGH -- ensure you have an alternative management path.

> **Required safety notice:** Network changes can result in outages that disconnect you from your ability to correct them. Never make changes to a network you cannot reach through an out-of-band path (serial console, IPMI/iDRAC, a separate management VLAN on a different physical interface, or physical access). Netex will assess this risk for you, but it cannot guarantee your recovery path -- only you can verify that.

## Related Workflows

- [Check VPN Health](check-vpn-health.md)
- [Review Firewall Rules](review-firewall.md)
