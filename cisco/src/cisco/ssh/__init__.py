"""SSH client for Cisco SG-300 managed switches.

Provides an async-compatible wrapper around Netmiko's ``ConnectHandler``
with ``device_type="cisco_s300"``.  All blocking Netmiko calls are
dispatched via :func:`asyncio.to_thread` so the MCP event loop is never
blocked.

Usage::

    from cisco.ssh import get_client

    client = get_client()
    await client.connect()
    output = await client.send_command("show vlan")
"""

from cisco.ssh.client import CiscoSSHClient, get_client

__all__ = [
    "CiscoSSHClient",
    "get_client",
]
