"""CLI output parsers for Cisco SG-300.

Each parser is a pure function that takes raw CLI text output and returns
typed Pydantic models.  Parsing is done via regex -- no TextFSM dependency.

Usage::

    from cisco.parsers import parse_show_vlan, parse_show_interfaces_status
    from cisco.parsers import parse_show_mac_address_table, parse_show_lldp_neighbors
    from cisco.parsers import parse_show_version, parse_show_switchport
    from cisco.parsers import parse_hostname_from_config

    vlans = parse_show_vlan(raw_output)
    ports = parse_show_interfaces_status(raw_output)
"""

from cisco.parsers.interfaces import parse_show_interfaces_status, parse_show_switchport
from cisco.parsers.lldp import parse_show_lldp_neighbors
from cisco.parsers.mac_table import parse_show_mac_address_table
from cisco.parsers.system import parse_hostname_from_config, parse_show_version
from cisco.parsers.vlan import parse_show_vlan

__all__ = [
    "parse_hostname_from_config",
    "parse_show_interfaces_status",
    "parse_show_lldp_neighbors",
    "parse_show_mac_address_table",
    "parse_show_switchport",
    "parse_show_version",
    "parse_show_vlan",
]
