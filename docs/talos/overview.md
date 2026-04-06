# Talos Plugin Overview

The **talos** plugin provides Kubernetes cluster intelligence for Talos Linux deployments. It covers the **compute layer** of the infrastructure: cluster lifecycle management, node operations, etcd cluster health, Kubernetes component status, diagnostics, configuration management, security auditing, and container image tracking.

## What is Talos Linux?

Talos Linux is an immutable, minimal operating system purpose-built for running Kubernetes. Unlike traditional Linux distributions:

- **No SSH, no shell, no package manager** -- the OS is entirely API-driven via `talosctl`
- **Immutable root filesystem** -- the OS image cannot be modified at runtime
- **Declarative configuration** -- a single machine config YAML defines the entire system state
- **A/B partition scheme** -- OS upgrades are atomic; the new image is written to the inactive partition and activated on reboot, with automatic rollback on failure
- **Secure by default** -- mutual TLS (mTLS) for all API communication, minimal attack surface, no unnecessary services
- **Runs anywhere** -- bare-metal, VMs, and cloud providers

Talos is designed so that the only way to manage a node is through its gRPC API. There is no way to log in, no way to install packages, and no way to modify the running system outside of the API. This makes it exceptionally secure but requires purpose-built tooling -- which is what this plugin provides.

## What the Plugin Covers

- **Cluster lifecycle** -- generate secrets and machine configs, apply configs to nodes, bootstrap etcd, retrieve kubeconfig, guided cluster setup workflow
- **Cluster health** -- composite health reports covering node readiness, etcd membership, and Kubernetes component status (apiserver, controller-manager, scheduler)
- **Node operations** -- reboot, shutdown, and reset individual nodes with role-aware safety checks (etcd quorum verification for control plane nodes)
- **etcd management** -- member listing, cluster status, snapshots, defragmentation
- **Kubernetes upgrades** -- rolling Kubernetes version upgrades with pre-flight health checks
- **Diagnostics** -- service logs, kernel messages (dmesg), process listing, mount points, network interfaces
- **Configuration** -- generate, validate, and patch machine configs; inspect running node configuration (secrets redacted)
- **Security** -- certificate inventory with expiry tracking, API connectivity and mTLS verification
- **Image management** -- list container images cached on nodes

## What the Plugin Does NOT Cover

The talos plugin is scoped to the Talos OS and cluster infrastructure layer. It does **not** manage:

- **Kubernetes workloads** -- pods, deployments, services, ingress resources (use `kubectl`)
- **CNI configuration** -- Cilium, Flannel, or other CNI plugin setup and tuning
- **Storage provisioning** -- PersistentVolumes, CSI drivers, storage classes
- **Ingress and service mesh** -- ingress controllers, Istio, Linkerd
- **Network infrastructure** -- switches, firewalls, VLANs, DNS

These are Kubernetes-layer or network-layer concerns. Network infrastructure belongs to the **unifi**, **opnsense**, **cisco**, and **nextdns** plugins. When all plugins are installed, the **netex** umbrella orchestrator coordinates cross-vendor workflows -- for example, verifying that switch port VLAN assignments are correct before bootstrapping a Talos cluster.

## Architecture

Unlike other plugins that use `httpx` to call REST APIs, the talos plugin wraps the `talosctl` CLI binary via `asyncio.create_subprocess_exec`. Talos exposes a gRPC API (not REST), and `talosctl` is the canonical, well-tested management interface that handles mTLS negotiation, talosconfig context management, and output formatting natively.

The plugin is structured in three layers:

```
Commands (user-facing)
  talos cluster-setup, talos cluster-status, talos health, talos diagnose
    |
Tools (MCP tools -- talosctl subprocess calls)
  cluster skill, config skill, nodes skill, etcd skill,
  diagnostics skill, kubernetes skill, security skill, images skill
    |
TalosCtl Client (async subprocess wrapper)
  asyncio.create_subprocess_exec -> talosctl binary -> gRPC + mTLS -> Talos nodes
```

**TalosCtl Client** is an async subprocess wrapper that constructs `talosctl` commands, executes them, and parses the output. It prefers JSON output mode (`-o json`) for structured data, with text parsing as a fallback for commands that do not support JSON. Results are cached with per-data-type TTLs (e.g., cluster health 1 min, etcd status 30 sec, node list 5 min).

**Tools** are MCP-registered functions that call the TalosCtl Client and return normalized Pydantic models. Each tool follows the naming convention `talos__{skill}__{operation}`.

**Commands** are user-facing entry points that orchestrate multiple tools to produce complete reports or execute multi-step workflows (e.g., the guided cluster setup).

There is no `httpx` dependency. The only external binary requirement is `talosctl`, which the plugin validates at startup via the `--check` health probe.

## Communication Model

All communication with Talos nodes uses a single tier:

| Tier | Transport | Authentication | Port |
|------|-----------|---------------|------|
| Talos API | gRPC over mTLS (via `talosctl`) | Certificate-based (talosconfig) | 50000/TCP |

Authentication uses a **talosconfig** file containing mTLS client certificates and cluster endpoint information. This file is analogous to a kubeconfig but for the Talos API. It is generated during cluster setup (`talosctl gen config`) and contains contexts for each cluster, similar to kubeconfig contexts.

There is no REST API, no SSH, and no direct shell access. Every operation goes through `talosctl` subcommands executed as subprocesses.

## Required Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 50000 | TCP | Talos API (gRPC + mTLS) -- primary management interface |
| 6443 | TCP | Kubernetes API server |
| 2379-2380 | TCP | etcd client and peer communication |
| 10250 | TCP | kubelet API |
| 51820 | UDP | KubeSpan (WireGuard-based cluster mesh, optional) |

## Authentication

The plugin requires the following environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `TALOS_CONFIG` | Yes | Path to the talosconfig file containing mTLS certificates and endpoint configuration |

Optional variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `TALOS_CONTEXT` | *(current context)* | Named context within the talosconfig file |
| `TALOS_WRITE_ENABLED` | `false` | Set to `"true"` to enable write operations |
| `TALOS_NODES` | *(from talosconfig)* | Comma-separated list of default target node IPs |
| `NETEX_CACHE_TTL` | `300` | Override TTL for cached responses (seconds) |

On startup, the plugin verifies `TALOS_CONFIG` is set and the file exists. If missing, it reports which variable is absent and what it is used for, without attempting any API calls. Run `talos-server --check` to probe Talos API connectivity and validate all environment variables before starting the server.

## Read-Only by Default

The talos plugin operates in **read-only mode** by default. All read operations (health checks, node info, diagnostics, configuration inspection) work without any write gate.

Write operations require the standard three-step safety gate:

1. `TALOS_WRITE_ENABLED` set to `"true"`
2. The `--apply` flag on the command
3. Explicit operator confirmation of the change plan

### Bootstrap Safety

`talosctl bootstrap` initializes etcd on the first control plane node. This is a **one-shot operation** -- running it on a cluster that already has etcd members will corrupt the cluster. The plugin enforces extra safeguards beyond the standard write gate:

- Pre-flight check: queries etcd membership and blocks if etcd already has members
- Pre-flight check: verifies the target node is a control plane node
- Explicit warning: *"Bootstrap initializes etcd on {node}. This is irreversible and must only be run ONCE across the entire cluster."*

### Reset Safety

`talosctl reset` wipes a node's state completely -- OS, data, and cluster membership. The plugin requires an additional `--reset-node` flag beyond the standard write gate:

- Pre-flight check: verifies the target is not the last control plane node (which would destroy the cluster)
- Presents node role, hostname, and cluster membership before confirmation
- Control plane nodes receive an additional warning about etcd quorum impact

## Skill Groups

| Skill | Tools | Description |
|-------|-------|-------------|
| `cluster` | 7 | Cluster lifecycle: health, bootstrap, kubeconfig, apply config, version, endpoints, merge talosconfig |
| `config` | 5 | Configuration management: generate secrets, generate configs, validate, patch, inspect running config |
| `nodes` | 5 | Node operations: list, info, reboot, shutdown, reset |
| `etcd` | 4 | etcd management: member list, status, snapshot, defrag |
| `diagnostics` | 5 | System diagnostics: logs, dmesg, processes, mounts, network interfaces |
| `kubernetes` | 2 | Kubernetes components: status, version upgrade |
| `security` | 2 | Security: certificate inventory, API access check |
| `images` | 1 | Container images: list cached images on a node |

## Plugin Role

The talos plugin introduces **`compute`** as a new role in the Vendor Plugin Contract (v1.0.0). This role represents infrastructure that runs workloads and depends on the network layer.

In cross-vendor workflows orchestrated by the netex umbrella:

- **`compute` executes after `edge`** -- nodes need switch port connectivity and VLAN assignments configured before cluster bootstrap
- Proposed full ordering: `gateway` -> `dns` -> `edge` -> `wireless` -> `compute`

This means that when provisioning a new site end-to-end, network infrastructure (OPNsense gateway, UniFi switches, DNS) is configured first, and the Talos cluster is bootstrapped only after the network layer is verified.

## Related Documentation

- [Commands Reference](commands.md) -- Phase 1 commands with examples
- [Skills Reference](skills.md) -- individual MCP tool documentation
