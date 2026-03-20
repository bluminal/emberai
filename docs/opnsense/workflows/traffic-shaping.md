# Traffic Shaping Configuration

> **Difficulty:** Advanced | **Time:** 20-30 minutes | **Risk:** Write operation

## Problem Statement

You need to configure traffic shaping (QoS) on OPNsense to prioritize critical traffic (VoIP, management) over bulk traffic (downloads, streaming) and limit bandwidth for guest or IoT VLANs.

## Prerequisites

- OPNsense plugin installed with `OPNSENSE_WRITE_ENABLED=true`
- Knowledge of your WAN bandwidth (upload and download)
- Understanding of which VLANs/services need priority

## Workflow

### Step 1: Assess Current Traffic

```
"Show me interface traffic statistics for all VLAN interfaces"
```

The plugin calls `opnsense__diagnostics__get_interface_stats` to show current throughput on each interface. This helps identify which VLANs are consuming the most bandwidth.

### Step 2: Review Existing Shaper Configuration

```
"List all traffic shaper pipes and queues"
```

The plugin calls `opnsense__services__list_traffic_shaper_rules`. Check for:
- Existing pipes (bandwidth limits)
- Existing queues (priority assignments)
- Any rules already matching traffic

### Step 3: Design the Shaping Policy

A typical home/SMB shaping policy:

| Priority | Traffic Type | VLAN | Bandwidth |
|---|---|---|---|
| 1 (highest) | VoIP / SIP | Trusted | Guaranteed 5 Mbps |
| 2 | Management SSH/HTTPS | Management | Guaranteed 2 Mbps |
| 3 | General browsing | Trusted | Best effort, up to 80% WAN |
| 4 | Guest browsing | Guest | Limited to 25% WAN |
| 5 (lowest) | IoT telemetry | IoT | Limited to 10% WAN |

### Step 4: Create Pipes and Queues

```
"Set up traffic shaping with these priorities:
- VoIP traffic on the trusted VLAN gets guaranteed 5 Mbps
- Guest VLAN is limited to 25% of my 100 Mbps WAN
- IoT VLAN is limited to 10 Mbps"
```

The plugin builds a change plan:

1. **[OPNsense]** Create pipe: WAN-Download (100 Mbps)
2. **[OPNsense]** Create pipe: Guest-Limit (25 Mbps)
3. **[OPNsense]** Create pipe: IoT-Limit (10 Mbps)
4. **[OPNsense]** Create queue: VoIP-Priority (weight 100, pipe WAN-Download)
5. **[OPNsense]** Create queue: General-Traffic (weight 50, pipe WAN-Download)
6. **[OPNsense]** Create shaper rules matching DSCP/port for VoIP
7. **[OPNsense]** Create shaper rules matching Guest VLAN source
8. **[OPNsense]** Create shaper rules matching IoT VLAN source
9. **[OPNsense]** Reconfigure traffic shaper

### Step 5: Verify

```
"Show me the traffic shaper configuration and current queue statistics"
```

After applying, verify:
- Pipes show correct bandwidth limits
- Queues are processing traffic in the expected priority order
- Guest and IoT VLANs are properly rate-limited

## Working Safely

Traffic shaping write operations modify the OPNsense traffic shaper configuration. While misconfigured shaping can degrade performance, it cannot cause a complete connectivity loss -- removing all shaper rules restores default behavior.

The OutageRiskAgent classifies traffic shaper changes as **MEDIUM** risk (services subsystem, indirect disruption potential).

> **Required safety notice:** Network changes can result in outages that disconnect you from your ability to correct them. Never make changes to a network you cannot reach through an out-of-band path (serial console, IPMI/iDRAC, a separate management VLAN on a different physical interface, or physical access). Netex will assess this risk for you, but it cannot guarantee your recovery path -- only you can verify that.

## Related Workflows

- [Review Firewall Rules](review-firewall.md)
- [First Time Scan](first-time-scan.md)
