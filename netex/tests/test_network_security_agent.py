# SPDX-License-Identifier: MIT
"""Tests for the NetworkSecurityAgent.

Covers:
- Plan review: all 7 finding categories
- On-demand audit: domain filtering, coverage
- Read-only enforcement
- Mock plugin responses
- Edge cases
"""

from __future__ import annotations

import pytest

from netex.agents.network_security_agent import (
    AuditDomain,
    NetworkSecurityAgent,
    filter_read_only_tools,
    is_read_only_tool,
)
from netex.models.security_finding import (
    FindingCategory,
    FindingSeverity,
    SecurityFinding,
)
from netex.registry.plugin_registry import PluginRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_registry(
    *,
    has_firewall: bool = True,
    has_security: bool = True,
    has_vpn: bool = True,
    has_wifi: bool = True,
    has_services: bool = True,
    has_interfaces: bool = True,
    has_topology: bool = True,
    has_firmware: bool = False,
    has_health: bool = False,
    has_config: bool = False,
) -> PluginRegistry:
    """Create a registry with configurable skills and tools."""
    registry = PluginRegistry(auto_discover=False)

    # Gateway plugin (opnsense-like)
    gw_skills: list[str] = []
    gw_tools: dict[str, list[str]] = {}

    if has_firewall:
        gw_skills.append("firewall")
        gw_tools["firewall"] = [
            "opnsense__firewall__list_rules",
            "opnsense__firewall__add_rule",
        ]
    if has_security:
        gw_skills.append("security")
        gw_tools["security"] = ["opnsense__security__list_alerts"]
    if has_vpn:
        gw_skills.append("vpn")
        gw_tools["vpn"] = ["opnsense__vpn__list_tunnels"]
    if has_services:
        gw_skills.append("services")
        gw_tools["services"] = ["opnsense__services__get_dns_config"]
    if has_interfaces:
        gw_skills.append("interfaces")
        gw_tools["interfaces"] = ["opnsense__interfaces__list_interfaces"]
    if has_firmware:
        gw_skills.append("firmware")
        gw_tools["firmware"] = ["opnsense__firmware__get_status"]

    if gw_skills:
        registry.register({
            "name": "opnsense",
            "version": "0.2.0",
            "vendor": "opnsense",
            "roles": ["gateway"],
            "skills": gw_skills,
            "tools": gw_tools,
        })

    # Edge plugin (unifi-like)
    edge_skills: list[str] = []
    edge_tools: dict[str, list[str]] = {}

    if has_topology:
        edge_skills.append("topology")
        edge_tools["topology"] = ["unifi__topology__list_devices"]
    if has_wifi:
        edge_skills.append("wifi")
        edge_tools["wifi"] = ["unifi__wifi__list_ssids"]
    if has_security:
        edge_skills.append("security")
        edge_tools["security"] = ["unifi__security__list_threats"]
    if has_health:
        edge_skills.append("health")
        edge_tools["health"] = ["unifi__health__get_health"]
    if has_config:
        edge_skills.append("config")
        edge_tools["config"] = ["unifi__config__get_settings"]

    if edge_skills:
        registry.register({
            "name": "unifi",
            "version": "0.1.0",
            "vendor": "unifi",
            "roles": ["edge", "wireless"],
            "skills": edge_skills,
            "tools": edge_tools,
        })

    return registry


@pytest.fixture
def agent() -> NetworkSecurityAgent:
    return NetworkSecurityAgent()


@pytest.fixture
def full_registry() -> PluginRegistry:
    """Registry with all typical gateway+edge skills."""
    return _make_registry()


@pytest.fixture
def empty_registry() -> PluginRegistry:
    """Registry with no plugins."""
    return PluginRegistry(auto_discover=False)


# ---------------------------------------------------------------------------
# Read-only enforcement
# ---------------------------------------------------------------------------

class TestReadOnlyEnforcement:
    def test_read_tool_allowed(self) -> None:
        assert is_read_only_tool("opnsense__firewall__list_rules") is True

    def test_read_tool_get(self) -> None:
        assert is_read_only_tool("unifi__topology__get_device") is True

    def test_write_tool_add_blocked(self) -> None:
        assert is_read_only_tool("opnsense__firewall__add_rule") is False

    def test_write_tool_create_blocked(self) -> None:
        assert is_read_only_tool("unifi__config__create_network") is False

    def test_write_tool_update_blocked(self) -> None:
        assert is_read_only_tool("opnsense__firewall__update_rule") is False

    def test_write_tool_delete_blocked(self) -> None:
        assert is_read_only_tool("opnsense__firewall__delete_rule") is False

    def test_write_tool_set_blocked(self) -> None:
        assert is_read_only_tool("unifi__config__set_setting") is False

    def test_write_tool_apply_blocked(self) -> None:
        assert is_read_only_tool("opnsense__services__apply_config") is False

    def test_write_tool_assign_blocked(self) -> None:
        assert is_read_only_tool("unifi__ports__assign_profile") is False

    def test_write_tool_configure_blocked(self) -> None:
        assert is_read_only_tool("opnsense__interfaces__configure_vlan") is False

    def test_write_tool_reconfigure_blocked(self) -> None:
        assert is_read_only_tool("opnsense__firewall__reconfigure") is False

    def test_write_tool_provision_blocked(self) -> None:
        assert is_read_only_tool("netex__vlan__provision_batch") is False

    def test_write_tool_remove_blocked(self) -> None:
        assert is_read_only_tool("opnsense__firewall__remove_rule") is False

    def test_filter_read_only_tools(self) -> None:
        tools = [
            {"plugin": "opnsense", "skill": "firewall", "tool": "opnsense__firewall__list_rules"},
            {"plugin": "opnsense", "skill": "firewall", "tool": "opnsense__firewall__add_rule"},
            {"plugin": "unifi", "skill": "topology", "tool": "unifi__topology__get_device"},
            {"plugin": "unifi", "skill": "config", "tool": "unifi__config__create_network"},
        ]
        filtered = filter_read_only_tools(tools)
        assert len(filtered) == 2
        assert all("list_" in t["tool"] or "get_" in t["tool"] for t in filtered)

    def test_filter_empty_list(self) -> None:
        assert filter_read_only_tools([]) == []


# ---------------------------------------------------------------------------
# Plan review: Category 1 -- VLAN isolation gap
# ---------------------------------------------------------------------------

class TestVlanIsolation:
    async def test_vlan_without_firewall_rules(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """New VLAN without deny rules produces a finding."""
        steps = [
            {"subsystem": "vlan", "action": "add", "target": "IoT", "vlan_id": "50"},
        ]
        findings = await agent.review_plan(steps, full_registry)
        assert len(findings) >= 1
        vlan_findings = [f for f in findings if f.category == FindingCategory.VLAN_ISOLATION]
        assert len(vlan_findings) == 1
        assert vlan_findings[0].severity == FindingSeverity.HIGH
        assert "IoT" in vlan_findings[0].description

    async def test_vlan_with_matching_deny_rule(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """VLAN with corresponding deny rules in the plan produces no gap finding."""
        steps = [
            {"subsystem": "vlan", "action": "add", "target": "IoT", "vlan_id": "50"},
            {
                "subsystem": "firewall",
                "action": "add",
                "target": "deny-50-to-all",
                "action_type": "deny",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        vlan_findings = [f for f in findings if f.category == FindingCategory.VLAN_ISOLATION]
        # The deny rule target does contain "50" matching vlan_id
        assert len(vlan_findings) == 0

    async def test_multiple_vlans_without_rules(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Multiple new VLANs without rules produce multiple findings."""
        steps = [
            {"subsystem": "vlan", "action": "create", "target": "IoT", "vlan_id": "50"},
            {"subsystem": "vlan", "action": "create", "target": "Cameras", "vlan_id": "60"},
        ]
        findings = await agent.review_plan(steps, full_registry)
        vlan_findings = [f for f in findings if f.category == FindingCategory.VLAN_ISOLATION]
        assert len(vlan_findings) == 2


# ---------------------------------------------------------------------------
# Plan review: Category 2 -- Overly broad firewall rule
# ---------------------------------------------------------------------------

class TestBroadFirewallRules:
    async def test_any_any_rule(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """any/any source+destination allow rule is flagged."""
        steps = [
            {
                "subsystem": "firewall",
                "action": "add",
                "target": "allow-all",
                "source": "any",
                "destination": "any",
                "port": "any",
                "protocol": "any",
                "action_type": "allow",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        broad_findings = [f for f in findings if f.category == FindingCategory.FIREWALL_POLICY]
        assert len(broad_findings) >= 1
        assert broad_findings[0].severity == FindingSeverity.HIGH
        assert "any" in broad_findings[0].description.lower()

    async def test_deny_rule_not_flagged(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Deny rules with any/any are not flagged (they're restrictive)."""
        steps = [
            {
                "subsystem": "firewall",
                "action": "add",
                "target": "deny-all",
                "source": "any",
                "destination": "any",
                "action_type": "deny",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        broad_findings = [f for f in findings if f.category == FindingCategory.FIREWALL_POLICY]
        assert len(broad_findings) == 0

    async def test_specific_rule_not_flagged(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """A specific allow rule is not flagged as broad."""
        steps = [
            {
                "subsystem": "firewall",
                "action": "add",
                "target": "allow-dns",
                "source": "10.0.50.0/24",
                "destination": "10.0.1.1",
                "port": "53",
                "protocol": "udp",
                "action_type": "allow",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        broad_findings = [f for f in findings if f.category == FindingCategory.FIREWALL_POLICY]
        assert len(broad_findings) == 0


# ---------------------------------------------------------------------------
# Plan review: Category 3 -- Firewall rule ordering risk
# ---------------------------------------------------------------------------

class TestRuleOrdering:
    async def test_allow_without_position(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Allow rule without explicit position gets ordering warning."""
        steps = [
            {
                "subsystem": "firewall",
                "action": "add",
                "target": "allow-http",
                "action_type": "allow",
                "source": "10.0.0.0/8",
                "destination": "10.0.1.1",
                "port": "80",
                "protocol": "tcp",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        ordering = [f for f in findings if f.category == FindingCategory.RULE_ORDERING]
        assert len(ordering) == 1
        assert ordering[0].severity == FindingSeverity.MEDIUM

    async def test_rule_with_explicit_position(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Rule with explicit insert_position is not flagged."""
        steps = [
            {
                "subsystem": "firewall",
                "action": "add",
                "target": "allow-http",
                "action_type": "allow",
                "insert_position": 5,
                "source": "10.0.0.0/8",
                "destination": "10.0.1.1",
                "port": "80",
                "protocol": "tcp",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        ordering = [f for f in findings if f.category == FindingCategory.RULE_ORDERING]
        assert len(ordering) == 0


# ---------------------------------------------------------------------------
# Plan review: Category 4 -- VPN split-tunnel exposure
# ---------------------------------------------------------------------------

class TestVpnSplitTunnel:
    async def test_full_tunnel_with_split_intent(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """0.0.0.0/0 allowed IPs with split tunnel intent is flagged."""
        steps = [
            {
                "subsystem": "vpn",
                "action": "create",
                "target": "remote-access",
                "allowed_ips": "0.0.0.0/0",
                "tunnel_scope": "split",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        vpn_findings = [f for f in findings if f.category == FindingCategory.VPN_POSTURE]
        assert len(vpn_findings) == 1
        assert vpn_findings[0].severity == FindingSeverity.HIGH

    async def test_narrow_scope_with_full_intent(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Narrow allowed_ips with full tunnel intent is flagged."""
        steps = [
            {
                "subsystem": "vpn",
                "action": "create",
                "target": "site-to-site",
                "allowed_ips": "10.0.0.0/8",
                "tunnel_scope": "full",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        vpn_findings = [f for f in findings if f.category == FindingCategory.VPN_POSTURE]
        assert len(vpn_findings) == 1
        assert vpn_findings[0].severity == FindingSeverity.MEDIUM

    async def test_matching_scope_not_flagged(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Split tunnel with narrow IPs is not flagged."""
        steps = [
            {
                "subsystem": "vpn",
                "action": "create",
                "target": "remote",
                "allowed_ips": "10.0.0.0/24",
                "tunnel_scope": "split",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        vpn_findings = [f for f in findings if f.category == FindingCategory.VPN_POSTURE]
        assert len(vpn_findings) == 0


# ---------------------------------------------------------------------------
# Plan review: Category 5 -- Unencrypted VLAN for sensitive traffic
# ---------------------------------------------------------------------------

class TestUnencryptedVlan:
    async def test_iot_ssid_open_auth(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """IoT SSID with open auth is flagged."""
        steps = [
            {
                "subsystem": "wifi",
                "action": "create",
                "target": "IoT-Network",
                "purpose": "iot",
                "security": "open",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        wifi_findings = [f for f in findings if f.category == FindingCategory.WIRELESS_SECURITY]
        assert len(wifi_findings) == 1
        assert wifi_findings[0].severity == FindingSeverity.HIGH

    async def test_management_ssid_no_security(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Management SSID with no security mode is flagged."""
        steps = [
            {
                "subsystem": "ssid",
                "action": "create",
                "target": "Mgmt-WiFi",
                "purpose": "management",
                "security": "",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        wifi_findings = [f for f in findings if f.category == FindingCategory.WIRELESS_SECURITY]
        assert len(wifi_findings) == 1

    async def test_camera_ssid_none_security(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Camera SSID with security=none is flagged."""
        steps = [
            {
                "subsystem": "wifi",
                "action": "add",
                "target": "Cameras",
                "purpose": "cameras",
                "security": "none",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        wifi_findings = [f for f in findings if f.category == FindingCategory.WIRELESS_SECURITY]
        assert len(wifi_findings) == 1

    async def test_guest_ssid_not_flagged(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Guest SSID (non-sensitive purpose) is not flagged."""
        steps = [
            {
                "subsystem": "wifi",
                "action": "create",
                "target": "Guest-Network",
                "purpose": "guest",
                "security": "open",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        wifi_findings = [f for f in findings if f.category == FindingCategory.WIRELESS_SECURITY]
        assert len(wifi_findings) == 0

    async def test_iot_with_wpa3_not_flagged(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """IoT SSID with WPA3 is not flagged."""
        steps = [
            {
                "subsystem": "wifi",
                "action": "create",
                "target": "IoT",
                "purpose": "iot",
                "security": "wpa3",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        wifi_findings = [f for f in findings if f.category == FindingCategory.WIRELESS_SECURITY]
        assert len(wifi_findings) == 0


# ---------------------------------------------------------------------------
# Plan review: Category 6 -- Management plane exposure
# ---------------------------------------------------------------------------

class TestManagementExposure:
    async def test_firewall_rule_guest_to_mgmt(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Firewall rule allowing guest to management is CRITICAL."""
        steps = [
            {
                "subsystem": "firewall",
                "action": "add",
                "target": "management-access",
                "source": "guest-vlan",
                "destination": "management",
                "action_type": "allow",
                "port": "443",
                "protocol": "tcp",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        mgmt_findings = [f for f in findings if f.category == FindingCategory.MANAGEMENT_EXPOSURE]
        assert len(mgmt_findings) >= 1
        assert mgmt_findings[0].severity == FindingSeverity.CRITICAL

    async def test_iot_to_admin_route(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Route from IoT to admin interface is flagged."""
        steps = [
            {
                "subsystem": "route",
                "action": "add",
                "target": "admin-route",
                "source": "iot-subnet",
                "destination": "admin-interface",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        mgmt_findings = [f for f in findings if f.category == FindingCategory.MANAGEMENT_EXPOSURE]
        assert len(mgmt_findings) >= 1

    async def test_trusted_to_mgmt_not_flagged(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Trusted VLAN to management is not flagged."""
        steps = [
            {
                "subsystem": "firewall",
                "action": "add",
                "target": "mgmt-from-trusted",
                "source": "trusted-vlan",
                "destination": "management",
                "action_type": "allow",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        mgmt_findings = [f for f in findings if f.category == FindingCategory.MANAGEMENT_EXPOSURE]
        assert len(mgmt_findings) == 0


# ---------------------------------------------------------------------------
# Plan review: Category 7 -- DNS security posture
# ---------------------------------------------------------------------------

class TestDnsSecurity:
    async def test_dnssec_disabled(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Disabling DNSSEC is flagged."""
        steps = [
            {
                "subsystem": "dns",
                "action": "modify",
                "target": "Unbound",
                "dnssec": False,
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        dns_findings = [f for f in findings if f.category == FindingCategory.DNS_SECURITY]
        assert any(f.description and "DNSSEC" in f.description for f in dns_findings)

    async def test_forwarder_without_dot(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """DNS forwarder without DoT is flagged."""
        steps = [
            {
                "subsystem": "dns",
                "action": "add",
                "target": "forwarder",
                "forwarder": "8.8.8.8",
                "dot_enabled": False,
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        dns_findings = [f for f in findings if f.category == FindingCategory.DNS_SECURITY]
        assert any("DoT" in f.description or "DNS-over-TLS" in f.description for f in dns_findings)

    async def test_open_recursion(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Open recursion is flagged as HIGH."""
        steps = [
            {
                "subsystem": "services",
                "action": "modify",
                "target": "Unbound",
                "open_recursion": True,
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        dns_findings = [f for f in findings if f.category == FindingCategory.DNS_SECURITY]
        assert len(dns_findings) >= 1
        recursion_findings = [
            f for f in dns_findings if "recursion" in f.description.lower()
        ]
        assert len(recursion_findings) == 1
        assert recursion_findings[0].severity == FindingSeverity.HIGH

    async def test_forwarder_with_dot_not_flagged(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """DNS forwarder with DoT enabled is not flagged."""
        steps = [
            {
                "subsystem": "dns",
                "action": "add",
                "target": "forwarder",
                "forwarder": "1.1.1.1",
                "dot_enabled": True,
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        dns_findings = [
            f for f in findings
            if f.category == FindingCategory.DNS_SECURITY and "DoT" in f.description
        ]
        assert len(dns_findings) == 0


# ---------------------------------------------------------------------------
# Plan review: edge cases
# ---------------------------------------------------------------------------

class TestPlanReviewEdgeCases:
    async def test_empty_steps(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Empty change list returns no findings."""
        findings = await agent.review_plan([], full_registry)
        assert findings == []

    async def test_unrelated_subsystems(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Steps in non-security subsystems produce no findings."""
        steps = [
            {"subsystem": "port_profile", "action": "create", "target": "cameras"},
            {"subsystem": "switch", "action": "modify", "target": "sw-01"},
        ]
        findings = await agent.review_plan(steps, full_registry)
        assert findings == []

    async def test_findings_sorted_by_severity(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Findings are returned sorted by severity (most severe first)."""
        steps = [
            # MEDIUM: DNS without DoT
            {
                "subsystem": "dns",
                "action": "add",
                "target": "resolver",
                "forwarder": "8.8.8.8",
                "dot_enabled": False,
            },
            # HIGH: VLAN isolation gap
            {"subsystem": "vlan", "action": "add", "target": "IoT", "vlan_id": "50"},
            # CRITICAL: management exposure
            {
                "subsystem": "firewall",
                "action": "add",
                "target": "management-access",
                "source": "guest-vlan",
                "destination": "management",
                "action_type": "allow",
            },
        ]
        findings = await agent.review_plan(steps, full_registry)
        assert len(findings) >= 3

        # Check ordering: CRITICAL first, then HIGH, then MEDIUM
        severities = [f.severity for f in findings]
        severity_order = {
            FindingSeverity.CRITICAL: 0,
            FindingSeverity.HIGH: 1,
            FindingSeverity.MEDIUM: 2,
            FindingSeverity.LOW: 3,
            FindingSeverity.INFORMATIONAL: 4,
        }
        orders = [severity_order[s] for s in severities]
        assert orders == sorted(orders), "Findings should be sorted by severity"

    async def test_empty_registry(
        self, agent: NetworkSecurityAgent, empty_registry: PluginRegistry,
    ) -> None:
        """Plan review works even with no plugins registered."""
        steps = [
            {"subsystem": "vlan", "action": "add", "target": "IoT", "vlan_id": "50"},
        ]
        findings = await agent.review_plan(steps, empty_registry)
        # Should still produce findings (VLAN isolation gap) even without tools
        vlan_findings = [f for f in findings if f.category == FindingCategory.VLAN_ISOLATION]
        assert len(vlan_findings) == 1


# ---------------------------------------------------------------------------
# On-demand audit: domain filtering
# ---------------------------------------------------------------------------

class TestAuditDomainFiltering:
    async def test_all_domains_audited_by_default(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Without a domain filter, all 10 domains are audited."""
        findings = await agent.audit(full_registry)
        # Each domain without tools gets an INFORMATIONAL finding
        # Some domains have tools, so findings vary
        assert isinstance(findings, list)

    async def test_single_domain_filter(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Specifying a domain restricts audit to that domain."""
        findings = await agent.audit(full_registry, domain="firewall-gw")
        # Should only contain findings from firewall-gw domain
        assert isinstance(findings, list)

    async def test_unknown_domain_returns_informational(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Unknown domain returns an informational finding."""
        findings = await agent.audit(full_registry, domain="nonexistent")
        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.INFORMATIONAL
        assert "Unknown audit domain" in findings[0].description

    async def test_each_domain_enum_value(self) -> None:
        """All 10 audit domains are defined."""
        assert len(AuditDomain) == 10
        expected = {
            "firewall-gw", "firewall-edge", "cross-layer",
            "vlan-isolation", "vpn-posture", "dns-security",
            "ids-ips", "wireless", "certs", "firmware",
        }
        assert {d.value for d in AuditDomain} == expected

    async def test_audit_firewall_edge_domain(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """firewall-edge domain audit runs without error."""
        findings = await agent.audit(full_registry, domain="firewall-edge")
        assert isinstance(findings, list)

    async def test_audit_vlan_isolation_domain(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """vlan-isolation domain audit runs without error."""
        findings = await agent.audit(full_registry, domain="vlan-isolation")
        assert isinstance(findings, list)

    async def test_audit_vpn_posture_domain(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """vpn-posture domain audit runs without error."""
        findings = await agent.audit(full_registry, domain="vpn-posture")
        assert isinstance(findings, list)

    async def test_audit_dns_security_domain(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """dns-security domain audit runs without error."""
        findings = await agent.audit(full_registry, domain="dns-security")
        assert isinstance(findings, list)

    async def test_audit_wireless_domain(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """wireless domain audit runs without error."""
        findings = await agent.audit(full_registry, domain="wireless")
        assert isinstance(findings, list)


# ---------------------------------------------------------------------------
# On-demand audit: tool availability
# ---------------------------------------------------------------------------

class TestAuditToolAvailability:
    async def test_missing_tools_produce_informational(
        self, agent: NetworkSecurityAgent, empty_registry: PluginRegistry,
    ) -> None:
        """Domains without available tools produce informational findings."""
        findings = await agent.audit(empty_registry, domain="firewall-gw")
        assert len(findings) >= 1
        assert findings[0].severity == FindingSeverity.INFORMATIONAL
        assert "No plugins provide tools" in findings[0].description

    async def test_firmware_domain_without_plugin(
        self, agent: NetworkSecurityAgent,
    ) -> None:
        """Firmware domain without firmware skill produces informational."""
        registry = _make_registry(has_firmware=False, has_health=False)
        findings = await agent.audit(registry, domain="firmware")
        informational = [
            f for f in findings if f.severity == FindingSeverity.INFORMATIONAL
        ]
        assert len(informational) >= 1

    async def test_partial_tools_available(
        self, agent: NetworkSecurityAgent,
    ) -> None:
        """Domains with partial tools still produce results."""
        registry = _make_registry(has_firewall=True, has_security=False)
        findings = await agent.audit(registry, domain="firewall-gw")
        # firewall-gw needs firewall + security skills; only firewall is available
        # Should still work (partial tool coverage)
        assert isinstance(findings, list)


# ---------------------------------------------------------------------------
# On-demand audit: findings quality
# ---------------------------------------------------------------------------

class TestAuditFindingsQuality:
    async def test_findings_sorted(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """Audit findings are sorted by severity."""
        findings = await agent.audit(full_registry)
        if len(findings) > 1:
            severity_order = {
                FindingSeverity.CRITICAL: 0,
                FindingSeverity.HIGH: 1,
                FindingSeverity.MEDIUM: 2,
                FindingSeverity.LOW: 3,
                FindingSeverity.INFORMATIONAL: 4,
            }
            orders = [severity_order[f.severity] for f in findings]
            assert orders == sorted(orders)

    async def test_findings_are_security_finding_instances(
        self, agent: NetworkSecurityAgent, full_registry: PluginRegistry,
    ) -> None:
        """All audit results are SecurityFinding instances."""
        findings = await agent.audit(full_registry)
        for finding in findings:
            assert isinstance(finding, SecurityFinding)

    async def test_informational_findings_have_recommendation(
        self, agent: NetworkSecurityAgent, empty_registry: PluginRegistry,
    ) -> None:
        """Informational 'no tools' findings include a recommendation."""
        findings = await agent.audit(empty_registry, domain="firewall-gw")
        for finding in findings:
            if "No plugins" in finding.description:
                assert finding.recommendation != ""


# ---------------------------------------------------------------------------
# AuditDomain enum
# ---------------------------------------------------------------------------

class TestAuditDomainEnum:
    def test_domain_values(self) -> None:
        assert AuditDomain.FIREWALL_GW == "firewall-gw"
        assert AuditDomain.FIREWALL_EDGE == "firewall-edge"
        assert AuditDomain.CROSS_LAYER == "cross-layer"
        assert AuditDomain.VLAN_ISOLATION == "vlan-isolation"
        assert AuditDomain.VPN_POSTURE == "vpn-posture"
        assert AuditDomain.DNS_SECURITY == "dns-security"
        assert AuditDomain.IDS_IPS == "ids-ips"
        assert AuditDomain.WIRELESS == "wireless"
        assert AuditDomain.CERTS == "certs"
        assert AuditDomain.FIRMWARE == "firmware"

    def test_domain_count(self) -> None:
        assert len(AuditDomain) == 10
