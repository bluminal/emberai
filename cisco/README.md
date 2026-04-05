# cisco -- Cisco SG-300 Managed Switch Plugin

Intelligent Cisco SG-300 managed switch control for [EmberAI](https://github.com/bluminal/emberai). Query, analyze, and manage your Cisco SG-300 switch through natural language -- from VLAN management and port configuration to MAC address table lookups and LLDP topology discovery.

Part of the [Netex](https://github.com/bluminal/emberai) plugin suite. Works standalone or alongside the unifi and opnsense plugins for full-stack network intelligence.

## Acknowledgments

This plugin uses [Netmiko](https://github.com/ktbyers/netmiko) by Kirk Byers for SSH CLI automation. Netmiko is licensed under the MIT License. Netmiko provides reliable, multi-vendor SSH connectivity and is the foundation of all CLI interactions in this plugin.

## What It Does

The cisco plugin covers the **edge switching layer** via SSH CLI (Netmiko) and SNMP:

- **VLAN management** -- list, create, and assign VLANs to ports
- **Port configuration** -- access/trunk mode, speed, duplex, descriptions, enable/disable
- **MAC address table** -- dynamic and static MAC lookups by port, VLAN, or address
- **LLDP topology** -- discover connected devices and build physical topology maps
- **Interface counters** -- traffic statistics, error rates, discard counts
- **Spanning tree** -- STP status and port roles
- **Health monitoring** -- firmware version, uptime, CPU/memory via SNMP
- **Running config** -- read-only config inspection

## Architecture

```
                 MCP Server (FastMCP)
                        |
              +---------+---------+
              |                   |
         SSH (Netmiko)       SNMP (pysnmp)
         device_type=        v2c community
         cisco_s300          string polls
              |                   |
              +-------------------+
                        |
                 Cisco SG-300 Switch
```

- **SSH CLI via Netmiko** -- All configuration reads and writes go through Netmiko's `ConnectHandler` with `device_type="cisco_s300"`. Blocking Netmiko calls are dispatched via `asyncio.to_thread` so the MCP event loop is never blocked.
- **SNMP for monitoring** -- Interface counters, CPU/memory utilization, and other polled metrics use SNMP v2c for efficient bulk retrieval without CLI overhead.

## Quick Install

### Prerequisites

- Python 3.12 or later
- SSH access to a Cisco SG-300 switch (SSH must be enabled on the switch)
- SNMP v2c community string configured on the switch (for monitoring features)

### Install

```bash
pip install -e ./cisco
```

### Configure

Set the required environment variables:

```bash
export CISCO_HOST="192.168.1.254"          # Switch IP or hostname
export CISCO_SSH_USERNAME="admin"           # SSH username
export CISCO_SSH_PASSWORD="your-password"   # SSH password
```

Or create a `.env` file in the project root:

```env
CISCO_HOST=192.168.1.254
CISCO_SSH_USERNAME=admin
CISCO_SSH_PASSWORD=your-password
```

Optional configuration:

```bash
export CISCO_ENABLE_PASSWORD=""             # Enable password (if configured)
export CISCO_SNMP_COMMUNITY="public"        # SNMP community string
export CISCO_VERIFY_SSH_HOST_KEY="false"    # Skip host key verification
```

### Run

```bash
# Start the MCP server (stdio transport)
cisco-server

# Test connectivity
cisco-server --check

# Or run directly
python -m cisco
```

### Verify

After starting the server, test connectivity:

```bash
cisco-server --check
```

Expected output on success:

```
cisco: running startup health check ...

  [PASS] CISCO_HOST = *.*.*. 254
  [PASS] CISCO_SSH_USERNAME = admin
  [PASS] CISCO_SSH_PASSWORD = ****rd
  [INFO] CISCO_ENABLE_PASSWORD = (default: )
  [INFO] CISCO_SNMP_COMMUNITY = ****ic
  [INFO] CISCO_WRITE_ENABLED = false
  [INFO] CISCO_VERIFY_SSH_HOST_KEY = true
  [INFO] NETEX_CACHE_TTL = 300

  Probing Cisco SG-300 at *.*.*.254 via SSH ...
  [PASS] Cisco SG-300 reachable: SSH OK to *.*.*.254: SW version 1.4.11.02

cisco: health check PASSED
```

## Read-Only by Default

The cisco plugin operates in **read-only mode** by default. All show, inventory, and topology commands are read-only.

Write operations (VLAN creation, port configuration changes) require three gates:

1. `CISCO_WRITE_ENABLED` set to `"true"`
2. The `--apply` flag on the command
3. Explicit operator confirmation of the change plan

Unlike OPNsense, the SG-300 applies configuration changes immediately via CLI -- there is no separate "reconfigure" step. However, changes are to the running config only; `write memory` is a separate confirmed operation.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CISCO_HOST` | Yes | -- | IP or hostname of the Cisco SG-300 switch |
| `CISCO_SSH_USERNAME` | Yes | -- | SSH username for CLI access |
| `CISCO_SSH_PASSWORD` | Yes | -- | SSH password for CLI access |
| `CISCO_ENABLE_PASSWORD` | No | (empty) | Enable password for privileged EXEC mode |
| `CISCO_SNMP_COMMUNITY` | No | `public` | SNMP v2c community string for monitoring |
| `CISCO_WRITE_ENABLED` | No | `false` | Set to `"true"` to enable write operations |
| `CISCO_VERIFY_SSH_HOST_KEY` | No | `true` | Set to `"false"` to skip SSH host key checks |
| `NETEX_CACHE_TTL` | No | `300` | Override cache TTL in seconds |

## Development

```bash
# Install with dev dependencies
pip install -e "./cisco[dev]"

# Run tests
pytest

# Run tests with coverage
coverage run -m pytest && coverage report

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

### Project Structure

```
cisco/
  src/cisco/
    ssh/              # Netmiko SSH client wrapper
    snmp/             # SNMP polling client
    parsers/          # CLI output parsers (regex-based, no TextFSM)
    models/           # Pydantic data models (strict mode)
    tools/            # MCP tool implementations
    server.py         # MCP server setup and entry point
    safety.py         # Write safety gate
    cache.py          # TTL cache with stampede protection
    errors.py         # Structured error hierarchy
  tests/
    fixtures/         # Mock CLI output for testing
    ...
  run.sh              # Plugin launcher script
  settings.json       # Env var declarations for EmberAI
  pyproject.toml
  README.md
```

### Testing

All tests use mock-based testing against virtual Cisco device responses. No real hardware is needed or contacted during testing:

- Mock Netmiko `ConnectHandler` with pre-recorded CLI output
- Mock SNMP responses with known OID/value pairs
- Test fixtures in `tests/fixtures/` contain sample CLI output from SG-300 switches

## License

MIT -- see [LICENSE](../LICENSE) for details.

## Author

[Bluminal Labs](https://bluminal.com)
