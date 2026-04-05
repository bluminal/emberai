"""Cisco SG-300 data models.

Re-exports all Pydantic models used to represent parsed CLI output from the
Cisco SG-300 managed switch.  Every model uses strict mode.  MAC addresses are
normalized to lowercase colon-separated format (aa:bb:cc:dd:ee:ff).

Usage::

    from cisco.models import SwitchInfo, VLAN, Port, PortDetail
    from cisco.models import MACEntry, LLDPNeighbor, InterfaceCounters
"""

from cisco.models.counters import InterfaceCounters
from cisco.models.interfaces import Port, PortDetail
from cisco.models.lldp import LLDPNeighbor
from cisco.models.mac_table import MACEntry
from cisco.models.system import SwitchInfo
from cisco.models.validators import MACAddress, normalize_mac
from cisco.models.vlan import VLAN

__all__ = [
    "VLAN",
    "InterfaceCounters",
    "LLDPNeighbor",
    "MACAddress",
    "MACEntry",
    "Port",
    "PortDetail",
    "SwitchInfo",
    "normalize_mac",
]
