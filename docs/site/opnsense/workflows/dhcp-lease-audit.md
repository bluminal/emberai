# DHCP Lease Audit

## Intent

"I want to see all active DHCP leases -- IP, MAC, hostname, and expiry -- to understand what is on my network."

## Prerequisites

- [opnsense plugin installed and configured](../../getting-started/installation.md)
- [Authentication set up](../../getting-started/authentication.md#opnsense-plugin)
- Kea DHCP enabled on OPNsense (default in OPNsense 24.1+)

## Commands Involved

- `opnsense scan`
- DHCP lease listing tools

For the full workflow walkthrough with example output, see the [complete guide](../../../opnsense/workflows/dhcp-lease-audit.md).
