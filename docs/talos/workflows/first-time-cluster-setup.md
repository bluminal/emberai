# First-Time Cluster Setup

## Intent

"I want to provision a new HA Kubernetes cluster on my bare-metal Talos Linux nodes."

## Prerequisites

- **Plugin:** `talos` v0.1.0 or later
- **Binary:** `talosctl` installed and on `PATH`
- **Environment variables:** `TALOS_CONFIG` (path to talosconfig file), `TALOS_WRITE_ENABLED=true`
- **Network access:** All nodes must be booted into Talos maintenance mode and reachable from the MCP server on port 50000 (Talos gRPC)
- **Hardware:** All target nodes powered on and PXE/ISO booted into Talos Linux (maintenance mode)

## Context

Run this workflow once when provisioning a brand-new Talos Linux Kubernetes cluster. It walks through the complete setup process: generating secrets, generating and patching configs, applying configs to each node, bootstrapping etcd, and retrieving the admin kubeconfig.

This workflow produces a fully operational HA Kubernetes cluster with 3 control plane nodes and 1 worker node, using a Virtual IP (VIP) for the Kubernetes API endpoint.

This workflow does not cover post-setup operations like deploying workloads, configuring CNI, or setting up ingress -- those are separate concerns after the cluster is running.

> **Working Safely**
>
> - **Bootstrap is irreversible and ONE-TIME.** Running `bootstrap` on a cluster that already has etcd members will corrupt the cluster and cause data loss. The plugin blocks this with a pre-flight check, but understand the risk.
> - **Apply-config wipes the install disk.** When you apply a config to a node in maintenance mode, Talos installs to the specified disk (e.g., `/dev/sda`), destroying all existing data on that disk.
> - **Use real control plane IPs for talosctl endpoints, NOT the VIP.** The VIP is for Kubernetes API access only. `talosctl` communicates via gRPC directly with nodes and needs their actual IPs. The VIP only works after the cluster is fully bootstrapped.
> - **Secrets file is the master credential.** The generated `secrets.yaml` contains the root CA and bootstrap token for the entire cluster. Store it securely (e.g., a secrets manager) and never commit it to version control.

## Commands

### Step 1: Start the guided setup

```
You: Set up a new Talos cluster called "homelab" with control plane nodes
at 10.10.10.11, 10.10.10.12, 10.10.10.13 and a worker at 10.10.10.21.
Use VIP 10.10.10.10 and install disk /dev/sda.
```

EmberAI calls `talos__cluster__setup` which orchestrates the full provisioning process in three phases: gather, plan, and execute.

### Step 2: Review the plan

Before executing, EmberAI presents the plan for confirmation:

```
EmberAI:

## Cluster Setup Plan: "homelab"

| Parameter         | Value                             |
|-------------------|-----------------------------------|
| Cluster name      | homelab                           |
| Control plane IPs | 10.10.10.11, 10.10.10.12, 10.10.10.13 |
| Worker IPs        | 10.10.10.21                       |
| VIP               | 10.10.10.10                       |
| API endpoint      | https://10.10.10.10:6443          |
| Install disk      | /dev/sda                          |

### Execution Steps (14 total)

| # | Step                                               |
|---|----------------------------------------------------|
| 1 | Generate cluster secrets bundle                    |
| 2 | Generate cluster configs for 'homelab'             |
| 3 | Patch controlplane config with VIP 10.10.10.10     |
| 4 | Validate controlplane configuration                |
| 5 | Validate worker configuration                      |
| 6 | Apply controlplane config to CP1 (10.10.10.11)     |
| 7 | Apply controlplane config to CP2 (10.10.10.12)     |
| 8 | Apply controlplane config to CP3 (10.10.10.13)     |
| 9 | Apply worker config to Worker1 (10.10.10.21)       |
| 10| Set talosctl endpoints to control plane IPs        |
| 11| Merge generated talosconfig into local config      |
| 12| Bootstrap etcd on first control plane (10.10.10.11)|
| 13| Wait for cluster to become healthy                 |
| 14| Retrieve admin kubeconfig                          |

**WARNING:** This is a write-heavy operation. Configs will be applied in
insecure (maintenance) mode. Install disk /dev/sda will be wiped on all
4 nodes. Bootstrap is irreversible.

Proceed?
```

### Step 3: Confirm and watch progress

```
You: Yes, proceed
```

EmberAI executes each step and reports progress:

```
EmberAI:

Step 1/14: Generate cluster secrets bundle ... done
Step 2/14: Generate cluster configs for 'homelab' ... done
Step 3/14: Patch controlplane config with VIP 10.10.10.10 ... done
Step 4/14: Validate controlplane configuration ... done
Step 5/14: Validate worker configuration ... done
Step 6/14: Apply controlplane config to CP1 (10.10.10.11) ... done
Step 7/14: Apply controlplane config to CP2 (10.10.10.12) ... done
Step 8/14: Apply controlplane config to CP3 (10.10.10.13) ... done
Step 9/14: Apply worker config to Worker1 (10.10.10.21) ... done
Step 10/14: Set talosctl endpoints to control plane IPs ... done
Step 11/14: Merge generated talosconfig into local config ... done
Step 12/14: Bootstrap etcd on first control plane (10.10.10.11) ... done
  Polling etcd members: 3/3 control plane nodes joined.
Step 13/14: Wait for cluster to become healthy ... done
Step 14/14: Retrieve admin kubeconfig ... done
```

### Step 4: Review the cluster summary

```
EmberAI:

## Cluster Setup Complete

Cluster 'homelab' setup completed successfully. All 14 steps passed.

| Metric              | Value                              |
|---------------------|------------------------------------|
| Cluster name        | homelab                            |
| API endpoint        | https://10.10.10.10:6443           |
| Control plane nodes | 10.10.10.11, 10.10.10.12, 10.10.10.13 |
| Worker nodes        | 10.10.10.21                        |
| Total nodes         | 4                                  |
| VIP                 | 10.10.10.10                        |
| Kubeconfig          | Retrieved                          |

SECURITY: Store the secrets.yaml file in a secure location and never
commit it to version control. It contains the cluster root CA and
bootstrap token.
```

### Alternative: Handling a failed step

If a step fails, the workflow stops and provides recovery guidance:

```
EmberAI:

## Cluster Setup Failed

Step 6/14 failed: Apply controlplane config to CP1 (10.10.10.11)

Error: connection refused: dial tcp 10.10.10.11:50000: connect: connection refused

### Completed Steps
| # | Step                                          |
|---|-----------------------------------------------|
| 1 | Generate cluster secrets bundle               |
| 2 | Generate cluster configs for 'homelab'        |
| 3 | Patch controlplane config with VIP            |
| 4 | Validate controlplane configuration           |
| 5 | Validate worker configuration                 |

### Recovery Guidance
Config apply failed for node 10.10.10.11. Verify the node is booted
into Talos maintenance mode and is reachable at that IP address.
Previously configured nodes do not need to be re-applied.
```

## What to Look For

**Plan presentation:**
- **Node count** -- confirm 3 control plane + 1 worker matches your hardware. Fewer than 3 control plane nodes means no HA (etcd requires a quorum of 3).
- **VIP** -- confirm the VIP does not collide with any node IP. The plugin validates this, but double-check the subnet.
- **Install disk** -- confirm `/dev/sda` (or your specified disk) is the correct target on all nodes. A wrong disk path will cause apply-config to fail.

**During execution:**
- **Apply-config steps** -- each node should complete within 30-60 seconds. If a node times out, it may not be in maintenance mode or may be unreachable.
- **Bootstrap step** -- this is the most critical step. It should complete within 30 seconds. After bootstrap, EmberAI polls for etcd member convergence (all 3 CP nodes should join within 3 minutes).
- **Health check** -- the cluster should become healthy within 5 minutes of bootstrap. Kubernetes components (apiserver, controller-manager, scheduler) start after etcd is ready.

**Cluster summary:**
- **Kubeconfig retrieved** -- confirms the cluster is fully operational and you can connect with `kubectl`.
- **All 14 steps passed** -- any step count mismatch indicates a problem.

## Next Steps

- [Check Cluster Health](check-cluster-health.md) -- run a health check to verify the cluster is stable after setup
- [Config Patches](config-patches.md) -- apply configuration patches (e.g., adding a second network interface, enabling KubeSpan)

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "TALOS_WRITE_ENABLED is not set" | Write gate not enabled | Set `TALOS_WRITE_ENABLED=true` in your environment |
| "At least 3 control plane IPs required" | Fewer than 3 CP nodes specified | Add more control plane IPs; HA requires a minimum of 3 |
| "VIP collides with node IP" | VIP is the same as a node's IP | Choose a VIP that is not assigned to any node -- it must be a free IP in the same subnet |
| Connection timeout on apply-config | Node not in maintenance mode or unreachable | Verify the node is PXE/ISO booted into Talos, check that port 50000 is open, and confirm the IP is correct |
| Bootstrap fails with "etcd already initialized" | Bootstrap was already run on this cluster | Bootstrap is ONE-TIME. If etcd exists, the cluster is already bootstrapped. Do NOT run bootstrap again -- use health check instead |
| Health check times out | Kubernetes components still starting | Wait 2-3 additional minutes and run `talos__cluster__health` manually with `wait_timeout="10m"`. Kubernetes components can take time to pull images on first boot |
| "talosctl not found" | `talosctl` binary not installed | Install talosctl: `curl -sL https://talos.dev/install | sh` and ensure it is on your PATH |
| Kubeconfig retrieval fails | Cluster not yet fully initialized | Wait for the health check to pass first, then retry `talos__cluster__kubeconfig` manually |
