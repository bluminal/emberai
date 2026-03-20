# DHCP Lease Audit

## Intent

"I want to see all active DHCP leases -- IP, MAC, hostname, and expiry -- to understand what is on my network."

## Prerequisites

- **Plugin:** `opnsense` v0.2.0 or later
- **API privileges:** Read-only access to Kea DHCP and Interfaces sections in Effective Privileges
- **Environment variables:** `OPNSENSE_HOST`, `OPNSENSE_API_KEY`, and `OPNSENSE_API_SECRET` must be configured
- **Kea DHCP enabled:** Kea must be the active DHCP server on the OPNsense instance (OPNsense 24.1+ uses Kea by default; older versions use ISC DHCP)

## Context

Run this workflow to inventory all devices that have received a DHCP lease from your OPNsense firewall. This is useful for discovering unknown devices on your network, verifying that new devices are getting the correct IP assignments, and checking lease expiry times before making changes.

The workflow combines DHCP lease data with interface information to show leases per VLAN/interface. It is entirely read-only.

This workflow shows DHCP leases issued by OPNsense only. Devices with static IPs or DHCP leases from other servers (e.g., a Docker network or a downstream AP in router mode) will not appear.

## Commands

### Step 1: Scan the system to see all interfaces

```
You: Scan my OPNsense firewall
```

EmberAI runs `opnsense scan` to inventory interfaces and VLANs. This establishes context for the lease audit.

### Step 2: Check DHCP leases

```
You: Show me all DHCP leases
```

EmberAI calls the DHCP lease tools to list all active leases across all interfaces.

### Step 3: Review the lease table

```
EmberAI:

## DHCP Leases
| Metric     | Value |
|------------|-------|
| Total      | 23    |
| Active     | 21    |
| Expired    | 2     |

## Active Leases by Interface

### LAN (10.0.0.0/24)
| MAC               | IP          | Hostname          | Expiry              | State  |
|-------------------|-------------|-------------------|---------------------|--------|
| a4:83:e7:11:22:33 | 10.0.0.101  | macbook-pro       | 2026-03-20 14:30:00 | active |
| dc:a6:32:44:55:66 | 10.0.0.102  | desktop-pc        | 2026-03-20 15:45:00 | active |
| 00:11:32:77:88:99 | 10.0.0.50   | synology-nas      | 2026-03-21 09:00:00 | active |

### Guest (10.10.0.0/24, VLAN 10)
| MAC               | IP          | Hostname          | Expiry              | State  |
|-------------------|-------------|-------------------|---------------------|--------|
| f8:e4:e3:aa:bb:cc | 10.10.0.101 | iphone-guest      | 2026-03-20 12:00:00 | active |
| 3c:22:fb:dd:ee:ff | 10.10.0.102 | --                | 2026-03-20 12:15:00 | active |

### IoT (10.20.0.0/24, VLAN 20)
| MAC               | IP          | Hostname          | Expiry              | State  |
|-------------------|-------------|-------------------|---------------------|--------|
| dc:a6:32:66:77:88 | 10.20.0.25  | ring-doorbell     | 2026-03-21 09:00:00 | active |
| b8:27:eb:11:22:33 | 10.20.0.30  | hue-bridge        | 2026-03-21 09:00:00 | active |
| 68:ff:7b:44:55:66 | 10.20.0.31  | sonos-livingroom  | 2026-03-21 09:00:00 | active |
| 50:c7:bf:77:88:99 | 10.20.0.32  | ecobee-thermostat | 2026-03-21 09:00:00 | active |

### Servers (10.30.0.0/24, VLAN 30)
| MAC               | IP          | Hostname          | Expiry              | State  |
|-------------------|-------------|-------------------|---------------------|--------|
| 00:11:32:aa:bb:cc | 10.30.0.10  | nas               | 2026-03-21 09:00:00 | active |
| 52:54:00:dd:ee:ff | 10.30.0.20  | plex-server       | 2026-03-21 09:00:00 | active |
```

### Step 4: Filter to a specific interface (optional)

```
You: Show me just the IoT VLAN leases
```

```
EmberAI:

## DHCP Leases: IoT (VLAN 20)
| MAC               | IP          | Hostname          | Expiry              | State  |
|-------------------|-------------|-------------------|---------------------|--------|
| dc:a6:32:66:77:88 | 10.20.0.25  | ring-doorbell     | 2026-03-21 09:00:00 | active |
| b8:27:eb:11:22:33 | 10.20.0.30  | hue-bridge        | 2026-03-21 09:00:00 | active |
| 68:ff:7b:44:55:66 | 10.20.0.31  | sonos-livingroom  | 2026-03-21 09:00:00 | active |
| 50:c7:bf:77:88:99 | 10.20.0.32  | ecobee-thermostat | 2026-03-21 09:00:00 | active |

4 active lease(s) on IoT interface.
```

## What to Look For

**Lease counts:**
- **Total vs. expected** -- if the total lease count is much higher than the number of devices you expect, unknown devices may be on your network. Cross-reference MAC addresses with known device inventories.
- **Active vs. expired** -- expired leases are normal and will be cleaned up by Kea. A large number of expired leases may indicate devices that disconnected or moved to a different VLAN.

**Per-interface distribution:**
- **Devices on correct VLANs** -- verify that devices are getting leases on the expected VLAN. An IoT device with a lease on the LAN interface may indicate a switch port misconfiguration or missing VLAN tagging.
- **Unexpected devices** -- unknown MAC addresses or hostnames on restricted VLANs (Management, Servers) warrant investigation.

**Individual leases:**
- **Hostname column** -- a `--` means the device did not send a hostname in its DHCP request. This is common for IoT devices and guest devices. You can identify them by MAC address and OUI lookup.
- **Expiry** -- leases with very short expiry times (minutes) may indicate a device that is repeatedly requesting new leases, which can signal a DHCP configuration issue.
- **MAC addresses** -- compare MAC address prefixes against known manufacturers. Unexpected prefixes may indicate unauthorized devices.

## Next Steps

- [Troubleshoot DNS](troubleshoot-dns.md) -- verify that the DHCP configuration hands out the correct DNS server to clients
- [Review Firewall Rules](review-firewall.md) -- check that firewall rules are correct for the VLANs where devices are connected
- [First-Time System Scan](first-time-scan.md) -- re-scan interfaces if you discover VLANs without DHCP or devices on unexpected VLANs

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| 0 leases returned | Kea DHCP not running or API privileges missing | Verify Kea is enabled in Services > Kea DHCP; add Kea to Effective Privileges |
| Leases show but no interface grouping | Interface mapping not available | The plugin maps leases to interfaces using the IP range; verify DHCP subnets are correctly configured |
| Device not appearing in leases | Device has a static IP or DHCP from another source | Statically configured devices do not appear in DHCP leases; use `opnsense diagnose` with host discovery to find them |
| Many unknown hostnames (--) | Devices not sending DHCP hostname option | This is normal for many IoT devices; identify by MAC address OUI prefix |
| Lease on wrong interface | Switch port VLAN misconfiguration | Verify the switch port connected to the device has the correct VLAN assignment using `unifi scan` or switch management |
| Very short lease times | DHCP lease duration set too low | Check the DHCP subnet configuration in Services > Kea DHCP; increase lease duration for stable networks |
