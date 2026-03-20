# OPNsense Commands Reference

Commands are the user-facing entry points to the opnsense plugin. Each command orchestrates multiple tools from the [Skills Reference](skills.md) to produce a complete, severity-ranked report.

All scan, health, and audit commands are **read-only**. Write commands (`--configure`, `--apply`) require `OPNSENSE_WRITE_ENABLED=true` and operator confirmation.

## Commands

| Command | Description | Read/Write |
|---------|-------------|------------|
| `opnsense scan` | Full inventory of interfaces, VLANs, routes, VPN tunnels, firmware | Read |
| `opnsense health` | Gateway health check with severity-tiered findings | Read |
| `opnsense diagnose [target]` | Root-cause analysis for a host or interface | Read |
| `opnsense firewall [--audit]` | Firewall rule listing and audit | Read |
| `opnsense firewall policy-from-matrix` | Derive ruleset from inter-VLAN access matrix | Read/Write |
| `opnsense vlan [--configure] [--audit]` | VLAN interface management | Read/Write |
| `opnsense dhcp reserve-batch` | Batch DHCP reservation creation | Write |
| `opnsense vpn [--tunnel name]` | VPN tunnel status (IPsec, OpenVPN, WireGuard) | Read |
| `opnsense dns [hostname]` | DNS overrides, forwarders, and resolution test | Read |
| `opnsense secure` | Security posture audit | Read |
| `opnsense firmware` | Firmware and package update status | Read |

For full command documentation with parameters and examples, see the [complete reference](../../opnsense/commands.md).
