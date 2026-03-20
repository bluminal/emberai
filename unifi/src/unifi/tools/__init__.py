"""MCP tool implementations registered via @server.tool()."""

# Import tool modules so that their @mcp_server.tool() decorators execute
# and register handlers when the server starts.
import unifi.tools.clients as clients  # noqa: F401
import unifi.tools.commands as commands  # noqa: F401
import unifi.tools.config as config  # noqa: F401
import unifi.tools.health as health  # noqa: F401
import unifi.tools.security as security  # noqa: F401
import unifi.tools.topology as topology  # noqa: F401
import unifi.tools.traffic as traffic  # noqa: F401
import unifi.tools.wifi as wifi  # noqa: F401
