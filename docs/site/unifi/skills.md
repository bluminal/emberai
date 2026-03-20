# UniFi Skills

!!! note "Coming soon"
    This page will be populated in Task 43 with detailed reference documentation
    for all Phase 1 skill tools. For a quick introduction, see the
    [Quick Start](../getting-started/quick-start.md) guide.

Skills are the atomic MCP tools that commands orchestrate. Each skill maps to
a specific UniFi API operation.

## Skill Groups

| Group | Tools | Description |
|-------|-------|-------------|
| topology | `unifi__topology__list_devices`, `unifi__topology__get_device` | Device discovery and network map |
| health | `unifi__health__site_health`, `unifi__health__device_health` | Status, uptime, firmware, events |
| clients | `unifi__clients__list_clients`, `unifi__clients__get_client` | Connected client inventory |
