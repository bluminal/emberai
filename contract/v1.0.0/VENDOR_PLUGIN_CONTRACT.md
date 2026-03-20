# Vendor Plugin Contract v1.0.0

This document defines the contract that vendor plugins must conform to in
order to be discovered and orchestrated by the netex umbrella plugin.

## Overview

The netex umbrella plugin discovers vendor plugins dynamically at runtime
via Python entry points (group: `netex.plugins`). Each conforming plugin
exports a `plugin_info()` callable that returns metadata describing the
plugin's capabilities.

Netex never hardcodes vendor names. Any plugin that conforms to this
contract can be orchestrated by netex.

## Entry Point Registration

Plugins register with the `netex.plugins` entry-point group in their
`pyproject.toml`:

```toml
[project.entry-points."netex.plugins"]
my_vendor = "my_vendor.server:plugin_info"
```

The entry point must resolve to a callable that takes no arguments and
returns a `dict[str, Any]` with the metadata fields described below.

## Required Metadata Fields

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Unique plugin name (lowercase, alphanumeric, hyphens/underscores) |
| `version` | `str` | Semantic version string (e.g., `"1.0.0"`) |
| `description` | `str` | Human-readable description of the plugin's capabilities |

## Recommended Metadata Fields

| Field | Type | Description |
|---|---|---|
| `vendor` | `str` | Vendor identifier (e.g., `"unifi"`, `"opnsense"`) |
| `roles` | `list[str]` | Network roles this plugin fulfills (see `skill_groups.md`) |
| `skills` | `list[str]` | Skill groups this plugin provides (see `skill_groups.md`) |
| `write_flag` | `str` | Env var name for write gate (e.g., `"UNIFI_WRITE_ENABLED"`) |
| `contract_version` | `str` | Version of this contract the plugin conforms to |
| `server_factory` | `Callable` | Returns the plugin's `FastMCP` server instance |

## Optional Metadata Fields

| Field | Type | Description |
|---|---|---|
| `tools` | `dict[str, list[str]]` | Maps skill groups to MCP tool names |
| `is_orchestrator` | `bool` | `True` if this is an orchestrator, not a vendor plugin |

## Write Safety Gate

All vendor plugins must implement the three-step write safety gate:

1. **Env var gate**: The environment variable named in `write_flag` must
   be set to `"true"` (case-insensitive).
2. **Apply flag gate**: The command must include `apply=True`.
3. **Operator confirmation**: The operator must confirm the change plan.

Plugins that do not support write operations may omit `write_flag`.

## SKILL.md

Each plugin should ship a `SKILL.md` file with YAML frontmatter that
provides supplementary metadata. See `skill_md_reference.md` for the
complete reference.

## Versioning

This contract follows semantic versioning. Breaking changes increment the
major version. netex validates `contract_version` at discovery time and
logs warnings for version mismatches.
