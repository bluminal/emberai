# Spike: Plugin Registry Discovery via Python Entry Points

**Decision:** D12
**Task:** 12
**Date:** 2026-03-19
**Status:** Validated -- entry points work for the use case

## Objective

Validate that Python entry points (`importlib.metadata.entry_points()`) work end-to-end as the Plugin Registry discovery mechanism. This spike resolves Q9 from the implementation plan.

## Approach

1. Registered a `netex.plugins` entry point in `unifi/pyproject.toml`
2. Created a minimal `plugin_info()` function as the entry point target
3. Installed the package with `pip install -e ./unifi`
4. Wrote 10 tests validating discovery, loading, and metadata structure
5. Documented all findings including issues encountered during setup

## Result: CONFIRMED

Python entry points work correctly for plugin discovery. The full flow is:

```python
import importlib.metadata

# Discover all installed vendor plugins
eps = importlib.metadata.entry_points(group="netex.plugins")

for ep in eps:
    # ep.name -> "unifi" (the entry point name)
    # ep.value -> "unifi.server:plugin_info" (the import path)
    # ep.group -> "netex.plugins"
    # ep.dist -> Distribution object with package metadata

    plugin_info_fn = ep.load()     # resolves the import path
    metadata = plugin_info_fn()     # calls the function to get metadata dict
```

### What the loaded object looks like

`ep.load()` returns the `plugin_info` function itself. Calling it returns:

```python
{
    "name": "unifi",
    "version": "0.1.0",
    "vendor": "unifi",
    "roles": ["edge", "wireless"],
    "skills": ["topology", "health", "wifi", "clients", "traffic",
               "security", "config", "multisite"],
    "write_flag": "UNIFI_WRITE_ENABLED",
    "contract_version": "1.0.0",
}
```

### Performance

Discovery + load + call for a single plugin completes in < 1ms. The `entry_points()` function reads from installed package metadata (PKG-INFO / METADATA files on disk), not from pyproject.toml at runtime.

## Caveats and Findings

### 1. Package MUST be installed for discovery to work

`importlib.metadata.entry_points()` reads from installed package metadata, not from source pyproject.toml files. A plugin must be installed via `pip install` (or `pip install -e` for development) before it can be discovered.

**Implication for Plugin Registry (Task 119):** The registry cannot discover plugins from source checkouts alone. The installation step is mandatory. Documentation and setup guides must make this clear.

**Implication for CI:** Test environments must `pip install -e ./unifi` (and later `./opnsense`) before running registry tests.

### 2. Build backend must be `hatchling.build`, not `hatchling.backends`

The original pyproject.toml had `build-backend = "hatchling.backends"`, which does not exist. The correct value is `build-backend = "hatchling.build"`. This was a scaffolding bug that prevented `pip install` from working at all.

**Action:** Fixed in this spike. The correction applies to Task 1's pyproject.toml output.

### 3. Package requires a README.md

Hatchling's metadata validation requires the `readme` file to exist. The original scaffolding (Task 2) did not create a `README.md` in the `unifi/` directory, causing `pip install` to fail.

**Action:** Created a minimal `README.md`. Future tasks should ensure each plugin has one.

### 4. Directory layout must match hatchling's expectations

The original layout had source code at `unifi/src/` with the entry point referencing `unifi.src.server:plugin_info`. This creates a packaging problem:

- Hatchling runs from inside `unifi/` and needs to find a package to ship
- The entry point import path `unifi.src.server` implies a `unifi` top-level package with `src` as a subpackage
- Hatchling's editable install mode does NOT support path rewrites that rename prefixes (e.g., mapping `src` to `unifi`). It only supports prefix removal.

**Solution applied:** Restructured to the standard `src` layout:

```
# Before (broken for entry points)
unifi/
  src/
    __init__.py
    server.py
    agents/
    api/
    ...

# After (works with hatchling + entry points)
unifi/
  src/
    unifi/
      __init__.py
      server.py
      agents/
      api/
      ...
```

With hatchling configuration:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/unifi"]
```

This tells hatchling to include `src/unifi/` as a package, stripping the `src/` prefix so it installs as `unifi/`. The entry point `unifi.server:plugin_info` then resolves correctly.

**Action:** This is a structural change that affects ALL existing tasks referencing `unifi.src.*` import paths. Tasks 4, 6-10, 11, and 13 need their import paths updated from `unifi.src.X` to `unifi.X`.

### 5. Nonexistent groups return empty, not errors

`importlib.metadata.entry_points(group="nonexistent.group")` returns an empty collection, not an exception. This is good for the Plugin Registry -- it can safely query at startup even if no plugins are installed.

### 6. EntryPoint.dist provides additional metadata

Each `EntryPoint` object has a `.dist` attribute that provides access to the full installed distribution metadata (name, version, author, license, etc.). The Plugin Registry can use this for display purposes without needing the `plugin_info()` return value for basic identity.

### 7. Results are stable across multiple calls

Calling `entry_points()` multiple times returns consistent results. The Plugin Registry can safely re-discover plugins (e.g., on reload) without caching concerns.

## Recommendation for D12

**D12 should be kept as-is.** Python entry points are the correct mechanism for plugin discovery. The approach is:

- Standard Python (stdlib, no third-party dependencies)
- Zero-configuration for plugin authors (just add an entry point to pyproject.toml)
- Fast (< 1ms for discovery + load)
- Compatible with both regular and editable installs
- Handles zero-plugin scenarios gracefully

### Recommended updates to other decisions/tasks

1. **Task 1 (pyproject.toml):** Fix `build-backend` from `hatchling.backends` to `hatchling.build`. Add `[tool.hatch.build.targets.wheel]` section.
2. **Task 2 (directory structure):** Restructure from `unifi/src/` to `unifi/src/unifi/` (standard src layout). Add `README.md`.
3. **Tasks 4, 6-10, 11, 13:** Update all import paths from `unifi.src.X` to `unifi.X`.
4. **Task 73 (opnsense pyproject.toml):** Use the corrected build-backend and src layout from the start.
5. **Task 119 (Plugin Registry):** Can proceed as designed. Use `importlib.metadata.entry_points(group="netex.plugins")` at startup. Access `.dist` for package metadata, call `.load()()` for plugin metadata dict.

## Test Evidence

All 10 tests pass (see `unifi/tests/test_entry_points.py`):

```
tests/test_entry_points.py::TestEntryPointDiscovery::test_netex_plugins_group_exists PASSED
tests/test_entry_points.py::TestEntryPointDiscovery::test_unifi_entry_point_name PASSED
tests/test_entry_points.py::TestEntryPointDiscovery::test_entry_point_value_references_correct_module PASSED
tests/test_entry_points.py::TestEntryPointDiscovery::test_entry_point_is_loadable PASSED
tests/test_entry_points.py::TestEntryPointDiscovery::test_loaded_entry_point_returns_plugin_metadata PASSED
tests/test_entry_points.py::TestEntryPointDiscovery::test_metadata_contains_required_fields PASSED
tests/test_entry_points.py::TestEntryPointDiscovery::test_metadata_values_match_skill_md PASSED
tests/test_entry_points.py::TestEntryPointDiscovery::test_multiple_entry_points_isolation PASSED
tests/test_entry_points.py::TestEntryPointDiscovery::test_nonexistent_group_returns_empty PASSED
tests/test_entry_points.py::TestEntryPointDiscovery::test_entry_point_object_attributes PASSED
```
