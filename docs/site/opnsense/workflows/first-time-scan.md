# First-Time System Scan

## Intent

"I want to inventory all interfaces, VLANs, routes, and VPN tunnels on my OPNsense firewall for the first time."

## Prerequisites

- **Plugin:** `opnsense` v0.2.0 or later
- **API privileges:** Read-only access (at minimum: Interfaces, Routes, VPN, Firmware sections in Effective Privileges)
- **Environment variables:** `OPNSENSE_HOST`, `OPNSENSE_API_KEY`, and `OPNSENSE_API_SECRET` must be configured
- **Network access:** The MCP server must be able to reach the OPNsense instance over HTTPS

## Context

Run this workflow when you first connect the opnsense plugin to a firewall, after a migration, or when you suspect the configuration has changed since your last scan. The scan is entirely read-only -- it makes no changes to your firewall.

This workflow gives you a complete inventory of the gateway layer: every interface (physical and VLAN), every route, every VPN tunnel, and the current firmware status. Use it as a baseline before running health checks, firewall audits, or VPN diagnostics.

This workflow does not cover firewall rule analysis or security posture -- see [Review Firewall Rules](review-firewall.md) and [Check VPN Health](check-vpn-health.md) for those.

## Commands

### Step 1: Run the scan

```
You: Scan my OPNsense firewall
```

EmberAI calls `opnsense scan` which orchestrates tools across interfaces, routing, VPN, and firmware skills to build a complete system inventory.

### Step 2: Review the results

```
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

## What to Look For

**Interfaces table:**
- **Status column** -- all interfaces you expect to be active should show `up`. An interface showing `down` may indicate a disconnected cable, a misconfigured interface, or an intentionally unused port.
- **IP column** -- verify each interface has the correct IP address. A `--` indicates no IP is assigned, which is expected for unused physical ports but not for active VLAN or LAN interfaces.
- **Type column** -- verify you see all expected interface types. Missing VLAN interfaces may indicate they were not created on OPNsense (even if the VLANs exist on the switch side).

**VLAN interfaces table:**
- **Tag column** -- confirm all expected VLAN IDs are present. If a VLAN exists on your switch but not on OPNsense, inter-VLAN routing and DHCP will not work for that VLAN.
- **Parent interface** -- all VLANs should be on the correct parent (typically the LAN interface connected to your switch trunk port).
- **IP column** -- each VLAN interface should have a gateway IP in the correct subnet. This IP becomes the default gateway for devices on that VLAN.

**Gateways table:**
- **Status** -- all gateways should show `online`. An `offline` gateway means traffic using that gateway cannot be routed.
- **RTT** -- latency should be consistent with expectations. WAN gateways typically show 1--20ms for local ISP hops. VPN gateways show latency to the remote endpoint.

**VPN status:**
- **IPSec** -- tunnels should show `established`. A `connecting` or `down` status means the tunnel is not passing traffic.
- **WireGuard** -- check the peer count matches your expected number of peers.

**Firmware:**
- Note the current version and whether an upgrade is available. Do not upgrade immediately -- see the `opnsense firmware` command for a detailed changelog review first.

## Next Steps

- [Review Firewall Rules](review-firewall.md) -- audit your firewall rules for overly permissive or shadowed entries
- [Check VPN Health](check-vpn-health.md) -- verify VPN tunnels are healthy and passing traffic
- [Troubleshoot DNS](troubleshoot-dns.md) -- confirm DNS resolution is working correctly

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "OPNSENSE_HOST is not set" | Missing environment variable | Set `OPNSENSE_HOST` to your OPNsense URL (e.g., `https://192.168.1.1`) |
| "OPNSENSE_API_KEY is not set" | Missing API credentials | Generate an API key in OPNsense (System > Access > Users) and set both `OPNSENSE_API_KEY` and `OPNSENSE_API_SECRET` |
| Connection timeout | OPNsense unreachable from MCP server | Verify network path; check that the web UI is accessible at the same URL |
| 401 Unauthorized | Invalid API credentials | Verify the API key and secret are correct; check that the key has not been revoked |
| 403 Forbidden | Insufficient API privileges | The API key owner needs Effective Privileges for the resources being accessed. Check System > Access > Users > Effective Privileges |
| SSL certificate error | Self-signed certificate | Set `OPNSENSE_VERIFY_SSL=false` (note: this disables TLS verification) |
| 0 VLANs returned | VLANs not configured on OPNsense | VLANs must be created on OPNsense separately from the switch configuration. Use `opnsense vlan --configure` to create them |
| Gateway shows "none" status | No monitor target configured | Configure a monitor IP for the gateway in System > Gateways |
