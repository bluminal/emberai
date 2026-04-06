# Talos Commands Reference

Commands are the user-facing entry points to the talos plugin. Each command orchestrates multiple tools from the skills layer to produce a complete workflow or report.

Phase 1 includes one **write command** (`cluster-setup`) and one **read-only command** (`cluster-status`).

---

## `talos cluster-setup`

Guided, multi-phase workflow to provision a Talos Linux Kubernetes cluster from scratch.

### What It Does

Walks the operator through a three-phase process that takes bare-metal nodes booted into Talos maintenance mode and produces a fully running HA Kubernetes cluster:

1. **Gather** -- Validates all cluster parameters (node IPs, VIP, disk, cluster name). Rejects invalid IPs, duplicate addresses, VIP collisions, and clusters with fewer than 3 control plane nodes.
2. **Plan** -- Builds an ordered list of execution steps with dependencies. The plan is logged before execution begins.
3. **Execute** -- Runs each step sequentially, verifies success, and reports progress. If any step fails, execution halts immediately with recovery guidance.

The full orchestration sequence:

1. Generate secrets bundle (`talos__config__gen_secrets`)
2. Generate cluster configs (`talos__config__gen_config`)
3. Patch controlplane config with VIP (if specified) (`talos__config__patch_machineconfig`)
4. Patch configs with KubeSpan (if enabled) (`talos__config__patch_machineconfig`)
5. Validate controlplane config (`talos__config__validate`)
6. Validate worker config (`talos__config__validate`)
7. Apply controlplane config to each CP node in insecure mode (`talos__cluster__apply_config`)
8. Apply worker config to each worker node in insecure mode (`talos__cluster__apply_config`)
9. Set talosctl endpoints to control plane IPs (`talos__cluster__set_endpoints`)
10. Merge generated talosconfig into local config (`talos__cluster__merge_talosconfig`)
11. Bootstrap etcd on the first control plane node (`talos__cluster__bootstrap`)
12. Wait for cluster health (`talos__cluster__health`)
13. Retrieve admin kubeconfig (`talos__cluster__kubeconfig`)

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cluster_name` | string | *(required)* | Name of the Kubernetes cluster |
| `control_plane_ips` | string | *(required)* | Comma-separated list of control plane node IPs (minimum 3 for HA) |
| `worker_ips` | string | `""` | Comma-separated list of worker node IPs. Empty for control-plane-only clusters |
| `vip` | string | `""` | Virtual IP for the Kubernetes API endpoint. Must not collide with any node IP |
| `install_disk` | string | `"/dev/sda"` | Target disk for Talos installation on each node |
| `kubernetes_version` | string | `""` | Pin a specific Kubernetes version. Empty uses the Talos default |
| `enable_kubespan` | bool | `false` | Enable KubeSpan (WireGuard mesh) between nodes |
| `output_dir` | string | `""` | Directory for generated config files. Empty uses current directory |
| `apply` | bool | `false` | Must be `true` to execute (requires `TALOS_WRITE_ENABLED=true`) |

### Write Safety

This command provisions an entire cluster. It is the most write-heavy operation in the plugin.

- **Env var gate:** `TALOS_WRITE_ENABLED` must be set to `"true"`
- **Apply flag gate:** `--apply` must be present
- **Operator confirmation:** The full plan is presented before execution begins

### Safety Warnings

- **Disk wipe:** Applying a Talos config to a node installs Talos to the specified disk, wiping all existing data on that disk. Double-check `install_disk` before confirming.
- **Bootstrap is irreversible:** The etcd bootstrap step is a ONE-TIME operation. Running bootstrap on a cluster that already has etcd members will corrupt the cluster. The workflow includes a pre-flight check (`etcd_members_count`) to prevent this.
- **Use real IPs, not VIP, for talosctl endpoints:** The VIP is for Kubernetes API access only. `talosctl` needs direct node IPs for gRPC communication. The workflow handles this automatically by setting endpoints to the control plane node IPs.
- **Nodes must be in maintenance mode:** All target nodes must be booted into Talos maintenance mode and reachable at the specified IPs before running this command.

### Example

```
You: Set up a 4-node Talos cluster with 3 control plane nodes and 1 worker

EmberAI: I'll walk you through the cluster setup. First, let me gather your
cluster parameters.

What cluster name would you like to use?

You: homelab

EmberAI: What are the control plane node IPs? (minimum 3 for HA)

You: 10.10.10.11, 10.10.10.12, 10.10.10.13

EmberAI: What is the worker node IP?

You: 10.10.10.21

EmberAI: What VIP should I use for the Kubernetes API endpoint?

You: 10.10.10.10

EmberAI:

## Cluster Setup Plan

| Parameter         | Value                                    |
|-------------------|------------------------------------------|
| Cluster name      | homelab                                  |
| Control plane IPs | 10.10.10.11, 10.10.10.12, 10.10.10.13   |
| Worker IPs        | 10.10.10.21                              |
| VIP               | 10.10.10.10                              |
| K8s API endpoint  | https://10.10.10.10:6443                 |
| Install disk      | /dev/sda                                 |
| KubeSpan          | Disabled                                 |

### Execution Steps (15 total)
 1. Generate cluster secrets bundle
 2. Generate cluster configs for 'homelab'
 3. Patch controlplane config with VIP 10.10.10.10
 4. Validate controlplane configuration
 5. Validate worker configuration
 6. Apply controlplane config to CP1 (10.10.10.11)
 7. Apply controlplane config to CP2 (10.10.10.12)
 8. Apply controlplane config to CP3 (10.10.10.13)
 9. Apply worker config to Worker1 (10.10.10.21)
10. Set talosctl endpoints to control plane IPs
11. Merge generated talosconfig into local config
12. Bootstrap etcd on first control plane (10.10.10.11)
13. Wait for cluster to become healthy
14. Retrieve admin kubeconfig

**WARNING:** Step 6-9 will wipe /dev/sda on each target node.
**WARNING:** Step 12 (bootstrap) is irreversible.

Proceed? Requires --apply and TALOS_WRITE_ENABLED=true.

You: Yes, apply

EmberAI:

## Cluster Setup Progress

| Step | Description                                  | Status  |
|------|----------------------------------------------|---------|
|  1   | Generate cluster secrets bundle              | done    |
|  2   | Generate cluster configs for 'homelab'       | done    |
|  3   | Patch controlplane config with VIP           | done    |
|  4   | Validate controlplane configuration          | done    |
|  5   | Validate worker configuration                | done    |
|  6   | Apply controlplane config to CP1             | done    |
|  7   | Apply controlplane config to CP2             | done    |
|  8   | Apply controlplane config to CP3             | done    |
|  9   | Apply worker config to Worker1               | done    |
| 10   | Set talosctl endpoints                       | done    |
| 11   | Merge talosconfig                            | done    |
| 12   | Bootstrap etcd on CP1                        | done    |
| 13   | Wait for cluster health                      | done    |
| 14   | Retrieve admin kubeconfig                    | done    |

## Cluster Summary

| Metric              | Value                                  |
|---------------------|----------------------------------------|
| Cluster name        | homelab                                |
| API endpoint        | https://10.10.10.10:6443               |
| Control plane nodes | 3 (10.10.10.11, 10.10.10.12, 10.10.10.13) |
| Worker nodes        | 1 (10.10.10.21)                        |
| VIP                 | 10.10.10.10                            |
| Steps completed     | 14/14                                  |
| Kubeconfig          | Retrieved                              |

Cluster 'homelab' setup completed successfully. All 14 steps passed.

**Important:** Store the generated secrets.yaml securely -- it contains
the root CAs and encryption keys for this cluster.
```

### Example (Failure with Recovery)

```
You: Set up the cluster with --apply

EmberAI:

## Cluster Setup Progress

| Step | Description                                  | Status  |
|------|----------------------------------------------|---------|
|  1   | Generate cluster secrets bundle              | done    |
|  2   | Generate cluster configs for 'homelab'       | done    |
|  3   | Patch controlplane config with VIP           | done    |
|  4   | Validate controlplane configuration          | done    |
|  5   | Validate worker configuration                | done    |
|  6   | Apply controlplane config to CP1             | done    |
|  7   | Apply controlplane config to CP2             | FAILED  |

## Failure Details

| Field    | Value                                                    |
|----------|----------------------------------------------------------|
| Step     | 7                                                        |
| Tool     | talos__cluster__apply_config                              |
| Node     | 10.10.10.12                                              |
| Error    | Connection refused: node not reachable in maintenance mode|

### Recovery Guidance
Config apply failed for node 10.10.10.12. Verify the node is booted into
Talos maintenance mode and is reachable at that IP address. Previously
configured nodes (10.10.10.11) do not need to be re-applied.
```

### Tools Called

The `cluster-setup` command orchestrates these tools in sequence:

- `talos__config__gen_secrets` -- generate the cluster secrets bundle (CAs, encryption keys)
- `talos__config__gen_config` -- generate controlplane and worker machine configs
- `talos__config__patch_machineconfig` -- apply VIP and/or KubeSpan patches
- `talos__config__validate` -- validate generated configs
- `talos__cluster__apply_config` -- push machine config to each node (insecure mode)
- `talos__cluster__set_endpoints` -- configure talosctl to use the CP node IPs
- `talos__cluster__merge_talosconfig` -- merge the generated talosconfig into local config
- `talos__cluster__bootstrap` -- initialize etcd on the first control plane node
- `talos__cluster__health` -- wait for the cluster to become healthy
- `talos__cluster__kubeconfig` -- retrieve the admin kubeconfig

---

## `talos cluster-status`

Quick cluster overview combining health, version, and node membership into a single report.

### What It Does

Runs three queries in parallel and merges the results into a unified report:

1. **Health check** -- executes `talosctl health` to determine cluster-level and per-node health
2. **Version info** -- executes `talosctl version` to get Talos and Kubernetes versions
3. **Node membership** -- executes `talosctl get members` to enumerate nodes by role

Each sub-query is independent. If one fails, the remaining results are still returned with the failure noted as a partial status.

The report assigns an overall severity:

| Severity | Condition |
|----------|-----------|
| **OK** | All nodes healthy, etcd healthy, Kubernetes healthy, all services healthy |
| **WARNING** | Some nodes unhealthy, or Kubernetes not healthy, or some services not healthy |
| **CRITICAL** | Zero nodes healthy, or etcd unhealthy |
| **UNKNOWN** | Health data unavailable (all sub-queries failed) |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `node` | string | `""` | Target node to query. Uses the default talosconfig node if empty |

### Example

```
You: How's the Talos cluster doing?

EmberAI:

## Cluster Status: OK

| Metric              | Value       |
|---------------------|-------------|
| Severity            | OK          |
| Total nodes         | 4           |
| Control plane       | 3           |
| Workers             | 1           |
| Talos version       | v1.9.5      |
| Kubernetes version  | v1.32.3     |
| etcd                | Healthy     |
| Kubernetes          | Healthy     |
| All services        | Healthy     |

### Node Inventory
| Hostname     | Role          | Addresses    | Ready |
|--------------|---------------|--------------|-------|
| cp1          | controlplane  | 10.10.10.11  | Yes   |
| cp2          | controlplane  | 10.10.10.12  | Yes   |
| cp3          | controlplane  | 10.10.10.13  | Yes   |
| worker1      | worker        | 10.10.10.21  | Yes   |
```

### Example (Degraded Cluster)

```
You: Cluster status

EmberAI:

## Cluster Status: WARNING

| Metric              | Value       |
|---------------------|-------------|
| Severity            | WARNING     |
| Total nodes         | 4           |
| Control plane       | 3           |
| Workers             | 1           |
| Talos version       | v1.9.5      |
| Kubernetes version  | v1.32.3     |
| etcd                | Healthy     |
| Kubernetes          | Healthy     |
| All services        | No          |

### Node Inventory
| Hostname     | Role          | Addresses    | Ready | Notes              |
|--------------|---------------|--------------|-------|--------------------|
| cp1          | controlplane  | 10.10.10.11  | Yes   |                    |
| cp2          | controlplane  | 10.10.10.12  | Yes   |                    |
| cp3          | controlplane  | 10.10.10.13  | No    | Unmet: NodeReady   |
| worker1      | worker        | 10.10.10.21  | Yes   |                    |

### Recommendations
- **cp3 is not ready**: Check node services with `talosctl services -n 10.10.10.13`
  and review logs with `talosctl logs kubelet -n 10.10.10.13`.
```

### Example (Partial Failure)

```
You: Cluster status

EmberAI:

## Cluster Status (Partial)

| Metric              | Value                        |
|---------------------|------------------------------|
| Severity            | OK                           |
| Total nodes         | 4                            |
| Control plane       | 3                            |
| Workers             | 1                            |

**Note:** 1 of 3 status sub-queries failed.

| Sub-query | Status  | Error                                  |
|-----------|---------|----------------------------------------|
| health    | OK      |                                        |
| version   | Failed  | talosctl not configured for this node  |
| members   | OK      |                                        |
```

### Output Fields

| Field | Type | Description |
|-------|------|-------------|
| `severity` | string | Overall cluster health: `OK`, `WARNING`, `CRITICAL`, or `UNKNOWN` |
| `nodes.total` | int | Total number of cluster members |
| `nodes.control_plane` | int | Number of control plane nodes |
| `nodes.workers` | int | Number of worker nodes |
| `nodes.details` | array | Per-node hostname, role, addresses, and ready status |
| `versions.talos_server` | string | Talos server version tag |
| `versions.talos_client` | string | Talos client version tag |
| `health.etcd_healthy` | bool | Whether etcd cluster is healthy |
| `health.kubernetes_healthy` | bool | Whether Kubernetes components are healthy |
| `health.all_services_healthy` | bool | Whether all node services are healthy |
| `health.nodes_healthy` | int | Count of healthy nodes |
| `health.nodes_total` | int | Total node count from health check |
| `errors` | array | Sub-query errors (only present if partial failure) |

### Tools Called

- `talos__cluster__health` -- cluster health check with severity classification
- `talos__cluster__get_version` -- Talos and Kubernetes version info
- `talosctl get members` (via `TalosCtlClient`) -- node membership and role enumeration

---

## Phase 2+ Commands (Not Yet Implemented)

The following commands are planned for future releases.

| Command | Intent | Phase |
|---------|--------|-------|
| `talos node-status` | Detailed single-node diagnostics (services, logs, resources) | Phase 2 |
| `talos etcd-status` | etcd cluster health, member list, DB size, defragmentation | Phase 2 |
| `talos upgrade` | Rolling Talos and Kubernetes upgrades with pre-flight checks | Phase 2 |
| `talos secure` | Security audit: SecureBoot status, CA rotation, API access | Phase 3 |
