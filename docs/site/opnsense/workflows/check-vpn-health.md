# Check VPN Tunnel Health

## Intent

"I want to verify that my IPSec tunnels and WireGuard peers are up and passing traffic."

## Prerequisites

- [opnsense plugin installed and configured](../../getting-started/installation.md)
- [Authentication set up](../../getting-started/authentication.md#opnsense-plugin)
- At least one VPN tunnel configured (IPSec, OpenVPN, or WireGuard)

## Commands Involved

- `opnsense vpn`
- `opnsense vpn --tunnel <name>`

For the full workflow walkthrough with example output, see the [complete guide](../../../opnsense/workflows/check-vpn-health.md).
