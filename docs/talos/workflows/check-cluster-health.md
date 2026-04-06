# Check Cluster Health

## Intent

"I want to verify my Talos cluster is healthy -- nodes, etcd, and Kubernetes components all operational."

## Prerequisites

- **Plugin:** `talos` v0.1.0 or later
- **Binary:** `talosctl` installed and on `PATH`
- **Environment variables:** `TALOS_CONFIG` (path to talosconfig file with valid cluster context)
- **Network access:** At least one control plane node must be reachable on port 50000 (Talos gRPC)
- **Cluster state:** Cluster must be bootstrapped (health checks cannot run against nodes still in maintenance mode)

## Context

Run this workflow after initial cluster setup, after node reboots, after applying config changes, or whenever you want a quick confirmation that everything is working. The health check is entirely read-only -- it makes no changes to the cluster.

The health check produces a severity-tiered report covering node readiness, etcd membership, and Kubernetes component health. Results are classified as OK, WARNING, or CRITICAL so you can prioritize response.

This workflow does not cover detailed diagnostics like log analysis, resource usage, or network connectivity -- use `talos__diagnostics__logs` and `talos__diagnostics__events` for deeper investigation.

> **Working Safely**
>
> - **Allow time for stabilization.** After applying config changes, bootstrapping, or upgrading nodes, wait 2-3 minutes before running a health check. Kubernetes components and etcd need time to converge. Running a health check too early will produce false CRITICAL/WARNING results.
> - **Health checks are read-only.** They never modify the cluster. It is always safe to run a health check.

## Commands

### Step 1: Run a quick cluster status check

```
You: Check my Talos cluster health
```

EmberAI calls `talos__cluster__status` which combines health, version, and node membership data into a single report.

### Step 2: Review a healthy cluster

```
EmberAI:

## Cluster Status: OK

| Metric              | Value     |
|---------------------|-----------|
| Severity            | OK        |
| Nodes (total)       | 4         |
| Control plane       | 3         |
| Workers             | 1         |
| etcd                | healthy   |
| Kubernetes          | healthy   |
| All services        | healthy   |

### Versions
| Component      | Version  |
|----------------|----------|
| Talos (client) | v1.9.5   |
| Talos (server) | v1.9.5   |

### Node Inventory
| Hostname   | Role         | IP           | Ready |
|------------|--------------|--------------|-------|
| cp1        | controlplane | 10.10.10.11  | Yes   |
| cp2        | controlplane | 10.10.10.12  | Yes   |
| cp3        | controlplane | 10.10.10.13  | Yes   |
| worker1    | worker       | 10.10.10.21  | Yes   |
```

### Alternative: Review a WARNING result

```
EmberAI:

## Cluster Status: WARNING

| Metric              | Value     |
|---------------------|-----------|
| Severity            | WARNING   |
| Nodes (total)       | 4         |
| Control plane       | 3         |
| Workers             | 1         |
| Nodes healthy       | 3/4       |
| etcd                | healthy   |
| Kubernetes          | healthy   |

### Node Inventory
| Hostname   | Role         | IP           | Ready |
|------------|--------------|--------------|-------|
| cp1        | controlplane | 10.10.10.11  | Yes   |
| cp2        | controlplane | 10.10.10.12  | Yes   |
| cp3        | controlplane | 10.10.10.13  | Yes   |
| worker1    | worker       | 10.10.10.21  | No    |

worker1 has unmet conditions: ["NodeReady: kubelet not ready"]
```

### Step 3: Investigate a WARNING

```
You: Why is worker1 not ready?
```

EmberAI runs a targeted health check and service inspection on the affected node:

```
EmberAI:

worker1 (10.10.10.21) is reporting kubelet not ready. This typically
means:

1. The kubelet service is starting but has not registered with the
   API server yet (common after a reboot -- wait 1-2 minutes)
2. The node's container runtime is pulling images for the first time
3. A config change was applied but the node has not finished rebooting

Recommendation: Wait 2 minutes and re-check health. If the node remains
not ready, inspect kubelet logs with:

  "Show me the kubelet logs from worker1"
```

### Alternative: Review a CRITICAL result

```
EmberAI:

## Cluster Status: CRITICAL

| Metric              | Value     |
|---------------------|-----------|
| Severity            | CRITICAL  |
| Nodes (total)       | 4         |
| Control plane       | 3         |
| Workers             | 1         |
| Nodes healthy       | 2/4       |
| etcd                | UNHEALTHY |
| Kubernetes          | UNHEALTHY |

### Node Inventory
| Hostname   | Role         | IP           | Ready |
|------------|--------------|--------------|-------|
| cp1        | controlplane | 10.10.10.11  | Yes   |
| cp2        | controlplane | 10.10.10.12  | No    |
| cp3        | controlplane | 10.10.10.13  | No    |
| worker1    | worker       | 10.10.10.21  | No    |

Cluster health check failed -- cluster may be unhealthy.
etcd quorum may be at risk: only 1 of 3 control plane nodes is healthy.
etcd requires a majority (2 of 3) to maintain quorum.

**IMMEDIATE ACTION REQUIRED:** If 2 or more control plane nodes are
down, etcd has lost quorum and the Kubernetes API server is unavailable.
Check physical connectivity, power, and node status for cp2 and cp3.
```

### Step 4: Respond to CRITICAL (etcd quorum at risk)

```
You: What should I do about the etcd quorum issue?
```

```
EmberAI:

etcd requires a strict majority of members to be healthy for quorum:
- 3 members: 2 must be healthy (can tolerate 1 failure)
- 5 members: 3 must be healthy (can tolerate 2 failures)

Current state: 1 of 3 healthy = quorum LOST.

Immediate steps:
1. Check physical access -- verify cp2 (10.10.10.12) and cp3
   (10.10.10.13) are powered on and network-connected
2. Ping the nodes from the MCP server to verify network path
3. If nodes are reachable, check Talos services:
   "Show Talos services on cp2"
4. If nodes are unreachable, check switch port status and cabling

Do NOT bootstrap etcd again -- this would destroy the cluster.
Do NOT reset any nodes -- this removes them from the cluster permanently.

Once the nodes come back online, etcd will automatically recover quorum.
```

## What to Look For

**Severity tiers:**
- **OK** -- all nodes healthy, etcd healthy, Kubernetes healthy. No action needed.
- **WARNING** -- one or more nodes not ready, or a Kubernetes component is unhealthy, but etcd has quorum. Investigate but not urgent.
- **CRITICAL** -- etcd unhealthy (quorum at risk or lost), or zero healthy nodes. Requires immediate attention.

**Node inventory:**
- **Ready column** -- all nodes should show "Yes". A node showing "No" needs investigation.
- **Node count** -- should match your expected cluster size. A missing node may indicate it was reset or never joined.
- **Role distribution** -- verify the expected number of control plane vs worker nodes.

**etcd health:**
- **healthy** -- etcd cluster is fully operational with quorum.
- **UNHEALTHY** -- etcd quorum is at risk or lost. This is the most critical finding -- without etcd, Kubernetes cannot function.

**Version alignment:**
- **Talos client and server** -- should match. A mismatch may cause compatibility issues.
- **Kubernetes version** -- all nodes should run the same Kubernetes version.

## Next Steps

- [First-Time Cluster Setup](first-time-cluster-setup.md) -- if the cluster is not yet provisioned
- [Config Patches](config-patches.md) -- apply configuration changes if adjustments are needed

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "health data unavailable" | Cannot reach any control plane node | Verify `TALOS_CONFIG` is set and talosctl endpoints point to reachable control plane IPs; check network connectivity |
| All three sub-queries failed | talosctl not configured or nodes unreachable | Run `talosctl version` manually to verify connectivity; check that `TALOS_CONFIG` points to a valid talosconfig |
| Single node shows "not ready" right after reboot | Node still converging | Wait 2-3 minutes and re-check; kubelet and container runtime need time to start after a reboot |
| CRITICAL with etcd UNHEALTHY | Control plane node(s) down | Check physical power, cabling, and network for affected CP nodes; do NOT re-bootstrap -- etcd recovers automatically when nodes return |
| WARNING with Kubernetes unhealthy but etcd healthy | API server or controller-manager restarting | Usually transient; wait 1-2 minutes and re-check. If persistent, inspect service logs on the affected node |
| Version shows "None" for server | Node unreachable or talosctl endpoint misconfigured | Verify endpoints with `talosctl config info`; endpoints must be real CP node IPs, not the VIP |
| "member data unavailable" | etcd not yet initialized or node not a CP | Ensure you are querying a control plane node; worker nodes do not have etcd |
