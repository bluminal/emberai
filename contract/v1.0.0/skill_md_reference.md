# SKILL.md Reference

Each vendor plugin should ship a `SKILL.md` file that serves as the
plugin's operational manifest. This file is read by both humans (for
documentation) and the Plugin Registry (for metadata extraction).

## Structure

A SKILL.md file consists of:

1. **YAML frontmatter** (between `---` delimiters) -- machine-readable metadata
2. **Markdown body** -- human-readable operational instructions for Claude

## YAML Frontmatter

### Required Fields

```yaml
---
name: my-plugin
version: 1.0.0
description: >
  Human-readable description of what this plugin does.
---
```

### Vendor Plugin Fields

Vendor plugins (not the orchestrator) should include:

```yaml
---
name: opnsense
version: 0.2.0
description: >
  OPNsense gateway intelligence plugin for EmberAI.
author: Bluminal Labs
license: MIT
repository: https://github.com/bluminal/emberai/tree/main/opnsense

netex_vendor: opnsense
netex_role:
  - gateway
netex_skills:
  - interfaces
  - firewall
  - routing
  - vpn
  - security
  - services
  - diagnostics
  - firmware
netex_contract_version: "1.0.0"
---
```

### Orchestrator Fields

The netex orchestrator does NOT declare `netex_vendor`, `netex_role`, or
`netex_skills`:

```yaml
---
name: netex
version: 0.3.0
description: >
  Cross-vendor network orchestration umbrella for EmberAI.
netex_contract_version: "1.0.0"
---
```

## Field Reference

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Plugin name (must match `plugin_info().name`) |
| `version` | string | Yes | Semantic version |
| `description` | string | Yes | Human-readable description |
| `author` | string | No | Plugin author |
| `license` | string | No | License identifier |
| `repository` | string | No | Source code URL |
| `docs` | string | No | Documentation URL |
| `netex_vendor` | string | No* | Vendor identifier |
| `netex_role` | list | No* | Network roles (see skill_groups.md) |
| `netex_skills` | list | No* | Skill groups (see skill_groups.md) |
| `netex_contract_version` | string | No | Contract version this plugin conforms to |

*Required for vendor plugins, omitted by the orchestrator.

## Validation

The Contract Validator (`contract_validator.py`) validates frontmatter
against this reference. See the validator for programmatic checks.
