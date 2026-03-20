"""OPNsense command orchestrator agents.

Imports all agent modules for generating formatted reports across
different OPNsense skill domains.

Agent modules:
- ``vpn`` -- VPN status report
- ``security`` -- IDS/certificate audit report
- ``services`` -- DNS/DHCP/traffic services report
- ``diagnostics`` -- Network diagnostics report
- ``firmware`` -- Firmware status report
"""

from opnsense.agents import diagnostics, firmware, security, services, vpn

__all__ = [
    "diagnostics",
    "firmware",
    "security",
    "services",
    "vpn",
]
