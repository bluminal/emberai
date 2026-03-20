"""OPNsense MCP tool implementations.

Importing this package registers all tool modules with the MCP server.
Each tool module decorates its handlers with ``@mcp_server.tool()`` so
they are automatically available when the server starts.

Tool modules:
    - ``interfaces`` -- interface, VLAN, and DHCP operations
    - ``firewall`` -- firewall rules, aliases, and NAT operations
    - ``routing`` -- static routes and gateway status
    - ``diagnostics`` -- LLDP neighbor discovery
"""

import opnsense.tools.diagnostics as diagnostics
import opnsense.tools.firewall as firewall
import opnsense.tools.interfaces as interfaces
import opnsense.tools.routing as routing

__all__ = [
    "diagnostics",
    "firewall",
    "interfaces",
    "routing",
]
