"""MCP tool implementations for the netex umbrella plugin.

Imports command modules to register their @mcp_server.tool() handlers
at module load time.
"""

from netex.tools.commands import (
    netex__dns__trace,
    netex__network__provision_site,
    netex__network__verify_policy,
    netex__policy__sync,
    netex__vlan__provision_batch,
    netex__vpn__status,
)

__all__ = [
    "netex__dns__trace",
    "netex__network__provision_site",
    "netex__network__verify_policy",
    "netex__policy__sync",
    "netex__vlan__provision_batch",
    "netex__vpn__status",
]
