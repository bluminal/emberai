# NextDNS Plugin Overview

The **nextdns** plugin provides DNS layer intelligence for NextDNS deployments. It covers DNS profile configuration, security posture auditing, analytics dashboards, query log analysis, and parental control management across all NextDNS profiles linked to an account.

## What the Plugin Covers

- **Profile management** -- inventory all profiles with configuration summaries, inspect individual profile settings, create and rename profiles
- **Security auditing** -- audit all 12 security toggles, evaluate blocklist coverage, detect overly broad allowlists, flag missing protections
- **Privacy controls** -- blocklist management, native tracking protection, disguised tracker detection, affiliate link settings
- **Parental controls** -- SafeSearch enforcement, YouTube restricted mode, service blocking (TikTok, Instagram, etc.), category blocking, bypass prevention
- **Analytics dashboards** -- query volume, block rates, top domains, top devices, protocol breakdown, encryption status, DNSSEC validation
- **Query log analysis** -- search logs by domain/device/status, poll-based live streaming, bulk download, log clearing
- **Profile comparison** -- side-by-side diff of security, privacy, parental, and general settings between any two profiles

## What the Plugin Does NOT Cover

The nextdns plugin is scoped to the DNS layer. It does **not** manage:

- **Routing and gateways** -- static routes, dynamic routing, gateway configuration
- **Firewall rules** -- zone-based firewall, ACLs, NAT, port forwarding
- **VPN tunnels** -- IPSec, WireGuard, OpenVPN
- **Physical network topology** -- switches, access points, cabling, VLANs on switch ports

These belong to the **opnsense** plugin (gateway layer) and **unifi** plugin (edge layer). When all three plugins are installed, the **netex** umbrella orchestrator coordinates cross-vendor workflows including DNS trace analysis.

## API

The plugin communicates with NextDNS through a single REST API:

| Endpoint | Authentication | Rate Limit |
|----------|---------------|------------|
| `https://api.nextdns.io` | `X-Api-Key` header | Respect 429 with exponential backoff |

The API key is obtained from [my.nextdns.io/account](https://my.nextdns.io/account) and provides access to all profiles associated with the account.

Response envelopes from the API follow a consistent `{data: ...}` pattern. The plugin normalizes all responses into typed Pydantic models before returning results.

## Architecture

The plugin is structured in three layers:

```
Commands (user-facing)
  nextdns profiles, nextdns analytics, nextdns audit, nextdns logs, nextdns manage
    |
Agents (orchestration)
  scan agent, health agent, analytics agent, logs agent, secure agent
    |
Tools (MCP tools -- direct API calls)
  profiles skill (8 read + 12 write), analytics skill (11 tools),
  logs skill (4 tools), security-posture skill (2 tools)
```

**Tools** are thin MCP-registered functions that make a single API call and return normalized data. Each tool follows the naming convention `nextdns__{skill}__{operation}`.

**Agents** orchestrate multiple tools to produce a complete report. For example, the audit agent calls `get_security`, `get_privacy`, `get_denylist`, and `get_allowlist`, then classifies findings by severity.

**Commands** are the user-facing entry points. Each command delegates to an agent function and returns a formatted report.

## Authentication

The plugin requires the following environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXTDNS_API_KEY` | Yes | API key from [my.nextdns.io/account](https://my.nextdns.io/account) |

Optional variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXTDNS_WRITE_ENABLED` | `false` | Set to `"true"` to enable write operations |
| `NETEX_CACHE_TTL` | `300` | Override TTL for cached responses (seconds) |

On startup, the plugin verifies the API key is set. If missing, it reports which variable is absent and what it is used for, without attempting any API calls.

## Read-Only by Default

The nextdns plugin operates in **read-only mode** by default. All read commands (`profiles`, `analytics`, `audit`, `logs`) work without any write gate configuration.

Write operations require:

1. `NEXTDNS_WRITE_ENABLED` set to `"true"`
2. The `--apply` flag on the command
3. Explicit operator confirmation of the change plan

Destructive operations carry additional safety gates:

- **Profile deletion** requires both `--apply` and `--delete-profile` flags
- **Log clearing** requires both `--apply` and `--clear-logs` flags

## Quick Start

### Install

```bash
pip install -e ./nextdns
```

### Configure

```bash
export NEXTDNS_API_KEY="your-api-key"    # From my.nextdns.io/account
```

### Verify

```bash
nextdns-server --check
```

### First Commands

```
You: Show me my NextDNS profiles
You: Audit the security of my DNS profiles
You: Show DNS analytics for profile abc123
```

## Related Documentation

- [Commands Reference](commands.md) -- all commands with parameters and examples
- [Skills Reference](skills.md) -- individual MCP tool documentation
- [Workflows](workflows/) -- step-by-step workflow examples
- [Authentication Setup](../getting-started/authentication.md) -- API key configuration
