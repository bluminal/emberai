# Implementation Plan: Cisco SG-300 Vendor Plugin

## Overview

A new vendor plugin for the Cisco SG-300 managed switch series, conforming to Vendor Plugin Contract v1.0.0. The plugin communicates via SSH CLI (Netmiko) for configuration and SNMP for monitoring -- the SG-300 has no REST API, NETCONF, or RESTCONF. It lives at `cisco/` alongside the existing `unifi/`, `opnsense/`, `nextdns/`, and `netex/` plugins and is independently installable. Once registered, the netex umbrella orchestrates it for cross-vendor VLAN provisioning, topology mapping, and policy verification.

Link to PRD: `docs/reqs/main.md` (Section 2.3 references Cisco as a future vendor candidate; Section 2.4 defines the contract this plugin must conform to).

## Decisions

| # | Decision | Context | Rationale |
|---|----------|---------|-----------|
| CD1 | SSH CLI via Netmiko as primary interface, SNMP as secondary | SG-300 has no REST API, no NETCONF/RESTCONF, no gRPC. Web UI is form-POST only. | Netmiko has a native `cisco_s300` device type. SSH CLI covers all read and write operations. SNMP supplements with real-time monitoring (MAC table, interface counters, LLDP) without establishing SSH sessions. |
| CD2 | CLI output parsed with regex, not TextFSM | TextFSM templates for SG-300 are sparse in the NTC-templates library. SG-300 CLI output is simpler than IOS-XE. | Custom regex parsers are more maintainable for a small set of well-known commands. If parser count grows beyond 10, reconsider TextFSM. |
| CD3 | No candidate config / no dry-run -- capture-before-change safety model | SG-300 applies config commands immediately with no rollback mechanism. | Before every write: (1) capture `show running-config` as rollback baseline, (2) apply changes, (3) verify, (4) only then `write memory` to persist. If verification fails, attempt CLI rollback from captured baseline. |
| CD4 | Read-only tools first, write tools in Phase 2 | Matches the depth-first approach (main plan D2) and reduces risk during initial development. | Prove SSH client, CLI parsers, and SNMP work correctly before introducing mutation. Write tools depend on reliable read tools for verification. |
| CD5 | Single SSH connection with session reuse | SG-300 has limited concurrent SSH sessions (typically 2-4). | Netmiko `ConnectHandler` is held as a singleton. Reconnect on timeout/disconnect. `asyncio.Lock` prevents concurrent command interleaving. |
| CD6 | `edge` role in Vendor Plugin Contract | SG-300 is a managed switch (Layer 2/3 switching, VLANs, ports). | Matches the `edge` role defined in `contract/v1.0.0/skill_groups.md`. Same role as the unifi plugin's switching capabilities. |
| CD7 | Netmiko runs in thread executor (asyncio-compatible) | Netmiko is synchronous (blocking I/O). MCP server is async. | Wrap all Netmiko calls in `asyncio.to_thread()` to avoid blocking the event loop. This is a standard pattern for sync-to-async bridging. |
| CD8 | SNMP via `pysnmp-lextudio` (community fork) | Original `pysnmp` is unmaintained. `pysnmp-lextudio` is the active community fork with Python 3.12 support and async capabilities. | Active development, async support, compatible API. |

## Open Questions

| # | Question | Impact | Status |
|---|----------|--------|--------|
| CQ1 | SG-300 firmware version -- does CLI output format vary across firmware versions? | Parser stability. May need version-specific parsing branches. | Open -- test against live switch in Phase 1 M1.2 |
| CQ2 | SG-300 concurrent SSH session limit -- exact number? | Connection pooling strategy. If limit is 2, singleton is mandatory. | Open -- test in Phase 1 M1.2 |
| CQ3 | SNMP v3 support on SG-300 -- is it configured / worth the complexity? | Security posture. v2c is simpler but uses community strings. | Open -- start with v2c, add v3 if user requires it |
| CQ4 | Cross-vendor VLAN provisioning sequencing -- does netex need a Cisco-specific step between gateway and edge? | Affects Phase 3 netex integration. SG-300 trunk ports may need explicit VLAN allowed-list updates. | Open -- resolve in Phase 3 |
| CQ5 | `write memory` persistence timing -- should saves be batched or immediate? | Write safety UX. Immediate save after each change is safer but slower for batch operations. | Open -- start with immediate, reconsider if batch VLAN provisioning is too slow |

---

## Phase 1: Read-Only Foundation (v0.1.0)

### Milestone 1.1: Project Scaffold + CI

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 1 | Create `cisco/pyproject.toml`: hatchling build system, `src/cisco` package, dependencies (`mcp>=1.26.0,<2`, `netmiko>=4.0,<5`, `pysnmp-lextudio>=6.0,<7`, `pydantic>=2.12,<3`, `python-dotenv>=1.2,<2`), dev deps (`pytest`, `pytest-asyncio`, `coverage`, `ruff`, `mypy`), `[project.scripts] cisco-server = "cisco.server:main"`, `[project.entry-points."netex.plugins"] cisco = "cisco.server:plugin_info"`. Follow opnsense pyproject.toml structure. | M | None | done |
| 2 | Create directory structure: `cisco/src/cisco/{__init__.py, __main__.py, server.py, safety.py, errors.py, cache.py}`, `cisco/src/cisco/ssh/` (SSH client), `cisco/src/cisco/snmp/` (SNMP client), `cisco/src/cisco/parsers/` (CLI output parsers), `cisco/src/cisco/tools/` (MCP tool files), `cisco/src/cisco/models/` (Pydantic models), `cisco/tests/`, `cisco/tests/fixtures/` (mock CLI output text files), `cisco/knowledge/`, `.env.example`. | S | None | done |
| 3 | Create `cisco/src/cisco/errors.py`: same error hierarchy as opnsense (NetexError base -> AuthenticationError, NetworkError, ValidationError, WriteGateError). Add `SSHCommandError` for CLI command failures and `CLIParseError` for unexpected output formats. | M | None | done |
| 4 | Create `cisco/src/cisco/safety.py`: write gate decorator reusing the same pattern as opnsense (`write_gate("CISCO")`). No reconfigure gate needed -- SG-300 commands take effect immediately. Add `config_backup` utility that captures `show running-config` before writes (used in Phase 2). | M | None | done |
| 5 | Create `cisco/src/cisco/cache.py`: TTL cache (copy pattern from opnsense). Per-data-type TTLs: VLAN list 5 min, MAC table 30 sec, interface status 2 min, LLDP neighbors 5 min, running-config 10 min. | S | None | done |
| 6 | Create `cisco/src/cisco/server.py`: FastMCP server entry point with `plugin_info()` function returning contract metadata (`name="cisco"`, `version="0.1.0"`, `vendor="cisco"`, `roles=["edge"]`, `skills=[...]`, `write_flag="CISCO_WRITE_ENABLED"`, `contract_version="1.0.0"`). CLI flag `--transport stdio|http`, `--check` health probe. Env var loading and validation. Structured JSON logging to stderr. | M | Tasks 1, 3 | done |
| 7 | Create `cisco/SKILL.md` with YAML frontmatter (`netex_vendor: cisco`, `netex_role: [edge]`, `netex_skills: [topology, health, interfaces, config]`, `netex_write_flag: CISCO_WRITE_ENABLED`, `netex_contract_version: "1.0.0"`) and Claude instruction content covering: SSH CLI interface model, available skill groups, tool signatures, write safety gate, config persistence model. | M | None | pending |
| 8 | Create `cisco/run.sh` (EmberAI bootstrap script -- same pattern as opnsense: create venv, install plugin, exec server) and `cisco/settings.json` (env var declarations for `CISCO_HOST`, `CISCO_SSH_USERNAME`, `CISCO_SSH_PASSWORD`, `CISCO_ENABLE_PASSWORD`, `CISCO_SNMP_COMMUNITY`, `CISCO_WRITE_ENABLED`, `CISCO_VERIFY_SSH_HOST_KEY`). | S | None | done |
| 9 | Create `.github/workflows/cisco.yml`: ruff lint, mypy type-check, pytest with coverage (80% threshold). Trigger on PR changes to `cisco/`. Follow opnsense CI workflow pattern. | S | Task 1 | pending |
| 10 | Create base Pydantic models in `cisco/src/cisco/models/`: `SwitchInfo` (hostname, firmware, serial, uptime), `VLAN` (id, name, ports, tagged_ports), `Port` (id, name, status, speed, duplex, vlan, mode, description), `MACEntry` (mac, vlan, interface, type), `LLDPNeighbor` (local_port, remote_device, remote_port, remote_ip), `InterfaceCounters` (port, rx_bytes, tx_bytes, rx_errors, tx_errors, rx_discards, tx_discards). Strict mode, validators for MAC address format. | M | None | done |
| 11 | Write scaffold tests: `test_safety.py` (write gate env var + apply flag enforcement), `test_cache.py` (TTL expiry, stampede protection), `test_errors.py` (error hierarchy, structured context). | M | Tasks 3-5 | done |

**Parallelizable:** Tasks 1-5, 7-8, 10 can all run concurrently (8 tasks). Tasks 6, 9 depend on Task 1. Task 11 depends on Tasks 3-5.
**Milestone Value:** Runnable MCP server skeleton with CI, write gate, caching, error hierarchy, and Pydantic models. `python -m cisco` starts without errors. Tests pass. Lint clean. Plugin discoverable by netex registry via entry point.

### Milestone 1.2: SSH Client + CLI Parsers

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 12 | Create `cisco/src/cisco/ssh/client.py`: async-compatible SSH client wrapping Netmiko `ConnectHandler(device_type="cisco_s300")`. Singleton connection with `asyncio.Lock` for command serialization (CD5). All Netmiko calls via `asyncio.to_thread()` (CD7). Auto-reconnect on `NetmikoTimeoutException` / `NetmikoAuthenticationException`. Methods: `connect()`, `disconnect()`, `send_command(cmd) -> str`, `send_config_set(cmds) -> str`, `save_config()`, `get_running_config() -> str`. SSH host key verification toggle via `CISCO_VERIFY_SSH_HOST_KEY`. Enable mode entry via `CISCO_ENABLE_PASSWORD` if set. Map Netmiko exceptions to plugin error hierarchy (AuthenticationError, NetworkError, SSHCommandError). | L | M1.1 | done |
| 13 | Create `cisco/src/cisco/parsers/__init__.py` with base parser contract: each parser is a function `parse_<command>(raw: str) -> list[Model]` that takes raw CLI text and returns typed Pydantic models. | S | Task 10 | done |
| 14 | Create `cisco/src/cisco/parsers/vlan.py`: parse `show vlan` output into `list[VLAN]`. SG-300 output format: table with VLAN ID, Name, Ports (tagged), Ports (untagged). Handle multi-line port lists. Handle default VLAN (1) and reserved VLANs. | M | Task 13 | done |
| 15 | Create `cisco/src/cisco/parsers/interfaces.py`: parse `show interfaces status` into `list[Port]`. Fields: port ID, name, status (Up/Down), speed, duplex, type. Parse `show interfaces switchport {port}` for detailed port config (mode, access VLAN, trunk allowed VLANs, native VLAN). | M | Task 13 | done |
| 16 | Create `cisco/src/cisco/parsers/mac_table.py`: parse `show mac address-table` into `list[MACEntry]`. Fields: VLAN, MAC address, type (dynamic/static), interface. Handle "Total Mac Addresses" footer line. | M | Task 13 | done |
| 17 | Create `cisco/src/cisco/parsers/lldp.py`: parse `show lldp neighbors` into `list[LLDPNeighbor]`. Fields: local port, remote device ID, remote port ID, capabilities. Handle truncated device names. | M | Task 13 | done |
| 18 | Create `cisco/src/cisco/parsers/system.py`: parse `show version` into `SwitchInfo` (model, firmware version, serial, uptime, hostname). Parse `show running-config` header for system-level settings. | M | Task 13 | done |
| 19 | Create `cisco/tests/fixtures/`: text files with real SG-300 CLI output for each parsed command. Capture from live switch: `show_vlan.txt`, `show_interfaces_status.txt`, `show_interfaces_switchport_gi1.txt`, `show_mac_address_table.txt`, `show_lldp_neighbors.txt`, `show_version.txt`, `show_running_config.txt`. Include edge cases (empty VLAN, no LLDP neighbors, port down). | M | None | done |
| 20 | Write parser tests: `test_parsers_vlan.py`, `test_parsers_interfaces.py`, `test_parsers_mac_table.py`, `test_parsers_lldp.py`, `test_parsers_system.py`. Each test loads fixture text, parses it, and asserts correct Pydantic model fields. Test edge cases (empty tables, single-entry tables, multi-line port lists). | L | Tasks 14-19 | done |
| 21 | Write SSH client tests: `test_ssh_client.py`. Mock Netmiko `ConnectHandler`. Test: connection establishment, auto-reconnect on timeout, enable mode entry, command serialization (concurrent calls wait), `asyncio.to_thread()` wrapping, error mapping (Netmiko exceptions -> plugin errors), host key verification toggle. | L | Task 12 | done |

**Parallelizable:** Tasks 12 and 19 can start immediately. Tasks 13-18 depend on M1.1 (Task 10) but can all run concurrently (5 parsers). Tasks 20-21 depend on their respective implementations.
**Milestone Value:** Reliable SSH communication with the SG-300. All CLI output from key commands is parsed into typed models. Test fixtures capture real switch output. Foundation for all read tools.

### Milestone 1.3: SNMP Client

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 22 | Create `cisco/src/cisco/snmp/client.py`: async SNMP client using `pysnmp-lextudio`. SNMPv2c with community string from `CISCO_SNMP_COMMUNITY` (default: "public"). Methods: `get(oid) -> Any`, `get_bulk(oid, max_repetitions) -> list`, `walk(oid) -> list[tuple[OID, value]]`. Target host from `CISCO_HOST`. Map SNMP errors to plugin error hierarchy. | M | M1.1 | pending |
| 23 | Create `cisco/src/cisco/snmp/oids.py`: constants for standard MIBs used with SG-300. IF-MIB (interface counters, status), BRIDGE-MIB (MAC table), LLDP-MIB (neighbor discovery), ENTITY-MIB (hardware info), SNMPv2-MIB (sysDescr, sysUpTime, sysName). | S | None | pending |
| 24 | Create `cisco/src/cisco/snmp/mappers.py`: functions that convert raw SNMP walk results into Pydantic models. `map_interface_counters(walk_result) -> list[InterfaceCounters]`, `map_mac_table(walk_result) -> list[MACEntry]`, `map_lldp_neighbors(walk_result) -> list[LLDPNeighbor]`. | M | Tasks 22-23 | pending |
| 25 | Write SNMP tests: `test_snmp_client.py` (mock pysnmp engine, test get/walk/error handling), `test_snmp_mappers.py` (test OID-to-model conversion with realistic SNMP response data). | M | Tasks 22-24 | pending |

**Parallelizable:** Tasks 22 and 23 can run concurrently. Task 24 depends on both. Task 25 depends on 24.
**Milestone Value:** SNMP monitoring capability for real-time interface counters, MAC table polling, and LLDP discovery without SSH overhead. Complements SSH CLI for monitoring use cases.

### Milestone 1.4: Read-Only MCP Tools

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 26 | Create `cisco/src/cisco/tools/topology.py`: `cisco__topology__get_device_info` (SSH: `show version` -> SwitchInfo), `cisco__topology__list_vlans` (SSH: `show vlan` -> list[VLAN]), `cisco__topology__get_lldp_neighbors` (SSH or SNMP: `show lldp neighbors` -> list[LLDPNeighbor]). Register with `@mcp_server.tool()`. Integrate TTL cache for each query. | M | M1.2, M1.3 | pending |
| 27 | Create `cisco/src/cisco/tools/interfaces.py`: `cisco__interfaces__list_ports` (SSH: `show interfaces status` -> list[Port]), `cisco__interfaces__get_port_detail` (SSH: `show interfaces switchport {port}` -> Port with VLAN details), `cisco__interfaces__get_counters` (SNMP: IF-MIB walk -> list[InterfaceCounters]). | M | M1.2, M1.3 | pending |
| 28 | Create `cisco/src/cisco/tools/clients.py`: `cisco__clients__list_mac_table` (SSH or SNMP: `show mac address-table` -> list[MACEntry]), `cisco__clients__find_mac` (filter MAC table by MAC address -- useful for cross-vendor device tracing), `cisco__clients__list_mac_by_vlan` (SSH: `show mac address-table vlan {id}` -> list[MACEntry]), `cisco__clients__list_mac_by_port` (SSH: `show mac address-table interface {port}` -> list[MACEntry]). | M | M1.2 | pending |
| 29 | Create `cisco/src/cisco/tools/health.py`: `cisco__health__get_status` (composite: switch uptime, port up/down counts, error counters summary, LLDP neighbor count). Aggregates data from SSH + SNMP to produce a single health overview. | M | Tasks 26-28 | pending |
| 30 | Create `cisco/src/cisco/tools/config.py`: `cisco__config__get_running_config` (SSH: `show running-config` -> full config text), `cisco__config__get_startup_config` (SSH: `show startup-config` -> full config text), `cisco__config__detect_drift` (compare running vs startup config, report differences -- indicates unsaved changes). | M | M1.2 | pending |
| 31 | Register all tools in `server.py`. Ensure `--check` health probe validates SSH connectivity (attempt `show version`) and optionally SNMP connectivity (attempt sysDescr GET). | S | Tasks 26-30 | pending |
| 32 | Write tool tests: `test_tools_topology.py`, `test_tools_interfaces.py`, `test_tools_clients.py`, `test_tools_health.py`, `test_tools_config.py`. Mock SSH client (return fixture text) and SNMP client (return fixture data). Test cache integration (cache hit skips SSH call). Test tool parameter validation. | L | Tasks 26-31 | pending |

**Parallelizable:** Tasks 26-28, 30 can all run concurrently (4 tasks). Task 29 depends on 26-28. Task 31 depends on 26-30. Task 32 depends on all.
**Milestone Value:** Complete read-only Cisco plugin. Operators can discover VLANs, list MAC addresses (device discovery), view port configurations, check switch health, read LLDP topology, and detect unsaved config changes. All tools registered as MCP tools and usable from Claude conversations. Plugin is installable and functional in plan-only mode (no writes).

---

## Phase 2: Write Operations + Config Safety (v0.2.0)

### Milestone 2.1: VLAN Write Tools

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 33 | Implement config backup utility in `cisco/src/cisco/ssh/config_backup.py`: before any write operation, capture `show running-config` with timestamp. Store in memory (last N backups, configurable). Provide `get_last_backup() -> str` and `diff_with_current() -> str` for verification. This is the safety net for CD3 (no candidate config). | M | M1.2 | done |
| 34 | Create `cisco/src/cisco/tools/vlan_write.py`: `cisco__interfaces__create_vlan` (create VLAN with ID and name). CLI sequence: backup running-config, `configure terminal`, `vlan {id}`, `name {name}`, `exit`, `exit`, verify with `show vlan`. Write-gated (CD4: env var + apply). Does NOT call `write memory` -- operator must explicitly persist. | M | Task 33 | done |
| 35 | Add `cisco__interfaces__delete_vlan` (delete VLAN by ID). CLI sequence: backup running-config, `configure terminal`, `no vlan {id}`, `exit`, verify VLAN removed. Refuse to delete VLAN 1 (default). Warn if ports are still assigned to the VLAN. Write-gated. | M | Task 33 | done |
| 36 | Add `cisco__interfaces__set_port_vlan` (assign a port to a VLAN in access mode). CLI sequence: backup running-config, `configure terminal`, `interface {port}`, `switchport mode access`, `switchport access vlan {id}`, `exit`, `exit`, verify with `show interfaces switchport {port}`. Validate VLAN exists before assignment. Write-gated. | M | Task 33 | done |
| 37 | Add `cisco__interfaces__set_trunk_port` (configure a port as trunk with allowed VLANs). CLI sequence: backup running-config, `configure terminal`, `interface {port}`, `switchport mode trunk`, `switchport trunk allowed vlan add {ids}`, `exit`, `exit`, verify. Support `add`, `remove`, and `replace` operations on the allowed VLAN list. Write-gated. | M | Task 33 | done |
| 38 | Add `cisco__config__save_config` (persist running-config to startup-config). CLI: `write memory`. Write-gated. This is the explicit persistence step -- separated from VLAN/port changes per CD3. Returns confirmation with diff between old startup and new. | S | M1.2 | done |
| 39 | Write tests for all VLAN write tools: mock SSH client, verify correct CLI command sequences sent, verify backup captured before changes, verify write gate enforcement, test VLAN validation (duplicate ID, reserved VLAN, VLAN 1 protection), test port validation (invalid port name). | L | Tasks 34-38 | done |

**Parallelizable:** Task 33 first. Tasks 34-38 can all run concurrently after Task 33 (5 tasks). Task 39 depends on all.
**Milestone Value:** Full VLAN lifecycle management: create VLANs, assign ports, configure trunks, persist config. Config backup before every write provides a safety net on hardware with no rollback support.

### Milestone 2.2: Port Management Write Tools

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 40 | Add `cisco__interfaces__set_port_description` (set a port description for operational labeling). CLI: `configure terminal`, `interface {port}`, `description {text}`, verify. Write-gated. | S | Task 33 | done |
| 41 | Add `cisco__interfaces__set_port_state` (enable or disable a port -- admin shutdown/no shutdown). CLI: `configure terminal`, `interface {port}`, `shutdown` or `no shutdown`, verify with `show interfaces status`. Write-gated. Include warning when disabling a port with active MAC entries. | S | Task 33 | done |
| 42 | Write tests for port management tools. Mock SSH client, verify CLI sequences, test write gate, test warning for active-port shutdown. | M | Tasks 40-41 | done |

**Parallelizable:** Tasks 40-41 can run concurrently. Task 42 depends on both.
**Milestone Value:** Port-level operational control: label ports, enable/disable ports for maintenance or security isolation.

### Milestone 2.3: Knowledge Base + Operational Docs

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 43 | Create `cisco/knowledge/INDEX.md` and initial knowledge entries: `sg300-cli-quirks.md` (command syntax differences vs IOS, known parser gotchas discovered during development), `config-persistence.md` (the no-candidate-config model, when to `write memory`, risks of unsaved changes). | S | M1.2 | done |
| 44 | Update `cisco/SKILL.md` with complete tool documentation: all read and write tool signatures, parameters, return types, usage examples. Include the config persistence safety model and write gate instructions. | M | M2.1, M2.2 | done |
| 45 | Create `cisco/README.md`: plugin overview, installation, environment variables, quick-start guide, link to SKILL.md. | S | Task 44 | done |

**Parallelizable:** Task 43 can run anytime after M1.2. Tasks 44-45 depend on M2.1 and M2.2.
**Milestone Value:** Operational documentation for both human operators and Claude. Knowledge base captures lessons learned from live switch testing. SKILL.md provides Claude with full tool awareness.

---

## Phase 3: Cross-Vendor Integration (v0.3.0)

### Milestone 3.1: Netex Plugin Registry Integration

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 46 | Verify Cisco plugin discovery via netex Plugin Registry. Install cisco plugin in dev environment alongside netex, confirm `importlib.metadata.entry_points(group="netex.plugins")` returns cisco with correct metadata. Fix any contract conformance issues. | S | Phase 2 | pending |
| 47 | Test netex `topology` command includes Cisco switch data. The netex umbrella queries all plugins with the `topology` skill -- verify the Cisco switch appears in the unified network topology alongside UniFi devices and OPNsense gateway. | M | Task 46 | pending |
| 48 | Test netex `health` command includes Cisco switch health. Verify switch uptime, port status, and error counters appear in the unified health report. | M | Task 46 | pending |
| 49 | Implement Cisco-aware VLAN provisioning in netex. When `netex vlan provision-batch` runs, the sequencing should be: (1) OPNsense creates VLAN interface + DHCP, (2) Cisco creates VLAN + configures trunk ports, (3) UniFi creates network. The Cisco step needs to know which trunk port connects upstream (to OPNsense) and add the new VLAN to that trunk's allowed list. Input: VLAN ID, name, trunk port for upstream. | L | Tasks 47-48 | pending |
| 50 | Test cross-vendor VLAN provisioning with Cisco in the loop. Mock all three plugins (OPNsense, Cisco, UniFi). Verify correct sequencing, verify Cisco trunk port gets VLAN added, verify rollback on failure at Cisco step. | M | Task 49 | pending |

**Parallelizable:** Task 46 first. Tasks 47-48 can run concurrently. Task 49 depends on 47-48. Task 50 depends on 49.
**Milestone Value:** Cisco switch is a first-class participant in the netex orchestration layer. Unified topology and health reports include the Cisco switch. VLAN provisioning spans all three vendors (OPNsense gateway -> Cisco switch -> UniFi edge) in a single coordinated operation.

### Milestone 3.2: Device Discovery + Cross-Vendor Tracing

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 51 | Enhance `cisco__clients__find_mac` to return enriched results: MAC, VLAN, port, plus a cross-reference hint (the MAC can be looked up in OPNsense DHCP leases for IP/hostname resolution and in UniFi client list for device type/manufacturer). The tool returns the data; Claude performs the cross-reference in conversation. | M | M1.4 | pending |
| 52 | Enhance `cisco__topology__get_lldp_neighbors` to identify which neighbor devices are managed by other netex plugins. If an LLDP neighbor's name/IP matches a known UniFi device (from `unifi__topology__list_devices`) or the OPNsense gateway, annotate the neighbor with the managing plugin name. | M | Task 47 | pending |
| 53 | Write tests for cross-vendor tracing enhancements. | M | Tasks 51-52 | pending |

**Parallelizable:** Tasks 51-52 can run concurrently. Task 53 depends on both.
**Milestone Value:** Operators can trace devices across the Cisco switch and correlate with DHCP leases (OPNsense) and wireless clients (UniFi). LLDP topology shows how the Cisco switch interconnects with other managed network devices.

### Milestone 3.3: Policy Verification

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 54 | Add Cisco switch checks to `netex verify-policy`. Verify: (a) all VLANs defined in the network manifest exist on the Cisco switch, (b) trunk ports carry the expected VLANs, (c) access ports are on the correct VLAN, (d) LLDP neighbors match expected topology. Report discrepancies as policy violations. | M | Task 47 | pending |
| 55 | Write tests for Cisco policy verification checks with mock switch state (correct config, missing VLAN, wrong trunk allowed list, unexpected access VLAN). | M | Task 54 | pending |

**Parallelizable:** Task 54 first. Task 55 depends on 54.
**Milestone Value:** Automated network policy verification includes the Cisco switch. Operators can detect configuration drift (VLAN mismatch, wrong port assignments) across the full OPNsense + Cisco + UniFi stack.

---

## Summary

| Phase | Milestones | Key Deliverable | Estimated Tasks |
|-------|-----------|-----------------|-----------------|
| Phase 1 (v0.1.0) | M1.1-M1.4 | Read-only Cisco plugin: SSH + SNMP clients, CLI parsers, 14 read tools, CI | 32 tasks |
| Phase 2 (v0.2.0) | M2.1-M2.3 | Write operations: VLAN CRUD, port management, config persistence, docs | 13 tasks |
| Phase 3 (v0.3.0) | M3.1-M3.3 | Netex integration: unified topology, cross-vendor VLAN provisioning, policy verification | 10 tasks |
| **Total** | **10 milestones** | | **55 tasks** |
