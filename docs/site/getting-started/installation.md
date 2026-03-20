# Installation

This guide covers installing Netex suite plugins via the EmberAI marketplace in Claude Code.

## Prerequisites

- **Python 3.12 or later** -- check with `python3 --version`
- **Claude Code** -- Netex plugins run as MCP servers inside Claude's plugin ecosystem

## Add the EmberAI Marketplace

Register the EmberAI marketplace so Claude Code can discover Netex plugins:

```
/plugin marketplace add bluminal/emberai
```

## Install Plugins

Install the plugins you need. Each plugin is independent -- install only what matches your network equipment.

### UniFi Plugin (edge layer)

For UniFi switches, access points, and wireless management:

```
/plugin install unifi@emberai
```

### OPNsense Plugin (gateway layer)

For OPNsense firewall, routing, VPN, DNS, DHCP, and IDS/IPS:

```
/plugin install opnsense@emberai
```

### Netex Umbrella Plugin (cross-vendor orchestration)

For operations that span both UniFi and OPNsense (unified topology, VLAN provisioning, security audits):

```
/plugin install netex@emberai
```

!!! tip "Install order does not matter"
    Each plugin manages its own virtual environment and dependencies. The netex umbrella
    plugin discovers installed vendor plugins automatically at startup via the Plugin Registry.

## What Happens on First Run

When a plugin runs for the first time, it:

1. Creates an isolated Python virtual environment
2. Installs the plugin package and its dependencies
3. Starts the MCP server

Subsequent runs reuse the existing virtual environment and start immediately.

## Verify Installation

After configuring authentication (see next step), verify each installed plugin:

```
unifi-server --check
opnsense-server --check
netex-server --check
```

A successful check prints connection status and exits with code 0.

## Alternative: Install from Source (Development)

For contributors or local development, you can install plugins directly:

```bash
git clone https://github.com/bluminal/emberai.git
cd emberai
pip install -e "./unifi"       # and/or opnsense, netex
```

For development dependencies (testing, linting, type checking):

```bash
pip install -e "./unifi" --group dev
```

## What's Installed

Each plugin provides an MCP server with specialized network intelligence tools:

| Plugin | Scope | Key Capabilities |
|--------|-------|------------------|
| `unifi` | Edge layer | Topology discovery, health monitoring, WiFi analysis, client management, traffic inspection, security audit, multi-site operations |
| `opnsense` | Gateway layer | Interface/VLAN management, firewall rules, routing, VPN tunnels, DNS, DHCP, IDS/IPS, diagnostics |
| `netex` | Cross-vendor | Unified topology, cross-vendor health, VLAN provisioning, security audit, policy sync |

## Next Steps

- [Authentication](authentication.md) -- create API keys and configure environment variables
- [Quick Start](quick-start.md) -- run your first network scan
- [Safety & Human Supervision](safety.md) -- understand the human-in-the-loop model
