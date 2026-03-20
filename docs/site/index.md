# Netex Suite Documentation

!!! warning "Netex is an assistant, not an autonomous agent"
    Netex is an assistant, not an autonomous agent. It will always ask before
    changing anything on your network. Every write operation requires explicit
    operator confirmation. See [Safety & Human Supervision](getting-started/safety.md)
    for the full interaction model.

## What is Netex?

Netex is a suite of three complementary plugins for [EmberAI](https://github.com/bluminal/emberai) that provide intelligent network operations through Claude. The suite spans the full network stack of a typical self-hosted or SMB environment.

### The Three Plugins

| Plugin | Layer | What it covers |
|--------|-------|----------------|
| **unifi** | Edge | Device topology, wireless health, client management, traffic analysis, security posture, and multi-site operations across UniFi networks. |
| **opnsense** | Gateway | Interface and VLAN management, firewall rules, routing, VPN tunnels, DNS, IDS/IPS, and system diagnostics for OPNsense firewalls. |
| **netex** | Umbrella | Cross-vendor orchestration — VLAN provisioning, policy auditing, end-to-end topology mapping, and configuration drift detection across both systems. |

Each plugin can be used independently. The **unifi** plugin is fully functional without OPNsense, and vice versa. When both are installed, the **netex** umbrella orchestrates cross-vendor operations automatically.

### The Guiding Principle

**Keep the light on.** Netex gives operators intelligence and actionable insight, not raw API responses. It understands your network as a system, not a collection of endpoints.

---

## Quick Links

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Getting Started**

    ---

    Install the unifi plugin, set up API keys, and run your first network scan.

    [:octicons-arrow-right-24: Installation](getting-started/installation.md)

-   :material-router-network:{ .lg .middle } **UniFi Plugin**

    ---

    Commands, skills, and workflow examples for UniFi network management.

    [:octicons-arrow-right-24: UniFi Overview](unifi/overview.md)

-   :material-shield-check:{ .lg .middle } **Safety & Human Supervision**

    ---

    How Netex keeps the operator in control of every network change.

    [:octicons-arrow-right-24: Safety](getting-started/safety.md)

-   :material-book-open-variant:{ .lg .middle } **Reference**

    ---

    Environment variables, write safety gates, and configuration details.

    [:octicons-arrow-right-24: Environment Variables](reference/environment-variables.md)

</div>
