# Per-VLAN NextDNS Profiles via ctrld

**Severity:** critical
**Triggers:** nextdns, dns, per-vlan, vlan dns, dns profile, dns forwarding, ctrld, unbound views, split dns

## Problem

NextDNS differentiates profiles via the DNS-over-TLS/HTTPS hostname (e.g., `fe1de8.dns.nextdns.io`), not by destination IP. All profiles share the same IPs (45.90.28.0, 45.90.30.0). To route different VLANs to different NextDNS profiles, the DNS resolver must select the upstream based on the client's source IP/subnet.

**Unbound views DO NOT WORK for this use case.** Unbound's `access-control-view` with per-view `forward-zone` directives does not correctly route queries to view-specific forward-zones. All traffic falls through to the last defined view regardless of source subnet. This was extensively tested on OPNsense 26.x with Unbound 1.24.2.

## Working Solution: ctrld (ControlD DNS Forward Proxy)

`ctrld` is a DNS forward proxy that routes queries to different upstream resolvers based on client source IP. It has first-class support for NextDNS via DNS-over-HTTPS.

### Architecture

```
VLAN clients → gateway:53 → ctrld (port 53, routes by subnet to NextDNS profiles via DoH)
                                ↓ (for local domains like *.home.example.net)
                            Unbound (127.0.0.1:10053, local resolution only)
```

**Critical:** ctrld MUST listen on port 53 directly (not behind Unbound). If Unbound proxies queries to ctrld, all queries appear to come from 127.0.0.1 and subnet-based routing is destroyed.

### OPNsense Configuration

1. **Move Unbound to port 10053**: OPNsense UI → Services → Unbound DNS → General → Listen Port: `10053`
2. **Remove NextDNS DoT forwarders from Unbound**: They're no longer needed since ctrld handles NextDNS
3. **Install ctrld**: Download from GitHub releases (FreeBSD amd64 binary) to `/usr/local/bin/ctrld`
4. **Configure ctrld**: Write TOML config to `/usr/local/etc/ctrld/ctrld.toml`
5. **Start as service**: `ctrld service start --config /usr/local/etc/ctrld/ctrld.toml --skip_self_checks`

### Configuration File Format

```toml
[service]
  log_level = "info"

[listener]
  [listener.0]
    ip = "0.0.0.0"
    port = 53

    [listener.0.policy]
      name = "NextDNS VLAN Routing"

      networks = [
        {"network.0" = ["upstream.0"]},
        {"network.1" = ["upstream.1"]}
        # ... one entry per VLAN
      ]

      rules = [
        {"*.home.example.net" = ["upstream.local"]},
        {"*.in-addr.arpa" = ["upstream.local"]},
        {"*.ip6.arpa" = ["upstream.local"]}
      ]

[network]
  [network.0]
    name = "Trusted"
    cidrs = ["172.16.30.0/24"]
  [network.1]
    name = "Kids"
    cidrs = ["172.16.80.0/24"]
  # ... one entry per VLAN

[upstream]
  [upstream.0]
    name = "NextDNS-Trusted"
    type = "doh"
    endpoint = "https://dns.nextdns.io/PROFILE_ID_HERE"
    timeout = 5000
  [upstream.1]
    name = "NextDNS-Kids"
    type = "doh"
    endpoint = "https://dns.nextdns.io/PROFILE_ID_HERE"
    timeout = 5000
  [upstream.local]
    name = "Local-Unbound"
    type = "legacy"
    endpoint = "127.0.0.1:10053"
    timeout = 5000
```

**IMPORTANT:** Network and upstream keys MUST be numbered (`0`, `1`, `2`, ...), not named. Named keys cause a "missing listener config" panic.

### Service Management

```bash
ctrld service status          # Check if running
ctrld service restart         # Restart
ctrld service stop            # Stop
ctrld service uninstall       # Remove service
```

### Backup and Restore

The ctrld config at `/usr/local/etc/ctrld/ctrld.toml` survives OPNsense minor updates but should be backed up. The Unbound port change (10053) is managed by OPNsense and persists in its config database.

To restore from backup:
```bash
# Restore Unbound to port 53 (via OPNsense UI or API)
# Re-add NextDNS DoT forwarders to Unbound
# Stop and uninstall ctrld: ctrld service uninstall
```

### Alternatives Evaluated and Rejected

| Approach | Why it doesn't work |
|----------|-------------------|
| Unbound views with per-view forward-zone | Views don't route to view-specific forward-zones on OPNsense 26.x |
| dnsmasq per-interface DNS forwarding | dnsmasq doesn't support DNS-over-TLS natively |
| Multiple Unbound instances on different ports | DHCP clients can't use non-standard DNS ports |
| NextDNS linked IP | All VLANs share one WAN IP, can't differentiate |
| NextDNS CLI | Not in FreeBSD ports on OPNsense 26.x, same architecture as ctrld |
