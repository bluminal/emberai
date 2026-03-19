"""MCP tool implementations registered via @server.tool()."""

# Import tool modules so that their @mcp_server.tool() decorators execute
# and register handlers when the server starts.
import unifi.tools.clients as clients  # noqa: F401
import unifi.tools.health as health  # noqa: F401
import unifi.tools.topology as topology  # noqa: F401
