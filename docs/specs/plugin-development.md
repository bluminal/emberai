# Plugin Development Guide

Lessons learned and patterns established while building EmberAI vendor plugins. This guide supplements the [Vendor Plugin Contract](../../contract/v1.0.0/VENDOR_PLUGIN_CONTRACT.md) with practical development guidance derived from building the opnsense, unifi, and cisco plugins.

## Plugin Anatomy

Every plugin requires these files. Copy from an existing plugin rather than starting from scratch.

```
{plugin}/
  .claude-plugin/
    plugin.json              # Marketplace metadata (name, version, description)
  src/{plugin}/
    __init__.py              # Package docstring
    __main__.py              # python -m {plugin} entry point
    server.py                # FastMCP server, plugin_info(), CLI, health check
    errors.py                # Error hierarchy (extend NetexError)
    safety.py                # Write gate decorator
    cache.py                 # TTL cache with per-data-type expiration
    models/                  # Pydantic models (strict mode)
    tools/                   # MCP tool modules (@mcp_server.tool())
      __init__.py            # Imports all tool modules to trigger registration
  tests/
    conftest.py              # Shared fixtures and mock device classes
    fixtures/                # Realistic device output files for parser tests
  skills/{plugin}/
    SKILL.md                 # Claude instruction manifest (YAML frontmatter + tool docs)
  knowledge/
    INDEX.md                 # Operational lessons learned
  pyproject.toml             # Hatchling build, deps, ruff, mypy, pytest config
  run.sh                     # EmberAI bootstrap (venv + install + exec)
  settings.json              # Env var declarations for the plugin UI
  SKILL.md -> skills/...     # Symlink to the skill manifest
```

### Marketplace Registration

Two files control plugin visibility in the EmberAI plugin manager:

1. **`{plugin}/.claude-plugin/plugin.json`** in the plugin source — declares the plugin's identity:
   ```json
   {
     "name": "cisco",
     "description": "Cisco network intelligence — switch management, VLANs, ...",
     "version": "0.1.0",
     "author": { "name": "Bluminal Labs" },
     "repository": "https://github.com/bluminal/emberai",
     "license": "MIT",
     "keywords": ["cisco", "switch", "vlan", "mcp", "emberai"]
   }
   ```

2. **`.claude-plugin/marketplace.json`** at the repo root — registers the plugin in the marketplace catalog:
   ```json
   {
     "plugins": [
       { "name": "cisco", "source": "./cisco", "description": "..." }
     ]
   }
   ```

Both files are required. The plugin won't appear in `/plugin` until it's listed in both. After adding, the user runs "Update marketplace" in the plugin manager, then installs.

### run.sh Bootstrap Pattern

The bootstrap script creates a venv and installs the plugin on first run. Prefer `uv` for speed, fall back to `pip`:

```bash
#!/usr/bin/env bash
set -euo pipefail
PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${CLAUDE_PLUGIN_DATA:-$PLUGIN_DIR/.data}/.venv"

if [ ! -d "$VENV_DIR" ]; then
    if command -v uv &>/dev/null; then
        uv venv "$VENV_DIR" --python python3 -q
        uv pip install -q -e "$PLUGIN_DIR" --python "$VENV_DIR/bin/python"
    else
        python3 -m venv "$VENV_DIR"
        "$VENV_DIR/bin/pip" install -q -e "$PLUGIN_DIR"
    fi
fi

exec "$VENV_DIR/bin/python" -m {plugin} "$@"
```

## Development Phases

Build plugins in this order. Resist the urge to build write tools before read tools are solid.

### Phase 1: Read-Only Foundation

1. **Scaffold** — pyproject.toml, errors, safety gate, cache, server, models, settings
2. **Device client** — The communication layer (HTTP, SSH, SNMP, etc.)
3. **Output parsers** — If the device returns structured data (JSON/XML), parsing is trivial. If it returns CLI text, you need regex parsers with fixture-based tests.
4. **Read-only MCP tools** — Wire parsers to tools, add caching
5. **Tests** — Mock the device entirely. 80%+ coverage gate.

### Phase 2: Write Operations

6. **Config safety** — Pre-write backup mechanism appropriate to the device
7. **Write tools** — All decorated with `@write_gate`, all capturing backups before changes
8. **Verification** — Every write tool verifies its change took effect by reading back

### Phase 3: Integration

9. **Netex registry** — Entry point, plugin_info(), contract conformance
10. **Cross-vendor operations** — Unified topology, coordinated provisioning

## Patterns to Reuse

### Error Hierarchy

Extend `NetexError` with device-specific errors. Every plugin should have at minimum:

```
NetexError (base — carries status_code, endpoint, retry_hint, details)
├── AuthenticationError      # Bad credentials
├── NetworkError             # Connection failed, timeout, unreachable
├── ValidationError          # Bad input from caller
└── WriteGateError           # Safety gate blocked the operation
```

Add device-specific errors as needed (e.g., `SSHCommandError`, `CLIParseError` for CLI devices; `APIError` for REST devices).

### Write Safety Gate

All write operations across all plugins follow the same three-step gate:

1. Environment variable (`{PLUGIN}_WRITE_ENABLED=true`)
2. Apply flag (`apply=True` as keyword-only parameter)
3. Operator confirmation (handled by the conversation layer, not the plugin)

The `@write_gate("{PLUGIN}")` decorator enforces steps 1 and 2. Copy `safety.py` from an existing plugin — the implementation is identical except for the plugin name.

### TTL Cache

Every plugin gets its own `TTLCache` instance. Set per-data-type TTLs that reflect how frequently each data type changes:

| Volatility | TTL | Examples |
|------------|-----|---------|
| Static | 5-10 min | VLANs, firmware version, certificates |
| Moderate | 1-2 min | Interface config, firewall rules, routes |
| Dynamic | 30-60 sec | MAC table, DHCP leases, VPN sessions |
| Real-time | 15-30 sec | IDS alerts, traffic counters |

Invalidate relevant cache entries after write operations using `flush_by_prefix()`.

### Tool Return Pattern

MCP tools return JSON-serializable dicts, not Pydantic models directly:

```python
@mcp_server.tool()
async def plugin__skill__operation() -> dict[str, Any]:
    result = get_data()           # Returns Pydantic model
    return result.model_dump()    # Convert to dict for JSON serialization
```

For errors, return error dicts rather than raising (keeps the MCP conversation flowing):

```python
try:
    client = get_client()
    await client.connect()
except AuthenticationError:
    return {"error": "SSH authentication failed", "hint": "Check CISCO_SSH_USERNAME and CISCO_SSH_PASSWORD"}
```

### Tool Registration

Tools register via decorators at import time. The `tools/__init__.py` imports all modules to trigger registration, and `server.py` imports `tools` before starting:

```python
# tools/__init__.py
from {plugin}.tools import topology, interfaces, clients, health, config

# server.py main()
import {plugin}.tools  # noqa: F401  — triggers tool registration
mcp_server.run(transport="stdio")
```

## Testing Strategy

### Mock Everything — No Real Devices

Tests must never contact real hardware. Create a mock device class in `conftest.py` that simulates the device's interface:

- **REST API devices** — Mock `httpx.AsyncClient` responses with fixture JSON files
- **SSH CLI devices** — Mock `netmiko.ConnectHandler` with a class that returns fixture text files for each command
- **SNMP devices** — Mock `pysnmp` engine calls with fixture OID/value tuples

### Fixture Files

Store realistic device output in `tests/fixtures/`. Include:

- **Happy path** — Normal output with typical data
- **Empty results** — Empty tables, no neighbors, no entries
- **Edge cases** — Single entry, maximum entries, multi-line values

Name fixtures after the command they represent: `show_vlan.txt`, `show_interfaces_status.txt`, etc.

### Coverage Threshold

Set `fail_under = 80` in pyproject.toml. Server startup code (`main()`, `_run_check()`) is acceptable to exclude — it requires a running MCP server or device connection.

### Test Categories

| Category | What to test | Mock target |
|----------|-------------|-------------|
| Parser tests | CLI/API output parsing into models | Pure functions, no mocking needed |
| Client tests | Connection, auth, reconnect, error mapping | Device communication library |
| Tool tests | End-to-end tool execution, caching, validation | Device client |
| Safety tests | Write gate env var + apply flag enforcement | Environment variables |
| Model tests | Pydantic validation, serialization, field validators | None |

## Device Communication Patterns

### REST API Devices (e.g., OPNsense, UniFi Cloud)

- Use `httpx.AsyncClient` with configurable base URL, auth, and SSL verification
- Normalize response envelopes — strip vendor-specific wrappers
- Handle pagination if the API uses it

### SSH CLI Devices (e.g., Cisco SG-300)

- Use [Netmiko](https://github.com/ktbyers/netmiko) by Kirk Byers (MIT license) — it has device-type-specific drivers that handle prompt detection, pagination, and CLI quirks
- Wrap all Netmiko calls in `asyncio.to_thread()` since Netmiko is synchronous
- Use `asyncio.Lock` to serialize commands — many devices have very limited concurrent SSH sessions
- Singleton connection pattern with auto-reconnect

### SNMP Devices

- Use `pysnmp-lextudio` (the maintained community fork of pysnmp)
- Use numeric OIDs (e.g., `1.3.6.1.2.1.2.2.1.2`) rather than MIB names — not all devices have MIBs loaded
- SNMP is best for monitoring (interface counters, MAC table polling); use SSH/REST for configuration

### Legacy Device SSH Considerations

Older devices may only support deprecated SSH algorithms (SHA1 key exchange, CBC ciphers). Netmiko handles this automatically for known device types. Document any SSH negotiation quirks in the plugin's `knowledge/` directory so operators aren't surprised.

## SKILL.md Authoring

The SKILL.md is the plugin's instruction manual for Claude. It must contain:

1. **YAML frontmatter** — `netex_vendor`, `netex_role`, `netex_skills`, `netex_contract_version`
2. **Authentication section** — Required and optional env vars, what each does
3. **Interaction model** — Human-in-the-loop, write gate, confirmation flow
4. **Tool signatures** — Every tool with parameters, return type, and one-line description
5. **Command examples** — Common workflows (scan, health, diagnose)
6. **Safety warnings** — Device-specific risks (e.g., no rollback, destructive array replacements)

Keep tool signatures accurate to the actual code. Stale SKILL.md tool docs cause Claude to call tools with wrong parameters.

## Knowledge Base

Each plugin should maintain a `knowledge/` directory with operational lessons. Entries should document:

- **Device quirks** — CLI syntax differences, API version incompatibilities, firmware-specific behaviors
- **Safety-critical patterns** — Destructive API behaviors, no-rollback situations, array replacement risks
- **Troubleshooting** — Common failure modes and their solutions

Mark entries with severity (`critical`, `warning`, `informational`) and triggers (keywords that indicate when the entry is relevant).

## Dependency Management

- Pin major versions with compatible ranges (`>=4.0,<5`) not exact pins
- Check dependencies for vulnerabilities before adding (use Sonatype MCP tools if available)
- Dev dependencies (pytest, ruff, mypy, coverage) go in `[dependency-groups] dev`
- Give credit to significant library authors in README.md — especially for libraries that do the heavy lifting (e.g., Netmiko for SSH, httpx for HTTP)

## pyproject.toml Checklist

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{plugin}"]

[project]
name = "{plugin}"
version = "0.1.0"
requires-python = ">=3.12"
license = "MIT"

[project.scripts]
{plugin}-server = "{plugin}.server:main"

[project.entry-points."netex.plugins"]
{plugin} = "{plugin}.server:plugin_info"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "N", "UP", "B", "SIM", "TCH", "RUF"]

[tool.ruff.lint.isort]
known-first-party = ["{plugin}"]

[tool.mypy]
python_version = "3.12"
strict = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.coverage.run]
source = ["src/{plugin}"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

## Common Mistakes

1. **Writing to the plugin cache directly** — Always edit source code in the repo, then refresh the marketplace cache. The cache is a deployment artifact, not a source of truth.

2. **Building write tools before read tools** — Write tools depend on read tools for verification. If `show vlan` parsing is broken, `create_vlan` verification will silently fail.

3. **Hardcoding device-specific values** — Use env vars for anything that varies between deployments (host, credentials, community strings). The plugin should work on anyone's hardware.

4. **Testing against real devices** — Tests must be fully mock-based. Real devices make tests flaky, slow, and impossible to run in CI.

5. **Skipping the config backup before writes** — Devices without candidate configs or rollback mechanisms need explicit pre-write snapshots. Always capture state before mutating it.

6. **Forgetting to invalidate cache after writes** — A `create_vlan` that doesn't flush the VLAN cache will show stale data on the next `list_vlans` call.

7. **Returning Pydantic models from MCP tools** — Tools must return JSON-serializable dicts. Use `model.model_dump()`.

8. **Not adding the plugin to marketplace.json** — The plugin won't appear in `/plugin` without both `.claude-plugin/plugin.json` (in the plugin source) AND an entry in the repo-root `.claude-plugin/marketplace.json`.
