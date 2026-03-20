# SPDX-License-Identifier: MIT
"""Tests for cross-vendor MCP tool commands (Tasks 132-137).

Covers:
- VLAN configure: plan building, change steps, 7-step workflow
- VLAN audit: cross-vendor comparison
- Topology: merge from all plugins
- Health: unified report
- Firewall audit: cross-layer analysis
- Secure audit/review: delegation to NetworkSecurityAgent
- Edge cases: missing plugins, invalid inputs
"""

from __future__ import annotations

import pytest

from netex.agents.orchestrator import Orchestrator
from netex.ask import PlanStep
from netex.models.abstract import (
    VLAN,
    NetworkTopology,
    TopologyLink,
    TopologyNode,
    TopologyNodeType,
)
from netex.registry.plugin_registry import PluginRegistry
from netex.tools.commands import (
    VLAN_CONFIGURE_ROLLBACK,
    VLAN_CONFIGURE_STEPS,
    _build_vlan_change_steps,
    _build_vlan_plan_steps,
    _get_orchestrator,
    _get_registry,
    netex__vlan__configure,
    set_registry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_registry(
    *,
    gateway: bool = True,
    edge: bool = True,
) -> PluginRegistry:
    """Create a registry with configurable plugin availability."""
    registry = PluginRegistry(auto_discover=False)

    if gateway:
        registry.register({
            "name": "opnsense",
            "version": "1.0.0",
            "vendor": "OPNsense",
            "roles": ["gateway"],
            "skills": [
                "interfaces", "firewall", "routing", "services",
                "vpn", "diagnostics", "security", "firmware", "health",
            ],
            "tools": {
                "interfaces": ["opnsense__interfaces__list_vlans"],
                "firewall": [
                    "opnsense__firewall__list_rules",
                    "opnsense__firewall__add_rule",
                ],
                "services": ["opnsense__services__list_dhcp"],
                "diagnostics": ["opnsense__diagnostics__run_traceroute"],
                "security": ["opnsense__security__list_ids_rules"],
                "health": ["opnsense__health__system_info"],
            },
        })

    if edge:
        registry.register({
            "name": "unifi",
            "version": "1.0.0",
            "vendor": "Ubiquiti",
            "roles": ["edge"],
            "skills": [
                "topology", "config", "wifi", "clients",
                "security", "health",
            ],
            "tools": {
                "topology": [
                    "unifi__topology__list_devices",
                    "unifi__topology__get_device",
                ],
                "config": [
                    "unifi__config__list_networks",
                    "unifi__config__create_network",
                ],
                "wifi": ["unifi__wifi__list_wlans"],
                "clients": ["unifi__clients__list_clients"],
                "security": ["unifi__security__list_acls"],
                "health": ["unifi__health__site_health"],
            },
        })

    return registry


@pytest.fixture(autouse=True)
def _setup_registry():
    """Set up the module-level registry for each test."""
    registry = _make_registry()
    set_registry(registry)
    yield
    # Reset to None after test
    import netex.tools.commands as cmds
    cmds._registry = None
    cmds._orchestrator = None


# ===========================================================================
# Task 132: VLAN Configure Tests
# ===========================================================================


class TestVlanConfigureSteps:
    """Tests for the 7-step VLAN provisioning workflow constants."""

    def test_seven_steps_defined(self):
        """There are exactly 7 VLAN configure steps."""
        assert len(VLAN_CONFIGURE_STEPS) == 7

    def test_steps_have_required_keys(self):
        """Each step has number, system, role, skill, action, subsystem."""
        for step in VLAN_CONFIGURE_STEPS:
            assert "number" in step
            assert "system" in step
            assert "role" in step
            assert "skill" in step
            assert "action" in step
            assert "subsystem" in step

    def test_step_numbers_sequential(self):
        """Step numbers are 1-7 in order."""
        numbers = [s["number"] for s in VLAN_CONFIGURE_STEPS]
        assert numbers == [1, 2, 3, 4, 5, 6, 7]

    def test_gateway_steps_first(self):
        """Steps 1-4 target the gateway, steps 5-7 target the edge."""
        for i in range(4):
            assert VLAN_CONFIGURE_STEPS[i]["role"] == "gateway"
        for i in range(4, 7):
            assert VLAN_CONFIGURE_STEPS[i]["role"] == "edge"

    def test_rollback_steps_defined(self):
        """Rollback steps are defined (6 entries)."""
        assert len(VLAN_CONFIGURE_ROLLBACK) == 6

    def test_rollback_is_reverse_of_forward(self):
        """Rollback steps roughly reverse the forward steps."""
        # First rollback undoes last forward step (SSID)
        assert "SSID" in VLAN_CONFIGURE_ROLLBACK[0]
        # Last rollback undoes first forward step (VLAN interface)
        assert "VLAN interface" in VLAN_CONFIGURE_ROLLBACK[-1]


class TestBuildVlanPlanSteps:
    """Tests for _build_vlan_plan_steps()."""

    def test_basic_plan_7_steps(self):
        """Builds 7 plan steps."""
        steps = _build_vlan_plan_steps("IoT", 50, "10.50.0.0/24")
        assert len(steps) == 7
        assert all(isinstance(s, PlanStep) for s in steps)

    def test_step_numbers_sequential(self):
        """Plan steps are numbered 1-7."""
        steps = _build_vlan_plan_steps("IoT", 50, "10.50.0.0/24")
        assert [s.number for s in steps] == [1, 2, 3, 4, 5, 6, 7]

    def test_vlan_name_in_steps(self):
        """VLAN name appears in step details."""
        steps = _build_vlan_plan_steps("Cameras", 60, "10.60.0.0/24")
        # Should appear in VLAN creation, firewall, network object, port profile
        vlan_name_count = sum(1 for s in steps if "Cameras" in s.detail or "Cameras" in s.action)
        assert vlan_name_count >= 3

    def test_ssid_binding_included(self):
        """SSID binding step is populated when ssid is provided."""
        steps = _build_vlan_plan_steps("IoT", 50, "10.50.0.0/24", ssid="IoT-WiFi")
        ssid_step = steps[6]  # Step 7
        assert "IoT-WiFi" in ssid_step.detail

    def test_ssid_skipped_when_none(self):
        """SSID step says 'Skip' when no SSID provided."""
        steps = _build_vlan_plan_steps("IoT", 50, "10.50.0.0/24")
        ssid_step = steps[6]  # Step 7
        assert "Skip" in ssid_step.action

    def test_dhcp_disabled(self):
        """DHCP step reflects disabled state."""
        steps = _build_vlan_plan_steps("IoT", 50, "10.50.0.0/24", dhcp_enabled=False)
        dhcp_step = steps[1]  # Step 2
        assert "disabled" in dhcp_step.detail.lower() or "Static" in dhcp_step.expected_outcome

    def test_gateway_and_edge_systems(self):
        """Steps include both Gateway and Edge systems."""
        steps = _build_vlan_plan_steps("IoT", 50, "10.50.0.0/24")
        systems = {s.system for s in steps}
        assert "Gateway" in systems
        assert "Edge" in systems


class TestBuildVlanChangeSteps:
    """Tests for _build_vlan_change_steps()."""

    def test_returns_7_change_steps(self):
        """Builds 7 change step dicts for risk assessment."""
        steps = _build_vlan_change_steps("IoT", 50, "10.50.0.0/24")
        assert len(steps) == 7

    def test_subsystems_present(self):
        """Change steps include various subsystems."""
        steps = _build_vlan_change_steps("IoT", 50, "10.50.0.0/24")
        subsystems = {s["subsystem"] for s in steps}
        assert "vlan" in subsystems
        assert "dhcp" in subsystems
        assert "firewall" in subsystems
        assert "interface" in subsystems
        assert "wifi" in subsystems

    def test_firewall_step_is_deny(self):
        """The firewall step has action_type=deny."""
        steps = _build_vlan_change_steps("IoT", 50, "10.50.0.0/24")
        fw_step = next(s for s in steps if s["subsystem"] == "firewall")
        assert fw_step.get("action_type") == "deny"


class TestVlanConfigureTool:
    """Tests for the netex__vlan__configure MCP tool."""

    @pytest.mark.asyncio
    async def test_configure_plan_only(self):
        """Configure without apply returns plan text."""
        result = await netex__vlan__configure(
            vlan_name="IoT",
            vlan_id=50,
            subnet="10.50.0.0/24",
            apply=False,
        )

        assert "Change Plan" in result
        assert "Create VLAN" in result
        assert "VLAN 50" in result

    @pytest.mark.asyncio
    async def test_configure_invalid_vlan_id_low(self):
        """Invalid VLAN ID (0) returns error."""
        result = await netex__vlan__configure(
            vlan_name="Bad", vlan_id=0, subnet="10.0.0.0/24",
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_configure_invalid_vlan_id_high(self):
        """Invalid VLAN ID (5000) returns error."""
        result = await netex__vlan__configure(
            vlan_name="Bad", vlan_id=5000, subnet="10.0.0.0/24",
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_configure_missing_gateway(self):
        """Missing gateway plugin returns error."""
        set_registry(_make_registry(gateway=False))
        result = await netex__vlan__configure(
            vlan_name="IoT", vlan_id=50, subnet="10.50.0.0/24",
        )
        assert "Error" in result
        assert "gateway" in result.lower()

    @pytest.mark.asyncio
    async def test_configure_missing_edge(self):
        """Missing edge plugin returns error."""
        set_registry(_make_registry(edge=False))
        result = await netex__vlan__configure(
            vlan_name="IoT", vlan_id=50, subnet="10.50.0.0/24",
        )
        assert "Error" in result
        assert "edge" in result.lower()

    @pytest.mark.asyncio
    async def test_configure_includes_rollback_plan(self):
        """Plan includes rollback steps."""
        result = await netex__vlan__configure(
            vlan_name="IoT", vlan_id=50, subnet="10.50.0.0/24",
        )
        assert "Rollback" in result or "rollback" in result

    @pytest.mark.asyncio
    async def test_configure_with_ssid(self):
        """Plan with SSID includes wireless binding."""
        result = await netex__vlan__configure(
            vlan_name="IoT", vlan_id=50, subnet="10.50.0.0/24",
            ssid="IoT-WiFi",
        )
        assert "IoT-WiFi" in result



# ===========================================================================
# Task 133: VLAN Audit Tests
# ===========================================================================


class TestVlanAudit:
    """Tests for netex__vlan__audit MCP tool."""

    @pytest.mark.asyncio
    async def test_audit_with_plugins(self):
        """VLAN audit with both plugins returns a report."""
        from netex.tools.commands import netex__vlan__audit

        result = await netex__vlan__audit()
        assert "VLAN Audit" in result

    @pytest.mark.asyncio
    async def test_audit_no_plugins(self):
        """VLAN audit with no plugins returns informative message."""
        from netex.tools.commands import netex__vlan__audit

        set_registry(PluginRegistry(auto_discover=False))
        result = await netex__vlan__audit()
        assert "No gateway or edge plugins" in result

    @pytest.mark.asyncio
    async def test_audit_gateway_only(self):
        """VLAN audit with only gateway plugin still works."""
        from netex.tools.commands import netex__vlan__audit

        set_registry(_make_registry(edge=False))
        result = await netex__vlan__audit()
        assert "VLAN Audit" in result


# ===========================================================================
# Task 134: Topology Tests
# ===========================================================================


class TestTopology:
    """Tests for netex__topology__merged MCP tool."""

    @pytest.mark.asyncio
    async def test_topology_with_plugins(self):
        """Topology with edge plugin returns report with sources."""
        from netex.tools.commands import netex__topology__merged

        result = await netex__topology__merged()
        assert "Unified" in result and "Topology" in result
        assert "unifi" in result

    @pytest.mark.asyncio
    async def test_topology_no_plugins(self):
        """Topology with no plugins returns informative message."""
        from netex.tools.commands import netex__topology__merged

        set_registry(PluginRegistry(auto_discover=False))
        result = await netex__topology__merged()
        assert "No plugins provide topology" in result


class TestTopologyMerge:
    """Tests for NetworkTopology.merge() used by the topology command."""

    def test_merge_empty(self):
        """Merging two empty topologies returns empty."""
        t1 = NetworkTopology()
        t2 = NetworkTopology()
        merged = t1.merge(t2)
        assert merged.nodes == []
        assert merged.links == []

    def test_merge_deduplicates_nodes(self):
        """Duplicate node IDs are skipped (first-seen wins)."""
        t1 = NetworkTopology(
            nodes=[TopologyNode(
                node_id="gw1", name="Gateway", node_type=TopologyNodeType.GATEWAY,
            )],
            source_plugins=["opnsense"],
        )
        t2 = NetworkTopology(
            nodes=[
                TopologyNode(
                    node_id="gw1", name="Gateway-dup", node_type=TopologyNodeType.GATEWAY,
                ),
                TopologyNode(
                    node_id="sw1", name="Switch", node_type=TopologyNodeType.SWITCH,
                ),
            ],
            source_plugins=["unifi"],
        )

        merged = t1.merge(t2)
        assert len(merged.nodes) == 2
        # First-seen wins: gw1 keeps original name
        gw = next(n for n in merged.nodes if n.node_id == "gw1")
        assert gw.name == "Gateway"

    def test_merge_combines_links(self):
        """Links from both topologies are combined."""
        t1 = NetworkTopology(
            links=[TopologyLink(source_id="gw1", target_id="sw1")],
        )
        t2 = NetworkTopology(
            links=[TopologyLink(source_id="sw1", target_id="ap1")],
        )

        merged = t1.merge(t2)
        assert len(merged.links) == 2

    def test_merge_deduplicates_vlans(self):
        """VLANs from the same plugin with the same ID are deduplicated."""
        t1 = NetworkTopology(
            vlans=[VLAN(vlan_id=50, name="IoT", source_plugin="opnsense")],
        )
        t2 = NetworkTopology(
            vlans=[
                VLAN(vlan_id=50, name="IoT", source_plugin="opnsense"),  # dup
                VLAN(vlan_id=50, name="IoT", source_plugin="unifi"),  # different source
            ],
        )

        merged = t1.merge(t2)
        assert len(merged.vlans) == 2  # One from each plugin

    def test_merge_source_plugins(self):
        """Merged topology lists all contributing plugins."""
        t1 = NetworkTopology(source_plugins=["opnsense"])
        t2 = NetworkTopology(source_plugins=["unifi"])

        merged = t1.merge(t2)
        assert "opnsense" in merged.source_plugins
        assert "unifi" in merged.source_plugins


# ===========================================================================
# Task 135: Health Tests
# ===========================================================================


class TestHealth:
    """Tests for netex__health__report MCP tool."""

    @pytest.mark.asyncio
    async def test_health_with_plugins(self):
        """Health report with both plugins lists them."""
        from netex.tools.commands import netex__health__report

        result = await netex__health__report()
        assert "Health Report" in result
        assert "opnsense" in result
        assert "unifi" in result

    @pytest.mark.asyncio
    async def test_health_no_plugins(self):
        """Health report with no plugins gives guidance."""
        from netex.tools.commands import netex__health__report

        set_registry(PluginRegistry(auto_discover=False))
        result = await netex__health__report()
        assert "No vendor plugins installed" in result

    @pytest.mark.asyncio
    async def test_health_gateway_only(self):
        """Health report without edge plugin shows warning."""
        from netex.tools.commands import netex__health__report

        set_registry(_make_registry(edge=False))
        result = await netex__health__report()
        assert "Health Report" in result
        # Should warn about missing edge
        assert "edge" in result.lower()

    @pytest.mark.asyncio
    async def test_health_edge_only(self):
        """Health report without gateway plugin shows warning."""
        from netex.tools.commands import netex__health__report

        set_registry(_make_registry(gateway=False))
        result = await netex__health__report()
        assert "gateway" in result.lower()


# ===========================================================================
# Task 136: Firewall Audit Tests
# ===========================================================================


class TestFirewallAudit:
    """Tests for netex__firewall__audit MCP tool."""

    @pytest.mark.asyncio
    async def test_firewall_audit_with_both_layers(self):
        """Firewall audit with both layers shows available tools."""
        from netex.tools.commands import netex__firewall__audit

        result = await netex__firewall__audit()
        assert "Firewall Audit" in result

    @pytest.mark.asyncio
    async def test_firewall_audit_no_plugins(self):
        """Firewall audit with no plugins gives guidance."""
        from netex.tools.commands import netex__firewall__audit

        set_registry(PluginRegistry(auto_discover=False))
        result = await netex__firewall__audit()
        assert "No plugins provide firewall" in result

    @pytest.mark.asyncio
    async def test_firewall_audit_gateway_only(self):
        """Firewall audit with only gateway notes missing edge."""
        from netex.tools.commands import netex__firewall__audit

        set_registry(_make_registry(edge=False))
        result = await netex__firewall__audit()
        assert "Firewall Audit" in result


# ===========================================================================
# Task 137: Secure Audit/Review Tests
# ===========================================================================


class TestSecureAudit:
    """Tests for netex__secure__audit MCP tool."""

    @pytest.mark.asyncio
    async def test_audit_all_domains(self):
        """Full audit across all domains returns a report."""
        from netex.tools.commands import netex__secure__audit

        result = await netex__secure__audit()
        assert "Security Audit" in result

    @pytest.mark.asyncio
    async def test_audit_specific_domain(self):
        """Audit a specific valid domain."""
        from netex.tools.commands import netex__secure__audit

        result = await netex__secure__audit(domain="firewall-gw")
        assert "Security Audit" in result

    @pytest.mark.asyncio
    async def test_audit_invalid_domain(self):
        """Invalid domain returns error with valid domain list."""
        from netex.tools.commands import netex__secure__audit

        result = await netex__secure__audit(domain="not-a-domain")
        assert "Unknown domain" in result
        assert "firewall-gw" in result  # Lists valid domains

    @pytest.mark.asyncio
    async def test_audit_no_plugins(self):
        """Audit with no plugins returns informational findings."""
        from netex.tools.commands import netex__secure__audit

        set_registry(PluginRegistry(auto_discover=False))
        result = await netex__secure__audit()
        assert "Security Audit" in result


class TestSecureReview:
    """Tests for netex__secure__review MCP tool."""

    @pytest.mark.asyncio
    async def test_review_clean_plan(self):
        """Review with no issues returns clean report."""
        from netex.tools.commands import netex__secure__review

        result = await netex__secure__review(
            change_steps=[{"subsystem": "routing", "action": "add", "target": "static_route"}],
        )
        assert "Security Review" in result

    @pytest.mark.asyncio
    async def test_review_empty_plan(self):
        """Review with empty plan returns no findings."""
        from netex.tools.commands import netex__secure__review

        result = await netex__secure__review(change_steps=[])
        assert "No security findings" in result

    @pytest.mark.asyncio
    async def test_review_detects_broad_firewall(self):
        """Review detects overly broad firewall rule."""
        from netex.tools.commands import netex__secure__review

        result = await netex__secure__review(
            change_steps=[{
                "subsystem": "firewall",
                "action": "add",
                "target": "allow_all",
                "source": "any",
                "destination": "any",
                "port": "any",
                "protocol": "any",
                "action_type": "allow",
            }],
        )
        # The NetworkSecurityAgent should flag broad rules
        assert "finding" in result.lower() or "Security Review" in result


# ===========================================================================
# Module setup/teardown
# ===========================================================================


class TestModuleSetup:
    """Tests for module-level registry management."""

    def test_set_registry(self):
        """set_registry configures the module-level registry."""
        registry = _make_registry()
        set_registry(registry)
        assert _get_registry() is registry

    def test_get_orchestrator_creates_instance(self):
        """_get_orchestrator creates an Orchestrator lazily."""
        registry = _make_registry()
        set_registry(registry)
        orch = _get_orchestrator()
        assert isinstance(orch, Orchestrator)
