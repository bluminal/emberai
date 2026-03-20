# Tool Naming Convention

All MCP tools registered by netex-conforming plugins must follow the
standard naming convention:

```
{plugin}__{skill}__{operation}
```

## Format

- **plugin**: The plugin name (lowercase, alphanumeric). Must match the
  `name` field in `plugin_info()`.
- **skill**: The skill group this tool belongs to. Must be one of the
  recognized skill groups (see `skill_groups.md`).
- **operation**: The specific operation (lowercase, underscores allowed).

Separators are double underscores (`__`).

## Examples

```
unifi__topology__list_devices
unifi__topology__get_device
unifi__health__get_health
opnsense__firewall__list_rules
opnsense__interfaces__list_vlan_interfaces
opnsense__diagnostics__run_traceroute
```

## Validation

The Contract Validator checks tool names against this pattern. Tools
that do not conform will trigger a validation error:

```python
import re
TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*__[a-z][a-z0-9_]*__[a-z][a-z0-9_]*$")
```

## Rationale

The naming convention enables:

1. **Plugin attribution**: The registry can determine which plugin owns
   a tool by parsing the prefix.
2. **Skill indexing**: Tools can be grouped by skill for cross-vendor
   queries like `registry.tools_for_skill("firewall")`.
3. **Collision avoidance**: The plugin prefix prevents name collisions
   when multiple plugins are installed.
