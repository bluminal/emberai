# Diagnose a Client Connectivity Complaint

## Intent

"I want to trace why a client cannot reach a destination through all layers."

## Prerequisites

- **Plugin:** `unifi` v0.2.0 or later
- **API privileges:** Read-only access to the Local Gateway API
- **Environment variables:** `UNIFI_LOCAL_HOST` and `UNIFI_LOCAL_KEY` must be configured
- **Recommended:** The `opnsense` plugin configured for gateway-layer diagnostics (firewall rules, routing). Without it, the workflow covers UniFi-side analysis only.

## Context

Run this workflow when a user reports they cannot reach a specific destination -- a file server, a printer, a cloud service, or an internal application. The workflow traces the connectivity path through multiple layers: client health, wireless signal, VLAN assignment, firewall rules, and gateway routing.

This workflow combines three commands in sequence: `unifi diagnose` for client-side analysis, `unifi secure` for firewall posture, and `unifi health` for infrastructure-level checks. Each layer either clears or identifies the probable root cause.

This workflow is entirely read-only. No changes are made to the network. For optimization recommendations, see [Optimize WiFi](optimize-wifi.md).

## Commands

### Step 1: Identify and diagnose the client

Start by diagnosing the affected client. Use any identifier: hostname, IP, MAC, or alias.

```
You: Sarah's laptop can't reach the file server. Diagnose it.
```

```
EmberAI:

## Diagnosis: macbook-pro-sdavis
| Metric     | Value           |
|------------|-----------------|
| Type       | Client          |
| Connection | Wireless        |
| IP         | 192.168.1.142   |

### Client Details
| Field      | Value              |
|------------|--------------------|
| MAC        | a4:83:e7:22:33:44  |
| Hostname   | macbook-pro-sdavis |
| IP         | 192.168.1.142      |
| VLAN       | LAN                |
| Connection | Wireless           |
| Uptime     | 0d 1h 22m          |
| AP         | e0:63:da:cc:55:66  |
| SSID       | CorpNet            |
| RSSI       | 42                 |

### Associated AP Health
| Field  | Value          |
|--------|----------------|
| Name   | Office-AP-Main |
| Status | connected      |
| Uptime | 20d 0h 7m      |
| CPU    | 12.4%          |
| Memory | 38.1%          |

### Diagnostic Findings

#### Informational
- **Good signal quality**: RSSI is 42, indicating adequate signal strength.
  No wireless issues detected at this layer.

- **No disconnect events in the last 24 hours**: The client has maintained
  a stable connection.
```

### Step 2: Check the destination

If the client looks healthy, diagnose the destination device next.

```
You: Now check the file server at 192.168.1.50
```

```
EmberAI:

## Diagnosis: synology-nas
| Metric     | Value           |
|------------|-----------------|
| Type       | Client          |
| Connection | Wired           |
| IP         | 192.168.1.50    |

### Client Details
| Field      | Value              |
|------------|--------------------|
| MAC        | 00:11:32:aa:bb:cc  |
| Hostname   | synology-nas       |
| IP         | 192.168.1.50       |
| VLAN       | LAN                |
| Connection | Wired (Port 4)     |
| Uptime     | 45d 3h 12m         |

### Diagnostic Findings

#### Informational
- **Wired connection**: Client is connected via switch port 4. No wireless
  signal issues apply.

- **No disconnect events in the last 24 hours**: The file server has
  maintained a stable connection.
```

### Step 3: Audit the firewall posture

If both endpoints are healthy and on the same VLAN, the issue may be at the firewall or application layer. If the endpoints are on different VLANs, inter-VLAN firewall rules are the most common cause.

```
You: Check the firewall rules between these VLANs
```

```
EmberAI:

## Security Posture Audit

### Firewall Rules (LAN interface)
| # | Action | Source           | Destination      | Protocol | Enabled | Log |
|---|--------|-----------------|------------------|----------|---------|-----|
| 1 | pass   | 192.168.1.0/24  | any              | any      | Yes     | No  |

### Zone-Based Firewall Policies
| Source Zone | Dest Zone | Action | Description         |
|-------------|-----------|--------|---------------------|
| LAN         | WAN       | Allow  | Default outbound    |
| LAN         | LAN       | Allow  | Intra-VLAN traffic  |
| Guest       | LAN       | Block  | Guest isolation     |

### Findings

#### Informational
- **Same-VLAN traffic**: Both macbook-pro-sdavis (192.168.1.142) and
  synology-nas (192.168.1.50) are on the LAN VLAN. Intra-VLAN traffic
  is permitted by default. Firewall rules are not blocking this path.

  Recommendation: The issue is likely at the application layer (SMB share
  permissions, DNS resolution, or service availability on the file server).
```

### Step 4: Check infrastructure health

As a final layer, verify that the underlying infrastructure is healthy.

```
You: Quick health check
```

```
EmberAI:

## Health Check
| Metric  | Value |
|---------|-------|
| Devices | 3     |
| Clients | 42    |

All systems healthy -- 3 device(s) online, 42 client(s) connected.

## Findings

### Informational
- **ISP metrics**: ISP: Example ISP, Latency: 6ms, Download: 487.2 Mbps,
  Upload: 42.1 Mbps, Drops: 0.
```

## What to Look For

**Client diagnosis layer:**
- **Signal quality** -- Fair or Poor RSSI is a common root cause for intermittent connectivity. RSSI below 20 almost always explains the problem.
- **Disconnect events** -- Frequent disconnects (5+ in 24 hours) indicate instability, not a permanent block.
- **VLAN assignment** -- Verify the client is on the expected VLAN. A client on the Guest VLAN cannot reach LAN resources by design.
- **Uptime** -- Very short uptime (minutes) may indicate the client just reconnected after an outage.

**Destination layer:**
- **Reachability** -- If the destination is not in the client list, it may be offline or on a different site.
- **Connection type** -- A wired device showing disconnects is unusual and points to switch port or cabling issues.

**Firewall layer:**
- **Inter-VLAN rules** -- If source and destination are on different VLANs, look for explicit pass rules. Default deny between zones is the most common cause of cross-VLAN connectivity failures.
- **Shadowed rules** -- A pass rule positioned after a broader block rule will never match. Check rule ordering.
- **Port forwarding** -- If the destination is behind NAT, verify the port forward exists and maps to the correct internal IP.

**Infrastructure layer:**
- **Subsystem degradation** -- A degraded LAN or WLAN subsystem affects all clients, not just one.
- **AP health** -- High CPU (>80%) or memory (>85%) on the AP serving the affected client can cause packet loss.

## Next Steps

- [Optimize WiFi](optimize-wifi.md) -- if the diagnosis points to RF congestion or poor signal
- [Firewall Posture Audit](firewall-posture-audit.md) -- for a comprehensive security audit beyond the quick check above
- [Daily Health Check](daily-health-check.md) -- if the issue affects multiple clients

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Client not found by hostname | Client not currently connected, or hostname not matching | Search by MAC address or IP instead |
| Client on wrong VLAN | DHCP assigned IP from unexpected subnet, or port profile misconfigured | Verify switch port VLAN assignment and DHCP scope |
| Firewall rules show empty | Security skill group returns no rules for the site | Verify API key has permissions to read firewall configuration |
| Both endpoints healthy, same VLAN, no firewall blocks | Application-layer issue | Check DNS resolution, service availability (ping, port scan), and application-level access control (SMB, HTTP auth) |
| Cross-VLAN traffic blocked | No inter-VLAN pass rule exists | Review firewall rules on the source VLAN interface; add a pass rule if appropriate (requires `opnsense` plugin for gateway-side rules) |
