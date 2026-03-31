# Netex Suite -- EmberAI Marketplace

## Project Structure

Four independent Python MCP server plugins in a monorepo:

```
emberai/
  unifi/       # Edge layer (UniFi networks) -- Python MCP server
  opnsense/    # Gateway layer (OPNsense firewalls) -- Python MCP server
  nextdns/     # DNS layer (NextDNS profiles & analytics) -- Python MCP server
  netex/       # Umbrella orchestrator (cross-vendor) -- Python MCP server
  docs/        # GitHub Pages (MkDocs Material)
  contract/    # Vendor Plugin Contract v1.0.0 spec
```

Each plugin has its own `pyproject.toml` and is independently installable. No shared code between plugins at the package level.

## Stack

- Python 3.12
- `mcp` SDK -- MCP server with `@server.tool()` registration, dual transport (stdio + Streamable HTTP)
- `httpx` -- async HTTP client
- `pydantic` -- data models with strict mode
- `python-dotenv` -- env var loading

## Tool Naming Convention

All MCP tools follow: `{plugin}__{skill}__{operation}`

```
unifi__topology__list_devices(site_id)
opnsense__firewall__list_rules(interface?)
```

## Testing

- `pytest` + `pytest-asyncio` + `coverage`
- 80% coverage threshold
- Mock httpx responses for API client tests
- Test write gate enforcement (env var disabled, --apply missing)

## Linting & Type Checking

- `ruff` for linting
- `mypy` for type checking (strict mode)

## Write Safety Gate

All write operations across all four plugins follow the same three-step gate:
1. Env var must be set to `"true"` (`UNIFI_WRITE_ENABLED`, `OPNSENSE_WRITE_ENABLED`, `NEXTDNS_WRITE_ENABLED`, or `NETEX_WRITE_ENABLED`)
2. Command must include `--apply` flag
3. Operator must confirm the presented change plan

OPNsense has an additional pattern: write (saves config) and reconfigure (applies to live) are always separate steps.
NextDNS has additional safeguards: profile deletion requires `--delete-profile` flag, log clearing requires `--clear-logs` flag.

## Environment Variables

| Variable | Plugin | Purpose |
|---|---|---|
| `UNIFI_LOCAL_HOST` | unifi | IP/hostname of UniFi local gateway |
| `UNIFI_LOCAL_KEY` | unifi | API key for local gateway |
| `UNIFI_API_KEY` | unifi | API key for Cloud V1 / Site Manager |
| `OPNSENSE_HOST` | opnsense | OPNsense instance URL (include scheme) |
| `OPNSENSE_API_KEY` | opnsense | API key (Basic Auth username) |
| `OPNSENSE_API_SECRET` | opnsense | API secret (Basic Auth password) |
| `OPNSENSE_VERIFY_SSL` | opnsense | Set to "false" for self-signed certs |
| `OPNSENSE_USERNAME` | opnsense | Web UI username (for legacy page operations) |
| `OPNSENSE_PASSWORD` | opnsense | Web UI password (for legacy page operations) |
| `NEXTDNS_API_KEY` | nextdns | API key from https://my.nextdns.io/account |
| `NEXTDNS_WRITE_ENABLED` | nextdns | Set to "true" to enable profile mutations |

## Key Architectural Rules

- **Human-in-the-loop assistant model** -- NOT autonomous agent. All writes require operator confirmation.
- **OutageRiskAgent** and **NetworkSecurityAgent** run before every write plan in the netex umbrella.
- **Plugin Registry** discovers vendor plugins dynamically -- netex never hardcodes vendor names.
- **Vendor Plugin Contract v1.0.0** -- any conforming plugin can be orchestrated by netex.

## Critical Safety Rules

### NEVER send partial array replacements to vendor APIs

Several vendor APIs (notably UniFi Controller) use PUT endpoints where sending an array **replaces the entire array**, not just the entries you include. Sending a partial `port_overrides` array to a UniFi switch wipes all port profiles, VLAN assignments, link aggregation groups, and PoE settings — causing network-wide outages.

**Mandatory pattern for ALL array-modifying write operations:**
1. READ the full current state first
2. MODIFY only the specific entry you need to change
3. WRITE the complete modified array back (with all original entries preserved)

See `unifi/knowledge/switch-port-overrides.md` and `netex/knowledge/destructive-api-patterns.md` for details.

### NEVER use raw API calls to bypass plugin tool safety

Plugin tools encapsulate read-modify-write patterns and safety checks. When a plugin tool exists for an operation, use it instead of raw `curl` or direct API calls. If a tool doesn't exist, build one with proper safety checks before performing the operation.

## Plugin Knowledge Base

Each plugin may have a `knowledge/` directory with operational lessons learned. Before making changes in a topic area, check the relevant plugin's `knowledge/INDEX.md` for matching entries and read any files whose triggers match the current task. This is especially important for entries marked `severity: critical`.

## Documents

- PRD: `docs/reqs/main.md`
- Implementation Plan: `docs/plans/main.md`
