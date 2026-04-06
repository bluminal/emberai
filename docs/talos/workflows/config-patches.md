# Configuration Patches

## Intent

"I want to generate, patch, and validate Talos machine configurations before applying them to my cluster."

## Prerequisites

- **Plugin:** `talos` v0.1.0 or later
- **Binary:** `talosctl` installed and on `PATH`
- **Environment variables:** `TALOS_CONFIG` (path to talosconfig file). `TALOS_WRITE_ENABLED=true` required for generating configs, patching files, and applying configs to nodes.
- **Network access:** For applying patches to running nodes, the target node must be reachable on port 50000 (Talos gRPC). Config generation and file-based patching are local operations and do not require network access.

## Context

Run this workflow when you need to modify Talos machine configuration -- adding a network interface, changing the install disk, enabling KubeSpan, adjusting kubelet settings, or any other machine config change. Talos uses immutable infrastructure: you cannot SSH into a node and edit files. All configuration changes go through the machine config.

This workflow covers three scenarios: generating a fresh config and patching it before first apply, patching an existing config file offline, and patching a running node's config. All scenarios follow the same principle: generate or retrieve the config, apply patches, validate, then apply.

This workflow does not cover cluster-wide upgrades (Talos or Kubernetes version changes) -- those use the upgrade tools.

> **Working Safely**
>
> - **Always validate patches before applying to running nodes.** Use `dry_run=True` or `talos__config__validate` to catch errors before they reach a live node. A malformed config applied to a control plane node can make the node unreachable.
> - **Use dry-run mode first.** The `talos__cluster__apply_config` tool supports `dry_run=True` which validates the config without applying it. Always dry-run before applying to production nodes.
> - **Understand reboot behavior.** Some config changes require a node reboot (e.g., disk, network interface changes). Talos will reboot the node automatically when the apply mode is `"auto"` or `"reboot"`. Use `"no-reboot"` or `"staged"` if you want to control the reboot timing.
> - **Patch one node at a time in production.** When applying config changes to a running cluster, patch and apply to one node, verify it comes back healthy, then proceed to the next. Never apply untested patches to all nodes simultaneously.

## Commands

### Scenario 1: Generate a config and patch it with a VIP

This is the most common scenario during initial cluster setup -- generate the base configs, then patch them with site-specific settings.

#### Step 1: Generate the base configuration

```
You: Generate Talos configs for a cluster called "homelab" with endpoint
https://10.10.10.10:6443 and install disk /dev/sda
```

```
EmberAI:

Configuration files generated.

| File               | Description                     |
|--------------------|---------------------------------|
| controlplane.yaml  | Control plane machine config    |
| worker.yaml        | Worker machine config           |
| talosconfig        | Client configuration (talosctl) |

Output directory: ./homelab-configs/

SECURITY: The generated configs contain cluster secrets. Store them
securely and never commit them to version control.
```

#### Step 2: Patch the controlplane config with a VIP

```
You: Patch the controlplane config to add VIP 10.10.10.10 on eth0
```

EmberAI calls `talos__config__patch_machineconfig` with an inline JSON patch:

```
EmberAI:

Machine config patched successfully.

Patch applied:
  [{"op": "add",
    "path": "/machine/network/interfaces/-",
    "value": {"interface": "eth0", "vip": {"ip": "10.10.10.10"}}}]

Config file: ./homelab-configs/controlplane.yaml
Output: ./homelab-configs/controlplane.yaml (in-place)
```

#### Step 3: Validate the patched config

```
You: Validate the controlplane config
```

```
EmberAI:

Configuration is valid.

| Field       | Value                              |
|-------------|------------------------------------|
| Config file | ./homelab-configs/controlplane.yaml|
| Mode        | metal                              |
| Status      | pass                               |
```

### Scenario 2: Enable KubeSpan on an existing config file

#### Step 1: Patch with KubeSpan enabled

```
You: Enable KubeSpan on both the controlplane and worker configs
```

EmberAI patches both files:

```
EmberAI:

Machine config patched successfully (controlplane).

Patch applied:
  [{"op": "add",
    "path": "/machine/network/kubespan",
    "value": {"enabled": true}}]

Config file: ./homelab-configs/controlplane.yaml

---

Machine config patched successfully (worker).

Patch applied:
  [{"op": "add",
    "path": "/machine/network/kubespan",
    "value": {"enabled": true}}]

Config file: ./homelab-configs/worker.yaml
```

#### Step 2: Validate both configs

```
You: Validate both configs
```

```
EmberAI:

controlplane.yaml: pass
worker.yaml: pass

Both configurations are valid.
```

### Scenario 3: Patch a running node's configuration

This scenario applies a config change to a node that is already part of a running cluster.

#### Step 1: Retrieve the current config from the node

```
You: Show me the current machine config on cp1 (10.10.10.11)
```

EmberAI calls `talos__config__get_machineconfig`:

```
EmberAI:

Machine config retrieved from 10.10.10.11.

Note: Secrets and keys have been redacted from the output.

Cluster: homelab
Machine type: controlplane
Install disk: /dev/sda
Network interfaces:
  - interface: eth0
    addresses: [10.10.10.11/24]
    vip: 10.10.10.10
Kubernetes version: v1.32.0
```

#### Step 2: Patch the config to add a second network interface

```
You: Add a second network interface eth1 with address 10.20.20.11/24 on
cp1's config. Write the patched config to cp1-patched.yaml.
```

```
EmberAI:

Machine config patched successfully.

Patch applied:
  [{"op": "add",
    "path": "/machine/network/interfaces/-",
    "value": {"interface": "eth1",
              "addresses": ["10.20.20.11/24"]}}]

Config file: controlplane.yaml
Output file: cp1-patched.yaml
```

#### Step 3: Dry-run the config apply

```
You: Dry-run applying cp1-patched.yaml to cp1
```

EmberAI calls `talos__cluster__apply_config` with `dry_run=True`:

```
EmberAI:

Config validation passed. Dry run -- no changes applied.

| Field       | Value            |
|-------------|------------------|
| Node        | 10.10.10.11      |
| Config file | cp1-patched.yaml |
| Status      | ok (dry run)     |

The config is valid and ready to apply. To apply for real, confirm
and I will use apply mode "auto" (Talos will reboot the node if the
change requires it).
```

#### Step 4: Apply the config to the running node

```
You: Apply it for real
```

```
EmberAI:

Configuration applied successfully.

| Field       | Value            |
|-------------|------------------|
| Node        | 10.10.10.11      |
| Config file | cp1-patched.yaml |
| Mode        | auto             |
| Insecure    | No               |

The node may reboot to apply network interface changes. Wait 2-3
minutes, then run a health check to verify the node comes back healthy.
```

#### Step 5: Verify the node is healthy after the change

```
You: Check cluster health
```

```
EmberAI:

## Cluster Status: OK

All 4 nodes healthy. etcd healthy. Kubernetes healthy.

cp1 (10.10.10.11): Ready
```

## What to Look For

**Config generation:**
- **Three files generated** -- `controlplane.yaml`, `worker.yaml`, and `talosconfig` should all be present. A missing file indicates a generation error.
- **Endpoint URL** -- confirm the endpoint in the generated config matches your VIP or first CP node IP with port 6443.

**Patching:**
- **Patch syntax** -- patches use JSON Patch (RFC 6902) format with `op`, `path`, and `value` fields. Common operations are `add`, `replace`, and `remove`.
- **Output file** -- when patching, you can write to a new file (`output_file`) or patch in-place. For running clusters, always write to a new file first so you can dry-run before applying.

**Validation:**
- **"pass" result** -- the config is syntactically valid and structurally correct for the specified mode (metal, cloud, or container).
- **"fail" result** -- review the error output carefully. Common issues: invalid YAML, unknown fields, conflicting settings, or missing required fields after patching.

**Applying to running nodes:**
- **Dry-run first** -- always dry-run before applying to catch validation errors without impacting the node.
- **Reboot behavior** -- network and disk changes typically require a reboot. Use `mode="staged"` to stage the config for next reboot without rebooting immediately.
- **Node health after apply** -- wait 2-3 minutes after applying, then run a health check. The node should return to "Ready" state.

## Next Steps

- [First-Time Cluster Setup](first-time-cluster-setup.md) -- use the generated and patched configs to provision a new cluster
- [Check Cluster Health](check-cluster-health.md) -- verify cluster health after applying config changes to running nodes

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "Config validation failed" after patching | Invalid JSON patch syntax or wrong path | Verify the patch JSON is valid RFC 6902 format; check that the target path exists in the config (use `get_machineconfig` to inspect the current structure) |
| "TALOS_WRITE_ENABLED is not set" | Write gate not enabled | Set `TALOS_WRITE_ENABLED=true` for gen_secrets, gen_config, patch_machineconfig, and apply_config operations |
| Patch applies but validation fails | Patch created an invalid config state | Review the patch output; the patch may have added a field in the wrong location or with an invalid value. Regenerate and re-patch |
| Apply-config times out on a running node | Node unreachable or config causes immediate reboot | If the node rebooted, wait 2-3 minutes and check health. If unreachable, verify network connectivity to the node's IP |
| Node does not come back after apply | Config change broke networking or boot | If the node had a network config error, it may be unreachable at its old IP. Check if it is reachable at a new IP, or connect via console/IPMI to inspect. In the worst case, re-apply the previous working config via maintenance mode (insecure) |
| "Secrets and keys have been redacted" when retrieving config | Normal behavior -- plugin redacts secrets | This is expected. The plugin never exposes secrets in its output. Use the original secrets.yaml file if you need to regenerate configs |
| Patch succeeds but change not visible on node | Config applied with `mode="staged"` or `mode="no-reboot"` | The change is staged for next reboot. Reboot the node to activate, or re-apply with `mode="reboot"` |
