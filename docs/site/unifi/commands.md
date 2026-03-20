# UniFi Commands

Commands are high-level operational entry points. Each command orchestrates
multiple skill tools to deliver a complete operational picture.

## Available Commands

| Command | Purpose | Status |
|---------|---------|--------|
| `unifi scan` | Full network topology discovery | Available |
| `unifi health` | Severity-ranked health summary | Available |
| `unifi clients` | Client inventory and search | Available |
| `unifi diagnose` | Deep client diagnostics | Available |
| `unifi wifi` | Wireless RF environment analysis | Phase 2 |
| `unifi optimize` | Prioritized WiFi improvement recommendations | Phase 2 |
| `unifi secure` | Security posture audit (firewall, ACLs, port forwarding, IDS) | Phase 2 |
| `unifi config` | Configuration state review and drift detection | Phase 2 |
| `unifi port-profile create` | Create a named switch port profile | Phase 2 |
| `unifi port-profile assign` | Assign a port profile to a switch port | Phase 2 |

For detailed documentation of each command including parameters, examples,
and tools called, see the full [Commands Reference](../../unifi/commands.md).
