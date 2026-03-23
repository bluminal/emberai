# Netex Suite -- EmberAI Marketplace

## Project Structure

Three independent Python MCP server plugins in a monorepo:

```
emberai/
  unifi/       # Edge layer (UniFi networks) -- Python MCP server
  opnsense/    # Gateway layer (OPNsense firewalls) -- Python MCP server
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

All write operations across all three plugins follow the same three-step gate:
1. Env var must be set to `"true"` (`UNIFI_WRITE_ENABLED`, `OPNSENSE_WRITE_ENABLED`, or `NETEX_WRITE_ENABLED`)
2. Command must include `--apply` flag
3. Operator must confirm the presented change plan

OPNsense has an additional pattern: write (saves config) and reconfigure (applies to live) are always separate steps.

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

## Key Architectural Rules

- **Human-in-the-loop assistant model** -- NOT autonomous agent. All writes require operator confirmation.
- **OutageRiskAgent** and **NetworkSecurityAgent** run before every write plan in the netex umbrella.
- **Plugin Registry** discovers vendor plugins dynamically -- netex never hardcodes vendor names.
- **Vendor Plugin Contract v1.0.0** -- any conforming plugin can be orchestrated by netex.

## Documents

- PRD: `docs/reqs/main.md`
- Implementation Plan: `docs/plans/main.md`
