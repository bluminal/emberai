"""OPNsense MCP tool implementations.

Imports all skill tool modules so they are registered when the
``opnsense.tools`` package is imported.

Skill modules:
- ``vpn`` -- IPSec, OpenVPN, WireGuard status
- ``security`` -- IDS/IPS alerts, rules, policy, certificates
- ``services`` -- DNS overrides, DHCP leases, traffic shaping
- ``diagnostics`` -- Ping, traceroute, DNS lookup, LLDP, host discovery
- ``firmware`` -- Firmware status, package inventory
- ``commands`` -- User-facing command tools (scan, health, diagnose, etc.)
"""

from opnsense.tools import commands, diagnostics, firmware, security, services, vpn

__all__ = [
    "commands",
    "diagnostics",
    "firmware",
    "security",
    "services",
    "vpn",
]
