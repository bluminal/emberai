# Talos Skills Reference

Skills are groups of MCP tools that provide access to Talos Linux cluster operations via the `talosctl` CLI. Each tool wraps a single `talosctl` command and returns normalized data. Tools are called by [commands](commands.md) through agent orchestrators, but can also be called individually.

All tools follow the naming convention: `talos__{skill}__{operation}`

---

## config

Configuration generation and validation. Five tools covering secrets generation, cluster config generation, config validation, machine config patching, and live config retrieval.

### `talos__config__gen_secrets` (write)

Generate a cluster secrets bundle and write it to a file. The secrets file contains the root CA and bootstrap token for the entire cluster -- store it securely and never commit it to version control.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_path` | string | *required* | Filesystem path where the secrets bundle will be written |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `TALOS_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"success"` or `"error"` |
| `output_path` | string | Path where the secrets file was written |
| `message` | string | Human-readable result message |
| `warning` | string | Security warning about storing the secrets file safely |

On error:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"error"` |
| `error` | string | Error message |
| `stderr` | string | Raw stderr output |
| `exit_code` | int | Process exit code |

**CLI:** `talosctl gen secrets -o <output_path>`

---

### `talos__config__gen_config` (write)

Generate Talos machine configuration files (controlplane.yaml, worker.yaml, talosconfig) for a cluster.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cluster_name` | string | *required* | Name of the Kubernetes cluster |
| `endpoint` | string | *required* | Control plane endpoint URL (e.g. `https://10.0.0.1:6443`) |
| `secrets_file` | string | `""` | Path to a previously generated secrets bundle |
| `install_disk` | string | `"/dev/sda"` | Target disk for Talos installation |
| `kubernetes_version` | string | `""` | Pin a specific Kubernetes version |
| `talos_version` | string | `""` | Pin a specific Talos version for the generated config |
| `output_dir` | string | `""` | Directory to write generated files into (default: current directory) |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `TALOS_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"success"` or `"error"` |
| `cluster_name` | string | Cluster name used for generation |
| `endpoint` | string | Control plane endpoint used |
| `output_dir` | string | Directory where files were written |
| `message` | string | Human-readable result message |
| `generated_files` | list[string] | List of generated files: `controlplane.yaml`, `worker.yaml`, `talosconfig` |

On error:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"error"` |
| `error` | string | Error message |
| `stderr` | string | Raw stderr output |
| `exit_code` | int | Process exit code |

**CLI:** `talosctl gen config <cluster_name> <endpoint> [--with-secrets <file>] [--install-disk <disk>] [--kubernetes-version <ver>] [--talos-version <ver>] [--output-dir <dir>]`

---

### `talos__config__validate`

Validate a Talos machine configuration file. Read-only -- makes no changes.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `config_file` | string | *required* | Path to the machine configuration YAML to validate |
| `mode` | string | `"metal"` | Validation mode: `metal`, `cloud`, or `container` |

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"pass"` or `"fail"` |
| `config_file` | string | Path to the validated config file |
| `mode` | string | Validation mode used |
| `message` | string | Human-readable result (on pass) |
| `errors` | string | Validation errors (on fail) |
| `exit_code` | int | Process exit code (on fail) |

**CLI:** `talosctl validate --config <file> --mode <mode> --strict`

---

### `talos__config__patch_machineconfig` (write)

Patch a Talos machine configuration file using JSON patches. Accepts inline JSON or a `@<filepath>` reference to a patch file.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `config_file` | string | *required* | Path to the machine configuration YAML to patch |
| `patches` | string | *required* | Inline JSON patch string or `@<filepath>` pointing to a patch file |
| `output_file` | string | `""` | Output path for patched config. If omitted, patched config is returned in the response |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `TALOS_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"success"` or `"error"` |
| `config_file` | string | Path to the original config file |
| `message` | string | Human-readable result message |
| `output_file` | string | Output path (when `output_file` was provided) |
| `patched_config` | string | Patched config content (when `output_file` was omitted) |

On error:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"error"` |
| `error` | string | Error message |
| `stderr` | string | Raw stderr output |
| `exit_code` | int | Process exit code |

**CLI:** `talosctl machineconfig patch <config_file> --patch <patches> [--output <output_file>]`

---

### `talos__config__get_machineconfig`

Retrieve the machine configuration from a running Talos node. Read-only. Secrets and keys are automatically redacted from the output.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `node` | string | `""` | Target node IP or hostname. Uses the default node from talosconfig if not specified |

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"success"` or `"error"` |
| `node` | string | Target node (when specified) |
| `machineconfig` | dict | Parsed machine config with secrets redacted (when JSON parsing succeeds) |
| `raw_output` | string | Raw config output (fallback when JSON parsing fails) |
| `note` | string | Reminder that secrets have been redacted |

On error:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"error"` |
| `error` | string | Error message |
| `stderr` | string | Raw stderr output |
| `exit_code` | int | Process exit code |

**Redaction:** Keys matching `key`, `secret`, `token`, `crt`, `cert`, `ca`, `bootstrap`, `aescbcEncryptionSecret`, `trustdinfo`, `bootstraptoken` (case-insensitive) are replaced with `[REDACTED]`.

**CLI:** `talosctl get machineconfig [-n <node>] -o json`

---

## cluster

Cluster lifecycle operations. Eight tools covering config application, etcd bootstrap, kubeconfig retrieval, health checks, version queries, endpoint configuration, talosconfig merging, and a unified status overview.

### `talos__cluster__apply_config` (write)

Apply a machine configuration to a Talos node. Validates the config file first via `talosctl validate`. Use `insecure=True` for first-time apply to unconfigured nodes (before mTLS is established).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `node` | string | *required* | Target node IP or hostname |
| `config_file` | string | *required* | Path to the machine configuration YAML file |
| `insecure` | bool | `false` | Use insecure (maintenance) mode for first-time apply |
| `mode` | string | `"auto"` | Apply mode: `auto`, `interactive`, `no-reboot`, `reboot`, `staged` |
| `dry_run` | bool | `false` | If `true`, validate only -- do not apply |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `TALOS_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` or `"error"` |
| `operation` | string | `"apply_config"` or `"dry_run"` or `"validate"` |
| `node` | string | Target node |
| `config_file` | string | Config file path |
| `insecure` | bool | Whether insecure mode was used |
| `mode` | string | Apply mode used |
| `message` | string | Human-readable result message |

On validation or apply error:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"error"` |
| `operation` | string | Which step failed (`"validate"` or `"apply_config"`) |
| `error` | string | Error message |
| `stderr` | string | Raw stderr output |

**CLI:** `talosctl apply-config --file <config_file> [--mode <mode>] [-n <node>] [--insecure]`

---

### `talos__cluster__bootstrap` (write)

Bootstrap etcd on the first control plane node. **This is a ONE-TIME operation.** Running bootstrap on a cluster that already has etcd members will corrupt the cluster and cause data loss.

The caller MUST query `talosctl etcd members` beforehand and pass the result count as `etcd_members_count`. The `bootstrap_gate` decorator blocks execution if `etcd_members_count > 0`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `node` | string | *required* | The first control plane node to bootstrap etcd on |
| `etcd_members_count` | int | `0` | Number of existing etcd members (0 = safe to bootstrap) |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `TALOS_WRITE_ENABLED=true`, `apply=True`, AND `etcd_members_count=0` (bootstrap gate, TD5).

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` or `"error"` |
| `operation` | string | `"bootstrap"` |
| `node` | string | Target node |
| `message` | string | Human-readable result message |
| `warning` | string | Reminder that bootstrap is a ONE-TIME operation |

On error:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"error"` |
| `operation` | string | `"bootstrap"` |
| `error` | string | Error message |
| `stderr` | string | Raw stderr output |

**CLI:** `talosctl bootstrap [-n <node>]`

---

### `talos__cluster__kubeconfig`

Retrieve the admin kubeconfig from the Talos cluster. If `output_path` is provided, the kubeconfig is written to that file. Otherwise the kubeconfig content is returned in the response. Read-only.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `node` | string | `""` | Target node to retrieve kubeconfig from. Uses default if empty |
| `output_path` | string | `""` | File path to write the kubeconfig to. If empty, returns the content directly |

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` or `"error"` |
| `operation` | string | `"kubeconfig"` |
| `output_path` | string | File path (when written to file) |
| `kubeconfig` | string | Kubeconfig content (when returned directly) |
| `message` | string | Human-readable result message |

On error:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"error"` |
| `operation` | string | `"kubeconfig"` |
| `error` | string | Error message |
| `stderr` | string | Raw stderr output |

**CLI:** `talosctl kubeconfig [<output_path>|-] [-n <node>]`

---

### `talos__cluster__health`

Run a cluster health check and return a severity-tiered report. Categorizes results into CRITICAL, WARNING, and OK tiers based on node health, etcd status, Kubernetes health, and service state.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `node` | string | `""` | Target node to check health from. Uses default if empty |
| `wait_timeout` | string | `""` | Timeout to wait for cluster to be healthy (e.g. `"5m"`). Uses talosctl default if empty |

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` or `"error"` |
| `operation` | string | `"health"` |
| `severity` | string | `"OK"`, `"WARNING"`, or `"CRITICAL"` |
| `cluster` | dict | Cluster-level health summary |
| `nodes` | list[dict] | Per-node health details |
| `message` | string | Human-readable health summary |

Cluster-level fields:

| Field | Type | Description |
|-------|------|-------------|
| `nodes_healthy` | int | Number of healthy nodes |
| `nodes_total` | int | Total number of nodes |
| `etcd_healthy` | bool | Whether etcd is healthy |
| `kubernetes_healthy` | bool | Whether Kubernetes is healthy |
| `all_services_healthy` | bool | Whether all Talos services are healthy |

Per-node fields:

| Field | Type | Description |
|-------|------|-------------|
| `hostname` | string | Node hostname |
| `ready` | bool | Whether the node is ready |
| `error` | string | Error message (when present) |
| `unmet_conditions` | list | Unmet health conditions (when present) |

**Severity logic:**
- **CRITICAL** -- No healthy nodes, or etcd unhealthy
- **WARNING** -- Some nodes unhealthy, or Kubernetes unhealthy, or services unhealthy
- **OK** -- All nodes healthy, etcd healthy, Kubernetes healthy, all services healthy

**CLI:** `talosctl health [-n <node>] [--wait-timeout <duration>] -o json`

---

### `talos__cluster__get_version`

Get talosctl client and server version information. Read-only.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `node` | string | `""` | Target node to query. Uses default if empty |

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` or `"error"` |
| `operation` | string | `"version"` |
| `client_version` | dict | Client version details (e.g. `{"tag": "v1.9.0", ...}`) |
| `server_versions` | list[dict] | Per-node server version details |

Each server version entry:

| Field | Type | Description |
|-------|------|-------------|
| `hostname` | string | Node hostname |
| `version` | dict | Server version details |

On error:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"error"` |
| `operation` | string | `"version"` |
| `error` | string | Error message |
| `stderr` | string | Raw stderr output |

**CLI:** `talosctl version [-n <node>] -o json`

---

### `talos__cluster__set_endpoints` (write)

Set the talosctl config endpoints. Updates the talosconfig to point at the specified control plane node IPs.

**Warning:** Do not use a VIP (Virtual IP) as an endpoint. VIPs are for Kubernetes API access; talosctl needs direct node IPs for gRPC communication.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `endpoints` | string | *required* | Space-separated list of control plane node IPs (e.g. `"192.168.30.10 192.168.30.11 192.168.30.12"`) |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `TALOS_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` or `"error"` |
| `operation` | string | `"set_endpoints"` |
| `endpoints` | list[string] | List of endpoint IPs that were set |
| `message` | string | Human-readable result message |
| `warnings` | list[string] | VIP warnings (when VIP-like addresses detected) |
| `warning` | string | VIP usage warning summary (when VIP-like addresses detected) |

On error:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"error"` |
| `operation` | string | `"set_endpoints"` |
| `error` | string | Error message |
| `stderr` | string | Raw stderr output |

**CLI:** `talosctl config endpoint <ip1> <ip2> ...`

---

### `talos__cluster__merge_talosconfig` (write)

Merge a talosconfig file into the current default talosconfig. Merges contexts from the specified file.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `talosconfig_path` | string | *required* | Path to the talosconfig file to merge |
| `apply` | bool | `false` | Must be `true` to execute (write gate) |

**Write safety:** Requires `TALOS_WRITE_ENABLED=true` and `apply=True`.

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` or `"error"` |
| `operation` | string | `"merge_talosconfig"` |
| `talosconfig_path` | string | Path to the merged talosconfig file |
| `message` | string | Human-readable result message |

On error:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"error"` |
| `operation` | string | `"merge_talosconfig"` |
| `error` | string | Error message |
| `stderr` | string | Raw stderr output |

**CLI:** `talosctl config merge <talosconfig_path>`

---

### `talos__cluster__status`

Get a unified cluster status overview in a single call. Combines health, version, and node membership data into one structured report. Each sub-call is independent -- if one fails, the remaining results are still returned with the failure noted. Read-only.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `node` | string | `""` | Target node to query. Uses default if empty |

**Returns:** `dict`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` or `"error"` |
| `operation` | string | `"cluster_status"` |
| `severity` | string | `"OK"`, `"WARNING"`, `"CRITICAL"`, or `"UNKNOWN"` |
| `health` | dict | Cluster health summary (from `talos__cluster__health`) |
| `versions` | dict | Talos and Kubernetes version info |
| `nodes` | dict | Node inventory |
| `errors` | list[dict] | Sub-call errors (when any sub-query failed) |
| `message` | string | Human-readable status summary |

Version fields:

| Field | Type | Description |
|-------|------|-------------|
| `talos_client` | string | Talos client version tag |
| `talos_server` | string | Talos server version tag |

Node inventory fields:

| Field | Type | Description |
|-------|------|-------------|
| `total` | int | Total node count |
| `control_plane` | int | Number of control plane nodes |
| `workers` | int | Number of worker nodes |
| `details` | list[dict] | Per-node details |

Per-node detail:

| Field | Type | Description |
|-------|------|-------------|
| `hostname` | string | Node hostname |
| `role` | string | Node role: `controlplane` or `worker` |
| `addresses` | list[string] | Node IP addresses |
| `ready` | bool | Whether the node is ready (from health data, when available) |
| `error` | string | Node-level error (when present) |

Error entry:

| Field | Type | Description |
|-------|------|-------------|
| `component` | string | Which sub-query failed: `health`, `version`, or `members` |
| `error` | string | Error message |

**CLI:** Composite -- calls `talosctl health`, `talosctl version`, and `talosctl get members` internally

---

## Phase 2+ Skills (Not Yet Implemented)

The following skill groups are defined in the plugin manifest but not yet implemented:

| Skill Group | Tools | Phase |
|-------------|-------|-------|
| node | `reboot`, `shutdown`, `reset`, `upgrade`, `get_services`, `get_service_info`, `restart_service` | Phase 2 |
| etcd | `get_members`, `snapshot`, `restore`, `defrag`, `remove_member`, `force_new_cluster` | Phase 2 |
| diagnostics | `get_logs`, `get_events`, `get_resources`, `get_mounts`, `dmesg`, `netstat`, `dashboard_snapshot` | Phase 2 |
| security | `rotate_ca`, `get_secureboot_status`, `enroll_secureboot_keys`, `get_certificates`, `rotate_certificates` | Phase 3 |
| images | `list_images`, `pull_image`, `get_image_usage`, `cleanup_images`, `verify_image_signatures` | Phase 3 |
