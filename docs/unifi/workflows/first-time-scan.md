# First-Time Site Scan

## Intent

"I want to discover everything on my UniFi network for the first time."

## Prerequisites

- **Plugin:** `unifi` v0.1.0 or later
- **API privileges:** Read-only access to the Local Gateway API
- **Environment variables:** `UNIFI_LOCAL_HOST` and `UNIFI_LOCAL_KEY` must be configured
- **Network access:** The MCP server must be able to reach the UniFi gateway

## Context

Run this workflow when you first connect the unifi plugin to a network, or when you suspect the network has changed since your last scan (new devices added, VLANs reconfigured, cabling changes). The scan is entirely read-only -- it makes no changes to your network.

This workflow gives you a complete inventory: every device, every VLAN, and how everything is connected. Use it as a baseline before running health checks or client diagnostics.

This workflow does not cover WiFi channel analysis or security posture -- see [Check WiFi Channels](check-wifi-channels.md) and the `unifi secure` command (Phase 2).

## Commands

### Step 1: Run the scan

```
You: Scan my UniFi network
```

EmberAI calls `unifi scan` which orchestrates three topology tools to build a complete site map.

### Step 2: Review the results

```
EmberAI:

## Site Scan Complete
| Metric   | Value |
|----------|-------|
| Devices  | 3     |
| VLANs    | 4     |
| Uplinks  | 2     |

## Devices
| Name             | Model      | IP           | Status    | Firmware       | Uptime      |
|------------------|------------|--------------|-----------|----------------|-------------|
| USG-Gateway      | UXG-Max    | 192.168.1.1  | connected | 4.0.6.6754     | 20d 0h 7m   |
| Office-Switch-16 | USLITE16P  | 192.168.1.10 | connected | 7.0.50.15116   | 10d 0h 3m   |
| Office-AP-Main   | U6-Pro     | 192.168.1.20 | connected | 7.0.76.15293   | 20d 0h 7m   |

## VLANs
| Name       | VLAN ID | Subnet           | DHCP | Purpose   |
|------------|---------|------------------|------|-----------|
| Default    |         | 192.168.1.0/24   | Yes  | corporate |
| Guest      | 10      | 192.168.10.0/24  | Yes  | guest     |
| IoT        | 30      | 192.168.30.0/24  | Yes  | corporate |
| Management | 99      | 192.168.99.0/24  | Yes  | corporate |

## Uplinks
| Device -> Parent                     | Port | Speed   | Type |
|--------------------------------------|------|---------|------|
| Office-Switch-16 -> USG-Gateway      | 1    | 10 Gbps | wire |
| Office-AP-Main -> Office-Switch-16   | 1    | 1 Gbps  | wire |
```

## What to Look For

**Devices table:**
- **Status column** -- all devices should show `connected`. Any device showing `disconnected`, `pending_adoption`, or `heartbeat_missed` needs attention.
- **Firmware column** -- note firmware versions for each device. Mismatched firmware across devices of the same model can indicate inconsistent update practices.
- **Uptime column** -- very short uptimes (minutes or hours) on devices you did not recently restart may indicate instability or power issues.

**VLANs table:**
- **VLAN IDs** -- confirm that all expected VLANs are present. Missing VLANs may indicate configuration issues on the UniFi side (gateway-side VLANs are managed by the opnsense plugin).
- **DHCP** -- verify DHCP is enabled on VLANs where you expect automatic IP assignment.
- **Subnet** -- confirm subnets match your network design. Overlapping subnets between VLANs will cause routing problems.

**Uplinks table:**
- **Speed** -- verify link speeds match expectations. A 10 Gbps uplink dropping to 1 Gbps may indicate a cable issue or port negotiation problem.
- **Connectivity chain** -- the uplink graph should form a tree rooted at the gateway. Orphaned devices (not appearing in the uplinks table) may not be properly cabled.

## Next Steps

- [Daily Health Check](daily-health-check.md) -- run a health check to identify issues with the devices you discovered
- [Locate a Client](locate-client.md) -- find a specific device connected to your network
- [Firmware Update Status](firmware-update-status.md) -- check which devices need firmware updates

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "UNIFI_LOCAL_HOST is not set" | Missing environment variable | Set `UNIFI_LOCAL_HOST` to your gateway IP (e.g., `192.168.1.1`) |
| "UNIFI_LOCAL_KEY is not set" | Missing API key | Generate an API key in UniFi Network Settings and set `UNIFI_LOCAL_KEY` |
| Connection timeout | Gateway unreachable from MCP server | Verify network path between MCP server and gateway; check firewall rules |
| 0 devices returned | Wrong site ID or API key lacks permissions | Try with `site_id="default"`; verify API key has site admin access |
| Devices show but VLANs are empty | Networks not configured in UniFi | VLANs may be configured on OPNsense only; check that UniFi has corresponding network entries |
