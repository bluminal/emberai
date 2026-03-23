"""Plugin Registry -- discovers and indexes installed vendor plugins.

Discovers vendor plugins at runtime via Python entry points (group
``netex.plugins``, per Decision D12).  Each conforming plugin exports a
``plugin_info()`` callable that returns a metadata dict.

The registry indexes plugins by name, role, and skill, enabling queries
like:

    registry.list_plugins()
    registry.plugins_with_role("gateway")
    registry.plugins_with_skill("firewall")
    registry.tools_for_skill("topology")

SKILL.md Frontmatter
--------------------
If a plugin ships a ``SKILL.md`` file alongside its package, the registry
parses its YAML frontmatter for additional metadata (netex_vendor,
netex_role, netex_skills).  This supplements (but does not replace) the
``plugin_info()`` return values.
"""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("netex.registry")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PluginMetadata:
    """Parsed and validated metadata for a single vendor plugin.

    Fields are populated from the plugin's ``plugin_info()`` return value,
    optionally enriched by SKILL.md frontmatter.
    """

    name: str
    version: str = ""
    vendor: str = ""
    description: str = ""
    roles: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    write_flag: str = ""
    contract_version: str = ""
    is_orchestrator: bool = False
    tools: dict[str, list[str]] = field(default_factory=dict)
    """Maps skill group name to list of tool names within that group."""
    server_factory: Any = None
    """Callable that returns the plugin's FastMCP server instance."""
    raw_info: dict[str, Any] = field(default_factory=dict)
    """Raw plugin_info() return value for debugging."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for API responses."""
        return {
            "name": self.name,
            "version": self.version,
            "vendor": self.vendor,
            "description": self.description,
            "roles": self.roles,
            "skills": self.skills,
            "write_flag": self.write_flag,
            "contract_version": self.contract_version,
            "is_orchestrator": self.is_orchestrator,
        }


# ---------------------------------------------------------------------------
# Plugin Registry
# ---------------------------------------------------------------------------


class PluginRegistry:
    """Discovers and indexes installed vendor plugins via entry points.

    On instantiation, scans the ``netex.plugins`` entry-point group for
    installed packages that export a ``plugin_info()`` callable.

    Parameters
    ----------
    auto_discover:
        If ``True`` (default), run discovery immediately on construction.
        Set to ``False`` for testing with manual registration.
    """

    ENTRY_POINT_GROUP = "netex.plugins"

    def __init__(self, auto_discover: bool = True) -> None:
        self._plugins: dict[str, PluginMetadata] = {}
        self._role_index: dict[str, list[str]] = {}
        self._skill_index: dict[str, list[str]] = {}

        if auto_discover:
            self.discover()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> int:
        """Scan entry points and register all discovered plugins.

        Returns the number of plugins discovered.  Plugins that fail to
        load or return invalid metadata are logged and skipped.
        """
        count = 0

        try:
            entry_points = importlib.metadata.entry_points(group=self.ENTRY_POINT_GROUP)
        except Exception:
            logger.warning("Failed to query entry points for group %s", self.ENTRY_POINT_GROUP)
            return 0

        for ep in entry_points:
            try:
                plugin_info_fn = ep.load()
                info = plugin_info_fn()
                if not isinstance(info, dict):
                    logger.warning(
                        "Plugin %s: plugin_info() returned %s, expected dict",
                        ep.name,
                        type(info).__name__,
                    )
                    continue

                self.register(info)
                count += 1
                logger.info("Discovered plugin: %s", info.get("name", ep.name))

            except Exception as exc:
                logger.warning("Failed to load plugin %s: %s", ep.name, exc)

        return count

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, info: dict[str, Any]) -> PluginMetadata:
        """Register a plugin from its ``plugin_info()`` dict.

        Parameters
        ----------
        info:
            Plugin metadata dict as returned by ``plugin_info()``.

        Returns
        -------
        PluginMetadata
            The registered plugin metadata.

        Raises
        ------
        ValueError
            If ``name`` is missing from the info dict.
        """
        name = info.get("name")
        if not name:
            raise ValueError("Plugin info must include a 'name' field")

        metadata = PluginMetadata(
            name=name,
            version=info.get("version", ""),
            vendor=info.get("vendor", ""),
            description=info.get("description", ""),
            roles=list(info.get("roles", [])),
            skills=list(info.get("skills", [])),
            write_flag=info.get("write_flag", ""),
            contract_version=info.get("contract_version", ""),
            is_orchestrator=info.get("is_orchestrator", False),
            tools=dict(info.get("tools", {})),
            server_factory=info.get("server_factory"),
            raw_info=info,
        )

        self._plugins[name] = metadata
        self._rebuild_indexes()
        return metadata

    def unregister(self, name: str) -> bool:
        """Remove a plugin from the registry.

        Returns ``True`` if the plugin was found and removed, ``False``
        if it was not registered.
        """
        if name in self._plugins:
            del self._plugins[name]
            self._rebuild_indexes()
            return True
        return False

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def list_plugins(self) -> list[dict[str, Any]]:
        """Return metadata for all registered plugins.

        Returns
        -------
        list[dict]
            List of plugin metadata dicts, one per registered plugin.
            Excludes the orchestrator (netex itself) from the list.
        """
        return [p.to_dict() for p in self._plugins.values() if not p.is_orchestrator]

    def get_plugin(self, name: str) -> PluginMetadata | None:
        """Return metadata for a specific plugin by name."""
        return self._plugins.get(name)

    def plugins_with_role(self, role: str) -> list[dict[str, Any]]:
        """Return all plugins that declare the given role.

        Parameters
        ----------
        role:
            Role to filter by (e.g. ``"gateway"``, ``"edge"``).

        Returns
        -------
        list[dict]
            Metadata dicts for matching plugins.
        """
        names = self._role_index.get(role, [])
        return [
            self._plugins[n].to_dict()
            for n in names
            if n in self._plugins and not self._plugins[n].is_orchestrator
        ]

    def plugins_with_skill(self, skill: str) -> list[dict[str, Any]]:
        """Return all plugins that declare the given skill.

        Parameters
        ----------
        skill:
            Skill to filter by (e.g. ``"firewall"``, ``"topology"``).

        Returns
        -------
        list[dict]
            Metadata dicts for matching plugins.
        """
        names = self._skill_index.get(skill, [])
        return [
            self._plugins[n].to_dict()
            for n in names
            if n in self._plugins and not self._plugins[n].is_orchestrator
        ]

    def tools_for_skill(self, skill: str) -> list[dict[str, str]]:
        """Return all tools across all plugins for the given skill.

        Parameters
        ----------
        skill:
            Skill group to query (e.g. ``"topology"``, ``"firewall"``).

        Returns
        -------
        list[dict]
            List of dicts with ``plugin``, ``skill``, and ``tool`` keys.
        """
        results: list[dict[str, str]] = []

        names = self._skill_index.get(skill, [])
        for name in names:
            plugin = self._plugins.get(name)
            if plugin is None or plugin.is_orchestrator:
                continue

            # Check if the plugin has registered specific tools for this skill
            tool_names = plugin.tools.get(skill, [])
            for tool_name in tool_names:
                results.append(
                    {
                        "plugin": name,
                        "skill": skill,
                        "tool": tool_name,
                    }
                )

            # If no specific tools are registered but the plugin has the skill,
            # generate the conventional tool name pattern
            if not tool_names:
                results.append(
                    {
                        "plugin": name,
                        "skill": skill,
                        "tool": f"{name}__{skill}",
                    }
                )

        return results

    @property
    def plugin_count(self) -> int:
        """Return the number of registered plugins (excluding orchestrator)."""
        return sum(1 for p in self._plugins.values() if not p.is_orchestrator)

    @property
    def all_roles(self) -> list[str]:
        """Return all roles declared across all registered plugins."""
        return sorted(self._role_index.keys())

    @property
    def all_skills(self) -> list[str]:
        """Return all skills declared across all registered plugins."""
        return sorted(self._skill_index.keys())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rebuild_indexes(self) -> None:
        """Rebuild the role and skill indexes from current plugin state."""
        self._role_index.clear()
        self._skill_index.clear()

        for name, plugin in self._plugins.items():
            for role in plugin.roles:
                self._role_index.setdefault(role, []).append(name)
            for skill in plugin.skills:
                self._skill_index.setdefault(skill, []).append(name)
