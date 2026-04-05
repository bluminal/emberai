"""MCP tool registration for the Talos plugin.

Tool modules are imported here to trigger @mcp_server.tool() registration.
Each module registers its tools as a side effect of import.
"""

from talos.tools import cluster, config, setup

__all__ = [
    "cluster",
    "config",
    "setup",
]
