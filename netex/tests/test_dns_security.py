# SPDX-License-Identifier: MIT
"""Tests for DNS filtering security checks in NetworkSecurityAgent.

Covers Task 262:
- DNS security gaps detected (weak profile)
- DNS security gaps -- all secure (strong profile)
- DNS logging disabled (WARNING finding)
- DNS logging enabled (no finding)
- Graceful skip when no dns plugin installed
- Multiple profiles (mixed weak + strong)
"""

from __future__ import annotations

import pytest

from netex.agents.network_security_agent import NetworkSecurityAgent
from netex.models.security_finding import FindingCategory, FindingSeverity
from netex.registry.plugin_registry import PluginRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_nextdns_profile(
    *,
    profile_id: str = "abc123",
    name: str = "Home",
    security_enabled_count: int = 12,
    security_total: int = 12,
    blocklist_count: int = 3,
    denylist_count: int = 0,
    allowlist_count: int = 0,
    logging_enabled: bool = True,
    parental_control_active: bool = False,
) -> dict:
    """Create a mock NextDNS profile summary dict."""
    return {
        "id": profile_id,
        "name": name,
        "security_enabled_count": security_enabled_count,
        "security_total": security_total,
        "blocklist_count": blocklist_count,
        "denylist_count": denylist_count,
        "allowlist_count": allowlist_count,
        "logging_enabled": logging_enabled,
        "parental_control_active": parental_control_active,
    }


def _make_registry_with_dns() -> PluginRegistry:
    """Create a registry with a nextdns plugin registered."""
    registry = PluginRegistry(auto_discover=False)
    registry.register(
        {
            "name": "nextdns",
            "version": "0.1.0",
            "vendor": "nextdns",
            "description": "NextDNS intelligence plugin",
            "roles": ["dns"],
            "skills": ["profiles", "analytics", "logs", "security-posture"],
            "write_flag": "NEXTDNS_WRITE_ENABLED",
            "contract_version": "1.0.0",
            "tools": {
                "profiles": [
                    "nextdns__profiles__list_profiles",
                    "nextdns__profiles__get_profile",
                    "nextdns__profiles__get_security",
                    "nextdns__profiles__get_privacy",
                    "nextdns__profiles__get_parental_control",
                    "nextdns__profiles__get_denylist",
                    "nextdns__profiles__get_allowlist",
                    "nextdns__profiles__get_settings",
                ],
                "analytics": [
                    "nextdns__analytics__get_status",
                    "nextdns__analytics__get_top_domains",
                ],
                "logs": [
                    "nextdns__logs__search",
                    "nextdns__logs__stream",
                ],
                "security-posture": [
                    "nextdns__security_posture__audit",
                    "nextdns__security_posture__compare",
                ],
            },
        }
    )
    return registry


def _make_registry_with_dns_and_gateway() -> PluginRegistry:
    """Create a registry with both nextdns and opnsense plugins."""
    registry = _make_registry_with_dns()
    registry.register(
        {
            "name": "opnsense",
            "version": "0.2.0",
            "vendor": "opnsense",
            "description": "OPNsense gateway intelligence",
            "roles": ["gateway"],
            "skills": ["interfaces", "firewall", "services"],
            "tools": {
                "firewall": ["opnsense__firewall__list_rules"],
                "services": ["opnsense__services__get_dns_config"],
            },
        }
    )
    return registry


def _make_registry_without_dns() -> PluginRegistry:
    """Create a registry with only gateway and edge plugins (no dns)."""
    registry = PluginRegistry(auto_discover=False)
    registry.register(
        {
            "name": "opnsense",
            "version": "0.2.0",
            "vendor": "opnsense",
            "roles": ["gateway"],
            "skills": ["firewall", "services"],
            "tools": {
                "firewall": ["opnsense__firewall__list_rules"],
            },
        }
    )
    registry.register(
        {
            "name": "unifi",
            "version": "0.1.0",
            "vendor": "unifi",
            "roles": ["edge"],
            "skills": ["topology"],
            "tools": {},
        }
    )
    return registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agent() -> NetworkSecurityAgent:
    return NetworkSecurityAgent()


@pytest.fixture
def dns_registry() -> PluginRegistry:
    return _make_registry_with_dns()


@pytest.fixture
def dns_gw_registry() -> PluginRegistry:
    return _make_registry_with_dns_and_gateway()


@pytest.fixture
def no_dns_registry() -> PluginRegistry:
    return _make_registry_without_dns()


@pytest.fixture
def empty_registry() -> PluginRegistry:
    return PluginRegistry(auto_discover=False)


# ---------------------------------------------------------------------------
# Test 1: DNS security gaps detected (weak profile)
# ---------------------------------------------------------------------------


class TestDnsSecurityGaps:
    def test_weak_profile_produces_high_finding(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Profile with 4/12 security toggles produces a HIGH finding."""
        profiles = [
            _make_nextdns_profile(
                profile_id="weak1",
                name="IoT",
                security_enabled_count=4,
                security_total=12,
            ),
        ]
        findings = agent.check_dns_filtering_security(dns_registry, profiles=profiles)
        security_gap_findings = [
            f
            for f in findings
            if f.category == FindingCategory.DNS_SECURITY
            and "weak threat protection" in f.description
        ]
        assert len(security_gap_findings) == 1
        assert security_gap_findings[0].severity == FindingSeverity.HIGH
        assert "4/12" in security_gap_findings[0].description
        assert "IoT" in security_gap_findings[0].description

    def test_threshold_7_produces_finding(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Profile with exactly 7/12 toggles (below threshold of 8) is flagged."""
        profiles = [
            _make_nextdns_profile(
                profile_id="borderline",
                name="Guest",
                security_enabled_count=7,
            ),
        ]
        findings = agent.check_dns_filtering_security(dns_registry, profiles=profiles)
        gap_findings = [f for f in findings if "weak threat protection" in f.description]
        assert len(gap_findings) == 1
        assert "7/12" in gap_findings[0].description


# ---------------------------------------------------------------------------
# Test 2: DNS security gaps -- all secure (no finding)
# ---------------------------------------------------------------------------


class TestDnsSecurityAllSecure:
    def test_strong_profile_no_finding(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Profile with 12/12 security toggles produces no gap finding."""
        profiles = [
            _make_nextdns_profile(
                profile_id="strong1",
                name="Main",
                security_enabled_count=12,
                security_total=12,
                logging_enabled=True,
            ),
        ]
        findings = agent.check_dns_filtering_security(dns_registry, profiles=profiles)
        gap_findings = [f for f in findings if "weak threat protection" in f.description]
        assert len(gap_findings) == 0

    def test_threshold_exactly_8_no_finding(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Profile with exactly 8/12 toggles (at threshold) is not flagged."""
        profiles = [
            _make_nextdns_profile(
                profile_id="ok",
                name="Office",
                security_enabled_count=8,
                logging_enabled=True,
            ),
        ]
        findings = agent.check_dns_filtering_security(dns_registry, profiles=profiles)
        gap_findings = [f for f in findings if "weak threat protection" in f.description]
        assert len(gap_findings) == 0


# ---------------------------------------------------------------------------
# Test 3: DNS logging disabled (WARNING finding)
# ---------------------------------------------------------------------------


class TestDnsLoggingDisabled:
    def test_logging_disabled_produces_warning(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Profile with logging disabled produces a MEDIUM finding."""
        profiles = [
            _make_nextdns_profile(
                profile_id="nolog1",
                name="Guest-NoLog",
                security_enabled_count=12,
                logging_enabled=False,
            ),
        ]
        findings = agent.check_dns_filtering_security(dns_registry, profiles=profiles)
        log_findings = [
            f
            for f in findings
            if f.category == FindingCategory.DNS_SECURITY and "logging disabled" in f.description
        ]
        assert len(log_findings) == 1
        assert log_findings[0].severity == FindingSeverity.MEDIUM
        assert "Guest-NoLog" in log_findings[0].description


# ---------------------------------------------------------------------------
# Test 4: DNS logging enabled (no finding)
# ---------------------------------------------------------------------------


class TestDnsLoggingEnabled:
    def test_logging_enabled_no_finding(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Profile with logging enabled produces no logging finding."""
        profiles = [
            _make_nextdns_profile(
                profile_id="logged1",
                name="Main-Logged",
                security_enabled_count=12,
                logging_enabled=True,
            ),
        ]
        findings = agent.check_dns_filtering_security(dns_registry, profiles=profiles)
        log_findings = [f for f in findings if "logging disabled" in f.description]
        assert len(log_findings) == 0


# ---------------------------------------------------------------------------
# Test 5: Graceful skip when no dns plugin installed
# ---------------------------------------------------------------------------


class TestGracefulSkipNoDns:
    def test_no_dns_plugin_no_findings_no_errors(
        self,
        agent: NetworkSecurityAgent,
        no_dns_registry: PluginRegistry,
    ) -> None:
        """Without a dns plugin, check returns empty list, no errors."""
        profiles = [
            _make_nextdns_profile(
                security_enabled_count=2,
                logging_enabled=False,
            ),
        ]
        # Even though we pass profile data, the check should
        # silently skip because no dns plugin is registered
        findings = agent.check_dns_filtering_security(no_dns_registry, profiles=profiles)
        assert findings == []

    def test_empty_registry_no_findings_no_errors(
        self,
        agent: NetworkSecurityAgent,
        empty_registry: PluginRegistry,
    ) -> None:
        """Completely empty registry returns no findings, no errors."""
        findings = agent.check_dns_filtering_security(empty_registry)
        assert findings == []


# ---------------------------------------------------------------------------
# Test 6: Multiple profiles (mixed weak + strong)
# ---------------------------------------------------------------------------


class TestMultipleProfiles:
    def test_two_weak_one_strong(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Two weak profiles + one strong: findings only for the weak ones."""
        profiles = [
            _make_nextdns_profile(
                profile_id="weak-iot",
                name="IoT",
                security_enabled_count=3,
                logging_enabled=True,
            ),
            _make_nextdns_profile(
                profile_id="strong-main",
                name="Main",
                security_enabled_count=12,
                logging_enabled=True,
            ),
            _make_nextdns_profile(
                profile_id="weak-guest",
                name="Guest",
                security_enabled_count=5,
                logging_enabled=True,
            ),
        ]
        findings = agent.check_dns_filtering_security(dns_registry, profiles=profiles)
        gap_findings = [f for f in findings if "weak threat protection" in f.description]
        assert len(gap_findings) == 2

        # Verify the right profiles are identified
        names_in_findings = [f.description for f in gap_findings]
        assert any("IoT" in d for d in names_in_findings)
        assert any("Guest" in d for d in names_in_findings)
        assert not any("Main" in d for d in names_in_findings)

    def test_mixed_logging_and_security(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Profiles with mixed issues produce findings for each issue."""
        profiles = [
            _make_nextdns_profile(
                profile_id="p1",
                name="Profile-A",
                security_enabled_count=4,
                logging_enabled=False,
            ),
            _make_nextdns_profile(
                profile_id="p2",
                name="Profile-B",
                security_enabled_count=12,
                logging_enabled=True,
            ),
            _make_nextdns_profile(
                profile_id="p3",
                name="Profile-C",
                security_enabled_count=10,
                logging_enabled=False,
            ),
        ]
        findings = agent.check_dns_filtering_security(dns_registry, profiles=profiles)

        # Profile-A: weak security + no logging = 2 findings
        # Profile-B: strong + logging = 0 findings
        # Profile-C: strong + no logging = 1 finding
        gap_findings = [f for f in findings if "weak threat protection" in f.description]
        log_findings = [f for f in findings if "logging disabled" in f.description]
        assert len(gap_findings) == 1  # only Profile-A
        assert len(log_findings) == 2  # Profile-A and Profile-C
        assert "Profile-A" in gap_findings[0].description

    def test_findings_sorted_by_severity(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Findings are sorted by severity (HIGH before MEDIUM)."""
        profiles = [
            _make_nextdns_profile(
                profile_id="p1",
                name="Weak-NoLog",
                security_enabled_count=2,
                logging_enabled=False,
            ),
        ]
        findings = agent.check_dns_filtering_security(dns_registry, profiles=profiles)
        # Should have HIGH (security gap) before MEDIUM (logging)
        assert len(findings) == 2
        assert findings[0].severity == FindingSeverity.HIGH
        assert findings[1].severity == FindingSeverity.MEDIUM


# ---------------------------------------------------------------------------
# DNS filtering bypass (VLAN without NextDNS forwarder)
# ---------------------------------------------------------------------------


class TestDnsFilteringBypass:
    def test_vlan_without_forwarder_produces_finding(
        self,
        agent: NetworkSecurityAgent,
        dns_gw_registry: PluginRegistry,
    ) -> None:
        """VLAN without a NextDNS forwarder produces a HIGH finding."""
        profiles = [
            _make_nextdns_profile(security_enabled_count=12, logging_enabled=True),
        ]
        vlans = [
            {
                "name": "IoT",
                "vlan_id": 50,
                "dns_forwarder": "",
            },
        ]
        findings = agent.check_dns_filtering_security(
            dns_gw_registry, profiles=profiles, vlans=vlans
        )
        bypass_findings = [f for f in findings if "bypass" in f.description.lower()]
        assert len(bypass_findings) == 1
        assert bypass_findings[0].severity == FindingSeverity.HIGH
        assert "IoT" in bypass_findings[0].description

    def test_vlan_with_nextdns_forwarder_no_finding(
        self,
        agent: NetworkSecurityAgent,
        dns_gw_registry: PluginRegistry,
    ) -> None:
        """VLAN with a NextDNS forwarder produces no bypass finding."""
        profiles = [
            _make_nextdns_profile(security_enabled_count=12, logging_enabled=True),
        ]
        vlans = [
            {
                "name": "IoT",
                "vlan_id": 50,
                "dns_forwarder": "dns.nextdns.io/abc123",
            },
        ]
        findings = agent.check_dns_filtering_security(
            dns_gw_registry, profiles=profiles, vlans=vlans
        )
        bypass_findings = [f for f in findings if "bypass" in f.description.lower()]
        assert len(bypass_findings) == 0

    def test_bypass_check_skipped_without_gateway(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Without a gateway plugin, bypass check is silently skipped."""
        profiles = [
            _make_nextdns_profile(security_enabled_count=12, logging_enabled=True),
        ]
        vlans = [
            {
                "name": "IoT",
                "vlan_id": 50,
                "dns_forwarder": "",
            },
        ]
        # dns_registry has no gateway plugin
        findings = agent.check_dns_filtering_security(dns_registry, profiles=profiles, vlans=vlans)
        bypass_findings = [f for f in findings if "bypass" in f.description.lower()]
        assert len(bypass_findings) == 0

    def test_bypass_check_skipped_without_vlan_data(
        self,
        agent: NetworkSecurityAgent,
        dns_gw_registry: PluginRegistry,
    ) -> None:
        """Without VLAN data provided, bypass check is silently skipped."""
        profiles = [
            _make_nextdns_profile(security_enabled_count=12, logging_enabled=True),
        ]
        findings = agent.check_dns_filtering_security(
            dns_gw_registry, profiles=profiles, vlans=None
        )
        bypass_findings = [f for f in findings if "bypass" in f.description.lower()]
        assert len(bypass_findings) == 0


# ---------------------------------------------------------------------------
# Plugin registry: dns role queries (Task 260)
# ---------------------------------------------------------------------------


class TestPluginRegistryDnsRole:
    def test_plugins_with_role_dns(self, dns_registry: PluginRegistry) -> None:
        """plugins_with_role('dns') returns the nextdns plugin."""
        plugins = dns_registry.plugins_with_role("dns")
        assert len(plugins) == 1
        assert plugins[0]["name"] == "nextdns"
        assert "dns" in plugins[0]["roles"]

    def test_tools_for_skill_profiles(self, dns_registry: PluginRegistry) -> None:
        """tools_for_skill('profiles') returns nextdns profile tools."""
        tools = dns_registry.tools_for_skill("profiles")
        assert len(tools) == 8
        assert all(t["plugin"] == "nextdns" for t in tools)
        tool_names = [t["tool"] for t in tools]
        assert "nextdns__profiles__list_profiles" in tool_names
        assert "nextdns__profiles__get_security" in tool_names

    def test_tools_for_skill_analytics(self, dns_registry: PluginRegistry) -> None:
        """tools_for_skill('analytics') returns nextdns analytics tools."""
        tools = dns_registry.tools_for_skill("analytics")
        assert len(tools) == 2
        assert all(t["plugin"] == "nextdns" for t in tools)

    def test_tools_for_skill_logs(self, dns_registry: PluginRegistry) -> None:
        """tools_for_skill('logs') returns nextdns log tools."""
        tools = dns_registry.tools_for_skill("logs")
        assert len(tools) == 2
        assert all(t["plugin"] == "nextdns" for t in tools)

    def test_tools_for_skill_security_posture(self, dns_registry: PluginRegistry) -> None:
        """tools_for_skill('security-posture') returns nextdns audit tools."""
        tools = dns_registry.tools_for_skill("security-posture")
        assert len(tools) == 2
        assert all(t["plugin"] == "nextdns" for t in tools)

    def test_all_roles_includes_dns(self, dns_registry: PluginRegistry) -> None:
        """all_roles property includes 'dns'."""
        assert "dns" in dns_registry.all_roles

    def test_all_skills_includes_dns_skills(self, dns_registry: PluginRegistry) -> None:
        """all_skills includes profiles, analytics, logs, security-posture."""
        skills = dns_registry.all_skills
        assert "profiles" in skills
        assert "analytics" in skills
        assert "logs" in skills
        assert "security-posture" in skills


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_profiles_list(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Empty profile list produces no findings."""
        findings = agent.check_dns_filtering_security(dns_registry, profiles=[])
        assert findings == []

    def test_none_profiles_defaults_to_empty(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """None profiles defaults to empty list (no crash)."""
        findings = agent.check_dns_filtering_security(dns_registry, profiles=None)
        assert findings == []

    def test_finding_has_source_attribution(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Findings have correct source_plugin and source_tool."""
        profiles = [
            _make_nextdns_profile(security_enabled_count=2, logging_enabled=False),
        ]
        findings = agent.check_dns_filtering_security(dns_registry, profiles=profiles)
        for finding in findings:
            assert finding.source_plugin == "nextdns"

    def test_finding_has_affected_resource(
        self,
        agent: NetworkSecurityAgent,
        dns_registry: PluginRegistry,
    ) -> None:
        """Findings include the profile ID as affected_resource."""
        profiles = [
            _make_nextdns_profile(
                profile_id="abc123",
                security_enabled_count=2,
                logging_enabled=True,
            ),
        ]
        findings = agent.check_dns_filtering_security(dns_registry, profiles=profiles)
        assert len(findings) >= 1
        assert findings[0].affected_resource == "abc123"
