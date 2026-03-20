# Quick Start

This guide assumes you have [installed the plugins](installation.md) and [configured authentication](authentication.md). Let's run your first commands.

!!! info "Prerequisites"
    - At least one plugin installed via `/plugin install unifi@emberai` (or opnsense, netex)
    - Environment variables configured for the installed plugins
    - Health check passes (e.g., `unifi-server --check`)

## Scan Your Network

The first thing most operators want to do is discover what's on their network. In Claude, say:

> **You:** Scan my UniFi network.

Claude will call `unifi scan`, which discovers all devices, their roles, uplink relationships, firmware status, and client counts. The output is a structured topology -- not a raw API dump.

Example output:

```
UniFi Site: Default (192.168.1.1)

Devices (6):
  UDM-Pro          online   fw 4.0.6   uplink: WAN
    USW-Pro-24-PoE  online   fw 7.0.50  uplink: UDM-Pro (port 1)
      U6-Pro (Living Room)   online   fw 7.0.43  uplink: USW (port 5)
      U6-Pro (Office)        online   fw 7.0.43  uplink: USW (port 9)
    USW-Flex-Mini    online   fw 7.0.50  uplink: UDM-Pro (port 3)
      U6-Lite (Garage)       online   fw 7.0.43  uplink: Flex (port 1)

Clients: 47 connected (32 wireless, 15 wired)
```

## Check Network Health

> **You:** How's my network doing?

Claude will call `unifi health`, which checks device uptime, firmware currency, ISP metrics, and event logs. It returns a severity-ranked summary -- not just green/red status.

Example output:

```
Network Health: GOOD (1 advisory)

All Devices: 6/6 online, 0 alerts
Firmware: all current
ISP: 940 Mbps down / 42 Mbps up, 0.1% packet loss (24h)

Advisory:
  - U6-Lite (Garage): 2 client roaming events in the last hour
    (may indicate marginal signal at the coverage boundary)
```

## Find a Specific Client

> **You:** Where is my Sonos speaker connected?

Claude will search by hostname, IP, or MAC address and show you exactly where the client is connected -- which AP, which VLAN, signal strength, and recent traffic.

Example output:

```
Client: Sonos-Living-Room
  MAC:    a4:5e:60:xx:xx:xx
  IP:     192.168.30.42 (VLAN 30 -- IoT)
  AP:     U6-Pro (Living Room)
  Signal: -52 dBm (excellent)
  Channel: 5 GHz / 80 MHz / ch 36
  Traffic: 12 MB down / 0.8 MB up (last hour)
```

## What's Next?

Now that you've run your first commands, explore the workflow examples for common operational tasks:

- [First-Time Site Scan](../unifi/workflows/first-time-scan.md) -- detailed walkthrough of the initial discovery process
- [Daily Health Check](../unifi/workflows/daily-health-check.md) -- what to check every morning
- [Locate a Client](../unifi/workflows/locate-client.md) -- find any device on your network

Before enabling write operations, read [Safety & Human Supervision](safety.md) to understand how Netex keeps you in control of every network change.
