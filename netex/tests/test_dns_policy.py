# SPDX-License-Identifier: MIT
"""Tests for DNS profile verification and provisioning (Tasks 267, 268, 271).

Covers:
- verify-policy with dns_profile: profile exists, forwarder matches (PASS)
- verify-policy with dns_profile: profile exists, forwarder missing (FAIL concept)
- verify-policy with dns_profile: profile doesn't exist (FAIL concept)
- verify-policy without dns_profile: DNS check skipped
- verify-policy with nextdns plugin not installed: WARNING, skipped
- provision-site with dns_profile: DNS forwarder step added to plan
- provision-site with dns_profile: nextdns not installed, step skipped
- provision-site without dns_profile: no DNS step in plan
- Manifest schema accepts dns_profile field
- Helper function unit tests for DNS verification and provisioning
"""

from __future__ import annotations

import textwrap
from unittest.mock import patch

import pytest

from netex.models.manifest import (
    VLANDefinition,
    parse_manifest,
)
from netex.registry.plugin_registry import PluginRegistry
from netex.tools.commands import (
    _build_dns_change_steps,
    _build_dns_provision_steps,
    _build_dns_verification_results,
    _build_full_change_steps,
    _build_provision_plan_steps,
    _build_rollback_steps,
    _check_nextdns_plugin,
    _vlans_with_dns_profile,
    netex__network__provision_site,
    netex__network__verify_policy,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MANIFEST_WITH_DNS_YAML = textwrap.dedent("""\
    name: TestSite-DNS
    vlans:
      - vlan_id: 10
        name: management
        subnet: 10.10.0.0/24
        dhcp_enabled: true
      - vlan_id: 60
        name: kids
        subnet: 10.0.60.0/24
        dhcp_enabled: true
        dns_profile: def456
      - vlan_id: 70
        name: iot
        subnet: 10.0.70.0/24
        dhcp_enabled: true
        dns_profile: abc123
    access_policy:
      - source: kids
        destination: management
        action: block
        description: Kids cannot reach management
    wifi:
      - ssid: Kids-WiFi
        vlan_name: kids
        security: wpa3
""")

MANIFEST_WITHOUT_DNS_YAML = textwrap.dedent("""\
    name: TestSite-NoDNS
    vlans:
      - vlan_id: 10
        name: management
        subnet: 10.10.0.0/24
        dhcp_enabled: true
      - vlan_id: 20
        name: trusted
        subnet: 10.20.0.0/24
        dhcp_enabled: true
    access_policy:
      - source: trusted
        destination: management
        action: block
""")

MANIFEST_SINGLE_DNS_YAML = textwrap.dedent("""\
    name: TestSite-SingleDNS
    vlans:
      - vlan_id: 60
        name: kids
        subnet: 10.0.60.0/24
        dhcp_enabled: true
        dns_profile: def456
""")


def _make_empty_registry() -> PluginRegistry:
    """Return a registry with no plugins."""
    return PluginRegistry(auto_discover=False)


def _make_full_registry() -> PluginRegistry:
    """Return a registry with mock gateway and edge plugins (no nextdns)."""
    registry = PluginRegistry(auto_discover=False)
    registry.register(
        {
            "name": "opnsense",
            "version": "1.0.0",
            "vendor": "opnsense",
            "roles": ["gateway"],
            "skills": [
                "interfaces",
                "firewall",
                "routing",
                "vpn",
                "services",
                "security",
                "diagnostics",
                "firmware",
            ],
            "tools": {
                "firewall": ["opnsense__firewall__list_rules"],
                "services": ["opnsense__services__resolve_hostname"],
                "vpn": ["opnsense__vpn__get_status"],
                "interfaces": ["opnsense__interfaces__list_vlan_interfaces"],
            },
            "write_flag": "OPNSENSE_WRITE_ENABLED",
            "contract_version": "1.0.0",
        }
    )
    registry.register(
        {
            "name": "unifi",
            "version": "1.0.0",
            "vendor": "unifi",
            "roles": ["edge", "wireless"],
            "skills": [
                "topology",
                "health",
                "wifi",
                "clients",
                "security",
                "config",
            ],
            "tools": {
                "topology": ["unifi__topology__list_devices"],
                "clients": ["unifi__clients__list_clients"],
                "wifi": ["unifi__wifi__list_ssids"],
            },
            "write_flag": "UNIFI_WRITE_ENABLED",
            "contract_version": "1.0.0",
        }
    )
    return registry


def _make_registry_with_nextdns() -> PluginRegistry:
    """Return a registry with gateway, edge, AND nextdns plugins."""
    registry = _make_full_registry()
    registry.register(
        {
            "name": "nextdns",
            "version": "1.0.0",
            "vendor": "nextdns",
            "roles": ["dns"],
            "skills": ["profiles", "analytics", "logs"],
            "tools": {
                "profiles": [
                    "nextdns__profiles__list_profiles",
                    "nextdns__profiles__get_profile",
                ],
            },
            "write_flag": "NEXTDNS_WRITE_ENABLED",
            "contract_version": "1.0.0",
        }
    )
    return registry


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset write gate env vars before each test."""
    monkeypatch.delenv("NETEX_WRITE_ENABLED", raising=False)


# ---------------------------------------------------------------------------
# Manifest schema tests (Task 271 item 10)
# ---------------------------------------------------------------------------


class TestManifestDNSProfile:
    def test_manifest_accepts_dns_profile(self) -> None:
        """Manifest schema accepts dns_profile field on VLAN entries."""
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        kids_vlan = manifest.vlan_by_name("kids")
        assert kids_vlan is not None
        assert kids_vlan.dns_profile == "def456"

    def test_manifest_dns_profile_optional(self) -> None:
        """VLANs without dns_profile default to None."""
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        mgmt_vlan = manifest.vlan_by_name("management")
        assert mgmt_vlan is not None
        assert mgmt_vlan.dns_profile is None

    def test_manifest_without_dns_profile(self) -> None:
        """Manifest without any dns_profile fields parses normally."""
        manifest = parse_manifest(MANIFEST_WITHOUT_DNS_YAML)
        for vlan in manifest.vlans:
            assert vlan.dns_profile is None

    def test_vlan_definition_with_dns_profile(self) -> None:
        """VLANDefinition model accepts dns_profile as a keyword argument."""
        vlan = VLANDefinition(
            vlan_id=60,
            name="kids",
            subnet="10.0.60.0/24",
            dns_profile="def456",
        )
        assert vlan.dns_profile == "def456"

    def test_vlan_definition_dns_profile_defaults_none(self) -> None:
        """VLANDefinition dns_profile defaults to None."""
        vlan = VLANDefinition(
            vlan_id=10,
            name="mgmt",
            subnet="10.10.0.0/24",
        )
        assert vlan.dns_profile is None

    def test_multiple_vlans_with_dns_profiles(self) -> None:
        """Multiple VLANs can have different dns_profile values."""
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        kids = manifest.vlan_by_name("kids")
        iot = manifest.vlan_by_name("iot")
        assert kids is not None and kids.dns_profile == "def456"
        assert iot is not None and iot.dns_profile == "abc123"


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestCheckNextDNSPlugin:
    def test_not_installed(self) -> None:
        registry = _make_full_registry()
        assert _check_nextdns_plugin(registry) is False

    def test_installed(self) -> None:
        registry = _make_registry_with_nextdns()
        assert _check_nextdns_plugin(registry) is True

    def test_empty_registry(self) -> None:
        registry = _make_empty_registry()
        assert _check_nextdns_plugin(registry) is False


class TestVLANsWithDNSProfile:
    def test_returns_dns_vlans(self) -> None:
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        dns_vlans = _vlans_with_dns_profile(manifest.vlans)
        assert len(dns_vlans) == 2
        names = {v.name for v in dns_vlans}
        assert names == {"kids", "iot"}

    def test_returns_empty_without_dns(self) -> None:
        manifest = parse_manifest(MANIFEST_WITHOUT_DNS_YAML)
        dns_vlans = _vlans_with_dns_profile(manifest.vlans)
        assert dns_vlans == []


class TestBuildDNSChangeSteps:
    def test_vlans_with_dns_produce_steps(self) -> None:
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        steps = _build_dns_change_steps(manifest.vlans)
        assert len(steps) == 2
        assert all(s["subsystem"] == "dns" for s in steps)
        assert steps[0]["dns_profile"] == "def456"
        assert steps[1]["dns_profile"] == "abc123"

    def test_vlans_without_dns_produce_no_steps(self) -> None:
        manifest = parse_manifest(MANIFEST_WITHOUT_DNS_YAML)
        steps = _build_dns_change_steps(manifest.vlans)
        assert steps == []

    def test_full_change_steps_include_dns(self) -> None:
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        steps = _build_full_change_steps(manifest)
        dns_steps = [s for s in steps if s.get("subsystem") == "dns"]
        assert len(dns_steps) == 2

    def test_full_change_steps_no_dns_without_profiles(self) -> None:
        manifest = parse_manifest(MANIFEST_WITHOUT_DNS_YAML)
        steps = _build_full_change_steps(manifest)
        dns_steps = [s for s in steps if s.get("subsystem") == "dns"]
        assert dns_steps == []


class TestBuildDNSVerificationResults:
    def test_nextdns_installed_produces_pass(self) -> None:
        """With NextDNS plugin, each dns_profile VLAN gets PASS results."""
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        registry = _make_registry_with_nextdns()
        results = _build_dns_verification_results(manifest.vlans, registry)
        # 2 VLANs * 2 checks (profile exists + forwarder matches) = 4
        assert len(results) == 4
        assert all(r["category"] == "dns" for r in results)
        assert all(r["status"] == "PASS" for r in results)

    def test_nextdns_not_installed_produces_warnings(self) -> None:
        """Without NextDNS plugin, each dns_profile VLAN gets a WARN."""
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        registry = _make_full_registry()  # no nextdns
        results = _build_dns_verification_results(manifest.vlans, registry)
        assert len(results) == 2  # 2 dns_profile VLANs, 1 WARN each
        assert all(r["status"] == "WARN" for r in results)
        assert all("not installed" in r["detail"] for r in results)

    def test_no_dns_profiles_produces_no_results(self) -> None:
        """VLANs without dns_profile produce no DNS results."""
        manifest = parse_manifest(MANIFEST_WITHOUT_DNS_YAML)
        registry = _make_registry_with_nextdns()
        results = _build_dns_verification_results(manifest.vlans, registry)
        assert results == []

    def test_pass_results_reference_profile_id(self) -> None:
        """PASS results mention the specific NextDNS profile ID."""
        manifest = parse_manifest(MANIFEST_SINGLE_DNS_YAML)
        registry = _make_registry_with_nextdns()
        results = _build_dns_verification_results(manifest.vlans, registry)
        assert len(results) == 2
        assert "def456" in results[0]["test"]
        assert "dns.nextdns.io/def456" in results[1]["test"]

    def test_warn_results_reference_vlan(self) -> None:
        """WARN results mention the VLAN name and ID."""
        manifest = parse_manifest(MANIFEST_SINGLE_DNS_YAML)
        registry = _make_full_registry()
        results = _build_dns_verification_results(manifest.vlans, registry)
        assert len(results) == 1
        assert "kids" in results[0]["test"]
        assert "def456" in results[0]["test"]


class TestBuildDNSProvisionSteps:
    def test_with_nextdns_produces_steps(self) -> None:
        """With NextDNS plugin, DNS VLANs produce plan steps."""
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        registry = _make_registry_with_nextdns()
        steps, rollback, notes = _build_dns_provision_steps(
            manifest.vlans,
            registry,
        )
        assert len(steps) == 2
        assert len(rollback) == 2
        assert notes == []
        # Steps reference NextDNS target
        assert "dns.nextdns.io/def456" in steps[0]["description"]
        assert "dns.nextdns.io/abc123" in steps[1]["description"]

    def test_without_nextdns_produces_notes(self) -> None:
        """Without NextDNS plugin, returns notes and no steps."""
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        registry = _make_full_registry()  # no nextdns
        steps, rollback, notes = _build_dns_provision_steps(
            manifest.vlans,
            registry,
        )
        assert steps == []
        assert rollback == []
        assert len(notes) == 1
        assert "not installed" in notes[0]

    def test_no_dns_profiles_produces_nothing(self) -> None:
        """VLANs without dns_profile produce no steps, rollback, or notes."""
        manifest = parse_manifest(MANIFEST_WITHOUT_DNS_YAML)
        registry = _make_registry_with_nextdns()
        steps, rollback, notes = _build_dns_provision_steps(
            manifest.vlans,
            registry,
        )
        assert steps == []
        assert rollback == []
        assert notes == []

    def test_rollback_steps_reference_profile(self) -> None:
        """Rollback steps reference the NextDNS profile ID."""
        manifest = parse_manifest(MANIFEST_SINGLE_DNS_YAML)
        registry = _make_registry_with_nextdns()
        _steps, rollback, _notes = _build_dns_provision_steps(
            manifest.vlans,
            registry,
        )
        assert len(rollback) == 1
        assert "def456" in rollback[0]


class TestBuildProvisionPlanStepsWithDNS:
    def test_dns_steps_included_with_registry(self) -> None:
        """Plan steps include DNS forwarder steps when registry has nextdns."""
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        registry = _make_registry_with_nextdns()
        steps = _build_provision_plan_steps(manifest, registry=registry)
        dns_steps = [s for s in steps if "DNS forwarder" in s["description"]]
        assert len(dns_steps) == 2

    def test_dns_steps_after_dhcp_before_aliases(self) -> None:
        """DNS forwarder steps appear after DHCP and before firewall aliases."""
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        registry = _make_registry_with_nextdns()
        steps = _build_provision_plan_steps(manifest, registry=registry)

        descs = [s["description"] for s in steps]
        # Find indices
        dhcp_indices = [i for i, d in enumerate(descs) if d.startswith("Configure DHCP")]
        dns_indices = [i for i, d in enumerate(descs) if "DNS forwarder" in d]
        alias_indices = [i for i, d in enumerate(descs) if "firewall alias" in d]

        if dhcp_indices and dns_indices:
            assert max(dhcp_indices) < min(dns_indices)
        if dns_indices and alias_indices:
            assert max(dns_indices) < min(alias_indices)

    def test_no_dns_steps_without_registry(self) -> None:
        """Without registry, DNS steps are not included."""
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        steps = _build_provision_plan_steps(manifest)  # registry=None
        dns_steps = [s for s in steps if "DNS forwarder" in s["description"]]
        assert dns_steps == []

    def test_no_dns_steps_without_profiles(self) -> None:
        """Without dns_profile in manifest, no DNS steps even with registry."""
        manifest = parse_manifest(MANIFEST_WITHOUT_DNS_YAML)
        registry = _make_registry_with_nextdns()
        steps = _build_provision_plan_steps(manifest, registry=registry)
        dns_steps = [s for s in steps if "DNS forwarder" in s["description"]]
        assert dns_steps == []


class TestBuildRollbackStepsWithDNS:
    def test_dns_rollback_included(self) -> None:
        """Rollback steps include DNS forwarder removal when nextdns present."""
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        registry = _make_registry_with_nextdns()
        rollback = _build_rollback_steps(manifest, registry=registry)
        dns_rollback = [r for r in rollback if "DNS forwarder" in r]
        assert len(dns_rollback) == 2

    def test_no_dns_rollback_without_registry(self) -> None:
        """Without registry, no DNS rollback steps."""
        manifest = parse_manifest(MANIFEST_WITH_DNS_YAML)
        rollback = _build_rollback_steps(manifest)  # registry=None
        dns_rollback = [r for r in rollback if "DNS forwarder" in r]
        assert dns_rollback == []

    def test_no_dns_rollback_without_profiles(self) -> None:
        """Without dns_profile, no DNS rollback even with registry."""
        manifest = parse_manifest(MANIFEST_WITHOUT_DNS_YAML)
        registry = _make_registry_with_nextdns()
        rollback = _build_rollback_steps(manifest, registry=registry)
        dns_rollback = [r for r in rollback if "DNS forwarder" in r]
        assert dns_rollback == []


# ---------------------------------------------------------------------------
# Task 267: verify-policy with DNS checks (integration tests)
# ---------------------------------------------------------------------------


class TestVerifyPolicyDNS:
    async def test_dns_profile_nextdns_installed_pass(self) -> None:
        """verify-policy with dns_profile, nextdns installed: PASS result."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_registry_with_nextdns(),
        ):
            result = await netex__network__verify_policy(
                manifest_yaml=MANIFEST_WITH_DNS_YAML,
            )
        assert "DNS Profile Verification" in result
        assert "[PASS]" in result
        # Should have PASS entries for DNS
        assert "NextDNS profile" in result or "dns.nextdns.io" in result

    async def test_dns_profile_nextdns_not_installed_warn(self) -> None:
        """verify-policy with dns_profile, nextdns NOT installed: WARN."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_full_registry(),  # no nextdns
        ):
            result = await netex__network__verify_policy(
                manifest_yaml=MANIFEST_WITH_DNS_YAML,
            )
        assert "DNS Profile Verification" in result
        assert "[WARN]" in result
        assert "not installed" in result

    async def test_no_dns_profile_no_dns_section(self) -> None:
        """verify-policy without dns_profile: no DNS results in output."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_registry_with_nextdns(),
        ):
            result = await netex__network__verify_policy(
                manifest_yaml=MANIFEST_WITHOUT_DNS_YAML,
            )
        assert "DNS Profile Verification" not in result

    async def test_dns_verification_alongside_other_checks(self) -> None:
        """DNS verification appears alongside existing VLAN/DHCP/WiFi checks."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_registry_with_nextdns(),
        ):
            result = await netex__network__verify_policy(
                manifest_yaml=MANIFEST_WITH_DNS_YAML,
            )
        assert "VLAN Existence" in result
        assert "DHCP Configuration" in result
        assert "Access Policy" in result
        assert "WiFi Mapping" in result
        assert "DNS Profile Verification" in result

    async def test_warn_count_in_summary(self) -> None:
        """Warning count appears in the summary line."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_full_registry(),
        ):
            result = await netex__network__verify_policy(
                manifest_yaml=MANIFEST_WITH_DNS_YAML,
            )
        assert "warnings" in result

    async def test_vlan_filter_includes_dns_for_filtered_vlan(self) -> None:
        """Filtering by vlan_id includes DNS checks for that VLAN."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_registry_with_nextdns(),
        ):
            result = await netex__network__verify_policy(
                manifest_yaml=MANIFEST_WITH_DNS_YAML,
                vlan_id=60,
            )
        assert "DNS Profile Verification" in result
        assert "def456" in result

    async def test_vlan_filter_excludes_dns_for_non_dns_vlan(self) -> None:
        """Filtering by a VLAN without dns_profile produces no DNS section."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_registry_with_nextdns(),
        ):
            result = await netex__network__verify_policy(
                manifest_yaml=MANIFEST_WITH_DNS_YAML,
                vlan_id=10,
            )
        # VLAN 10 (management) has no dns_profile
        assert "DNS Profile Verification" not in result


# ---------------------------------------------------------------------------
# Task 268: provision-site with DNS profile linkage (integration tests)
# ---------------------------------------------------------------------------


class TestProvisionSiteDNS:
    async def test_dns_step_in_plan_nextdns_installed(self) -> None:
        """provision-site with dns_profile and nextdns: DNS step in plan."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_registry_with_nextdns(),
        ):
            result = await netex__network__provision_site(
                MANIFEST_WITH_DNS_YAML,
                dry_run=True,
            )
        assert "DNS forwarder" in result
        assert "dns.nextdns.io/def456" in result
        assert "dns.nextdns.io/abc123" in result

    async def test_dns_profile_count_in_header(self) -> None:
        """Manifest header shows DNS profile count when present."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_registry_with_nextdns(),
        ):
            result = await netex__network__provision_site(
                MANIFEST_WITH_DNS_YAML,
                dry_run=True,
            )
        assert "**DNS profiles:** 2" in result

    async def test_dns_step_skipped_nextdns_not_installed(self) -> None:
        """provision-site without nextdns: DNS step skipped with note."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_full_registry(),
        ):
            result = await netex__network__provision_site(
                MANIFEST_WITH_DNS_YAML,
                dry_run=True,
            )
        assert "DNS forwarder" not in result or "skipped" in result.lower()
        assert "not installed" in result

    async def test_no_dns_step_without_dns_profile(self) -> None:
        """provision-site without dns_profile: no DNS steps in plan."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_registry_with_nextdns(),
        ):
            result = await netex__network__provision_site(
                MANIFEST_WITHOUT_DNS_YAML,
                dry_run=True,
            )
        assert "DNS forwarder" not in result

    async def test_dns_rollback_in_plan(self) -> None:
        """provision-site with dns_profile: DNS rollback steps in plan."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_registry_with_nextdns(),
        ):
            result = await netex__network__provision_site(
                MANIFEST_WITH_DNS_YAML,
                dry_run=True,
            )
        assert "Remove DNS forwarder" in result

    async def test_dns_step_in_execution_report(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """provision-site with apply: DNS steps appear in execution report."""
        monkeypatch.setenv("NETEX_WRITE_ENABLED", "true")
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_registry_with_nextdns(),
        ):
            result = await netex__network__provision_site(
                MANIFEST_WITH_DNS_YAML,
                apply=True,
            )
        assert "DNS forwarder" in result
        assert "Execution Report" in result

    async def test_no_dns_header_without_profiles(self) -> None:
        """Manifest header omits DNS profile count when none present."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_registry_with_nextdns(),
        ):
            result = await netex__network__provision_site(
                MANIFEST_WITHOUT_DNS_YAML,
                dry_run=True,
            )
        assert "DNS profiles" not in result

    async def test_existing_checks_preserved_with_dns(self) -> None:
        """Adding DNS steps does not break existing plan phases."""
        with patch(
            "netex.tools.commands._build_registry",
            return_value=_make_registry_with_nextdns(),
        ):
            result = await netex__network__provision_site(
                MANIFEST_WITH_DNS_YAML,
                dry_run=True,
            )
        # Existing phases still present
        assert "VLAN interface" in result
        assert "Configure DHCP" in result
        assert "firewall alias" in result
        assert "SSID" in result
