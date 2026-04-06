# talos -- Talos Linux Kubernetes Cluster Intelligence Plugin

Talos Linux Kubernetes cluster intelligence plugin for [EmberAI](https://github.com/bluminal/emberai). Manage cluster lifecycle, node operations, etcd health, diagnostics, configuration, and security via the `talosctl` CLI -- all through natural language.

Talos Linux is an immutable, API-driven operating system purpose-built for Kubernetes. There is no SSH, no shell, and no package manager. All management flows through the Talos API (gRPC + mTLS) via `talosctl`, and this plugin wraps that interface for seamless MCP integration.

Part of the [Netex](https://github.com/bluminal/emberai) plugin suite. Works standalone or alongside the unifi, opnsense, and cisco plugins for full-stack infrastructure intelligence -- from network switches and firewalls to Kubernetes clusters.

## Features

- **Guided cluster setup** -- Interactive HA cluster bootstrap with VIP support (3 control plane + N workers)
- **Node lifecycle** -- Reboot, shutdown, reset, and rolling OS upgrades across the cluster
- **etcd management** -- Member listing, status checks, snapshots, and defragmentation
- **Configuration management** -- Generate, validate, and apply machine configs with secret redaction
- **Cluster health monitoring** -- Composite health reports spanning nodes, etcd, and Kubernetes components
- **Diagnostics** -- Node logs, kernel messages, process lists, mounts, and network interfaces
- **Security auditing** -- Certificate expiry checks, API access verification, CA rotation readiness
- **Image management** -- List cached container images on any node

## Architecture

```
             MCP Server (FastMCP)
                    |
            TalosCtlClient
          (asyncio subprocess)
                    |
             talosctl CLI
           (gRPC + mTLS)
                    |
          Talos Linux Nodes
    (controlplane + worker roles)
```

- **CLI wrapper via subprocess** -- All communication goes through `talosctl` invoked via `asyncio.create_subprocess_exec`. No REST API, no direct gRPC -- `talosctl` handles mTLS negotiation, context management, and output formatting natively.
- **JSON output preferred** -- Most commands use `-o json` for structured parsing. Text fallback with regex parsers where JSON is unavailable.

## Quick Install

### Prerequisites

- Python 3.12 or later
- `talosctl` binary installed and on PATH (`brew install siderolabs/tap/talosctl`)
- A talosconfig file with mTLS credentials for your cluster

### Install

```bash
pip install -e ./talos
```

### Configure

Set the required environment variables:

```bash
export TALOS_CONFIG="/path/to/talosconfig"   # mTLS credentials and endpoints
```

Or create a `.env` file in the project root:

```env
TALOS_CONFIG=/path/to/talosconfig
```

Optional configuration:

```bash
export TALOS_CONTEXT=""                       # Named context within talosconfig
export TALOS_WRITE_ENABLED="false"            # Set to "true" to enable write operations
export TALOS_NODES=""                         # Default node IPs (comma-separated)
export NETEX_CACHE_TTL="300"                  # Cache TTL in seconds
```

### Run

```bash
# Start the MCP server (stdio transport)
talos-server

# Test connectivity and configuration
talos-server --check

# Or run directly
python -m talos
```

### Verify

After configuring, test connectivity:

```bash
talos-server --check
```

Expected output on success:

```
talos: running startup health check ...

  [PASS] TALOS_CONFIG = /path/to/talosconfig
  [INFO] TALOS_CONTEXT = (default: )
  [INFO] TALOS_WRITE_ENABLED = false
  [INFO] TALOS_NODES = (default: )
  [INFO] NETEX_CACHE_TTL = (default: 300)

  [PASS] talosctl found at /opt/homebrew/bin/talosctl (version: v1.12.0)
  [PASS] talosconfig found at /path/to/talosconfig (1234 bytes)

talos: health check PASSED
```

## Skill Groups

| Skill | Tools | Description |
|-------|-------|-------------|
| cluster | 4 | Cluster health, member listing, bootstrap, kubeconfig retrieval |
| nodes | 5 | Node info, services, reboot, shutdown, reset |
| etcd | 4 | Member listing, status, snapshots, defragmentation |
| config | 4 | Machine config retrieval, apply patches, generate configs, secrets bundle info |
| diagnostics | 5 | Logs, dmesg, processes, mounts, network interfaces |
| kubernetes | 2 | Component status, Kubernetes version upgrades |
| security | 2 | Certificate inspection, API access checks |
| images | 1 | List cached container images on nodes |

## Commands

| Command | Description |
|---------|-------------|
| `talos scan` | Discover cluster members with roles, versions, and ready state |
| `talos health` | Composite cluster health: nodes, etcd, Kubernetes components |
| `talos diagnose [node]` | Deep diagnostics for a specific node |
| `talos upgrade [--apply]` | Rolling Talos OS upgrade across all nodes |
| `talos config [node]` | Review machine configuration (secrets redacted) |

## Read-Only by Default

The talos plugin operates in **read-only mode** by default. All health, diagnostic, and inspection commands work without any write flags.

Write operations (bootstrap, reboot, shutdown, reset, upgrade, config apply) require the standard three-gate safety pattern:

1. `TALOS_WRITE_ENABLED` set to `"true"`
2. The `--apply` flag on the command
3. Explicit operator confirmation of the change plan

### Additional Safety Gates

Some operations carry extra safeguards beyond the standard write gate:

- **Bootstrap** (`talosctl bootstrap`) -- One-shot operation that initializes etcd. Running it twice corrupts the cluster. Pre-flight check verifies zero existing etcd members. Extra confirmation with irreversibility warning.
- **Reset** (`talosctl reset`) -- Wipes a node completely and removes it from the cluster. Requires additional `--reset-node` flag. Pre-flight check verifies the node is not the last control plane (which would destroy etcd quorum).
- **Upgrade** (`talosctl upgrade`) -- Replaces the OS on a node. Pre-flight checks verify cluster health and no concurrent upgrades. Control plane nodes are upgraded before workers, one at a time, with health verification between each.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TALOS_CONFIG` | Yes | -- | Path to the talosconfig file (mTLS credentials + endpoints) |
| `TALOS_CONTEXT` | No | (default context) | Named context within the talosconfig file |
| `TALOS_WRITE_ENABLED` | No | `false` | Set to `"true"` to enable write operations |
| `TALOS_NODES` | No | (from talosconfig) | Comma-separated default node IP addresses |
| `NETEX_CACHE_TTL` | No | `300` | Override cache TTL in seconds |

## Development

```bash
# Install with dev dependencies
pip install -e "./talos[dev]"

# Run tests
pytest

# Run tests with coverage
coverage run -m pytest && coverage report

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

### Project Structure

```
talos/
  src/talos/
    api/              # TalosCtlClient (asyncio subprocess wrapper)
    agents/           # Orchestrated workflows (cluster setup)
    models/           # Pydantic data models (strict mode)
    parsers/          # talosctl output parsers (JSON + text)
    tools/            # MCP tool implementations
    server.py         # MCP server setup and entry point
    safety.py         # Write safety gate + bootstrap/reset guards
    cache.py          # TTL cache with stampede protection
    errors.py         # Structured error hierarchy
  tests/
    fixtures/         # Mock talosctl output (JSON + text)
    ...
  knowledge/          # Operational lessons learned
  run.sh              # Plugin launcher script
  settings.json       # Env var declarations for EmberAI
  SKILL.md            # Plugin manifest (netex vendor contract)
  pyproject.toml
  README.md
```

### Testing

All tests use mock-based testing against recorded `talosctl` output. No real Talos cluster is needed or contacted during testing:

- Mock `asyncio.create_subprocess_exec` with pre-recorded stdout/stderr
- Test fixtures in `tests/fixtures/` contain sample `talosctl` JSON and text output
- Write gate enforcement tested with env var and flag combinations

## Documentation

- [Implementation Plan](../docs/plans/talos.md) -- architecture decisions, phased milestones
- [SKILL.md](SKILL.md) -- full plugin manifest with tool signatures and interaction model

## License

MIT -- see [LICENSE](../LICENSE) for details.

## Author

[Bluminal Labs](https://bluminal.com)
