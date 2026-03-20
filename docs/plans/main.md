# Implementation Plan: Netex Suite

## Overview

Netex is a three-plugin network intelligence suite for the EmberAI marketplace: **unifi** (edge layer), **opnsense** (gateway layer), and **netex** (cross-vendor umbrella orchestrator). This plan implements the full PRD (`docs/reqs/main.md`) across 5 plan phases. Phase 1 goes deep on core unifi skills via the Local Gateway API. Phase 2 completes unifi and scaffolds opnsense. Phase 3 completes opnsense. Phase 4 builds the netex umbrella. Phase 5 adds advanced features.

All plugins are independent Python MCP servers (Python 3.12, `mcp` SDK, `httpx` async HTTP, transport via CLI flag `--transport stdio|http`). Each follows the Vendor Plugin Contract v1.0.0 (`{plugin}__{skill}__{operation}` tool naming, SKILL.md manifests). Write operations are gated by env var + `--apply` flag + operator confirmation.

### Plan-to-PRD Phase Mapping

The plan uses a depth-first approach (D2) that restructures the PRD's breadth-first roadmap. Plan phases do NOT correspond 1:1 with PRD phases.

| Plan Phase | PRD Phase(s) Covered | Scope |
|---|---|---|
| Plan Phase 1 (v0.1.0-plan) | PRD Phase 1 partial (Local Gateway only, no Cloud V1) | unifi scaffold + Local Gateway API + topology/health/clients skills + 4 commands + docs |
| Plan Phase 2 (v0.1.1-plan) | PRD Phase 1 remainder + PRD Phase 2 scaffold | Cloud V1 client + remaining unifi read skills + unifi write ops + opnsense scaffold |
| Plan Phase 3 (v0.2.0-plan) | PRD Phase 2 core | opnsense complete |
| Plan Phase 4 (v0.3.0-plan) | PRD Phase 3 | netex umbrella complete |
| Plan Phase 5 (v0.4-0.5-plan) | PRD Phases 4-5 | Redis, Site Manager EA, advanced features |

## Decisions

| # | Decision | Context | Rationale |
|---|----------|---------|-----------|
| D1 | Local Gateway API first, Cloud V1 second, Site Manager EA last | PRD defines 3 API tiers for unifi. User confirmed Local Gateway priority. | Richest API surface, no rate limits, available for live testing. Cloud V1 adds multi-site in Phase 2. Site Manager EA deferred to Phase 5 (graduation timeline uncertain -- OQ1). |
| D2 | Depth-first: complete core unifi skills before starting opnsense | PRD roadmap is breadth-first (plugin per phase). User prefers depth. | Solo dev benefits from mastering one API surface before context-switching. Ensures unifi v0.1.0 is production-quality. |
| D3 | Python 3.12 + httpx + mcp SDK | User specified stack. | httpx provides native async HTTP. mcp SDK provides `@server.tool()` registration. |
| D4 | pytest + pytest-asyncio + coverage (80% threshold) | User specified testing stack. | Async-first plugin code requires pytest-asyncio. 80% matches existing EmberAI conventions. |
| D5 | Monorepo with independent pyproject.toml per plugin | PRD specifies `emberai/unifi/`, `emberai/opnsense/`, `emberai/netex/` layout. | Each plugin is independently installable and publishable. Shared nothing between plugins at the code level -- umbrella coordinates via MCP tool calls and the Plugin Registry. |
| D6 | GitHub Actions CI: lint + type-check + test on PR | User specified CI approach. | ruff for linting, mypy for type checking, pytest for tests. Single workflow file per plugin. |
| D7 | MkDocs Material for docs, scaffolded in Phase 1, content in each phase | PRD Section 9 requires docs-as-code with GitHub Pages. | Scaffold early so every phase ships with documentation. Versioning via `mike` plugin added in Phase 5. |
| D8 | Write Safety Gate is a shared pattern, implemented identically in each plugin | PRD Section 6.2 defines the three-step gate. | Env var check + `--apply` flag + operator confirmation. Implemented as a decorator/utility in each plugin's `src/` -- not a shared package (D5). |
| D9 | TTL cache implemented as in-memory dict with TTL per data type | PRD Section 6.3 defines per-data-type TTLs. Redis caching deferred to Phase 5. | Simple in-memory cache is sufficient for single-instance MCP servers. Redis adds complexity only needed at MSP scale. |
| D10 | Vendor Plugin Contract v1.0.0 spec written in Phase 4 alongside netex umbrella | Contract must be stable before third-party plugin authors consume it. | Writing the spec alongside the umbrella ensures the contract is validated by real usage. Published to `contract/v1.0.0/`. |
| D11 | `OPNSENSE_VERIFY_SSL` env var (not in PRD) | OPNsense commonly uses self-signed certs. Plan adds this env var to toggle SSL verification. | Plan-originated decision. Common operational need for self-hosted OPNsense instances. Default: `true`. |
| D12 | Plugin Registry discovery via Python entry points | Q9 resolved. Options evaluated: filesystem scan, env var list, config file, Python entry points. | Entry points (`[project.entry-points."netex.plugins"]`) are the standard Python mechanism for plugin discovery. Each vendor plugin declares its entry point in `pyproject.toml`. The registry calls `importlib.metadata.entry_points(group="netex.plugins")` at startup. No config files needed; works with pip install. Design spike in Phase 1 M1.1 validates approach. |
| D13 | Transport mode via CLI flag, not simultaneous | `mcp` SDK may not support both stdio + HTTP simultaneously. | CLI flag `--transport stdio|http` selects one transport mode per invocation. Default: `stdio` for local dev, `http` for production. |
| D14 | Structured error hierarchy shared across plugins | No error taxonomy leads to inconsistent error handling per plugin. | `NetexError -> AuthenticationError, RateLimitError, NetworkError, APIError, ValidationError, WriteGateError`. Each plugin implements the same hierarchy in `errors.py`. |
| D15 | Rollback workflow state machine | Q5 resolved for design phase. Rollback requires persistent state to handle partial failures. | States: `planned -> executing -> step-N-complete -> failed-at-step-N -> rolling-back -> rollback-complete | rollback-failed`. Design task in Phase 4 M4.1 before orchestrator implementation. |

## Open Questions

| # | Question | Impact | Status |
|---|----------|--------|--------|
| Q1 | Site Manager EA graduation timeline -- will Ubiquiti promote EA endpoints to stable v1? | Affects Phase 5 multi-site full support. If EA graduates, simplifies OAuth flow. | Open -- monitor `developer.ui.com` |
| Q2 | OPNsense multi-instance support -- should opnsense plugin support multiple OPNsense instances (HA pair, multiple sites)? | Phase 3 targets single-instance. Multi-instance adds credential management complexity. | Open -- decide at Phase 3 kickoff |
| Q3 | Local connectivity: how does a remote MCP server reach UniFi local gateway and OPNsense? | Affects deployment guide. Options: VPN, Site Magic, reverse proxy. | Open -- needs deployment guide in Phase 1 |
| Q4 | EmberAI tool registry dependency declaration -- how does netex SKILL.md declare vendor plugin dependencies at runtime? | Affects Plugin Registry discovery in Phase 4. | Open -- decide at Phase 4 kickoff |
| Q5 | Rollback atomicity: if cross-vendor rollback itself fails, what state model persists the workflow? | Resolved in principle (D15). Detailed design in Phase 4 M4.1. | Resolved -> D15 |
| Q6 | OPNsense Quagga plugin dependency -- routing skill needs graceful degradation if Quagga not installed. | Affects Phase 3 routing skill. Must detect and degrade, not fail. | Open -- resolve in Phase 3 |
| Q7 | UniFi Protect API integration -- API not publicly documented. | Deferred to Phase 5. No impact on Phases 1-4. | Open -- Phase 5 |
| Q8 | Vendor Plugin Contract versioning -- deprecation policy for breaking changes to third-party plugin authors. | Affects Phase 4 contract spec. Need changelog and migration policy. | Open -- resolve in Phase 4 |
| Q9 | Plugin Registry discovery mechanism -- how does the registry detect installed vendor plugins at runtime? | Resolved. Python entry points (D12). Design spike in Phase 1 validates. | Resolved -> D12 |
| Q10 | Cross-vendor workflow with 3+ vendors -- how does `vlan configure` determine sequencing with gateway + edge + hypervisor? | Phase 4 designs for 2 vendors. 3+ vendor support needs role-based dependency graph. | Open -- resolve in Phase 4 |

---

## Plan Phase 1: unifi Core -- Local Gateway Intelligence (v0.1.0-plan)

### Milestone 1.1: Project Scaffold + CI + Foundations

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 1 | Create `unifi/pyproject.toml` with dependencies: `mcp`, `httpx`, `pydantic`, `python-dotenv`. Dev deps: `pytest`, `pytest-asyncio`, `coverage`, `ruff`, `mypy`. Define `[project.scripts]` entry point for MCP server. Add `[project.entry-points."netex.plugins"]` entry point for Plugin Registry discovery (D12). | M | None | done |
| 2 | Create directory structure: `unifi/src/{agents,api,tools,models}/` with `__init__.py` files. Create `unifi/tests/` with conftest.py. Create `.env.example` with all env vars documented (required + optional). | S | None | done |
| 3 | Create `unifi/SKILL.md` from PRD Appendix A (YAML frontmatter + overview + auth + interaction model sections). | M | None | done |
| 4 | Create MCP server entry point (`unifi/src/server.py`): initialize `mcp.Server`, configure transport via `--transport stdio|http` CLI flag (D13), env var loading and validation (`UNIFI_LOCAL_HOST`, `UNIFI_LOCAL_KEY`, `UNIFI_WRITE_ENABLED`, `UNIFI_API_KEY` [optional -- used in Phase 2]). Add `--check` flag for startup health probe (verify env vars set, attempt API connectivity, report status, exit). Add structured logging (`structlog` or stdlib logging with JSON formatter). | M | Task 1 | done |
| 5 | Create GitHub Actions CI workflow (`.github/workflows/unifi.yml`): ruff lint, mypy type-check, pytest with coverage (80% threshold). Trigger on PR changes to `unifi/`. | M | Task 1 | done |
| 6 | Create `unifi/src/errors.py`: error hierarchy per D14 (`NetexError -> AuthenticationError, RateLimitError, NetworkError, APIError, ValidationError, WriteGateError`). All errors carry structured context (status code, endpoint, retry hint). | M | None | done |
| 7 | Create `unifi/src/cache.py`: TTL cache with per-key TTL, asyncio.Lock for concurrent access safety, stampede protection (single-flight pattern: concurrent requests for the same key await the first fetch), max_size with LRU eviction, manual flush method. | M | None | done |
| 8 | Create `unifi/src/safety.py`: write gate decorator -- checks env var `{PLUGIN}_WRITE_ENABLED`, validates `--apply` flag present, returns structured "write blocked" error with reason if either check fails. Does NOT handle operator confirmation (that is the agent/command layer's responsibility per PRD 10.2). | M | None | done |
| 9 | Create `unifi/src/output.py`: OX output formatting module. Defines standard formatters for: severity-tiered reports (Critical/Warning/Informational sections), device/client tables, key-value detail views, diff views, risk assessment blocks. All agents and commands use OX formatters -- no ad-hoc string building. | M | None | done |
| 10 | Create `unifi/src/ask.py`: AskUserQuestion utility implementing PRD Section 10.4 patterns. Templates for: assumption resolution (Phase 1 batch), plan presentation with single confirmation (Phase 2->3), outage risk callouts (CRITICAL/HIGH), mid-execution failure reporting, plan modification re-confirmation. | M | None | done |
| 11 | Create base Pydantic models in `unifi/src/models/`: `Site`, `Device`, `Client`, `VLAN`, `Event`, `HealthStatus`, `FirmwareStatus`. Use strict mode, field aliases for API response normalization. | M | None | done |
| 12 | Plugin Registry discovery spike: validate that Python entry points approach (D12) works end-to-end. Create a minimal test that registers `unifi` as an entry point and discovers it via `importlib.metadata.entry_points()`. Document findings. If entry points don't work for the use case, update D12. | S | Task 1 | done |
| 13 | Create `unifi/tests/test_safety.py`: test write gate decorator -- env var enabled/disabled, --apply present/missing, error message content. Create `unifi/tests/test_cache.py`: test TTL expiry, concurrent access, stampede protection, LRU eviction, manual flush. Create `unifi/tests/fixtures/`: realistic mock UniFi API response JSON files for topology, health, clients. | M | Tasks 7-8 | done |

**Parallelizable:** Tasks 1-3, 5-11 can all run concurrently (max 10). Tasks 4, 12, 13 have dependencies.
**Milestone Value:** Runnable MCP server skeleton with CI pipeline, structured errors, safe caching, write gate, output formatting, and AskUserQuestion patterns. `python -m unifi.src.server` starts without errors. Tests pass. Lint clean.

### Milestone 1.2: Local Gateway API Client

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 14 | Create `unifi/src/api/local_gateway_client.py`: async httpx client, base URL from `UNIFI_LOCAL_HOST`, X-API-KEY auth header from `UNIFI_LOCAL_KEY`, SSL verification toggle, request/response logging via structlog, error handling using error hierarchy (D14) -- map 401->AuthenticationError, 429->RateLimitError, 5xx->APIError, timeout->NetworkError. | L | M1.1 | done |
| 15 | Implement response normalization: unwrap `{data, count, totalCount}` envelope into clean data. Handle pagination for list endpoints. | M | Task 14 | done |
| 16 | Integrate TTL cache into API client: cache GET responses with configurable TTL per endpoint category (device list: 5 min, client list: 30 sec, events: no cache). Cache key = endpoint + params. Manual flush method. | M | Tasks 7, 14 | done |
| 17 | Write comprehensive tests for local gateway client: mock httpx responses, test auth header injection, response normalization, cache hit/miss/expiry, error handling for all status codes, pagination. Use fixtures from Task 13. | L | Tasks 14-16 | done |

**Parallelizable:** Task 14 must complete first. Tasks 15 and 16 can run concurrently after Task 14. Task 17 after all.
**Milestone Value:** Verified API client that can authenticate, make requests, normalize responses, and cache results. All tested with mocks.

### Milestone 1.3: Topology Skill + Tools

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 18 | Implement `unifi__topology__list_devices(site_id)` tool: call local API `/api/s/{site}/stat/device`, normalize to `Device` model, register via `@server.tool()`. | M | M1.2 | done |
| 19 | Implement `unifi__topology__get_device(device_id)` tool: fetch single device with port_table, uplink, vlan_assignments, radio_table. | M | M1.2 | done |
| 20 | Implement `unifi__topology__get_vlans(site_id)` tool: call `/api/s/{site}/rest/networkconf`, normalize to `VLAN` model. | M | M1.2 | done |
| 21 | Implement `unifi__topology__get_uplinks(site_id)` tool: derive uplink graph from device port_table and uplink fields. Return device-to-device relationships. | M | Task 18 | done |
| 22 | Create topology agent (`unifi/src/agents/topology.py`): orchestrates topology tools to build a complete site map. Uses OX formatters for output. Used by `unifi scan` command. | M | Tasks 18-21 | done |
| 23 | Write tests for all topology tools: mock API responses with realistic UniFi data (use fixtures), verify model normalization, test edge cases (offline devices, empty VLANs, single-device sites). | L | Tasks 18-21 | done |

**Parallelizable:** Tasks 18, 19, 20 can run concurrently. Task 21 depends on 18. Task 22 depends on 18-21. Task 23 can start alongside Task 22.
**Milestone Value:** `unifi scan` can discover and map all devices, VLANs, and uplinks for a site. Live-testable against real UniFi hardware.

### Milestone 1.4: Health Skill + Tools

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 24 | Implement `unifi__health__get_site_health(site_id)` tool: call `/api/s/{site}/stat/health`, return WAN/LAN/WLAN/WWW status, device counts. | M | M1.2 | done |
| 25 | Implement `unifi__health__get_device_health(device_id)` tool: uptime, CPU, memory, temperature, satisfaction score, firmware upgrade availability. | M | M1.2 | done |
| 26 | Implement `unifi__health__get_isp_metrics(site_id)` tool: WAN IP, latency, packet loss, uptime percentage, ISP name from gateway stats. | M | M1.2 | done |
| 27 | Implement `unifi__health__get_events(site_id, hours, severity)` tool: call `/api/s/{site}/stat/event`, filter by time window and severity. | M | M1.2 | done |
| 28 | Implement `unifi__health__get_firmware_status(site_id)` tool: list devices with current vs. latest firmware versions. Uses local device data only in Phase 1 (Cloud V1 enhancement in Phase 2 Task 56). | M | M1.2 | done |
| 29 | Create health agent (`unifi/src/agents/health.py`): aggregates all health tools into a severity-tiered report using OX formatters (Critical / Warning / Informational). Critical findings surfaced first. | M | Tasks 24-28 | done |
| 30 | Write tests for health tools and agent: mock data with healthy devices, degraded devices, offline devices, firmware-behind devices. Test severity classification logic. Use fixtures. | L | Tasks 24-29 | done |

**Parallelizable:** Tasks 24-28 can all run concurrently (5 tasks). Task 29 depends on 24-28. Task 30 can start alongside 29.
**Milestone Value:** `unifi health` produces a tiered health report. Live-testable. Surfaces critical issues immediately.

### Milestone 1.5: Clients Skill + Core Commands

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 31 | Implement `unifi__clients__list_clients(site_id, vlan_id?)` tool: call `/api/s/{site}/stat/sta`, optional VLAN filter, normalize to `Client` model. | M | M1.2 | done |
| 32 | Implement `unifi__clients__get_client(client_mac, site_id)` tool: detailed client info including AP, SSID, signal, traffic, first/last seen, OS detection. | M | M1.2 | done |
| 33 | Implement `unifi__clients__get_client_traffic(client_mac, site_id)` tool: tx/rx bytes, packets, DPI breakdown if available. | M | M1.2 | done |
| 34 | Implement `unifi__clients__search_clients(query, site_id?)` tool: search by MAC, hostname, IP, or alias with partial match (client-side filter). | M | M1.2 | done |
| 35 | Create clients agent (`unifi/src/agents/clients.py`): inventory with signal quality and traffic summary. Uses OX formatters. | M | Tasks 31-34 | done |
| 36 | Implement `unifi scan` command: wire topology agent to build full site map. **Phase 1 scope: single-site only.** Uses `UNIFI_LOCAL_HOST` to connect to one site. Multi-site selection (list sites, ask operator to choose) requires Cloud V1 `list_sites` tool, added in Phase 2 Task 50. | M | M1.3 | done |
| 37 | Implement `unifi health` command: wire health agent, output severity-tiered report via OX formatters. | M | M1.4 | done |
| 38 | Implement `unifi diagnose [target]` command: route to device or client diagnosis flow. **Phase 1 scope: correlate health events + client RF + traffic data only.** Security skill correlation added in Phase 2 when security tools are available. Uses AskUserQuestion patterns from Task 10 for ambiguous targets. | L | M1.3, M1.4, Tasks 31-34 | done |
| 39 | Implement `unifi clients [site?]` command: wire clients agent, support `--vlan` and `--ap` filters. | M | Tasks 31-35 | done |
| 40 | Write tests for clients tools and all 4 commands. Test command -> agent -> tool -> API flow. Break into sub-tasks per command if needed to stay under 80% coverage per test file. | L | Tasks 31-39 | done |

**Parallelizable:** Tasks 31-34 can run concurrently. Tasks 36-39 can run concurrently (each depends on different milestones, all satisfied). Task 40 after all.
**Milestone Value:** Four working commands (`scan`, `health`, `diagnose`, `clients`). The unifi plugin is usable for daily operations. This is the v0.1.0-plan feature set.

### Milestone 1.6: Docs Scaffold + Marketplace Packaging

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 41 | Scaffold MkDocs Material site: `docs/mkdocs.yml`, theme config, nav structure per PRD Section 9.2. Create `docs/index.md` (landing page with safety banner per PRD 10.5), `docs/getting-started/` stubs. | M | None | done |
| 42 | Create `docs/getting-started/installation.md`, `authentication.md` (UniFi API key setup), `quick-start.md`. | M | Task 41 | done |
| 43 | Create `docs/unifi/overview.md`, `docs/unifi/commands.md`, `docs/unifi/skills.md` -- reference docs for Phase 1 commands and skills. | M | M1.5 | done |
| 44 | Write 5 basic workflow examples (PRD Section 9.4): first-time site scan, daily health check, locate a client, check WiFi channel utilization, firmware update status. Follow 7-section template (PRD 9.3). Include "Working Safely" section in each. | L | M1.5 | done |
| 45 | Create `docs/reference/environment-variables.md`, `docs/reference/write-safety.md`. Create `docs/getting-started/safety.md` ("Safety & Human Supervision" page per PRD 10.5). Link from every workflow example's Prerequisites. | M | None | done |
| 46 | Set up GitHub Actions workflow for MkDocs build + deploy to GitHub Pages on push to main. | M | Task 41 | done |
| 47 | Create EmberAI marketplace packaging: ensure `unifi/pyproject.toml` has correct metadata, entry points, and README for marketplace listing. | S | M1.5 | done |

**Parallelizable:** Tasks 41, 45 can start immediately. Tasks 42, 46 depend on 41. Tasks 43-44 depend on M1.5. Task 47 depends on M1.5. Max 4 concurrent.
**Milestone Value:** Live documentation site at `bluminal.github.io/emberai`. Plugin packaged for EmberAI marketplace. Operators can install, configure, and follow workflow examples.

---

## Plan Phase 2: unifi Completion + opnsense Scaffold (v0.1.1-plan + v0.2.0-alpha-plan)

### Milestone 2.1: Cloud V1 API Client + Remaining unifi Read Skills

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 48 | Create `unifi/src/api/cloud_v1_client.py`: async httpx client, base URL `api.ui.com/v1/`, X-API-KEY auth from `UNIFI_API_KEY`, response normalization (`{data, httpStatusCode, traceId}` envelope). **Rate limit handling (D14):** track remaining quota via response headers, handle 429 with exponential backoff (initial 1s, max 60s, jitter), log quota usage at 80% threshold. 10,000 req/min limit. Update `unifi/src/server.py` to load and validate `UNIFI_API_KEY` when Cloud V1 features are used. | L | Plan Phase 1 | pending |
| 49 | Implement `unifi__topology__list_sites()` tool: call Cloud V1 `/v1/sites`, normalize to `Site` model. | M | Task 48 | pending |
| 50 | Update `unifi scan` command: when Cloud V1 is configured (`UNIFI_API_KEY` set), list sites and use AskUserQuestion to let operator select target site before scanning. Fall back to single-site mode (Phase 1 behavior) when Cloud V1 is not configured. | M | Task 49 | pending |
| 51 | Implement `unifi__topology__list_hosts()` tool: call Cloud V1 `/v1/hosts`, return host IDs, names, IPs, firmware. | M | Task 48 | pending |
| 52 | Implement wifi skill tools (6 tools): `get_wlans`, `get_aps`, `get_channel_utilization`, `get_rf_scan`, `get_roaming_events`, `get_client_rf`. All Local Gateway API. | L | Plan Phase 1 | pending |
| 53 | Create wifi agent (`unifi/src/agents/wifi.py`): orchestrates wifi tools, uses OX formatters for channel/RF reports. | M | Task 52 | pending |
| 54 | Implement traffic skill tools (4 tools): `get_bandwidth`, `get_dpi_stats`, `get_port_stats`, `get_wan_usage`. | L | Plan Phase 1 | pending |
| 55 | Create traffic agent (`unifi/src/agents/traffic.py`). | M | Task 54 | pending |
| 56 | Update `unifi__health__get_firmware_status` to use Cloud V1 `/v1/devices` for cloud-reported firmware state when available. Fall back to local data. | S | Task 48 | pending |
| 57 | Implement security skill tools (5 tools): `get_firewall_rules`, `get_zbf_policies`, `get_acls`, `get_port_forwards`, `get_ids_alerts`. | L | Plan Phase 1 | pending |
| 58 | Create security agent (`unifi/src/agents/security.py`): risk-ranked security posture summary. | M | Task 57 | pending |
| 59 | Implement config skill tools (3 read tools): `get_config_snapshot`, `diff_baseline`, `get_backup_state`. | M | Plan Phase 1 | pending |
| 60 | Create config agent (`unifi/src/agents/config.py`). | M | Task 59 | pending |
| 61 | Write tests for Cloud V1 client (rate limit handling, 429 backoff, envelope normalization), all new skill tools, and all new agents. Break into per-skill-group test files. | L | Tasks 48-60 | pending |

**Parallelizable:** Tasks 48, 52, 54, 57, 59 can run concurrently (5 tasks). Tasks 49, 51, 56 depend on 48. Tasks 53, 55, 58, 60 depend on their respective tools. Task 61 after all.
**Milestone Value:** Full read-only unifi skill coverage (topology, health, wifi, clients, traffic, security, config). Cloud V1 enables multi-site awareness and site selection.

### Milestone 2.2: Remaining unifi Commands + Write Operations

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 62 | Implement `unifi wifi` command: channel utilization summary, RF scan results, roaming stats per PRD command definition. | M | Task 53 | pending |
| 63 | Implement `unifi optimize` command: read phase calls wifi, traffic, security, config skills. Generates prioritized recommendations. Write gate enforces `--apply` + confirmation. **Write acceptance criteria:** (1) `UNIFI_WRITE_ENABLED` must be `true` or command returns write-blocked error, (2) without `--apply`, command produces read-only recommendations only, (3) with `--apply`, presents full change plan via AskUserQuestion Phase 2->3 template, (4) operator confirms once, (5) changes execute in presented order. | L | M2.1 | pending |
| 64 | Implement `unifi secure` command: firewall audit, ZBF review, ACL analysis, port forwarding, IDS trend, rogue AP detection. Risk-ranked output via OX formatters. | M | Task 58 | pending |
| 65 | Implement `unifi config` command: config state review, `--drift` diffs against stored baseline. | M | Task 60 | pending |
| 66 | Implement write tool `unifi__config__save_baseline(site_id)`: persists config snapshot as baseline. **Write acceptance criteria:** (1) `UNIFI_WRITE_ENABLED=true` required, (2) `--apply` flag required, (3) operator confirmation via AskUserQuestion, (4) returns structured success/failure result. | M | Task 59 | pending |
| 67 | Implement write tool `unifi__config__create_port_profile(name, native_vlan, tagged_vlans, poe?)`: POST to `/api/s/{site}/rest/portconf`. Same write acceptance criteria as Task 66. | M | Plan Phase 1 | pending |
| 68 | Implement write tool `unifi__topology__assign_port_profile(device_id, port_idx, profile_name)`: PUT port_overrides on device. Same write acceptance criteria as Task 66. | M | Plan Phase 1 | pending |
| 69 | Implement `unifi port-profile create` and `unifi port-profile assign` commands: three-phase confirmation model (PRD 10.2). Port-profile assign triggers OutageRiskAgent assessment (session port check) when netex umbrella is installed; without umbrella, presents warning that outage risk assessment is unavailable. | L | Tasks 67, 68 | pending |
| 70 | Write tests for all Phase 2 commands and write operations. Test write gate enforcement (env var disabled, --apply missing, confirmation flow). Test three-phase confirmation model end-to-end. | L | Tasks 62-69 | pending |

**Parallelizable:** Tasks 62-68 can all run concurrently (7 tasks). Task 69 depends on 67, 68. Task 70 after all.
**Milestone Value:** Complete unifi command set. Write operations available for port profiles and config baselines. All PRD Section 3 requirements fulfilled.

### Milestone 2.3: unifi Advanced Docs + opnsense Scaffold

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 71 | Write 5 advanced unifi workflow examples (PRD Section 9.4): diagnose client complaint, optimize WiFi, firewall posture audit, config drift detection, MSP fleet digest. Follow 7-section template. Include "Working Safely" section. | L | M2.2 | pending |
| 72 | Update `docs/unifi/commands.md` and `docs/unifi/skills.md` with all Phase 2 commands and skills. | M | M2.2 | pending |
| 73 | Create `opnsense/pyproject.toml` with dependencies (same stack: `mcp`, `httpx`, `pydantic`, `python-dotenv`). Define entry point. Add `[project.entry-points."netex.plugins"]` for Plugin Registry (D12). | M | None | pending |
| 74 | Create opnsense directory structure: `opnsense/src/{agents,api,tools,models}/`, `opnsense/tests/`, `__init__.py` files. Create `.env.example` with all opnsense env vars. | S | None | pending |
| 75 | Create `opnsense/SKILL.md` from PRD Appendix B (YAML frontmatter + overview + auth + interaction model). | M | None | pending |
| 76 | Create opnsense MCP server entry point (`opnsense/src/server.py`): initialize server, transport via `--transport stdio|http` (D13), `--check` startup health probe, env var loading (`OPNSENSE_HOST`, `OPNSENSE_API_KEY`, `OPNSENSE_API_SECRET`, `OPNSENSE_WRITE_ENABLED`, `OPNSENSE_VERIFY_SSL` (D11)). Structured logging. | M | Task 73 | pending |
| 77 | Create GitHub Actions CI workflow (`.github/workflows/opnsense.yml`): ruff, mypy, pytest with coverage. | M | Task 73 | pending |
| 78 | Create opnsense shared utilities: `opnsense/src/errors.py` (same hierarchy as unifi, D14), `opnsense/src/cache.py` (TTL cache, same design as unifi), `opnsense/src/safety.py` (write gate with reconfigure awareness -- blocks reconfigure unless write gate passed), `opnsense/src/output.py` (OX formatters), `opnsense/src/ask.py` (AskUserQuestion patterns). | L | None | pending |
| 79 | Create opnsense Pydantic models: `Interface`, `VLANInterface`, `FirewallRule`, `Alias`, `NATRule`, `Route`, `Gateway`, `IPSecSession`, `WireGuardPeer`, `OpenVPNInstance`, `DHCPLease`, `DNSOverride`, `IDSAlert`, `Certificate`, `FirmwareStatus`. | L | None | pending |
| 80 | Create `opnsense/tests/fixtures/`: realistic mock OPNsense API response JSON files. Create `opnsense/tests/test_safety.py` and `opnsense/tests/test_cache.py`. | M | Task 78 | pending |

**Parallelizable:** Tasks 71-72 (unifi docs) and Tasks 73-80 (opnsense scaffold) are fully independent. Within opnsense: 73-75, 78-79 concurrent. 76-77 depend on 73. Max 8 concurrent.
**Milestone Value:** unifi plugin is fully documented with advanced workflows. opnsense skeleton is ready for API client and skill implementation.

---

## Plan Phase 3: opnsense Plugin Complete (v0.2.0-plan)

### Milestone 3.1: OPNsense REST Client

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 81 | Create `opnsense/src/api/opnsense_client.py`: async httpx client, Basic Auth (API key as username, secret as password), SSL verification toggle via `OPNSENSE_VERIFY_SSL` (D11), module/controller/command URL builder (`{host}/api/{module}/{controller}/{command}`). Error handling using error hierarchy (D14): 403->"Insufficient privileges for {resource}. Required privilege: {path}", 401->AuthenticationError, 5xx->APIError, timeout->NetworkError. Structured logging. | L | M2.3 | pending |
| 82 | Implement reconfigure pattern: separate `_write()` and `_reconfigure()` methods. `_write()` saves config; `_reconfigure()` applies to live system. Reconfigure is never called without passing through write safety gate. Post-write cache flush for affected keys. | M | Task 81 | pending |
| 83 | Implement response normalization: handle flat JSON and `{result, changed}` action responses. | M | Task 81 | pending |
| 84 | Integrate TTL cache: interface/route list 5 min, firewall rules 2 min, DHCP leases 1 min. Post-write flush for affected cache keys. | M | Task 78, 81 | pending |
| 85 | Write tests for OPNsense client: mock httpx, test Basic Auth header, URL construction, reconfigure pattern, cache behavior, error handling (401, 403 with privilege message, 500, timeout, self-signed cert with VERIFY_SSL toggle). Use fixtures from Task 80. | L | Tasks 81-84 | pending |

**Parallelizable:** Task 81 first. Tasks 82, 83, 84 can run concurrently after 81. Task 85 after all.
**Milestone Value:** Verified OPNsense API client with reconfigure pattern, auth, caching, and comprehensive error handling.

### Milestone 3.2: Interfaces + Firewall + Routing Skills (Core Read + Write)

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 86 | Implement interfaces skill read tools: `list_interfaces`, `list_vlan_interfaces`, `get_dhcp_leases`. Register via `@server.tool()`. | M | M3.1 | pending |
| 87 | Implement `configure_vlan` write tool (atomic VLAN provisioning). **Design spec:** Step 1: POST VLAN interface (ID, description, parent interface). Step 2: POST IP assignment to new VLAN interface. Step 3: POST DHCP subnet (range, gateway, DNS). Step 4: Single `reconfigure` call. **Rollback on failure:** If step 3 fails, delete step 2 and step 1 artifacts. If step 2 fails, delete step 1 artifact. Rollback does NOT reconfigure (changes were never applied). **Write acceptance criteria:** env var + --apply + operator confirmation via three-phase model. | L | M3.1 | pending |
| 88 | Implement remaining interfaces write tools: `add_vlan_interface`, `add_dhcp_reservation`, `add_dhcp_subnet`. All write-gated with reconfigure. Same write acceptance criteria. | M | M3.1 | pending |
| 89 | Implement firewall skill read tools: `list_rules` (with interface filter), `get_rule`, `list_aliases`, `list_nat_rules`. | M | M3.1 | pending |
| 90 | Implement firewall skill write tools: `add_rule` (with position support), `toggle_rule`, `add_alias`. All write-gated. `add_alias` must precede `add_rule` when rule references an alias. Same write acceptance criteria. | L | M3.1 | pending |
| 91 | Implement routing skill: `list_routes`, `list_gateways`, `add_route` (write). Graceful degradation if Quagga not installed (Q6): detect via API probe, log warning, disable dynamic routing tools, keep static route tools available. | M | M3.1 | pending |
| 92 | Implement `get_lldp_neighbors` tool in diagnostics skill: GET `/api/diagnostics/interface/getLldpNeighbors`. | M | M3.1 | pending |
| 93 | Create agents: `interfaces_agent.py`, `firewall_agent.py`, `routing_agent.py`. All use OX formatters. | M | Tasks 86-91 | pending |
| 94 | Write tests: all interfaces/firewall/routing tools, `configure_vlan` full workflow (success + each rollback scenario), write gate enforcement, Quagga detection and degradation. | L | Tasks 86-92 | pending |

**Parallelizable:** Tasks 86-92 can all run concurrently (7 tasks). Task 93 depends on 86-91. Task 94 after all.
**Milestone Value:** Core gateway operations work: list/create VLANs (atomic with rollback), manage firewall rules and aliases, view routing. Write operations gated and tested.

### Milestone 3.3: VPN + Security + Services + Diagnostics + Firmware Skills

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 95 | Implement VPN skill (4 tools): `list_ipsec_sessions`, `list_openvpn_instances`, `list_wireguard_peers`, `get_vpn_status`. Create vpn agent. | M | M3.1 | pending |
| 96 | Implement security skill (4 tools): `get_ids_alerts`, `get_ids_rules`, `get_ids_policy`, `get_certificates`. Create security agent. | M | M3.1 | pending |
| 97 | Implement services skill (6 tools): `get_dns_overrides`, `get_dns_forwarders`, `resolve_hostname`, `add_dns_override` (write, same acceptance criteria), `get_dhcp_leases4`, `get_traffic_shaper`. Create services agent. | L | M3.1 | pending |
| 98 | Implement diagnostics skill (5 tools): `run_ping`, `run_traceroute`, `dns_lookup`, `get_lldp_neighbors` (reuse from Task 92 if already registered). Create diagnostics agent. `run_host_discovery` (async): **Polling strategy:** POST to start scan, poll GET status endpoint every 2s, timeout after 120s, return partial results on timeout with warning. Provide `--blocking` flag to wait synchronously (default) and `--background` to return immediately with a scan ID for later retrieval. | L | M3.1 | pending |
| 99 | Implement firmware skill (2 tools): `get_status`, `list_packages`. Create firmware agent. | S | M3.1 | pending |
| 100 | Write tests for all VPN/security/services/diagnostics/firmware tools. Test `run_host_discovery` polling (success, timeout with partial results, API error mid-poll). Test `add_dns_override` write gate. Per-skill-group test files. | L | Tasks 95-99 | pending |

**Parallelizable:** Tasks 95-99 can all run concurrently (5 tasks). Task 100 after all.
**Milestone Value:** Full opnsense read capability across all 8 skill groups. VPN monitoring, IDS/IPS visibility, DNS management, live diagnostics, firmware tracking.

### Milestone 3.4: All opnsense Commands

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 101 | Implement `opnsense scan` command: interfaces, VLANs, routes, gateways, VPN status, firmware. Flag down interfaces and lossy gateways. Uses OX formatters. | M | M3.2, M3.3 | pending |
| 102 | Implement `opnsense health` command: gateway latency/loss, IDS alerts (24h), firmware status, WAN reachability (ping 8.8.8.8), cert expiry check (30 days). | M | M3.2, M3.3 | pending |
| 103 | Implement `opnsense diagnose` command: host mode (ping, traceroute, DNS, firewall path) and interface mode (interfaces, gateways, host discovery, DHCP leases). Uses AskUserQuestion for ambiguous targets. | L | M3.2, M3.3 | pending |
| 104 | Implement `opnsense firewall` command: list rules/aliases/NAT. `--audit` adds shadow analysis, over-broad rule detection, disabled rule count. | L | M3.2 | pending |
| 105 | Implement `opnsense firewall policy-from-matrix` command. **Split into sub-tasks:** (a) Parse YAML/CSV access matrix into internal representation. (b) `--audit` mode: compare matrix against existing rules, surface gaps. (c) `--apply` mode: derive minimum ruleset (create aliases first via `add_alias`, then rules in correct order via `add_rule`, single `reconfigure`). Write acceptance criteria apply to (c). | L | M3.2 | pending |
| 106 | Implement `opnsense vlan` command: list VLANs. `--configure` uses atomic `configure_vlan` (Task 87). `--audit` checks VLAN-to-DHCP consistency (handles intentional range offsets). | M | M3.2 | pending |
| 107 | Implement `opnsense dhcp reserve-batch` command: parse device spec (hostname:mac:ip), verify MACs via DHCP leases, batch `add_dhcp_reservation`, single reconfigure. Write acceptance criteria. | M | M3.2 | pending |
| 108 | Implement `opnsense vpn`, `opnsense dns`, `opnsense secure`, `opnsense firmware` commands per PRD command definitions. | L | M3.3 | pending |
| 109 | Write tests for all opnsense commands. Test `policy-from-matrix` with sample access matrices (valid, invalid, partial overlap). Test `dhcp reserve-batch` with multi-device spec. Per-command test files. | L | Tasks 101-108 | pending |

**Parallelizable:** Tasks 101-108 can all run concurrently (8 tasks). Task 109 after all.
**Milestone Value:** Complete opnsense plugin with all commands from PRD Section 4. Operators can manage their OPNsense firewall end-to-end.

### Milestone 3.5: opnsense Docs + Marketplace

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 110 | Create `docs/opnsense/overview.md`, `docs/opnsense/commands.md`, `docs/opnsense/skills.md`. | M | M3.4 | pending |
| 111 | Write 5 basic opnsense workflow examples (PRD Section 9.5): first-time scan, review firewall, check VPN health, troubleshoot DNS, DHCP lease audit. Follow 7-section template. | L | M3.4 | pending |
| 112 | Update `docs/getting-started/authentication.md` -- add OPNsense API key + secret setup alongside existing UniFi auth docs. | S | M3.4 | pending |
| 113 | Set up mkdocstrings for auto-generated API reference from Python docstrings. Configure for both unifi and opnsense. | M | M3.4 | pending |
| 114 | Create EmberAI marketplace packaging for opnsense plugin. | S | M3.4 | pending |

**Parallelizable:** Tasks 110-114 can all run concurrently (5 tasks).
**Milestone Value:** opnsense plugin documented and published to EmberAI marketplace. Operators can install either or both plugins independently.

---

## Plan Phase 4: netex Umbrella Orchestrator (v0.3.0-plan)

### Milestone 4.1: Abstract Data Model + Plugin Registry + Rollback Design

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 115 | Create `netex/pyproject.toml`, directory structure (`src/{agents,registry,models,workflows,tools}/`), `netex/tests/`, `netex/SKILL.md` from PRD Appendix C. Add entry point. `.env.example`. | M | None | pending |
| 116 | Create netex MCP server entry point with `--transport stdio|http` (D13), `--check` health probe, env var loading (`NETEX_WRITE_ENABLED`, `NETEX_CACHE_TTL`). Structured logging. | M | Task 115 | pending |
| 117 | Implement abstract data model (`netex/src/models/abstract.py`): `VLAN`, `FirewallPolicy`, `Route`, `VPNTunnel`, `DNSRecord`, `DHCPLease`, `NetworkTopology`. Each with `from_vendor(vendor_name, raw_data)` class method and `to_vendor(vendor_name)` instance method. Document vendor-field mapping in docstrings. | L | Task 115 | pending |
| 118 | Implement `SecurityFinding` model (`netex/src/models/security_finding.py`): severity (CRITICAL/HIGH/MEDIUM/LOW), category (one of the 7 plan review categories from PRD 5.2.1), description, recommendation, source_plugin, source_tool. | M | Task 115 | pending |
| 119 | Implement Plugin Registry (`netex/src/registry/plugin_registry.py`): discover installed vendor plugins via Python entry points (D12, validated by Task 12 spike). Parse SKILL.md frontmatter, index tools by skill group. Methods: `list_plugins()`, `plugins_with_role(role)`, `plugins_with_skill(skill)`, `tools_for_skill(skill)`. | L | Task 115 | pending |
| 120 | Implement Contract Validator (`netex/src/registry/contract_validator.py`): validate SKILL.md compliance with contract v1.0.0. Check required fields, valid skill group names, tool naming convention. | M | Task 119 | pending |
| 121 | Write Vendor Plugin Contract spec (`contract/v1.0.0/`): `VENDOR_PLUGIN_CONTRACT.md`, `skill_groups.md`, `tool_naming.md`, `skill_md_reference.md`. | M | None | pending |
| 122 | Design rollback workflow state machine (D15): implement `netex/src/workflows/workflow_state.py`. States: `planned -> executing -> step-N-complete -> failed-at-step-N -> rolling-back -> rollback-complete | rollback-failed`. Persist state to local JSON file per workflow run. Include: step log with timestamps, rollback actions per step (recorded at execution time), current state. This design is consumed by the Orchestrator in M4.3. | L | Task 115 | pending |
| 123 | Create GitHub Actions CI for netex (`/.github/workflows/netex.yml`). | S | Task 115 | pending |
| 124 | Write tests: abstract model serialization + vendor mapping, Plugin Registry discovery with mock SKILL.md files and entry points, contract validation (valid + invalid manifests), workflow state machine transitions + persistence. | L | Tasks 117-122 | pending |

**Parallelizable:** Tasks 115, 121 can start immediately. Tasks 116-120, 122-123 depend on 115 and can run concurrently (7 tasks). Task 124 after 117-122.
**Milestone Value:** netex umbrella can discover installed vendor plugins, validate their contracts, provide a registry for skill-based tool lookup, and persist workflow state for rollback coordination. Abstract model enables vendor-neutral operations.

### Milestone 4.2: OutageRiskAgent + NetworkSecurityAgent

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 125 | Implement OutageRiskAgent (`netex/src/agents/outage_risk_agent.py`): session path resolution (source IP -> traceroute -> switch port -> VLAN), risk tier classification (CRITICAL/HIGH/MEDIUM/LOW per PRD 10.3), single-pass batch assessment. Uses registry to find diagnostics/topology/clients tools across all installed plugins. **Session path resolution fallback:** (1) Check `OPERATOR_IP` env var, (2) inspect HTTP request headers if transport=http, (3) accept `--operator-ip` CLI override, (4) if none available, default to HIGH and state "session path could not be determined." | L | M4.1 | pending |
| 126 | Implement NetworkSecurityAgent (`netex/src/agents/network_security_agent.py`) -- Role 1 (automatic plan review): 7 finding categories (PRD 5.2.1: VLAN isolation gap, overly broad rule, rule ordering risk, VPN split-tunnel, unencrypted VLAN, management exposure, DNS security). Read-only enforcement at tool registry level (agent can only call read tools). Output: list of `SecurityFinding` objects. If no issues: "Security review: no issues identified." | L | M4.1 | pending |
| 127 | Implement NetworkSecurityAgent -- Role 2 (on-demand audit): 10 audit domains (PRD 5.2.2). Uses `registry.tools_for_skill("security")` and `registry.tools_for_skill("config")`. `--domain` filter. Output via OX formatters. Remediation commands always without `--apply`. | L | Task 126 | pending |
| 128 | Write tests: OutageRiskAgent with mock plugin responses (test all 4 risk tiers, session path determination failure -> HIGH default, OPERATOR_IP env var, HTTP header fallback), NetworkSecurityAgent plan review (test all 7 finding categories), on-demand audit (test subset of domains). | L | Tasks 125-127 | pending |

**Parallelizable:** Tasks 125 and 126 can run concurrently. Task 127 depends on 126. Task 128 after all.
**Milestone Value:** Both safety agents operational. Every write plan gets an outage risk assessment and security review before presentation to the operator. On-demand security audit available.

### Milestone 4.3: Orchestrator + Core Cross-Vendor Commands

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 129 | Implement Orchestrator -- intent routing (`netex/src/agents/orchestrator.py`): single-vendor intent -> route directly to vendor plugin, cross-vendor intent -> umbrella workflow. Uses Plugin Registry to resolve vendor plugins by role. | M | M4.2 | pending |
| 130 | Implement Orchestrator -- three-phase confirmation model: (a) Phase 1 "Gather & Resolve": identify ambiguities, batch AskUserQuestion using templates from Task 10 patterns, run OutageRiskAgent + NetworkSecurityAgent in parallel. (b) Phase 2 "Build & Present": construct ordered change plan, structure as `[OUTAGE RISK] -> [SECURITY] -> [CHANGE PLAN] -> [ROLLBACK]`, present via OX formatters. (c) Phase 3 "Single Confirmation": one AskUserQuestion with step count and system summary. | L | Task 129 | pending |
| 131 | Implement Orchestrator -- rollback coordination: on step failure, stop execution, use workflow state machine (Task 122) to determine completed steps, execute rollback actions in reverse order, report final state. If rollback fails, set state to `rollback-failed` and report to operator via AskUserQuestion mid-execution failure template. | L | Task 130, Task 122 | pending |
| 132 | Implement `netex vlan configure` command/workflow: 7-step cross-vendor VLAN provisioning (PRD 5.3: gateway VLAN interface -> DHCP -> isolation rule -> reconfigure -> edge network -> port profiles -> SSID). Rollback on step 5+ failure. Uses workflow state machine. | L | Task 131 | pending |
| 133 | Implement `netex vlan audit` command/workflow: compare VLANs across gateway and edge plugins. Surface: defined-in-gateway-only, defined-in-edge-only, mismatched subnets/DHCP. | M | Task 129 | pending |
| 134 | Implement `netex topology` command: merge topology tools across all installed plugins into unified `NetworkTopology`. WAN -> gateway -> VLANs -> edge devices -> APs -> clients. | M | Task 129 | pending |
| 135 | Implement `netex health` command: merge health tools across all plugins into unified severity-tiered report. Critical/High first regardless of source plugin. | M | Task 129 | pending |
| 136 | Implement `netex firewall audit` command: cross-layer firewall analysis. Delegates consistency analysis to NetworkSecurityAgent. | M | Task 129 | pending |
| 137 | Implement `netex secure audit` and `netex secure review` commands: delegate to NetworkSecurityAgent. Support `--domain` filtering. | M | M4.2 | pending |
| 138 | Write tests for orchestrator routing, three-phase confirmation model, `vlan configure` full workflow (success + rollback scenarios + rollback failure), `vlan audit` with mismatched VLANs, cross-vendor topology merge. | L | Tasks 129-137 | pending |

**Parallelizable:** Task 129 first. Task 130 depends on 129. Task 131 depends on 130. Tasks 132-137 can run concurrently after 131 (6 tasks). Task 138 after all.
**Milestone Value:** Cross-vendor operations work. Operators can provision VLANs across both systems, audit consistency, view unified topology and health, and run security audits. Core netex value proposition delivered.

### Milestone 4.4: Advanced Umbrella Commands + Docs

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 139 | Implement `netex network provision-site` command: parse YAML manifest (vlans, access_policy, wifi, port_profiles), single OutageRiskAgent + NSA pass for entire batch, dependency-ordered execution (gateway interfaces -> DHCP -> aliases -> rules -> edge networks -> WiFi -> port profiles), single confirmation. Uses workflow state machine for full-batch rollback. | L | M4.3 | pending |
| 140 | Implement `netex verify-policy` command: run expected-allow and expected-block tests from manifest access_policy. Verify DHCP, DNS, WiFi SSID-to-VLAN mapping. Pass/fail per test. | L | Task 139 | pending |
| 141 | Implement `netex vlan provision-batch` command: create multiple VLANs from manifest vlans[] in one confirmed workflow. Single OutageRiskAgent pass. | M | M4.3 | pending |
| 142 | Implement `netex dns trace`, `netex vpn status`, `netex policy sync` commands per PRD definitions. | L | M4.3 | pending |
| 143 | Write 5 advanced opnsense workflow examples (PRD Section 9.5): routing black hole, full firewall audit, WireGuard peer, traffic shaping, IDS triage. Follow 7-section template. | L | Plan Phase 3 | pending |
| 144 | Write 3 basic + 5 advanced netex workflow examples (PRD Sections 9.6): unified health, VLAN audit, topology, Neffroad provision, guest WiFi isolation, cross-VLAN troubleshooting, post-change policy sync, new site onboarding. Follow 7-section template. | L | Tasks 139-142 | pending |
| 145 | Create `docs/netex/overview.md`, `docs/netex/abstract-model.md`, `docs/netex/commands.md`. | M | Tasks 139-142 | pending |
| 146 | Create `docs/getting-started/connectivity.md` -- deployment guide for remote MCP server connectivity (VPN, reverse proxy, Site Magic). Resolves Q3. | M | None | pending |
| 147 | Create "Netex vs. Autonomous Network Automation" explainer page (PRD 10.5). Add safety warning banner to docs home page. | M | None | pending |
| 148 | Create EmberAI marketplace packaging for netex umbrella plugin. | S | Tasks 139-142 | pending |
| 149 | Write tests for `provision-site`, `verify-policy`, `provision-batch`, `dns trace`, `vpn status`, `policy sync`. Test `provision-site` with Neffroad 7-VLAN manifest. | L | Tasks 139-142 | pending |

**Parallelizable:** Tasks 139, 141-143, 146-147 can run concurrently (6 tasks). Task 140 depends on 139. Tasks 144-145, 148-149 depend on 139-142. Max 8 concurrent.
**Milestone Value:** Complete netex umbrella with all PRD Section 5 commands. Full documentation suite. All three plugins published to EmberAI marketplace.

---

## Plan Phase 5: Advanced Features + Scale (v0.4.0-plan - v0.5.0-plan)

### Milestone 5.1: Redis Caching + Performance

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 150 | Add Redis cache backend as optional alternative to in-memory TTL cache. Shared cache config across all three plugins. Env var `NETEX_CACHE_BACKEND=redis` + `NETEX_REDIS_URL`. Fall back to in-memory if Redis unavailable. | L | Plan Phase 4 | pending |
| 151 | Implement cross-plugin cache invalidation for netex umbrella: when a vendor plugin write flushes its cache, notify umbrella to invalidate abstract model cache for affected entities. | M | Task 150 | pending |
| 152 | Write tests for Redis cache: connection failure fallback, cross-plugin invalidation, TTL enforcement, serialization. | M | Tasks 150-151 | pending |

**Parallelizable:** Task 150 first. Task 151 after 150. Task 152 after both.
**Milestone Value:** Production-grade caching for high-frequency query environments and MSP deployments.

### Milestone 5.2: Site Manager EA + Multi-Site

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 153 | Create `unifi/src/api/site_manager_client.py`: Site Manager EA API client (`api.ui.com/ea/`). **Rate limit handling:** 100 req/min -- track quota, handle 429 with exponential backoff (initial 2s, max 120s, jitter), log at 50% quota threshold (stricter due to low limit). Unwrapped response format. | L | Plan Phase 4 | pending |
| 154 | Implement multisite skill tools: `list_all_sites`, `get_site_health`, `compare_sites`, `search_across_sites`, `get_vantage_points`. All Site Manager EA API. | L | Task 153 | pending |
| 155 | Implement `unifi compare` command: cross-site comparison using multisite skill. | M | Task 154 | pending |
| 156 | Implement Site Manager OAuth flow (if EA graduates to stable -- Q1). Otherwise implement with EA API key auth. | L | Task 153 | pending |
| 157 | Write tests for Site Manager client (rate limit handling, 429 backoff) and all multisite tools/commands. | L | Tasks 153-156 | pending |

**Parallelizable:** Task 153 first. Tasks 154, 156 after 153. Task 155 after 154. Task 157 after all.
**Milestone Value:** Full multi-site support for MSP and enterprise deployments. Cross-site health comparison and fleet management.

### Milestone 5.3: Advanced opnsense Features

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 158 | Implement opnsense services skill enhancements: Unbound DNS advanced config (DNSSEC, DoT forwarders), traffic shaper management. | M | Plan Phase 3 | pending |
| 159 | Implement Quagga dynamic routing support (BGP/OSPF) with graceful degradation if Quagga plugin not installed (Q6). | M | Plan Phase 3 | pending |
| 160 | Implement IDS/IPS policy CRUD: rule enable/disable, policy tuning, ruleset update trigger. Write-gated with service restart warning. Write acceptance criteria. | M | Plan Phase 3 | pending |
| 161 | Write tests for advanced opnsense features. | M | Tasks 158-160 | pending |

**Parallelizable:** Tasks 158-160 can all run concurrently. Task 161 after all.
**Milestone Value:** Deep gateway management: dynamic routing, IDS tuning, advanced DNS/traffic shaping.

### Milestone 5.4: Docs Versioning + CI Doc Testing + MSP Guide

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 162 | Set up `mike` plugin for MkDocs versioning: `/latest` and `/vX.Y.Z` paths. Configure GitHub Actions to deploy versioned docs on tag push. | M | Plan Phase 4 | pending |
| 163 | Implement CI doc testing: extract code samples from workflow examples and validate against a reference environment. Broken examples fail the build. | L | Plan Phase 4 | pending |
| 164 | Create `docs/reference/changelog.md` and troubleshooting guide. | M | Plan Phase 4 | pending |
| 165 | Create MSP deployment guide: multi-tenant credential isolation, multi-instance OPNsense considerations, fleet management patterns. | M | M5.2 | pending |
| 166 | Add Plausible analytics to docs site (if configured). | S | Plan Phase 4 | pending |

**Parallelizable:** Tasks 162-164, 166 can run concurrently (4 tasks). Task 165 depends on M5.2.
**Milestone Value:** Production-quality documentation: versioned, tested, with MSP guidance. Full operational readiness for enterprise adoption.

### Milestone 5.5: Scheduled Digests + MSP Multi-Tenant (Future)

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 167 | Design and implement scheduled health digest system: periodic `netex health` runs with delta reporting. | L | Plan Phase 4 | pending |
| 168 | Implement MSP multi-tenant credential isolation: per-client credential vaults, secure context switching, audit logging. | L | Plan Phase 4 | pending |
| 169 | Write tests for scheduled digests and multi-tenant isolation. | L | Tasks 167-168 | pending |

**Parallelizable:** Tasks 167 and 168 can run concurrently. Task 169 after both.
**Milestone Value:** Proactive monitoring (digests) and enterprise-grade multi-tenancy for managed service providers.
