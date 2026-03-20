# Check VPN Tunnel Health

## Intent

"I want to verify that my IPSec tunnels and WireGuard peers are up and passing traffic."

## Prerequisites

- **Plugin:** `opnsense` v0.2.0 or later
- **API privileges:** Read-only access to IPSec, OpenVPN, and WireGuard sections in Effective Privileges
- **Environment variables:** `OPNSENSE_HOST`, `OPNSENSE_API_KEY`, and `OPNSENSE_API_SECRET` must be configured
- **VPN tunnels configured:** At least one IPSec, OpenVPN, or WireGuard tunnel must be configured on OPNsense

## Context

Run this workflow to verify that VPN tunnels are healthy, especially after a reboot, ISP failover, or certificate renewal. It checks all three VPN protocols that OPNsense supports: IPSec, OpenVPN, and WireGuard.

The check is entirely read-only. It reports tunnel status, traffic counters (byte counts), and handshake freshness. For WireGuard, stale handshakes (older than 3 minutes) are flagged as warnings because they may indicate the peer is offline.

This workflow does not cover firewall rules that may affect VPN traffic. If a tunnel is established but traffic is not flowing, use `opnsense diagnose` to trace the routing and firewall path.

## Commands

### Step 1: Check all VPN tunnels

```
You: Check VPN tunnel status
```

EmberAI calls `opnsense vpn` which queries all three VPN protocols.

### Step 2: Review the results

```
EmberAI:

## VPN Status
| Metric         | Value |
|----------------|-------|
| IPSec SAs      | 2     |
| OpenVPN        | 1     |
| WireGuard      | 3     |

## IPSec Sessions
| Name          | Status      | Local Traffic  | Remote Traffic  | RX       | TX       |
|---------------|-------------|----------------|-----------------|----------|----------|
| aws-tunnel-1  | established | 10.0.0.0/24    | 172.31.0.0/16   | 1.2 GB   | 890 MB   |
| office-link   | established | 10.0.0.0/16    | 192.168.50.0/24 | 450 MB   | 320 MB   |

## OpenVPN Instances
| Name           | Role   | Protocol | Port | Status  | Clients |
|----------------|--------|----------|------|---------|---------|
| site-to-site   | server | UDP      | 1194 | running | 1       |

## WireGuard Peers
| Name           | Endpoint          | Allowed IPs     | Last Handshake | RX      | TX      |
|----------------|-------------------|-----------------|----------------|---------|---------|
| mobile-phone   | 203.0.113.50:5182 | 10.8.0.2/32     | 45s ago        | 12 MB   | 89 MB   |
| laptop-remote  | 198.51.100.20:443 | 10.8.0.3/32     | 30s ago        | 450 MB  | 1.2 GB  |
| tablet         | --                | 10.8.0.4/32     | 4m 12s ago     | 1.2 MB  | 3.4 MB  |

## Findings

### Warning
- **WireGuard peer stale handshake**: "tablet" last handshake was 4m 12s
  ago (threshold: 3 minutes). The peer may be offline or unreachable.
  Recommendation: Verify the peer device is online and has network
  connectivity.

### Informational
- **All IPSec tunnels established**: 2 / 2 IPSec SAs are up and
  passing traffic.
- **OpenVPN healthy**: 1 instance running with 1 connected client.
```

### Step 3: Check a specific tunnel (optional)

```
You: Show me details for the aws-tunnel-1
```

EmberAI calls `opnsense vpn --tunnel aws-tunnel-1` to filter to a single tunnel.

```
EmberAI:

## IPSec: aws-tunnel-1
| Field           | Value            |
|-----------------|------------------|
| Status          | established      |
| Local traffic   | 10.0.0.0/24      |
| Remote traffic  | 172.31.0.0/16    |
| RX              | 1.2 GB           |
| TX              | 890 MB           |
| Established     | 2026-03-18 09:15 |
```

## What to Look For

**IPSec sessions:**
- **Status** -- should be `established`. A status of `connecting` means the tunnel is negotiating (may succeed shortly). A status of `down` means the tunnel is not working -- check IKE phase 1 and phase 2 parameters.
- **Traffic selectors** -- verify `Local Traffic` and `Remote Traffic` match your expected subnets. Mismatched traffic selectors are a common cause of tunnel establishment failure.
- **RX/TX** -- non-zero traffic counters confirm the tunnel is actively passing data. Zero counters on an `established` tunnel may indicate a routing problem.

**OpenVPN instances:**
- **Status** -- should be `running`. A stopped instance will not accept connections.
- **Clients** -- for server-mode instances, verify the expected number of clients are connected.

**WireGuard peers:**
- **Last Handshake** -- should be within the last 2--3 minutes for active peers. WireGuard sends a keepalive handshake every 25 seconds (by default). A handshake older than 3 minutes suggests the peer is offline or unreachable.
- **Endpoint** -- a `--` endpoint means the peer has never connected or the endpoint was not configured (common for peers behind NAT that initiate the connection).
- **RX/TX** -- confirm traffic is flowing. Very low counters on peers that should be active may indicate routing issues on the peer side.

## Next Steps

- [First-Time System Scan](first-time-scan.md) -- re-scan to verify interfaces and routes associated with VPN tunnels
- [Review Firewall Rules](review-firewall.md) -- check that firewall rules allow traffic between VPN subnets and local networks
- [Troubleshoot DNS](troubleshoot-dns.md) -- verify DNS resolution works over VPN if split DNS is configured

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| 0 IPSec sessions returned | No IPSec tunnels configured, or API privileges missing | Verify IPSec is configured in VPN > IPsec; add IPSec to Effective Privileges |
| IPSec shows "connecting" indefinitely | IKE negotiation failing | Check phase 1 settings (IKE version, auth, proposals) match the remote peer; verify the remote endpoint is reachable |
| IPSec "established" but 0 traffic | Routing issue or traffic selector mismatch | Verify that local routes point to the tunnel for the remote subnet; check traffic selectors match both sides |
| WireGuard shows all peers with no handshake | WireGuard service not running | Verify WireGuard is enabled in VPN > WireGuard > General |
| OpenVPN shows 0 clients | No clients connected or wrong auth | Check client configuration, certificates, and network path to the OpenVPN port |
| 403 on VPN endpoints | Insufficient API privileges | Add VPN > IPsec, VPN > OpenVPN, and VPN > WireGuard to Effective Privileges |
