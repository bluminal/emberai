"""OPNsense command orchestrator agents.

Agent modules provide higher-level reporting and analysis by composing
multiple tool calls and producing formatted OX reports.

Agents:
    - ``interfaces`` -- interface and VLAN inventory report
    - ``firewall`` -- firewall rule audit report
    - ``routing`` -- routing table report
"""

from opnsense.agents.firewall import run_firewall_audit
from opnsense.agents.interfaces import run_interface_report
from opnsense.agents.routing import run_routing_report

__all__ = [
    "run_firewall_audit",
    "run_interface_report",
    "run_routing_report",
]
