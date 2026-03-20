# SPDX-License-Identifier: MIT
"""Tests for netex umbrella command MCP tools (Tasks 139-142).

Covers:
- netex network provision-site (Task 139)
- netex verify-policy (Task 140)
- netex vlan provision-batch (Task 141)
- netex dns trace, vpn status, policy sync (Task 142)

At least 40 tests across all commands.
"""

from __future__ import annotations

import textwrap
from unittest.mock import patch

import pytest

from netex.tools.commands import (
    _build_full_change_steps,
    _build_provision_plan_steps,
    _build_rollback_steps,
    _build_vlan_change_steps,
    _format_risk_assessment,
    netex__dns__trace,
    netex__network__provision_site,
    netex__network__verify_policy,
    netex__policy__sync,
    netex__vlan__provision_batch,
    netex__vpn__status,
)
from netex.models.manifest import (
    AccessPolicyRule,
    PolicyAction,
    PortProfileDefinition,
    SiteManifest,
    VLANDefinition,
    WiFiDefinition,
    WiFiSecurity,
    parse_manifest,
)
from netex.registry.plugin_registry import PluginRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_MANIFEST_YAML = textwrap.dedent("""\
    vlans:
      - vlan_id: 10
        name: management
        subnet: 10.10.0.0/24
""")

FULL_MANIFEST_YAML = textwrap.dedent("""\
    name: TestSite
    description: Test site
    vlans:
      - vlan_id: 10
        name: management
        subnet: 10.10.0.0/24
        dhcp_enabled: true
        dhcp_range_start: 10.10.0.100
        dhcp_range_end: 10.10.0.254
        purpose: mgmt
      - vlan_id: 20
        name: trusted
        subnet: 10.20.0.0/24
        dhcp_enabled: true
        purpose: general
      - vlan_id: 50
        name: guest
        subnet: 10.50.0.0/24
        dhcp_enabled: true
        purpose: guest
    access_policy:
      - source: trusted
        destination: wan
        action: allow
        description: Trusted can reach internet
      - source: guest
        destination: trusted
        action: block
        description: Guest cannot reach trusted
    wifi:
      - ssid: Home-WiFi
        vlan_name: trusted
        security: wpa3
      - ssid: Guest-WiFi
        vlan_name: guest
        security: wpa2-wpa3
    port_profiles:
      - name: Trunk-All
        tagged_vlans:
          - management
          - trusted
          - guest
""")


def _make_empty_registry() -> PluginRegistry:
    """Return a registry with no plugins (auto_discover=False)."""
    return PluginRegistry(auto_discover=False)


def _make_full_registry() -> PluginRegistry:
    """Return a registry with mock gateway and edge plugins."""
    registry = PluginRegistry(auto_discover=False)
    registry.register({
        "name": "opnsense",
        "version": "1.0.0",
        "vendor": "opnsense",
        "roles": ["gateway"],
        "skills": [
            "interfaces", "firewall", "routing", "vpn",
            "services", "security", "diagnostics", "firmware",
        ],
        "tools": {
            "firewall": ["opnsense__firewall__list_rules"],
            "services": ["opnsense__services__resolve_hostname"],
            "vpn": ["opnsense__vpn__get_status"],
            "interfaces": ["opnsense__interfaces__list_vlan_interfaces"],
            "security": ["opnsense__security__list_alerts"],
            "diagnostics": ["opnsense__diagnostics__run_traceroute"],
            "firmware": ["opnsense__firmware__get_status"],
        },
        "write_flag": "OPNSENSE_WRITE_ENABLED",
        "contract_version": "1.0.0",
    })
    registry.register({
        "name": "unifi",
        "version": "1.0.0",
        "vendor": "unifi",
        "roles": ["edge", "wireless"],
        "skills": [
            "topology", "health", "wifi", "clients",
            "security", "config",
        ],
        "tools": {
            "topology": ["unifi__topology__list_devices"],
            "clients": ["unifi__clients__list_clients"],
            "wifi": ["unifi__wifi__list_ssids"],
            "health": ["unifi__health__get_status"],
        },
        "write_flag": "UNIFI_WRITE_ENABLED",
        "contract_version": "1.0.0",
    })
    return registry


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset write gate env vars before each test."""
    monkeypatch.delenv("NETEX_WRITE_ENABLED", raising=False)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestBuildVLANChangeSteps:
    def test_single_vlan(self) -> None:
        vlans = [VLANDefinition(vlan_id=10, name="mgmt", subnet="10.10.0.0/24")]
        steps = _build_vlan_change_steps(vlans)
        # 1 vlan step + 1 dhcp step (dhcp_enabled=True by default)
        assert len(steps) == 2
        assert steps[0]["subsystem"] == "vlan"
        assert steps[0]["action"] == "add"
        assert steps[1]["subsystem"] == "dhcp"

    def test_vlan_without_dhcp(self) -> None:
        vlans = [VLANDefinition(
            vlan_id=10, name="mgmt", subnet="10.10.0.0/24", dhcp_enabled=False,
        )]
        steps = _build_vlan_change_steps(vlans)
        assert len(steps) == 1
        assert steps[0]["subsystem"] == "vlan"

    def test_multiple_vlans(self) -> None:
        vlans = [
            VLANDefinition(vlan_id=10, name="mgmt", subnet="10.10.0.0/24"),
            VLANDefinition(vlan_id=20, name="trusted", subnet="10.20.0.0/24"),
        ]
        steps = _build_vlan_change_steps(vlans)
        # 2 vlans * 2 (vlan + dhcp) = 4
        assert len(steps) == 4


class TestBuildProvisionPlanSteps:
    def test_minimal_manifest(self) -> None:
        manifest = parse_manifest(MINIMAL_MANIFEST_YAML)
        steps = _build_provision_plan_steps(manifest)
        # 1 gateway interface + 1 DHCP + 1 alias + 1 edge network = 4
        assert len(steps) == 4
        assert steps[0]["system"] == "gateway"
        assert "VLAN interface" in steps[0]["description"]

    def test_full_manifest_step_order(self) -> None:
        manifest = parse_manifest(FULL_MANIFEST_YAML)
        steps = _build_provision_plan_steps(manifest)

        # Check that gateway steps come before edge steps
        gateway_indices = [i for i, s in enumerate(steps) if s["system"] == "gateway"]
        edge_indices = [i for i, s in enumerate(steps) if s["system"] == "edge"]

        if gateway_indices and edge_indices:
            assert max(gateway_indices) < min(edge_indices)

    def test_full_manifest_step_count(self) -> None:
        manifest = parse_manifest(FULL_MANIFEST_YAML)
        steps = _build_provision_plan_steps(manifest)

        # 3 gw interfaces + 3 DHCP + 3 aliases + 2 rules
        # + 3 edge networks + 2 WiFi + 1 port profile = 17
        assert len(steps) == 17


class TestBuildRollbackSteps:
    def test_rollback_is_reversed(self) -> None:
        manifest = parse_manifest(FULL_MANIFEST_YAML)
        rollback = _build_rollback_steps(manifest)
        assert len(rollback) > 0
        # Port profiles should be first in rollback (last to execute)
        assert "port profile" in rollback[0].lower()
        # VLAN interfaces should be last in rollback (first to execute)
        assert "vlan interface" in rollback[-1].lower()


class TestBuildFullChangeSteps:
    def test_includes_vlan_and_firewall_steps(self) -> None:
        manifest = parse_manifest(FULL_MANIFEST_YAML)
        steps = _build_full_change_steps(manifest)
        subsystems = {s["subsystem"] for s in steps}
        assert "vlan" in subsystems
        assert "firewall" in subsystems
        assert "wifi" in subsystems


class TestFormatRiskAssessment:
    def test_low_risk(self) -> None:
        assessment = {
            "risk_tier": "LOW",
            "description": "No intersection with session path.",
        }
        result = _format_risk_assessment(assessment)
        assert "LOW" in result
        assert "No intersection" in result


# ---------------------------------------------------------------------------
# Task 139: provision-site command tests
# ---------------------------------------------------------------------------

class TestProvisionSite:
    async def test_invalid_manifest_returns_error(self) -> None:
        result = await netex__network__provision_site("not: valid: yaml: []")
        assert "validation failed" in result.lower() or "error" in result.lower()

    async def test_dry_run_returns_plan(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__provision_site(
                MINIMAL_MANIFEST_YAML, dry_run=True,
            )
        assert "Dry-run" in result or "dry-run" in result.lower()
        assert "Change Plan" in result

    async def test_dry_run_full_manifest(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__provision_site(
                FULL_MANIFEST_YAML, dry_run=True,
            )
        assert "TestSite" in result
        assert "3" in result  # 3 VLANs

    async def test_no_plugins_returns_error(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_empty_registry()):
            result = await netex__network__provision_site(MINIMAL_MANIFEST_YAML)
        assert "Cannot provision" in result or "No gateway" in result

    async def test_plan_only_without_apply(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__provision_site(MINIMAL_MANIFEST_YAML)
        assert "Plan-only" in result or "Write operations are disabled" in result

    async def test_write_disabled_blocks_execution(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__provision_site(
                MINIMAL_MANIFEST_YAML, apply=True,
            )
        assert "Write operations are disabled" in result

    async def test_apply_with_write_enabled(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NETEX_WRITE_ENABLED", "true")
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__provision_site(
                MINIMAL_MANIFEST_YAML, apply=True,
            )
        assert "Execution Report" in result
        assert "completed" in result.lower()

    async def test_plan_includes_outage_risk(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__provision_site(
                MINIMAL_MANIFEST_YAML, dry_run=True,
            )
        assert "OUTAGE RISK" in result or "outage" in result.lower()

    async def test_plan_includes_rollback(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__provision_site(
                FULL_MANIFEST_YAML, dry_run=True,
            )
        assert "ROLLBACK" in result or "rollback" in result.lower()

    async def test_suggests_verify_policy_after_execution(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NETEX_WRITE_ENABLED", "true")
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__provision_site(
                MINIMAL_MANIFEST_YAML, apply=True,
            )
        assert "verify-policy" in result


# ---------------------------------------------------------------------------
# Task 140: verify-policy command tests
# ---------------------------------------------------------------------------

class TestVerifyPolicy:
    async def test_no_args_returns_error(self) -> None:
        result = await netex__network__verify_policy()
        assert "Error" in result

    async def test_with_manifest(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__verify_policy(
                manifest_yaml=FULL_MANIFEST_YAML,
            )
        assert "Verification Report" in result
        assert "PASS" in result

    async def test_with_vlan_filter(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__verify_policy(
                manifest_yaml=FULL_MANIFEST_YAML,
                vlan_id=10,
            )
        assert "management" in result

    async def test_vlan_not_in_manifest(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__verify_policy(
                manifest_yaml=FULL_MANIFEST_YAML,
                vlan_id=999,
            )
        assert "not found" in result.lower()

    async def test_invalid_manifest(self) -> None:
        result = await netex__network__verify_policy(
            manifest_yaml="bad: [yaml",
        )
        assert "failed" in result.lower() or "error" in result.lower()

    async def test_vlan_only_without_manifest(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__verify_policy(vlan_id=10)
        assert "VLAN 10" in result

    async def test_reports_test_categories(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__verify_policy(
                manifest_yaml=FULL_MANIFEST_YAML,
            )
        assert "VLAN Existence" in result
        assert "DHCP" in result
        assert "Access Policy" in result
        assert "WiFi" in result

    async def test_reports_pass_count(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__network__verify_policy(
                manifest_yaml=FULL_MANIFEST_YAML,
            )
        assert "tests passed" in result


# ---------------------------------------------------------------------------
# Task 141: vlan provision-batch command tests
# ---------------------------------------------------------------------------

class TestVLANProvisionBatch:
    async def test_invalid_manifest(self) -> None:
        result = await netex__vlan__provision_batch("not valid yaml")
        assert "failed" in result.lower()

    async def test_plan_only_mode(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__vlan__provision_batch(MINIMAL_MANIFEST_YAML)
        # Either plan-only message or write disabled
        assert "Plan-only" in result or "Write operations are disabled" in result

    async def test_write_disabled(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__vlan__provision_batch(
                MINIMAL_MANIFEST_YAML, apply=True,
            )
        assert "Write operations are disabled" in result

    async def test_apply_with_write_enabled(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NETEX_WRITE_ENABLED", "true")
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__vlan__provision_batch(
                MINIMAL_MANIFEST_YAML, apply=True,
            )
        assert "Execution Report" in result
        assert "completed" in result.lower()

    async def test_batch_with_multiple_vlans(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NETEX_WRITE_ENABLED", "true")
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__vlan__provision_batch(
                FULL_MANIFEST_YAML, apply=True,
            )
        assert "3 VLANs" in result
        assert "Execution Report" in result

    async def test_plan_includes_risk_assessment(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__vlan__provision_batch(FULL_MANIFEST_YAML)
        assert "OUTAGE RISK" in result or "outage" in result.lower()


# ---------------------------------------------------------------------------
# Task 142: dns trace command tests
# ---------------------------------------------------------------------------

class TestDNSTrace:
    async def test_no_plugins(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_empty_registry()):
            result = await netex__dns__trace("nas.home.lan")
        assert "Cannot trace" in result or "No plugins" in result

    async def test_basic_trace(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__dns__trace("nas.home.lan")
        assert "DNS Trace" in result
        assert "nas.home.lan" in result

    async def test_trace_with_client(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__dns__trace(
                "nas.home.lan", client_mac="aa:bb:cc:dd:ee:ff",
            )
        assert "aa:bb:cc:dd:ee:ff" in result
        assert "Client Context" in result

    async def test_trace_shows_tools(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__dns__trace("example.com")
        assert "Available DNS Tools" in result


# ---------------------------------------------------------------------------
# Task 142: vpn status command tests
# ---------------------------------------------------------------------------

class TestVPNStatus:
    async def test_no_plugins(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_empty_registry()):
            result = await netex__vpn__status()
        assert "No VPN tools" in result

    async def test_basic_status(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__vpn__status()
        assert "VPN Status" in result

    async def test_filtered_by_tunnel(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__vpn__status(tunnel_name="wg0")
        assert "wg0" in result
        assert "Filter" in result

    async def test_cross_layer_correlation(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__vpn__status()
        assert "Cross-Layer" in result


# ---------------------------------------------------------------------------
# Task 142: policy sync command tests
# ---------------------------------------------------------------------------

class TestPolicySync:
    async def test_no_plugins(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_empty_registry()):
            result = await netex__policy__sync()
        assert "Cannot sync" in result

    async def test_dry_run_default(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__policy__sync()
        assert "Dry-run" in result or "dry-run" in result.lower()
        assert "Policy Sync" in result

    async def test_reports_check_domains(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__policy__sync()
        assert "VLAN" in result
        assert "DNS" in result
        assert "Firewall" in result

    async def test_non_dry_run_write_disabled(self) -> None:
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__policy__sync(dry_run=False)
        assert "Write operations are disabled" in result

    async def test_non_dry_run_no_apply(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NETEX_WRITE_ENABLED", "true")
        with patch("netex.tools.commands._build_registry", return_value=_make_full_registry()):
            result = await netex__policy__sync(dry_run=False)
        assert "Plan-only" in result
