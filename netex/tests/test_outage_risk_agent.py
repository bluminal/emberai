# SPDX-License-Identifier: MIT
"""Tests for the OutageRiskAgent.

Covers:
- All 4 risk tiers (CRITICAL, HIGH, MEDIUM, LOW)
- Session path resolution fallback chain (4 steps)
- Batch assessment (single pass per batch)
- Edge cases (empty steps, no tools, no IP)
"""

from __future__ import annotations

import pytest

from netex.agents.outage_risk_agent import (
    OutageRiskAgent,
    RiskTier,
    resolve_operator_ip,
)
from netex.registry.plugin_registry import PluginRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_registry(
    *,
    has_diagnostics: bool = True,
    has_topology: bool = True,
    has_clients: bool = True,
) -> PluginRegistry:
    """Create a registry with configurable tool availability."""
    registry = PluginRegistry(auto_discover=False)

    skills: list[str] = []
    tools: dict[str, list[str]] = {}

    if has_diagnostics:
        skills.append("diagnostics")
        tools["diagnostics"] = ["opnsense__diagnostics__run_traceroute"]
    if has_topology:
        skills.append("topology")
        tools["topology"] = ["unifi__topology__list_devices", "unifi__topology__get_device"]
    if has_clients:
        skills.append("clients")
        tools["clients"] = ["unifi__clients__list_clients"]

    if skills:
        registry.register({
            "name": "test-plugin",
            "version": "1.0.0",
            "roles": ["gateway", "edge"],
            "skills": skills,
            "tools": tools,
        })

    return registry


@pytest.fixture
def agent() -> OutageRiskAgent:
    return OutageRiskAgent()


@pytest.fixture
def full_registry() -> PluginRegistry:
    """Registry with all diagnostic/topology/client tools."""
    return _make_registry(has_diagnostics=True, has_topology=True, has_clients=True)


@pytest.fixture
def empty_registry() -> PluginRegistry:
    """Registry with no tools at all."""
    return _make_registry(has_diagnostics=False, has_topology=False, has_clients=False)


# ---------------------------------------------------------------------------
# Session path resolution (4-step fallback)
# ---------------------------------------------------------------------------

class TestResolveOperatorIP:
    def test_step1_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Step 1: OPERATOR_IP env var is checked first."""
        monkeypatch.setenv("OPERATOR_IP", "10.0.0.5")
        result = resolve_operator_ip()
        assert result == "10.0.0.5"

    def test_step1_explicit_env_override(self) -> None:
        """Step 1: env_var parameter overrides os.environ."""
        result = resolve_operator_ip(env_var="192.168.1.100")
        assert result == "192.168.1.100"

    def test_step2_x_forwarded_for(self) -> None:
        """Step 2: X-Forwarded-For header (first IP in chain)."""
        result = resolve_operator_ip(
            http_headers={"X-Forwarded-For": "10.10.0.1, 172.16.0.1"},
        )
        assert result == "10.10.0.1"

    def test_step2_x_real_ip(self) -> None:
        """Step 2: X-Real-IP header."""
        result = resolve_operator_ip(
            http_headers={"X-Real-IP": "10.20.0.5"},
        )
        assert result == "10.20.0.5"

    def test_step2_x_forwarded_for_takes_precedence(self) -> None:
        """X-Forwarded-For is checked before X-Real-IP."""
        result = resolve_operator_ip(
            http_headers={
                "X-Forwarded-For": "10.10.0.1",
                "X-Real-IP": "10.20.0.5",
            },
        )
        assert result == "10.10.0.1"

    def test_step3_cli_override(self) -> None:
        """Step 3: --operator-ip CLI argument."""
        result = resolve_operator_ip(cli_override="10.30.0.1")
        assert result == "10.30.0.1"

    def test_step4_none_when_undetermined(self) -> None:
        """Step 4: Returns None when IP cannot be determined."""
        result = resolve_operator_ip()
        assert result is None

    def test_priority_order_env_over_header(self) -> None:
        """Env var takes priority over HTTP headers."""
        result = resolve_operator_ip(
            env_var="10.0.0.1",
            http_headers={"X-Forwarded-For": "10.0.0.2"},
            cli_override="10.0.0.3",
        )
        assert result == "10.0.0.1"

    def test_priority_order_header_over_cli(self) -> None:
        """HTTP headers take priority over CLI override."""
        result = resolve_operator_ip(
            http_headers={"X-Real-IP": "10.0.0.2"},
            cli_override="10.0.0.3",
        )
        assert result == "10.0.0.2"

    def test_empty_env_var_falls_through(self) -> None:
        """Empty env var falls through to next step."""
        result = resolve_operator_ip(
            env_var="",
            cli_override="10.0.0.3",
        )
        assert result == "10.0.0.3"

    def test_empty_headers_fall_through(self) -> None:
        """Empty header values fall through."""
        result = resolve_operator_ip(
            http_headers={"X-Forwarded-For": "", "X-Real-IP": ""},
            cli_override="10.0.0.3",
        )
        assert result == "10.0.0.3"


# ---------------------------------------------------------------------------
# Risk tier: LOW
# ---------------------------------------------------------------------------

class TestRiskTierLow:
    async def test_empty_change_steps(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """Empty change list returns LOW risk."""
        result = await agent.assess([], full_registry, operator_ip="10.0.0.1")
        assert result["risk_tier"] == RiskTier.LOW
        assert result["affected_path"] is None

    async def test_unrelated_subsystem(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """Changes to unrelated subsystems (e.g. wifi) are LOW risk."""
        steps = [
            {"subsystem": "wifi", "action": "modify", "target": "guest-ssid"},
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.LOW
        assert result["session_path_known"] is True

    async def test_multiple_unrelated_steps(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """Multiple unrelated steps still produce LOW risk."""
        steps = [
            {"subsystem": "wifi", "action": "modify", "target": "guest"},
            {"subsystem": "port_profile", "action": "create", "target": "cameras"},
            {"subsystem": "ssid", "action": "add", "target": "iot-network"},
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.LOW


# ---------------------------------------------------------------------------
# Risk tier: MEDIUM
# ---------------------------------------------------------------------------

class TestRiskTierMedium:
    async def test_dns_change(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """DNS changes are classified as MEDIUM (indirect disruption)."""
        steps = [
            {"subsystem": "dns", "action": "modify", "target": "forwarder"},
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.MEDIUM
        assert "indirect disruption" in result["description"]

    async def test_dhcp_change(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """DHCP changes are MEDIUM risk."""
        steps = [
            {"subsystem": "dhcp", "action": "modify", "target": "pool-10"},
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.MEDIUM

    async def test_routing_change(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """Routing (services) changes are MEDIUM risk."""
        steps = [
            {"subsystem": "routing", "action": "add", "target": "new-route"},
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.MEDIUM

    async def test_medium_trumps_low(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """Batch with LOW + MEDIUM steps results in MEDIUM overall."""
        steps = [
            {"subsystem": "wifi", "action": "modify", "target": "guest"},
            {"subsystem": "dns", "action": "modify", "target": "resolver"},
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.MEDIUM


# ---------------------------------------------------------------------------
# Risk tier: HIGH
# ---------------------------------------------------------------------------

class TestRiskTierHigh:
    async def test_interface_change_same_subsystem(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """Interface changes are HIGH when not directly on session path."""
        steps = [
            {"subsystem": "interface", "action": "modify", "target": "igb2"},
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.HIGH
        assert "same subsystem" in result["description"]

    async def test_vlan_change_same_subsystem(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """VLAN changes are HIGH when not intersecting session path."""
        steps = [
            {"subsystem": "vlan", "action": "add", "target": "99"},
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.HIGH

    async def test_firewall_change_same_subsystem(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """Firewall changes are HIGH when not matching session rules."""
        steps = [
            {"subsystem": "firewall", "action": "add", "target": "new-rule"},
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.HIGH

    async def test_route_change_same_subsystem(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """Route changes are HIGH when not on session path."""
        steps = [
            {"subsystem": "route", "action": "modify", "target": "10.99.0.0/24"},
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.HIGH

    async def test_undetermined_ip_defaults_to_high(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """When operator IP cannot be determined, default to HIGH."""
        steps = [
            {"subsystem": "vlan", "action": "add", "target": "50"},
        ]
        # No operator_ip, no env var, no headers, no CLI
        result = await agent.assess(steps, full_registry)
        assert result["risk_tier"] == RiskTier.HIGH
        assert result["session_path_known"] is False
        assert "could not be determined" in result["description"]

    async def test_no_tools_defaults_to_high(
        self, agent: OutageRiskAgent, empty_registry: PluginRegistry,
    ) -> None:
        """When no diagnostic tools are available, default to HIGH."""
        steps = [
            {"subsystem": "vlan", "action": "add", "target": "50"},
        ]
        result = await agent.assess(
            steps, empty_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.HIGH
        assert result["session_path_known"] is False

    async def test_high_trumps_medium(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """Batch with MEDIUM + HIGH steps results in HIGH overall."""
        steps = [
            {"subsystem": "dns", "action": "modify", "target": "resolver"},
            {"subsystem": "interface", "action": "modify", "target": "igb3"},
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.HIGH


# ---------------------------------------------------------------------------
# Risk tier: CRITICAL
# ---------------------------------------------------------------------------

class TestRiskTierCritical:
    async def test_interface_on_session_path(
        self, agent: OutageRiskAgent,
    ) -> None:
        """Modifying an interface in the session path is CRITICAL."""
        # Create registry with session path knowledge
        registry = _make_registry()

        # Manually patch the session path resolution to return known interfaces
        original_resolve = agent._resolve_session_path

        async def mock_resolve(ip, reg):
            return {
                "known": True,
                "interfaces": ["igb0", "igb1"],
                "vlans": [10, 20],
                "routes": ["0.0.0.0/0"],
                "firewall_rules": ["rule-abc-123"],
                "operator_ip": ip,
            }

        agent._resolve_session_path = mock_resolve  # type: ignore[assignment]

        steps = [
            {"subsystem": "interface", "action": "modify", "target": "igb0"},
        ]
        result = await agent.assess(
            steps, registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.CRITICAL
        assert "directly modifies" in result["description"]
        assert result["affected_path"] == "igb0"

        # Restore
        agent._resolve_session_path = original_resolve  # type: ignore[assignment]

    async def test_vlan_on_session_path(self, agent: OutageRiskAgent) -> None:
        """Modifying a VLAN in the session path is CRITICAL."""
        registry = _make_registry()

        async def mock_resolve(ip, reg):
            return {
                "known": True,
                "interfaces": ["igb0"],
                "vlans": [10, 20],
                "routes": [],
                "firewall_rules": [],
            }

        agent._resolve_session_path = mock_resolve  # type: ignore[assignment]

        steps = [
            {"subsystem": "vlan", "action": "modify", "target": "10"},
        ]
        result = await agent.assess(
            steps, registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.CRITICAL

    async def test_firewall_rule_on_session_path(
        self, agent: OutageRiskAgent,
    ) -> None:
        """Modifying a firewall rule permitting the session is CRITICAL."""
        registry = _make_registry()

        async def mock_resolve(ip, reg):
            return {
                "known": True,
                "interfaces": [],
                "vlans": [],
                "routes": [],
                "firewall_rules": ["rule-abc-123", "rule-def-456"],
            }

        agent._resolve_session_path = mock_resolve  # type: ignore[assignment]

        steps = [
            {"subsystem": "firewall", "action": "delete", "target": "rule-abc-123"},
        ]
        result = await agent.assess(
            steps, registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.CRITICAL

    async def test_route_on_session_path(self, agent: OutageRiskAgent) -> None:
        """Modifying a route in the session path is CRITICAL."""
        registry = _make_registry()

        async def mock_resolve(ip, reg):
            return {
                "known": True,
                "interfaces": [],
                "vlans": [],
                "routes": ["0.0.0.0/0", "10.0.0.0/8"],
                "firewall_rules": [],
            }

        agent._resolve_session_path = mock_resolve  # type: ignore[assignment]

        steps = [
            {"subsystem": "route", "action": "modify", "target": "0.0.0.0/0"},
        ]
        result = await agent.assess(
            steps, registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.CRITICAL
        assert result["affected_path"] == "0.0.0.0/0"

    async def test_critical_trumps_all(self, agent: OutageRiskAgent) -> None:
        """Batch with CRITICAL + lower risk steps => CRITICAL overall."""
        registry = _make_registry()

        async def mock_resolve(ip, reg):
            return {
                "known": True,
                "interfaces": ["igb0"],
                "vlans": [],
                "routes": [],
                "firewall_rules": [],
            }

        agent._resolve_session_path = mock_resolve  # type: ignore[assignment]

        steps = [
            {"subsystem": "wifi", "action": "modify", "target": "guest"},  # LOW
            {"subsystem": "dns", "action": "modify", "target": "resolver"},  # MEDIUM
            {"subsystem": "interface", "action": "modify", "target": "igb0"},  # CRITICAL
        ]
        result = await agent.assess(
            steps, registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.CRITICAL


# ---------------------------------------------------------------------------
# Batch assessment (single pass)
# ---------------------------------------------------------------------------

class TestBatchAssessment:
    async def test_single_assessment_per_batch(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """One assessment is produced for the entire batch."""
        steps = [
            {"subsystem": "wifi", "action": "modify", "target": "net1"},
            {"subsystem": "wifi", "action": "modify", "target": "net2"},
            {"subsystem": "dns", "action": "modify", "target": "resolver"},
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        # Result is a single dict, not a list
        assert isinstance(result, dict)
        assert "risk_tier" in result
        assert "description" in result

    async def test_batch_takes_highest_risk(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """Batch risk tier is the highest risk from any individual step."""
        steps = [
            {"subsystem": "wifi", "action": "modify", "target": "guest"},  # LOW
            {"subsystem": "interface", "action": "modify", "target": "igb5"},  # HIGH
        ]
        result = await agent.assess(
            steps, full_registry, operator_ip="10.0.0.1",
        )
        assert result["risk_tier"] == RiskTier.HIGH

    async def test_operator_ip_in_result(
        self, agent: OutageRiskAgent, full_registry: PluginRegistry,
    ) -> None:
        """The resolved operator IP is included in the result."""
        result = await agent.assess(
            [{"subsystem": "wifi", "action": "modify", "target": "x"}],
            full_registry,
            operator_ip="10.0.0.42",
        )
        assert result["operator_ip"] == "10.0.0.42"


# ---------------------------------------------------------------------------
# RiskTier enum
# ---------------------------------------------------------------------------

class TestRiskTierEnum:
    def test_values(self) -> None:
        assert RiskTier.CRITICAL == "CRITICAL"
        assert RiskTier.HIGH == "HIGH"
        assert RiskTier.MEDIUM == "MEDIUM"
        assert RiskTier.LOW == "LOW"

    def test_all_tiers_present(self) -> None:
        assert len(RiskTier) == 4
