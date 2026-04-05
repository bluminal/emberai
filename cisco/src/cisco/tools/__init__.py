"""MCP tool registration for the Cisco plugin.

Tool modules are imported here to trigger @mcp_server.tool() registration.
Each module registers its tools as a side effect of import.
"""

from cisco.tools import clients, config, health, interfaces, port_write, topology, vlan_write

__all__ = [
    "clients",
    "config",
    "health",
    "interfaces",
    "port_write",
    "topology",
    "vlan_write",
]
