"""OPNsense command orchestrator agents.

Imports all agent modules for generating formatted reports across
different OPNsense skill domains.

Agent modules:
- ``interfaces`` -- Interface & VLAN inventory report
- ``firewall`` -- Firewall audit report
- ``routing`` -- Routing report
- ``vpn`` -- VPN status report
- ``security`` -- IDS/certificate audit report
- ``services`` -- DNS/DHCP/traffic services report
- ``diagnostics`` -- Network diagnostics report
- ``firmware`` -- Firmware status report
"""

from opnsense.agents import diagnostics, firmware, security, services, vpn
from opnsense.agents.firewall import run_firewall_audit
from opnsense.agents.interfaces import run_interface_report
from opnsense.agents.routing import run_routing_report

__all__ = [
    "diagnostics",
    "firmware",
    "run_firewall_audit",
    "run_interface_report",
    "run_routing_report",
    "security",
    "services",
    "vpn",
]
