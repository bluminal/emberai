# SPDX-License-Identifier: MIT
"""Tests for the Plugin Registry."""

from __future__ import annotations

import pytest

from netex.registry.plugin_registry import PluginMetadata, PluginRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _unifi_info() -> dict:
    """Mock unifi plugin_info() return value."""
    return {
        "name": "unifi",
        "version": "0.1.0",
        "vendor": "unifi",
        "description": "UniFi network intelligence",
        "roles": ["edge", "wireless"],
        "skills": ["topology", "health", "wifi", "clients", "traffic", "security", "config"],
        "write_flag": "UNIFI_WRITE_ENABLED",
        "contract_version": "1.0.0",
        "tools": {
            "topology": ["unifi__topology__list_devices", "unifi__topology__get_device"],
            "health": ["unifi__health__get_health"],
        },
    }


def _opnsense_info() -> dict:
    """Mock opnsense plugin_info() return value."""
    return {
        "name": "opnsense",
        "version": "0.2.0",
        "vendor": "opnsense",
        "description": "OPNsense gateway intelligence",
        "roles": ["gateway"],
        "skills": [
            "interfaces",
            "firewall",
            "routing",
            "vpn",
            "security",
            "services",
            "diagnostics",
        ],
        "write_flag": "OPNSENSE_WRITE_ENABLED",
        "contract_version": "1.0.0",
        "tools": {
            "firewall": ["opnsense__firewall__list_rules", "opnsense__firewall__add_rule"],
            "diagnostics": ["opnsense__diagnostics__run_traceroute"],
        },
    }


def _netex_info() -> dict:
    """Mock netex orchestrator plugin_info() return value."""
    return {
        "name": "netex",
        "version": "0.3.0",
        "description": "Cross-vendor orchestration umbrella",
        "contract_version": "1.0.0",
        "is_orchestrator": True,
    }


@pytest.fixture
def registry() -> PluginRegistry:
    """Create a registry with auto_discover disabled."""
    return PluginRegistry(auto_discover=False)


@pytest.fixture
def populated_registry(registry: PluginRegistry) -> PluginRegistry:
    """Create a registry with mock plugins registered."""
    registry.register(_unifi_info())
    registry.register(_opnsense_info())
    registry.register(_netex_info())
    return registry


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_plugin(self, registry: PluginRegistry) -> None:
        metadata = registry.register(_unifi_info())
        assert isinstance(metadata, PluginMetadata)
        assert metadata.name == "unifi"
        assert metadata.version == "0.1.0"
        assert metadata.vendor == "unifi"

    def test_register_requires_name(self, registry: PluginRegistry) -> None:
        with pytest.raises(ValueError, match="name"):
            registry.register({"version": "1.0.0", "description": "no name"})

    def test_register_empty_name(self, registry: PluginRegistry) -> None:
        with pytest.raises(ValueError, match="name"):
            registry.register({"name": "", "version": "1.0.0", "description": "empty"})

    def test_register_overwrites(self, registry: PluginRegistry) -> None:
        registry.register(_unifi_info())
        updated = {**_unifi_info(), "version": "0.2.0"}
        metadata = registry.register(updated)
        assert metadata.version == "0.2.0"

    def test_unregister_existing(self, registry: PluginRegistry) -> None:
        registry.register(_unifi_info())
        assert registry.unregister("unifi") is True
        assert registry.get_plugin("unifi") is None

    def test_unregister_nonexistent(self, registry: PluginRegistry) -> None:
        assert registry.unregister("nonexistent") is False


# ---------------------------------------------------------------------------
# list_plugins
# ---------------------------------------------------------------------------


class TestListPlugins:
    def test_list_empty(self, registry: PluginRegistry) -> None:
        assert registry.list_plugins() == []

    def test_list_excludes_orchestrator(self, populated_registry: PluginRegistry) -> None:
        plugins = populated_registry.list_plugins()
        names = [p["name"] for p in plugins]
        assert "unifi" in names
        assert "opnsense" in names
        assert "netex" not in names

    def test_list_returns_dicts(self, populated_registry: PluginRegistry) -> None:
        plugins = populated_registry.list_plugins()
        for p in plugins:
            assert isinstance(p, dict)
            assert "name" in p
            assert "roles" in p
            assert "skills" in p


# ---------------------------------------------------------------------------
# plugins_with_role
# ---------------------------------------------------------------------------


class TestPluginsWithRole:
    def test_gateway_role(self, populated_registry: PluginRegistry) -> None:
        plugins = populated_registry.plugins_with_role("gateway")
        assert len(plugins) == 1
        assert plugins[0]["name"] == "opnsense"

    def test_edge_role(self, populated_registry: PluginRegistry) -> None:
        plugins = populated_registry.plugins_with_role("edge")
        assert len(plugins) == 1
        assert plugins[0]["name"] == "unifi"

    def test_wireless_role(self, populated_registry: PluginRegistry) -> None:
        plugins = populated_registry.plugins_with_role("wireless")
        assert len(plugins) == 1
        assert plugins[0]["name"] == "unifi"

    def test_unknown_role(self, populated_registry: PluginRegistry) -> None:
        plugins = populated_registry.plugins_with_role("nonexistent")
        assert plugins == []


# ---------------------------------------------------------------------------
# plugins_with_skill
# ---------------------------------------------------------------------------


class TestPluginsWithSkill:
    def test_security_skill_multiple(self, populated_registry: PluginRegistry) -> None:
        plugins = populated_registry.plugins_with_skill("security")
        names = [p["name"] for p in plugins]
        assert "unifi" in names
        assert "opnsense" in names

    def test_firewall_skill(self, populated_registry: PluginRegistry) -> None:
        plugins = populated_registry.plugins_with_skill("firewall")
        assert len(plugins) == 1
        assert plugins[0]["name"] == "opnsense"

    def test_topology_skill(self, populated_registry: PluginRegistry) -> None:
        plugins = populated_registry.plugins_with_skill("topology")
        assert len(plugins) == 1
        assert plugins[0]["name"] == "unifi"

    def test_unknown_skill(self, populated_registry: PluginRegistry) -> None:
        plugins = populated_registry.plugins_with_skill("nonexistent")
        assert plugins == []


# ---------------------------------------------------------------------------
# tools_for_skill
# ---------------------------------------------------------------------------


class TestToolsForSkill:
    def test_firewall_tools(self, populated_registry: PluginRegistry) -> None:
        tools = populated_registry.tools_for_skill("firewall")
        assert len(tools) == 2
        tool_names = [t["tool"] for t in tools]
        assert "opnsense__firewall__list_rules" in tool_names
        assert "opnsense__firewall__add_rule" in tool_names

    def test_topology_tools(self, populated_registry: PluginRegistry) -> None:
        tools = populated_registry.tools_for_skill("topology")
        assert len(tools) == 2
        assert all(t["plugin"] == "unifi" for t in tools)

    def test_skill_without_explicit_tools(self, populated_registry: PluginRegistry) -> None:
        """Skills without explicit tool lists fall back to convention."""
        tools = populated_registry.tools_for_skill("wifi")
        assert len(tools) == 1
        assert tools[0]["tool"] == "unifi__wifi"

    def test_unknown_skill(self, populated_registry: PluginRegistry) -> None:
        tools = populated_registry.tools_for_skill("nonexistent")
        assert tools == []


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    def test_plugin_count(self, populated_registry: PluginRegistry) -> None:
        assert populated_registry.plugin_count == 2  # excludes orchestrator

    def test_all_roles(self, populated_registry: PluginRegistry) -> None:
        roles = populated_registry.all_roles
        assert "gateway" in roles
        assert "edge" in roles
        assert "wireless" in roles

    def test_all_skills(self, populated_registry: PluginRegistry) -> None:
        skills = populated_registry.all_skills
        assert "topology" in skills
        assert "firewall" in skills
        assert "security" in skills


# ---------------------------------------------------------------------------
# get_plugin
# ---------------------------------------------------------------------------


class TestGetPlugin:
    def test_existing(self, populated_registry: PluginRegistry) -> None:
        p = populated_registry.get_plugin("unifi")
        assert p is not None
        assert p.name == "unifi"

    def test_nonexistent(self, populated_registry: PluginRegistry) -> None:
        assert populated_registry.get_plugin("nonexistent") is None


# ---------------------------------------------------------------------------
# PluginMetadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    def test_to_dict(self) -> None:
        m = PluginMetadata(
            name="test",
            version="1.0.0",
            vendor="test",
            roles=["edge"],
            skills=["topology"],
        )
        d = m.to_dict()
        assert d["name"] == "test"
        assert d["roles"] == ["edge"]
        # Should not include internal fields
        assert "server_factory" not in d
        assert "raw_info" not in d
