# Implementation Plan: Talos Linux Vendor Plugin

## Overview

A new vendor plugin for managing Talos Linux Kubernetes clusters on bare-metal hosts, conforming to Vendor Plugin Contract v1.0.0. Unlike other plugins that use `httpx` to call REST APIs, this plugin wraps the `talosctl` CLI tool via `asyncio.create_subprocess_exec` -- Talos uses gRPC + mTLS (not REST), and `talosctl` is the canonical management interface. The plugin lives at `talos/` alongside existing plugins and is independently installable. Once registered, the netex umbrella orchestrates it as the `compute` role for cross-vendor operations (e.g., verifying VLAN connectivity from Kubernetes pods to network infrastructure).

Primary use case: set up and manage an HA Kubernetes cluster across 4 bare-metal homelab hosts (3 control plane + 1 worker) using Talos VIP for the HA control plane endpoint.

Link to PRD: `docs/reqs/main.md` (Talos extends the suite beyond networking into compute infrastructure management).

## Decisions

| # | Decision | Context | Rationale |
|---|----------|---------|-----------|
| TD1 | CLI wrapper (`TalosCtlClient`) via `asyncio.create_subprocess_exec`, not gRPC client | Talos uses gRPC + mTLS. Options: (a) wrap `talosctl` CLI, (b) use `grpcio` directly against Talos API protobuf definitions. | `talosctl` is the canonical, well-tested interface. It handles mTLS, talosconfig context management, and output formatting natively. A raw gRPC client would require maintaining proto stubs, reimplementing mTLS negotiation, and tracking API changes across Talos versions. CLI wrapping is the same pattern the community uses. |
| TD2 | JSON output mode preferred, text fallback | Most `talosctl` commands support `--output json` (or `-o json`). Some commands (e.g., `dashboard`, `pcap`) are inherently non-JSON. | JSON output avoids brittle text parsing. For commands without JSON support, parse structured text output with regex. Each parser documents which output mode it uses. |
| TD3 | `compute` as a new network role in the Vendor Plugin Contract | Talos manages Kubernetes clusters on bare-metal, not network devices. Existing roles (`gateway`, `edge`, `wireless`, `dns`) don't fit. | A `compute` role represents infrastructure that runs workloads and depends on the network layer. In cross-vendor workflows, `compute` executes after `edge` (nodes need switch port and VLAN connectivity before cluster bootstrap). |
| TD4 | Talosconfig context management via env var, not interactive selection | `talosctl` uses a kubeconfig-like context file (talosconfig) with cluster contexts. | `TALOS_CONFIG` env var points to the talosconfig file. `TALOS_CONTEXT` optionally selects a named context within it. This matches how other plugins handle credentials (env vars, not interactive prompts). |
| TD5 | Bootstrap is a one-shot safety-critical operation with extra safeguards | `talosctl bootstrap` initializes etcd. Running it twice on an existing cluster corrupts etcd and destroys the cluster. | Bootstrap tool requires: (1) `TALOS_WRITE_ENABLED=true`, (2) `--apply` flag, (3) pre-flight check (query etcd members -- if etcd already exists, block with error), (4) operator confirmation with explicit warning about irreversibility. The pre-flight check is the key safety net. |
| TD6 | Cluster setup as a guided orchestrated workflow, not a single command | The 10-step cluster setup process has strict ordering, critical safety constraints (bootstrap once, VIP only works post-bootstrap, use real IPs not VIP for endpoints), and requires operator input (node IPs, disk device, VIP address). | An interactive workflow guides the operator step-by-step, validates preconditions at each stage, and prevents common mistakes (e.g., using VIP as talosctl endpoint, bootstrapping twice). Each step is independently callable as a tool for advanced users. |
| TD7 | No `httpx` dependency -- subprocess-only communication | Other plugins use `httpx` for REST APIs. Talos has no REST API. | Keeps the dependency footprint minimal. Only `talosctl` binary must be installed on the host. The plugin validates `talosctl` availability at startup (`--check`). |
| TD8 | Read-only tools first, write tools gated identically to other plugins | Matches depth-first approach (main plan D2) and standard write safety gate (D8). | Prove `talosctl` client wrapper, JSON parsing, and talosconfig management work before introducing mutations. Write tools follow env var + `--apply` + operator confirmation pattern. |
| TD9 | `reset` operation requires extra `--reset-node` flag (like NextDNS `--delete-profile`) | `talosctl reset` wipes a node completely -- OS, data, cluster membership. Accidentally resetting a control plane node can break etcd quorum and destroy the cluster. | Extra flag beyond the standard write gate. Presents node role, hostname, and cluster membership status before confirmation. Control plane nodes get an additional warning about etcd quorum impact. |
| TD10 | Secrets file handling -- plugin never stores or caches secrets.yaml | `talosctl gen secrets` produces a secrets bundle containing root CAs, encryption keys, and bootstrap tokens. This is the master credential for the cluster. | The plugin generates secrets to a user-specified path and immediately warns the operator to store it securely. Secrets are never cached, logged, or stored in plugin state. File path is passed by the operator, not defaulted. |

## Open Questions

| # | Question | Impact | Status |
|---|----------|--------|--------|
| TQ1 | `talosctl` JSON output coverage -- which commands support `-o json` and which require text parsing? | Affects parser count and maintenance burden. Need to audit each command during M1.2 implementation. | Open -- discover during Phase 1 M1.2 |
| TQ2 | Cross-vendor VLAN verification -- how to confirm a Talos node has correct VLAN connectivity from inside the cluster? | Affects Phase 3 netex integration. Options: talosctl netstat, pod-level connectivity tests, or Talos resource inspection for network interface state. | Open -- resolve in Phase 3 M3.5 |
| TQ3 | `talosctl` version compatibility -- does CLI output format change across Talos versions? | Parser stability. May need version detection and format branching. | Open -- test against Talos v1.12 in Phase 1, document any version-specific behavior |
| TQ4 | KubeSpan mesh networking -- should the plugin expose KubeSpan configuration and status tools? | Additional skill group surface area. KubeSpan uses WireGuard under the hood. | Open -- defer to Phase 3 unless user requests earlier |
| TQ5 | etcd snapshot storage -- where should `talosctl etcd snapshot` write to? Local filesystem? | Affects backup workflow design. Snapshots can be large. | Open -- resolve in Phase 2 M2.3 |
| TQ6 | `compute` role sequencing in netex cross-vendor workflows -- where does `compute` fit relative to existing roles? | Affects Phase 3 netex integration. Nodes need network infrastructure (gateway + edge) configured before cluster bootstrap. | Open -- proposed ordering: gateway -> dns -> edge -> wireless -> compute. Resolve in Phase 3 M3.5. |
| TQ7 | Talos machine config patching -- should the plugin support interactive config editing or only file-based patching? | Affects UX for config skill. `talosctl edit machineconfig` is interactive (opens editor), not suitable for MCP. `talosctl patch machineconfig` accepts patch files. | Resolved -> file-based patching only via `patch machineconfig`. Interactive editing is incompatible with MCP subprocess model. |

---

## Phase 1: Scaffold + CLI Client + Cluster Setup (v0.1.0)

The primary deliverable: ability to set up a full HA Kubernetes cluster from scratch across 4 bare-metal hosts (3 control plane + 1 worker) with Talos VIP.

### Milestone 1.1: Project Scaffold + CI + Foundations

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 1 | Create `talos/pyproject.toml`: hatchling build system, `src/talos` package, dependencies (`mcp>=1.26.0,<2`, `pydantic>=2.12,<3`, `python-dotenv>=1.2,<2`). No `httpx` (TD7). Dev deps: `pytest`, `pytest-asyncio`, `coverage`, `ruff`, `mypy`. Define `[project.scripts] talos-server = "talos.server:main"`. Add `[project.entry-points."netex.plugins"] talos = "talos.server:plugin_info"`. Follow cisco pyproject.toml structure. | M | None | done |
| 2 | Create directory structure: `talos/src/talos/{__init__.py, __main__.py, server.py, safety.py, errors.py, cache.py}`, `talos/src/talos/api/` (TalosCtlClient), `talos/src/talos/parsers/` (output parsers), `talos/src/talos/tools/` (MCP tool files), `talos/src/talos/models/` (Pydantic models), `talos/tests/`, `talos/tests/fixtures/` (mock talosctl output JSON/text files), `talos/knowledge/`, `.env.example` with all env vars documented. | S | None | done |
| 3 | Create `talos/src/talos/errors.py`: error hierarchy per D14 (`NetexError -> AuthenticationError, NetworkError, ValidationError, WriteGateError`). Add `TalosCtlError` for non-zero exit codes (captures stderr, exit code, and the command that failed). Add `TalosCtlNotFoundError` for missing `talosctl` binary. Add `ConfigParseError` for unparseable talosctl output. | M | None | done |
| 4 | Create `talos/src/talos/safety.py`: write gate decorator (`write_gate("TALOS")`) -- checks `TALOS_WRITE_ENABLED` env var, validates `--apply` flag. Add `reset_gate` requiring extra `--reset-node` flag (TD9). Add `bootstrap_gate` requiring pre-flight etcd membership check (TD5) -- calls `talosctl etcd members` and blocks if etcd already has members. | M | None | done |
| 5 | Create `talos/src/talos/cache.py`: TTL cache (same design as cisco/opnsense). Per-data-type TTLs: node list 5 min, cluster health 1 min, etcd status 30 sec, service status 1 min, resource queries 2 min, config generation: no cache. | S | None | done |
| 6 | Create `talos/src/talos/server.py`: FastMCP server entry point with `plugin_info()` returning contract metadata (`name="talos"`, `version="0.1.0"`, `vendor="talos"`, `roles=["compute"]`, `skills=["cluster", "nodes", "etcd", "kubernetes", "diagnostics", "config", "security", "images"]`, `write_flag="TALOS_WRITE_ENABLED"`, `contract_version="1.0.0"`). CLI flag `--transport stdio|http`, `--check` health probe (validates `talosctl` binary exists via `which talosctl`, validates talosconfig exists and is readable, attempts `talosctl version --client` to confirm version). Env var loading: `TALOS_CONFIG` (path to talosconfig, required), `TALOS_CONTEXT` (optional context name within talosconfig), `TALOS_WRITE_ENABLED` (default false), `TALOS_NODES` (optional comma-separated default node IPs). Structured JSON logging to stderr. | M | Tasks 1, 3 | done |
| 7 | Create `talos/SKILL.md` with YAML frontmatter (`netex_vendor: talos`, `netex_role: [compute]`, `netex_skills: [cluster, nodes, etcd, kubernetes, diagnostics, config, security, images]`, `netex_write_flag: TALOS_WRITE_ENABLED`, `netex_contract_version: "1.0.0"`) and Claude instruction content: gRPC + mTLS communication model (via talosctl), available skill groups, tool signatures, write safety gate, bootstrap safety, reset safety, cluster setup workflow, required ports (50000, 6443, 2379-2380, 10250, 51820). | M | None | done |
| 8 | Create `talos/run.sh` (EmberAI bootstrap script: create venv, install plugin, exec server) and `talos/settings.json` (env var declarations for `TALOS_CONFIG`, `TALOS_CONTEXT`, `TALOS_WRITE_ENABLED`, `TALOS_NODES`). | S | None | done |
| 9 | Create `.github/workflows/talos.yml`: ruff lint, mypy type-check, pytest with coverage (80% threshold). Trigger on PR changes to `talos/`. Follow cisco CI workflow pattern. | S | Task 1 | done |
| 10 | Create base Pydantic models in `talos/src/talos/models/`: `NodeInfo` (ip, hostname, role [controlplane/worker], machine_type, talos_version, kubernetes_version, ready), `ClusterHealth` (nodes, etcd_members, k8s_components [apiserver, controller-manager, scheduler, etcd], overall_status), `EtcdMember` (id, hostname, peer_urls, client_urls, is_leader, db_size, raft_term, raft_index), `Service` (id, state, health, events_count), `TalosResource` (namespace, type, id, spec, metadata), `MachineConfig` (cluster_name, endpoint, install_disk, network_config, patches), `SecretsBundle` (cluster_name, generated_at -- metadata only, never the actual secrets), `UpgradeStatus` (node, current_version, target_version, stage, progress). Strict mode. | M | None | done |
| 11 | Create `talos/tests/fixtures/`: mock talosctl output files. JSON: `version.json`, `health.json`, `etcd_members.json`, `services.json`, `get_members.json`, `cluster_info.json`. Text: `dashboard.txt`, `dmesg.txt`, `logs.txt`. Include edge cases: single-node cluster, node unreachable, etcd member missing. | M | None | done |
| 12 | Write scaffold tests: `test_safety.py` (write gate env var + apply flag, bootstrap gate with/without existing etcd, reset gate with/without `--reset-node` flag), `test_cache.py` (TTL expiry, stampede protection), `test_errors.py` (error hierarchy, TalosCtlError captures stderr and exit code). | M | Tasks 3-5 | done |

**Parallelizable:** Tasks 1-5, 7-8, 10-11 can all run concurrently (9 tasks). Tasks 6, 9 depend on Task 1. Task 12 depends on Tasks 3-5.
**Milestone Value:** Runnable MCP server skeleton with CI, write gate (including bootstrap and reset safeguards), caching, error hierarchy, and Pydantic models. `python -m talos` starts without errors. Tests pass. Lint clean. Plugin discoverable by netex registry via entry point.

### Milestone 1.2: TalosCtl Client

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 13 | Create `talos/src/talos/api/talosctl_client.py`: async subprocess wrapper for `talosctl`. Core method: `async run(args: list[str], *, nodes: str | list[str] | None, endpoints: str | list[str] | None, json_output: bool = True, timeout: float = 30.0) -> TalosCtlResult`. Constructs full command: `talosctl --talosconfig {TALOS_CONFIG} [--context {TALOS_CONTEXT}] [--nodes {nodes}] [--endpoints {endpoints}] [-o json] {args}`. Uses `asyncio.create_subprocess_exec` with stdout/stderr capture. Returns `TalosCtlResult(stdout: str, stderr: str, exit_code: int, parsed: dict | list | None)`. On non-zero exit: raise `TalosCtlError` with full command, stderr, and exit code. On timeout: raise `NetworkError`. | L | M1.1 | done |
| 14 | Implement JSON output parsing in TalosCtlClient: when `json_output=True`, parse stdout as JSON. Handle: (a) single JSON object, (b) JSON array, (c) newline-delimited JSON (NDJSON -- some talosctl commands emit one JSON object per node). For NDJSON, collect into list. On parse failure with `json_output=True`, log warning and fall back to raw text (populate `TalosCtlResult.parsed = None`). | M | Task 13 | done |
| 15 | Implement talosconfig management: on client init, validate `TALOS_CONFIG` file exists and is readable. Parse talosconfig YAML to extract available contexts and current context. Method: `get_contexts() -> list[str]`, `get_current_context() -> str`. If `TALOS_CONTEXT` env var is set, validate it exists in the talosconfig. If not set, use the current context from the file. | M | Task 13 | done |
| 16 | Implement node targeting: resolve `--nodes` parameter. Priority: (1) explicit `nodes` argument to `run()`, (2) `TALOS_NODES` env var (comma-separated), (3) nodes from current talosconfig context. Method: `get_default_nodes() -> list[str]`. For commands that must target a single node (e.g., bootstrap), validate exactly one node is specified and raise `ValidationError` if multiple given. | M | Task 13 | done |
| 17 | Integrate TTL cache into TalosCtlClient: cache results of read-only commands based on command + node combination. Cache key = `(command_args_tuple, target_nodes_tuple)`. Skip caching for write commands and commands with `--follow` or `--tail` flags. Manual flush method. Post-write cache flush for affected node keys. | M | Tasks 5, 13 | done |
| 18 | Implement `talosctl` binary validation: on startup, run `talosctl version --client -o json` to verify binary exists and capture client version. Store version for compatibility checks (TQ3). If binary not found, raise `TalosCtlNotFoundError` with installation instructions. | S | Task 13 | done |
| 19 | Write comprehensive tests for TalosCtlClient: mock `asyncio.create_subprocess_exec` to return fixture data. Test: command construction (with/without nodes, endpoints, json flag, context), JSON parsing (single object, array, NDJSON, parse failure fallback), talosconfig validation (valid file, missing file, invalid context), node targeting priority (explicit > env var > talosconfig), cache hit/miss/expiry/post-write-flush, timeout handling, non-zero exit code error mapping, binary validation. | L | Tasks 13-18 | done |

**Parallelizable:** Task 13 first. Tasks 14-18 can run concurrently after Task 13 (5 tasks). Task 19 after all.
**Milestone Value:** Verified async subprocess wrapper for `talosctl` that handles JSON/text output, talosconfig context management, node targeting, caching, and comprehensive error handling. All tested with mocked subprocess calls.

### Milestone 1.3: Config Skill -- Configuration Generation + Validation

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 20 | Implement `talos__config__gen_secrets(output_path)` write tool: execute `talosctl gen secrets -o {output_path}`. Write-gated. Returns confirmation with file path. Emits warning: "This file contains cluster root CAs and keys. Store it securely and never commit it to version control." (TD10). | M | M1.2 | done |
| 21 | Implement `talos__config__gen_config(cluster_name, endpoint, *, secrets_file, install_disk?, kubernetes_version?, talos_version?, config_patches?, control_plane_patches?, worker_patches?, with_kubespan?, additional_sans?, output_dir?)` write tool: execute `talosctl gen config` with all specified flags. Returns paths to generated files (controlplane.yaml, worker.yaml, talosconfig). Write-gated (generates files that will be applied to nodes). | L | M1.2 | done |
| 22 | Implement `talos__config__validate(config_file, *, mode?)` read tool: execute `talosctl validate --config {file} [--mode metal|cloud|container] [--strict]`. Returns validation result (pass/fail with error details). Default mode: `metal` (bare-metal is the primary use case). | S | M1.2 | done |
| 23 | Implement `talos__config__patch_machineconfig(config_file, patches)` write tool: execute `talosctl machineconfig patch {file} --patch {patches}`. Accepts inline JSON patch or path to patch file. Write-gated. Returns patched config summary (what changed). | M | M1.2 | done |
| 24 | Implement `talos__config__get_machineconfig(node?)` read tool: execute `talosctl get machineconfig` against a running node. Returns the current machine configuration (sanitized -- omit secrets/keys from output). Parse JSON output into structured view of key settings: cluster name, endpoint, install disk, network interfaces, CNI, kubelet config. | M | M1.2 | done |
| 25 | Create config generation helper: `build_cluster_config(cluster_name, endpoint, control_plane_ips, worker_ips, vip?, install_disk, patches?)`. Orchestrates: (1) gen_secrets if no secrets file provided, (2) gen_config with secrets, (3) apply VIP patch to control plane configs if VIP specified, (4) apply any additional patches, (5) validate all generated configs. Returns all file paths and a summary. This is the building block for the cluster setup workflow (M1.5). Not an MCP tool -- internal helper used by the orchestrated workflow. | L | Tasks 20-23 | not started |
| 26 | Write tests for all config tools: mock talosctl subprocess calls. Test gen_secrets (file creation, warning message), gen_config (all flag combinations, default install disk, with/without KubeSpan), validate (pass, fail with errors, strict mode), patch (inline JSON, file path), get_machineconfig (secrets sanitization). Test build_cluster_config orchestration (success, validation failure at step 4). | L | Tasks 20-25 | done |

**Parallelizable:** Tasks 20-24 can all run concurrently (5 tools). Task 25 depends on 20-23. Task 26 after all.
**Milestone Value:** Full configuration generation and validation pipeline. Operators can generate cluster secrets, create machine configs with VIP support, patch configs, and validate before applying. Foundation for the cluster setup workflow.

### Milestone 1.4: Cluster Skill -- Apply Config + Bootstrap + Health

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 27 | Implement `talos__cluster__apply_config(node, config_file, *, insecure?, mode?)` write tool: execute `talosctl apply-config --nodes {node} --file {config_file} [--insecure] [--mode auto|no-reboot|reboot|staged|try] [--dry-run]`. `--insecure` required for first-time apply to unconfigured nodes (no mTLS yet). Mode defaults to `auto`. Write-gated. Returns apply result with node response. Before applying, run `talos__config__validate` on the config file. Present warning: "This will configure the node at {node}. The disk ({install_disk}) will be wiped." | L | M1.2 | done |
| 28 | Implement `talos__cluster__bootstrap(node)` write tool: execute `talosctl bootstrap --nodes {node}`. **Extra safeguards (TD5):** (1) standard write gate, (2) pre-flight: call `talosctl etcd members --nodes {node}` -- if etcd already has members, block with error "etcd cluster already exists. Bootstrap is a one-time operation. Running it again will corrupt the cluster.", (3) pre-flight: verify node is a control plane node (check machine type from config), (4) operator confirmation with explicit warning: "Bootstrap initializes etcd on {node}. This is irreversible and must only be run ONCE across the entire cluster." | L | M1.2 | done |
| 29 | Implement `talos__cluster__kubeconfig(node?, *, output_path?)` read tool: execute `talosctl kubeconfig [--nodes {node}] [--output {path}]`. Returns kubeconfig content or confirms file written. If no output path, returns kubeconfig to stdout for operator to save. | S | M1.2 | done |
| 30 | Implement `talos__cluster__health(node?, *, wait_timeout?)` read tool: execute `talosctl health [--nodes {node}] [--wait-timeout {timeout}]`. Parse output into `ClusterHealth` model: node readiness, etcd member status, Kubernetes component health (apiserver, controller-manager, scheduler). Return severity-tiered report: CRITICAL (etcd quorum lost, apiserver down), WARNING (node not ready, component degraded), OK (all healthy). | M | M1.2 | done |
| 31 | Implement `talos__cluster__get_version(node?)` read tool: execute `talosctl version [--nodes {node}] -o json`. Returns client version and server version(s) per node. Used for compatibility checking and cluster version inventory. | S | M1.2 | done |
| 32 | Implement `talos__cluster__set_endpoints(endpoints)` write tool: execute `talosctl config endpoint {endpoints}`. Updates talosconfig with the control plane node real IPs. Write-gated. Validates that endpoints are IP addresses (not hostnames that might resolve to VIP). Warns: "Use real control plane node IPs, NOT the VIP. The VIP only works after bootstrap when etcd is running." | M | M1.2 | done |
| 33 | Implement `talos__cluster__merge_talosconfig(talosconfig_path)` write tool: execute `talosctl config merge {path}`. Merges generated talosconfig into the default talosconfig location. Write-gated. | S | M1.2 | done |
| 34 | Write tests for all cluster tools: mock talosctl subprocess. Test apply_config (insecure first-time, normal apply, dry-run, validation failure blocks apply), bootstrap (etcd already exists -> blocked, etcd empty -> proceeds, worker node -> blocked, confirmation flow), kubeconfig (to stdout, to file), health (all healthy, degraded, etcd quorum lost), set_endpoints (valid IPs, VIP detection warning), merge_talosconfig. | L | Tasks 27-33 | done |

**Parallelizable:** Tasks 27-33 can all run concurrently (7 tools). Task 34 after all.
**Milestone Value:** Core cluster lifecycle operations work: apply config to nodes, bootstrap etcd (with safety guards), retrieve kubeconfig, check cluster health, manage talosctl endpoints. All building blocks for the guided setup workflow.

### Milestone 1.5: Cluster Setup Workflow

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 35 | Implement `talos cluster-setup` orchestrated workflow. Interactive guided process through the full 10-step cluster setup. Phase 1 (Gather): collect from operator via AskUserQuestion: cluster name, control plane node IPs (expect 3 for HA), worker node IPs (expect 1+), VIP address, install disk (default `/dev/sda`), Kubernetes version (optional), whether to enable KubeSpan, any custom config patches. Validate inputs: IPs are reachable (attempt `talosctl version --insecure --nodes {ip}` to confirm Talos is booted), VIP is not one of the node IPs, at least 3 control plane nodes for HA. | L | M1.3, M1.4 | done |
| 36 | Implement cluster-setup Phase 2 (Plan + Present): build the ordered execution plan and present to operator. Steps: (1) Generate secrets bundle -> {path}, (2) Generate configs (controlplane.yaml, worker.yaml, talosconfig) with VIP patch, (3) Validate all configs, (4) Apply controlplane config to CP1 ({ip}), (5) Apply controlplane config to CP2 ({ip}), (6) Apply controlplane config to CP3 ({ip}), (7) Apply worker config to W1 ({ip}), (8) Set talosctl endpoints to [CP1, CP2, CP3] real IPs, (9) Merge talosconfig, (10) Bootstrap etcd on CP1, (11) Wait for cluster health (timeout 5 min), (12) Retrieve kubeconfig. Present full plan with safety notes: "Steps 4-7 will wipe the target disks. Step 10 (bootstrap) is irreversible. Step 12 will write kubeconfig to ~/.kube/config." | L | Task 35 | done |
| 37 | Implement cluster-setup Phase 3 (Execute): execute the plan step-by-step after single operator confirmation. On each step: log progress, validate preconditions, execute, verify success. On failure: stop execution, report which step failed and why, report which steps completed (nodes already configured). Do NOT attempt automatic rollback of applied configs (Talos nodes require `reset` to undo, which is destructive). Instead, provide manual recovery guidance: "To undo, run `talos__nodes__reset` on nodes {list} with `--reset-node` flag." After step 10 (bootstrap), wait for etcd to stabilize (poll `talosctl etcd members` until all CPs appear, timeout 3 min). After step 11 (health), report cluster summary: node count, etcd members, Kubernetes version, VIP status. | L | Task 36 | done |
| 38 | Implement `talos cluster-status` command: quick cluster overview. Calls `talos__cluster__health` + `talos__cluster__get_version` + `talos__cluster__list_nodes` (from M2.1, stub with version info for now). Returns: cluster name, node count (CP/worker), Kubernetes version, Talos version, etcd health, VIP status, overall health. | M | M1.4 | done |
| 39 | Write tests for cluster-setup workflow: test Phase 1 input validation (insufficient CP nodes, unreachable IP, VIP collision with node IP), test Phase 2 plan generation (correct step ordering, VIP patch included), test Phase 3 execution (all steps succeed, failure at step 6 stops and reports, bootstrap pre-flight blocks if etcd exists). Test cluster-status command. | L | Tasks 35-38 | done |

**Parallelizable:** Tasks 35-37 are sequential (each phase depends on the previous). Task 38 can run concurrently with 35-37. Task 39 after all.
**Milestone Value:** Complete guided cluster setup workflow. An operator can go from 4 bare-metal hosts with Talos ISO to a running HA Kubernetes cluster through a conversational, safety-guarded process. This is the primary use case delivered.

### Milestone 1.6: Docs + Marketplace Packaging

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 40 | Create `docs/talos/overview.md`: plugin purpose, architecture (CLI wrapper, not REST), Talos Linux primer (immutable OS, API-driven, no SSH), supported operations, required ports. | M | None | not started |
| 41 | Create `docs/talos/commands.md`: reference docs for Phase 1 commands (`cluster-setup`, `cluster-status`) with usage examples. | M | M1.5 | not started |
| 42 | Create `docs/talos/skills.md`: reference docs for Phase 1 skills (`config`, `cluster`) with all tool signatures. | M | M1.4 | not started |
| 43 | Update `docs/getting-started/authentication.md`: add Talos talosconfig setup (how to generate, where to store, env var configuration) alongside existing UniFi, OPNsense, NextDNS, and Cisco auth docs. | S | None | not started |
| 44 | Write 3 workflow examples: (a) first-time cluster setup (the full 10-step guided process), (b) check cluster health after setup, (c) generate and validate config patches. Follow 7-section template. Include "Working Safely" section emphasizing bootstrap irreversibility and disk wipe warnings. | L | M1.5 | not started |
| 45 | Create EmberAI marketplace packaging: ensure `talos/pyproject.toml` has correct metadata, entry points, and README for marketplace listing. | S | M1.5 | not started |

**Parallelizable:** Tasks 40, 43 can start immediately. Tasks 41-42 depend on M1.4/M1.5. Task 44 depends on M1.5. Task 45 depends on M1.5. Max 4 concurrent.
**Milestone Value:** Plugin documented and published to EmberAI marketplace. Operators can install, configure talosconfig, and follow the cluster setup workflow example.

---

## Phase 2: Node Operations + Monitoring (v0.2.0)

Day-2 operations for managing the running cluster.

### Milestone 2.1: Nodes Skill

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 46 | Implement `talos__nodes__list_nodes(*, role?)` read tool: execute `talosctl get members -o json` to list all cluster members. Parse into list of `NodeInfo` models. Optional filter by role (controlplane/worker). Return node IP, hostname, role, Talos version, Kubernetes version, ready status. | M | Phase 1 | not started |
| 47 | Implement `talos__nodes__get_node(node)` read tool: execute `talosctl version --nodes {node} -o json` + `talosctl get machineconfig --nodes {node}` + `talosctl service --nodes {node} -o json`. Return detailed node view: system info, machine config summary (install disk, network interfaces, cluster endpoint), service status list. | M | Phase 1 | not started |
| 48 | Implement `talos__nodes__reboot(node)` write tool: execute `talosctl reboot --nodes {node}`. Write-gated. Pre-flight: check if node is a control plane node and warn about temporary etcd member loss. If rebooting a CP node, verify remaining CP nodes maintain etcd quorum (need 2/3 CPs up). Present warning: "Node {node} ({role}) will be rebooted. Estimated downtime: 1-3 minutes." | M | Phase 1 | not started |
| 49 | Implement `talos__nodes__shutdown(node)` write tool: execute `talosctl shutdown --nodes {node}`. Write-gated. Pre-flight: same quorum check as reboot for CP nodes. Present warning: "Node {node} ({role}) will be shut down. It will NOT restart automatically." | M | Phase 1 | not started |
| 50 | Implement `talos__nodes__reset(node, *, graceful?, reboot?, wipe_mode?)` write tool: execute `talosctl reset --nodes {node} [--graceful] [--reboot] [--wipe-mode {mode}]`. **Extra safeguard (TD9):** requires `--reset-node` flag in addition to `--apply`. Pre-flight: identify node role, check etcd quorum impact for CP nodes, list workloads on the node. Present warning: "WARNING: This will completely wipe node {node} ({role}), removing all data, cluster membership, and OS state. This is irreversible." For CP nodes: "This node is a control plane member. Resetting it will remove it from etcd. Current etcd members: {count}. After reset: {count-1}. Minimum for quorum: {quorum_min}." | L | Phase 1 | not started |
| 51 | Implement `talos__nodes__upgrade(node, *, image?, force?, stage?, wait?)` write tool: execute `talosctl upgrade --nodes {node} [--image {image}] [--force] [--stage] [--wait]`. Write-gated. Pre-flight: compare current Talos version with target image version. For CP nodes, verify etcd quorum will be maintained during upgrade. Present plan: "Upgrade node {node} from Talos {current} to {target}. The node will reboot during upgrade. Estimated downtime: 3-5 minutes." | M | Phase 1 | not started |
| 52 | Implement `talos__nodes__rollback(node)` write tool: execute `talosctl rollback --nodes {node}`. Write-gated. Rolls back to the previous Talos installation (A/B partition scheme). Present plan: "Roll back node {node} from Talos {current} to {previous}. The node will reboot." | M | Phase 1 | not started |
| 53 | Implement `talos__nodes__apply_config_patch(node, patches, *, mode?)` write tool: execute `talosctl patch machineconfig --nodes {node} --patch {patches} [--mode auto|no-reboot|reboot|staged|try]`. Write-gated. For live config changes on running nodes (vs. M1.3 which patches local files). Supports `--dry-run` to preview changes without applying. | M | Phase 1 | not started |
| 54 | Write tests for all nodes tools: mock talosctl subprocess. Test list_nodes (with/without role filter, empty cluster), get_node (aggregated data from multiple commands), reboot/shutdown (quorum check pass/fail for CP nodes), reset (extra flag enforcement, CP quorum warning), upgrade (version comparison, CP quorum check), rollback, apply_config_patch (dry-run, live apply). | L | Tasks 46-53 | not started |

**Parallelizable:** Tasks 46-53 can all run concurrently (8 tools). Task 54 after all.
**Milestone Value:** Full node lifecycle management. Operators can list nodes, inspect details, reboot, shutdown, reset (with safety guards), upgrade Talos OS, rollback upgrades, and patch live configs.

### Milestone 2.2: Diagnostics Skill

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 55 | Implement `talos__diagnostics__get_logs(node, service, *, follow?, tail?, kubernetes?)` read tool: execute `talosctl logs {service} --nodes {node} [-f] [--tail {n}] [--kubernetes]`. Returns log lines for a specified Talos service (machined, trustd, networkd, containerd, etcd, kubelet, apid) or Kubernetes pod (with `--kubernetes`). Without `--follow`, returns last N lines. | M | Phase 1 | not started |
| 56 | Implement `talos__diagnostics__get_dmesg(node)` read tool: execute `talosctl dmesg --nodes {node} -o json`. Returns kernel log messages. Useful for hardware issues, driver problems, disk errors. | S | Phase 1 | not started |
| 57 | Implement `talos__diagnostics__get_events(node?, *, duration?, tail?, actor_id?)` read tool: execute `talosctl events [--nodes {node}] [--duration {d}] [--tail {n}] [--actor-id {id}]`. Returns Talos runtime events (config changes, service state transitions, network events). Parse into structured event list with timestamp, type, message, actor. | M | Phase 1 | not started |
| 58 | Implement `talos__diagnostics__list_services(node)` read tool: execute `talosctl service --nodes {node} -o json`. Returns list of all Talos services with state, health, and event count. | S | Phase 1 | not started |
| 59 | Implement `talos__diagnostics__control_service(node, service, action)` write tool: execute `talosctl service {service} {action} --nodes {node}` where action is `start|stop|restart`. Write-gated. Pre-flight: warn if stopping a critical service (etcd, kubelet, apid, containerd) -- "Stopping {service} on {node} may cause cluster instability." | M | Phase 1 | not started |
| 60 | Implement `talos__diagnostics__get_support_bundle(node?, *, output_path?)` read tool: execute `talosctl support [--nodes {node}] [--output {path}]`. Generates comprehensive debug bundle (logs, configs, resource state, kernel info). Returns bundle path. Warn about potentially large file size. | M | Phase 1 | not started |
| 61 | Implement system info tools (4 tools): `talos__diagnostics__get_processes(node)` (execute `talosctl processes --nodes {node}`), `talos__diagnostics__get_memory(node)` (execute `talosctl memory --nodes {node}`), `talos__diagnostics__get_mounts(node)` (execute `talosctl mounts --nodes {node}`), `talos__diagnostics__get_disk_usage(node, path?)` (execute `talosctl usage --nodes {node} [--path {path}]`). All read-only, parse structured output. | M | Phase 1 | not started |
| 62 | Implement container inspection tools (2 tools): `talos__diagnostics__list_containers(node, *, namespace?)` (execute `talosctl containers --nodes {node} [-k]`), `talos__diagnostics__get_container_stats(node)` (execute `talosctl stats --nodes {node}`). Return container name, image, state, CPU, memory. | M | Phase 1 | not started |
| 63 | Write tests for all diagnostics tools: mock talosctl subprocess. Test logs (service log, kubernetes pod log, follow mode), dmesg (normal, hardware error entries), events (time range filtering, actor filtering), services (all healthy, service down), control_service (critical service warning), support_bundle (single node, all nodes), system info tools, container tools. | L | Tasks 55-62 | not started |

**Parallelizable:** Tasks 55-62 can all run concurrently (8 tools). Task 63 after all.
**Milestone Value:** Full cluster observability. Operators can view logs, kernel messages, runtime events, service status, system resources (CPU, memory, disk), container state, and generate support bundles for troubleshooting.

### Milestone 2.3: etcd Skill

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 64 | Implement `talos__etcd__list_members(node?)` read tool: execute `talosctl etcd members [--nodes {node}] -o json`. Parse into list of `EtcdMember` models. Return member ID, hostname, peer URLs, client URLs, is_leader, learner status. | M | Phase 1 | not started |
| 65 | Implement `talos__etcd__get_status(node?)` read tool: execute `talosctl etcd status [--nodes {node}] -o json`. Return per-member status: DB size, leader, raft term, raft index, raft applied index, errors. Flag unhealthy members. | M | Phase 1 | not started |
| 66 | Implement `talos__etcd__snapshot(node, output_path)` write tool: execute `talosctl etcd snapshot {output_path} --nodes {node}`. Write-gated (writes to filesystem). Returns snapshot file path and size. Recommend regular snapshots: "etcd snapshots are your cluster backup. Store securely and retain multiple copies." | M | Phase 1 | not started |
| 67 | Implement `talos__etcd__defrag(node?)` write tool: execute `talosctl etcd defrag [--nodes {node}]`. Write-gated. Pre-flight: check DB size and fragmentation ratio from status. Present plan: "Defragment etcd on {node}. Current DB size: {size}. This may briefly increase latency." | M | Phase 1 | not started |
| 68 | Implement etcd alarm tools (2 tools): `talos__etcd__list_alarms(node?)` (execute `talosctl etcd alarm list [--nodes {node}]`), `talos__etcd__disarm_alarms(node?)` (execute `talosctl etcd alarm disarm [--nodes {node}]` -- write-gated). Return active alarms (NOSPACE, CORRUPT) with severity. | M | Phase 1 | not started |
| 69 | Implement etcd membership tools (2 tools): `talos__etcd__forfeit_leadership(node)` (execute `talosctl etcd forfeit-leadership --nodes {node}` -- write-gated, causes leader re-election), `talos__etcd__leave(node)` (execute `talosctl etcd leave --nodes {node}` -- write-gated, gracefully removes member from cluster). Pre-flight for leave: verify remaining members maintain quorum. | M | Phase 1 | not started |
| 70 | Implement `talos__etcd__remove_member(node, member_id)` write tool: execute `talosctl etcd remove-member {member_id} --nodes {node}`. Write-gated. **This is a forcible removal -- use when a member is permanently gone.** Pre-flight: verify member is actually unreachable (attempt `talosctl version --nodes {member_ip}`). Warn: "Forcibly removing etcd member {id}. Use only when the member node is permanently unavailable." | M | Phase 1 | not started |
| 71 | Write tests for all etcd tools: mock talosctl subprocess. Test list_members (healthy 3-node cluster, member missing), status (all healthy, DB size alarm threshold), snapshot (success, permission error), defrag (with fragmentation stats), alarms (no alarms, NOSPACE alarm), forfeit_leadership, leave (quorum check), remove_member (member reachable -> warn, unreachable -> proceed). | L | Tasks 64-70 | not started |

**Parallelizable:** Tasks 64-70 can all run concurrently (7 tools). Task 71 after all.
**Milestone Value:** Full etcd cluster management. Operators can monitor etcd health, take snapshots (backups), defragment, manage alarms, handle member lifecycle (leave, remove), and maintain cluster quorum safely.

### Milestone 2.4: Day-2 Commands

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 72 | Implement `talos nodes` command: list all cluster nodes with role, version, status, IP. Uses `talos__nodes__list_nodes`. Flag unhealthy nodes. `--detail {node}` for single-node deep view (via `talos__nodes__get_node`). | M | M2.1 | not started |
| 73 | Implement `talos upgrade [node|--all]` command: guided upgrade workflow. Single node: present version comparison, run upgrade, wait for node to rejoin, verify health. `--all` mode: rolling upgrade across all nodes -- workers first, then CP nodes one at a time, verifying etcd quorum between each CP upgrade. Uses AskUserQuestion for confirmation. Present full rolling upgrade plan before starting. | L | M2.1 | not started |
| 74 | Implement `talos diagnose [node|service]` command: node mode: aggregate logs, events, services, resource usage for a node. Service mode: get logs + events for a specific service across all nodes. Flag anomalies (service restart loops, high memory, disk pressure). Uses diagnostics skill tools. | L | M2.2 | not started |
| 75 | Implement `talos etcd` command: etcd cluster overview (members, leader, DB sizes, alarms). `--snapshot {path}` takes backup. `--defrag` runs defragmentation. `--status` for detailed per-member status. Uses etcd skill tools. | M | M2.3 | not started |
| 76 | Implement `talos health` command: enhanced version of `cluster-status` (M1.5). Adds: etcd health detail, per-node service status, Kubernetes component health, disk/memory pressure, recent warning events (last 1h). Severity-tiered output (CRITICAL/WARNING/OK). | M | M2.1, M2.2, M2.3 | not started |
| 77 | Write tests for all Phase 2 commands: test nodes command (list, detail, unhealthy flag), upgrade (single node, rolling upgrade plan generation, quorum maintenance during CP upgrades, failure mid-rolling-upgrade stops remaining), diagnose (node mode, service mode, anomaly detection), etcd (overview, snapshot, defrag), health (all healthy, degraded, critical). | L | Tasks 72-76 | not started |

**Parallelizable:** Tasks 72-76 can run concurrently (5 commands, each depends on different milestones all completed by this point). Task 77 after all.
**Milestone Value:** Complete day-2 operations command set. Operators can manage nodes, perform rolling upgrades, diagnose issues, manage etcd, and get comprehensive health reports -- all through conversational interaction with safety guards.

---

## Phase 3: Advanced Features + Netex Integration (v0.3.0)

### Milestone 3.1: Kubernetes Skill

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 78 | Implement `talos__kubernetes__upgrade(*, from_version?, to_version, dry_run?, pre_pull_images?)` write tool: execute `talosctl upgrade-k8s [--from {from}] --to {to} [--dry-run] [--pre-pull-images]`. Write-gated. Pre-flight: verify current Kubernetes version, check Talos version compatibility matrix for target K8s version. Present plan: "Upgrade Kubernetes from {current} to {target}. Components: kube-apiserver, kube-controller-manager, kube-scheduler, kube-proxy, CoreDNS. Dry-run will be performed first." Always run dry-run before actual upgrade unless operator explicitly skips. | L | Phase 2 | not started |
| 79 | Implement `talos__kubernetes__get_kubeconfig(node?, *, force?, merge?)` read tool: execute `talosctl kubeconfig [--nodes {node}] [--force] [--merge]`. Enhanced version of M1.4 Task 29 -- adds `--force` for regeneration and `--merge` to merge into existing kubeconfig. Return kubeconfig content or merge confirmation. | S | Phase 2 | not started |
| 80 | Write tests for Kubernetes tools: mock talosctl. Test upgrade (dry-run first, version compatibility check, write gate), kubeconfig (new, force regenerate, merge). | M | Tasks 78-79 | not started |

**Parallelizable:** Tasks 78 and 79 can run concurrently. Task 80 after both.
**Milestone Value:** Kubernetes lifecycle management -- operators can upgrade Kubernetes versions (independently from Talos OS upgrades) and manage kubeconfig access.

### Milestone 3.2: Security Skill

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 81 | Implement `talos__security__rotate_ca(*, talos?, kubernetes?, dry_run?)` write tool: execute `talosctl rotate-ca [--talos] [--kubernetes] [--dry-run]`. Write-gated. This is a highly disruptive operation -- rotates the root CA certificates for Talos and/or Kubernetes. Pre-flight: verify cluster is fully healthy (all nodes up, etcd healthy). Present warning: "CA rotation will restart all components on all nodes. Expect 2-5 minutes of disruption. All existing kubeconfigs and client certificates will be invalidated." | L | Phase 2 | not started |
| 82 | Implement `talos__security__get_secureboot_status(node?)` read tool: execute `talosctl get securitystate --nodes {node} -o json` (or equivalent resource). Returns SecureBoot enrollment status, PCR state, disk encryption status. | M | Phase 2 | not started |
| 83 | Implement `talos__security__inspect_rbac()` read tool: inspect talosconfig to determine which RBAC roles are configured (os:admin, os:operator, os:reader, os:etcd:backup). List configured endpoints and their role assignments. This is a client-side inspection of the talosconfig, not a talosctl command. | M | Phase 2 | not started |
| 84 | Write tests for security tools: test rotate_ca (healthy cluster proceeds, unhealthy cluster blocks, dry-run, write gate), secureboot_status (enabled, disabled, not available), inspect_rbac (multiple roles, single admin). | M | Tasks 81-83 | not started |

**Parallelizable:** Tasks 81-83 can all run concurrently. Task 84 after all.
**Milestone Value:** Security operations -- CA rotation (with strong safety guards), SecureBoot inspection, and RBAC role auditing.

### Milestone 3.3: Images Skill

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 85 | Implement `talos__images__list(node, *, namespace?)` read tool: execute `talosctl image list --nodes {node} [-n {namespace}]`. Returns list of container images on the node with name, digest, size, creation time. | S | Phase 2 | not started |
| 86 | Implement `talos__images__pull(node, ref)` write tool: execute `talosctl image pull {ref} --nodes {node}`. Write-gated. Pre-pull a container image to a node (useful before upgrades to reduce downtime). | S | Phase 2 | not started |
| 87 | Write tests for image tools: mock talosctl. Test list (with/without namespace filter, empty list), pull (valid image ref, write gate enforcement). | S | Tasks 85-86 | not started |

**Parallelizable:** Tasks 85-86 can run concurrently. Task 87 after both.
**Milestone Value:** Container image management -- operators can audit images on nodes and pre-pull images before upgrades.

### Milestone 3.4: Network Diagnostics

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 88 | Implement `talos__diagnostics__get_netstat(node, *, tcp?, udp?)` read tool: execute `talosctl netstat --nodes {node} [--tcp] [--udp] -o json`. Returns network connections with local/remote addresses, state, PID. Useful for verifying required ports (50000, 6443, 2379-2380, 10250) are listening and connected. | M | Phase 2 | not started |
| 89 | Implement `talos__diagnostics__get_resources(node, resource_type, *, id?, namespace?)` read tool: execute `talosctl get {type} [{id}] --nodes {node} [-n {namespace}] -o json`. Generic Talos resource inspection -- access any Talos resource definition (links, addresses, routes, members, services, etc.). Returns parsed `TalosResource` model. | M | Phase 2 | not started |
| 90 | Implement `talos__diagnostics__inspect_dependencies(node)` read tool: execute `talosctl inspect dependencies --nodes {node}`. Returns controller-resource dependency graph. Useful for understanding boot/startup ordering and debugging stuck services. | M | Phase 2 | not started |
| 91 | Implement `talos__diagnostics__check_time(node?)` read tool: execute `talosctl time [--nodes {node}]`. Returns NTP synchronization status. Flag if time drift exceeds threshold (etcd is sensitive to clock skew). | S | Phase 2 | not started |
| 92 | Implement `talos__diagnostics__list_files(node, path?)` and `talos__diagnostics__read_file(node, path)` read tools: execute `talosctl list [--nodes {node}] [{path}]` and `talosctl read {path} --nodes {node}`. Directory listing and file reading on the immutable filesystem. Useful for inspecting Talos-managed configs and state files. | M | Phase 2 | not started |
| 93 | Write tests for all network diagnostic tools: mock talosctl. Test netstat (TCP/UDP filtering, expected ports listening), resources (various resource types, missing resource 404), dependencies (dependency graph parsing), time (synced, drifted), list/read files (directory listing, file content). | L | Tasks 88-92 | not started |

**Parallelizable:** Tasks 88-92 can all run concurrently (5 tools). Task 93 after all.
**Milestone Value:** Deep system and network diagnostics. Operators can inspect network connections, Talos resources, controller dependencies, NTP status, and filesystem state for advanced troubleshooting.

### Milestone 3.5: Netex Umbrella Integration

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 94 | Update Vendor Plugin Contract (`contract/v1.0.0/skill_groups.md`): add `compute` role to the network roles table. Add new skill groups: `cluster` (cluster lifecycle), `nodes` (node management), `etcd` (etcd operations), `kubernetes` (K8s-specific ops), `config` (already exists -- extend description to include Talos machine config), `security` (already exists -- extend for CA rotation and SecureBoot), `images` (container image management). Define compute role sequencing: executes after `edge` (nodes need switch/VLAN connectivity) and after `wireless` (if any nodes use WiFi -- unlikely for bare-metal but contract should be correct). | M | Phase 2 | not started |
| 95 | Update netex Plugin Registry to handle `compute` role in `plugins_with_role("compute")` queries. Verify talos SKILL.md is discovered and indexed correctly. Add `tools_for_skill("cluster")`, `tools_for_skill("nodes")`, `tools_for_skill("etcd")`, `tools_for_skill("kubernetes")`, `tools_for_skill("images")` support. | S | Task 94 | not started |
| 96 | Extend netex abstract data model (`netex/src/models/abstract.py`): add `ComputeNode` (vendor-neutral representation of a cluster node -- hostname, IP, role, OS version, K8s version, health), `KubernetesCluster` (name, nodes, K8s version, endpoint, health), `EtcdCluster` (members, leader, health). Add `from_vendor("talos", raw_data)` / `to_vendor("talos")` support. | M | Task 94 | not started |
| 97 | Implement `netex compute health` umbrella command: aggregate Talos cluster health into the unified netex health report. When talos plugin is installed: include node count, etcd health, Kubernetes health, version info. Severity mapping: etcd quorum lost -> CRITICAL, node not ready -> WARNING, version mismatch across nodes -> WARNING. Gracefully skip when no compute-role plugin installed. | M | Tasks 95-96 | not started |
| 98 | Implement cross-vendor VLAN verification for compute nodes: `netex compute verify-network`. For each Talos node: (a) get node IP from talos plugin, (b) query opnsense DHCP leases or ARP table for the node IP, (c) verify node is on the expected VLAN (match IP subnet to VLAN), (d) verify switch port assignment via unifi/cisco plugin if edge plugin installed. Report: node hostname, IP, expected VLAN, actual VLAN match (Y/N), switch port, link status. Surface mismatches: node on wrong VLAN, node not appearing in DHCP, switch port down. | L | Tasks 95-96 | not started |
| 99 | Extend NetworkSecurityAgent to include compute-layer findings when talos plugin is installed: (a) control plane nodes on same VLAN as untrusted workloads (should be isolated), (b) Talos API port (50000) accessible from non-management VLANs, (c) etcd ports (2379-2380) exposed beyond control plane nodes, (d) Kubernetes API (6443) accessible from unexpected VLANs. Uses `registry.plugins_with_role("compute")` to detect talos. Gracefully skips when no compute-role plugin installed. | L | Tasks 95-96 | not started |
| 100 | Update `netex network provision-site` command to support optional compute node network verification in manifest: if `compute_nodes` section present, after all network provisioning completes, verify each listed node IP is on the specified VLAN with correct connectivity. | M | Task 98 | not started |
| 101 | Write tests for all netex integration: Plugin Registry discovers talos, abstract model conversion, `compute health` (with/without talos plugin), `verify-network` (all nodes matched, node on wrong VLAN, node missing from DHCP), NetworkSecurityAgent compute findings (all categories, graceful skip), `provision-site` with compute_nodes section. | L | Tasks 94-100 | not started |

**Parallelizable:** Task 94 first. Tasks 95-96 after 94, can run concurrently. Tasks 97-99 depend on 95-96, can run concurrently (3 tasks). Task 100 depends on 98. Task 101 after all.
**Milestone Value:** Talos is a first-class citizen in the netex ecosystem. Cross-vendor operations span from network infrastructure through to compute: operators can verify VLAN connectivity for cluster nodes, get unified health across all layers, audit security for compute exposure, and include cluster nodes in site provisioning workflows.

### Milestone 3.6: Phase 3 Docs + Advanced Commands

| # | Task | Complexity | Dependencies | Status |
|---|------|-----------|--------------|--------|
| 102 | Implement `talos secure` command: security posture audit. Check CA expiry dates, RBAC configuration, SecureBoot status, node API port exposure. Present severity-tiered findings. | M | M3.2 | not started |
| 103 | Implement `talos config` command: view current machine config for a node (`--node {ip}`), diff configs between two nodes (`--diff {ip1} {ip2}`), detect config drift from generated baseline. | M | M2.1 | not started |
| 104 | Update `docs/talos/commands.md`: add all Phase 2 and Phase 3 commands (nodes, upgrade, diagnose, etcd, health, secure, config, Kubernetes upgrade). | M | M3.5 | not started |
| 105 | Update `docs/talos/skills.md`: add all Phase 2 and Phase 3 skill groups (nodes, diagnostics, etcd, kubernetes, security, images, network diagnostics). | M | M3.5 | not started |
| 106 | Write 5 advanced workflow examples: (a) rolling Talos OS upgrade across 4 nodes, (b) etcd snapshot and disaster recovery, (c) diagnose a node that won't rejoin the cluster, (d) Kubernetes version upgrade with pre-pull, (e) cross-vendor network verification for cluster nodes. Follow 7-section template. Include "Working Safely" section. | L | M3.5 | not started |
| 107 | Write 2 cross-vendor workflow examples: (a) provision a new VLAN and verify Talos node connectivity, (b) unified health check across firewall + switch + DNS + Kubernetes cluster. | L | M3.5 | not started |
| 108 | Update `docs/netex/commands.md` to document compute-aware cross-vendor commands: `compute health`, `compute verify-network`, `provision-site` with compute_nodes. | M | M3.5 | not started |

**Parallelizable:** Tasks 102-103 can run concurrently (depend on different milestones). Tasks 104-108 can run concurrently after M3.5. Max 5 concurrent.
**Milestone Value:** Complete Talos plugin with all commands documented, advanced workflow examples, and cross-vendor integration documented. The plugin is fully operational for homelab Kubernetes cluster management.
