# SPDX-License-Identifier: MIT
"""Tests for cross-vendor DNS commands (Tasks 263-266).

Covers:
- Task 263: Enhanced ``netex dns trace`` with NextDNS awareness
- Task 264: ``netex dns verify-profiles`` VLAN-to-profile verification
- Task 265: Cross-profile analytics summary
- Task 266: Helper functions (profile ID extraction, ip_in_subnet)

10+ tests across all commands and helper functions.
"""

from __future__ import annotations

from unittest.mock import patch

from netex.registry.plugin_registry import PluginRegistry
from netex.tools.dns_tools import (
    _find_forwarder_for_subnet,
    _is_nextdns_target,
    compute_cross_profile_summary,
    extract_nextdns_profile_id,
    ip_in_subnet,
    netex__dns__get_cross_profile_summary,
    netex__dns__trace_enhanced,
    netex__dns__verify_profiles,
    verify_profiles_with_data,
)

# ---------------------------------------------------------------------------
# Registry fixtures
# ---------------------------------------------------------------------------


def _make_empty_registry() -> PluginRegistry:
    """Return a registry with no plugins (auto_discover=False)."""
    return PluginRegistry(auto_discover=False)


def _make_gateway_only_registry() -> PluginRegistry:
    """Return a registry with only a gateway plugin (no dns)."""
    registry = PluginRegistry(auto_discover=False)
    registry.register(
        {
            "name": "opnsense",
            "version": "1.0.0",
            "vendor": "opnsense",
            "roles": ["gateway"],
            "skills": ["interfaces", "firewall", "services"],
            "tools": {
                "services": ["opnsense__services__get_dns_forwarders"],
            },
            "contract_version": "1.0.0",
        }
    )
    return registry


def _make_dns_only_registry() -> PluginRegistry:
    """Return a registry with only a dns plugin (no gateway)."""
    registry = PluginRegistry(auto_discover=False)
    registry.register(
        {
            "name": "nextdns",
            "version": "0.1.0",
            "vendor": "nextdns",
            "roles": ["dns"],
            "skills": ["profiles", "analytics", "logs"],
            "tools": {
                "profiles": ["nextdns__profiles__list_profiles"],
                "analytics": [
                    "nextdns__analytics__get_status",
                    "nextdns__analytics__get_ips",
                    "nextdns__analytics__get_encryption",
                ],
                "logs": ["nextdns__logs__search"],
            },
            "contract_version": "1.0.0",
        }
    )
    return registry


def _make_full_registry() -> PluginRegistry:
    """Return a registry with gateway, edge, and dns plugins."""
    registry = PluginRegistry(auto_discover=False)
    registry.register(
        {
            "name": "opnsense",
            "version": "1.0.0",
            "vendor": "opnsense",
            "roles": ["gateway"],
            "skills": ["interfaces", "firewall", "services"],
            "tools": {
                "services": ["opnsense__services__get_dns_forwarders"],
                "interfaces": ["opnsense__interfaces__list_vlan_interfaces"],
            },
            "contract_version": "1.0.0",
        }
    )
    registry.register(
        {
            "name": "unifi",
            "version": "1.0.0",
            "vendor": "unifi",
            "roles": ["edge"],
            "skills": ["topology", "clients"],
            "tools": {
                "topology": [
                    "unifi__topology__list_devices",
                    "unifi__topology__get_vlans",
                ],
            },
            "contract_version": "1.0.0",
        }
    )
    registry.register(
        {
            "name": "nextdns",
            "version": "0.1.0",
            "vendor": "nextdns",
            "roles": ["dns"],
            "skills": ["profiles", "analytics", "logs"],
            "tools": {
                "profiles": ["nextdns__profiles__list_profiles"],
                "analytics": [
                    "nextdns__analytics__get_status",
                    "nextdns__analytics__get_ips",
                    "nextdns__analytics__get_encryption",
                ],
                "logs": ["nextdns__logs__search"],
            },
            "contract_version": "1.0.0",
        }
    )
    return registry


# ---------------------------------------------------------------------------
# Test 10: Profile ID extraction (extract_nextdns_profile_id)
# ---------------------------------------------------------------------------


class TestExtractNextDNSProfileId:
    """Test the extract_nextdns_profile_id helper with various URL formats."""

    def test_path_format(self) -> None:
        """dns.nextdns.io/{id} format."""
        assert extract_nextdns_profile_id("dns.nextdns.io/abc123") == "abc123"

    def test_path_format_with_https(self) -> None:
        """https://dns.nextdns.io/{id} format."""
        assert (
            extract_nextdns_profile_id("https://dns.nextdns.io/abc123")
            == "abc123"
        )

    def test_subdomain_format(self) -> None:
        """{id}.dns.nextdns.io (DoH subdomain) format."""
        assert extract_nextdns_profile_id("abc123.dns.nextdns.io") == "abc123"

    def test_path_format_with_alphanumeric(self) -> None:
        """Profile IDs with mixed case and numbers."""
        assert extract_nextdns_profile_id("dns.nextdns.io/XyZ789") == "XyZ789"

    def test_empty_string(self) -> None:
        """Empty string returns None."""
        assert extract_nextdns_profile_id("") is None

    def test_none_input(self) -> None:
        """None input returns None."""
        assert extract_nextdns_profile_id(None) is None  # type: ignore[arg-type]

    def test_non_nextdns_url(self) -> None:
        """Non-NextDNS URL returns None."""
        assert extract_nextdns_profile_id("8.8.8.8") is None

    def test_cloudflare_url(self) -> None:
        """Cloudflare DNS URL returns None."""
        assert extract_nextdns_profile_id("1.1.1.1") is None

    def test_partial_nextdns_no_id(self) -> None:
        """Bare dns.nextdns.io without a profile ID."""
        # This should not match since there is no profile ID
        result = extract_nextdns_profile_id("dns.nextdns.io/")
        assert result is None or result == ""

    def test_ip_address_format(self) -> None:
        """Plain IP address returns None."""
        assert extract_nextdns_profile_id("9.9.9.9") is None


# ---------------------------------------------------------------------------
# Test: ip_in_subnet helper
# ---------------------------------------------------------------------------


class TestIpInSubnet:
    def test_ip_in_subnet(self) -> None:
        assert ip_in_subnet("10.0.60.15", "10.0.60.0/24") is True

    def test_ip_not_in_subnet(self) -> None:
        assert ip_in_subnet("10.0.70.15", "10.0.60.0/24") is False

    def test_ip_at_network_boundary(self) -> None:
        assert ip_in_subnet("10.0.60.0", "10.0.60.0/24") is True

    def test_ip_at_broadcast(self) -> None:
        assert ip_in_subnet("10.0.60.255", "10.0.60.0/24") is True

    def test_invalid_ip(self) -> None:
        assert ip_in_subnet("not-an-ip", "10.0.60.0/24") is False

    def test_invalid_subnet(self) -> None:
        assert ip_in_subnet("10.0.60.15", "invalid") is False

    def test_empty_strings(self) -> None:
        assert ip_in_subnet("", "") is False


# ---------------------------------------------------------------------------
# Test: _is_nextdns_target helper
# ---------------------------------------------------------------------------


class TestIsNextDNSTarget:
    def test_nextdns_path(self) -> None:
        assert _is_nextdns_target("dns.nextdns.io/abc123") is True

    def test_nextdns_subdomain(self) -> None:
        assert _is_nextdns_target("abc123.dns.nextdns.io") is True

    def test_google_dns(self) -> None:
        assert _is_nextdns_target("8.8.8.8") is False

    def test_empty(self) -> None:
        assert _is_nextdns_target("") is False


# ---------------------------------------------------------------------------
# Test 1: DNS trace -- NextDNS forwarder detected
# ---------------------------------------------------------------------------


class TestDNSTraceNextDNSForwarder:
    async def test_trace_with_all_plugins(self) -> None:
        """With gateway and dns plugins, trace includes both layers."""
        with patch(
            "netex.tools.dns_tools._build_registry",
            return_value=_make_full_registry(),
        ):
            result = await netex__dns__trace_enhanced("example.com")

        assert result["domain"] == "example.com"
        assert len(result["trace"]) == 3  # source + forwarder + nextdns
        assert result["plugins_available"]["gateway"] is True
        assert result["plugins_available"]["dns"] is True

        # Check forwarder step
        forwarder_step = result["trace"][1]
        assert forwarder_step["step"] == "forwarder_lookup"
        assert forwarder_step["status"] == "available"
        assert forwarder_step["gateway_plugin"] == "opnsense"

        # Check nextdns step
        nextdns_step = result["trace"][2]
        assert nextdns_step["step"] == "nextdns_resolution"
        assert nextdns_step["status"] == "available"
        assert nextdns_step["dns_plugin"] == "nextdns"

    async def test_trace_with_source_vlan(self) -> None:
        """Source VLAN is included in the trace."""
        with patch(
            "netex.tools.dns_tools._build_registry",
            return_value=_make_full_registry(),
        ):
            result = await netex__dns__trace_enhanced(
                "example.com",
                source_vlan="kids",
            )

        source_step = result["trace"][0]
        assert source_step["vlan"] == "kids"

    async def test_trace_with_source_ip(self) -> None:
        """Source IP is included in the trace."""
        with patch(
            "netex.tools.dns_tools._build_registry",
            return_value=_make_full_registry(),
        ):
            result = await netex__dns__trace_enhanced(
                "example.com",
                source_ip="10.0.60.15",
            )

        source_step = result["trace"][0]
        assert source_step["ip"] == "10.0.60.15"


# ---------------------------------------------------------------------------
# Test 2: DNS trace -- non-NextDNS forwarder (gateway only)
# ---------------------------------------------------------------------------


class TestDNSTraceNonNextDNS:
    async def test_trace_gateway_only(self) -> None:
        """With only gateway plugin, trace shows forwarder but no NextDNS."""
        with patch(
            "netex.tools.dns_tools._build_registry",
            return_value=_make_gateway_only_registry(),
        ):
            result = await netex__dns__trace_enhanced("example.com")

        assert result["plugins_available"]["gateway"] is True
        assert result["plugins_available"]["dns"] is False

        # Forwarder step should be available
        forwarder_step = result["trace"][1]
        assert forwarder_step["status"] == "available"

        # NextDNS step should be skipped
        nextdns_step = result["trace"][2]
        assert nextdns_step["status"] == "skipped"
        assert "Install the nextdns plugin" in nextdns_step["note"]


# ---------------------------------------------------------------------------
# Test 3: DNS trace -- nextdns plugin not installed
# ---------------------------------------------------------------------------


class TestDNSTraceNoDNSPlugin:
    async def test_trace_no_dns_plugin(self) -> None:
        """Without dns plugin, NextDNS step is gracefully skipped."""
        with patch(
            "netex.tools.dns_tools._build_registry",
            return_value=_make_gateway_only_registry(),
        ):
            result = await netex__dns__trace_enhanced("example.com")

        assert result["plugins_available"]["dns"] is False
        nextdns_step = result["trace"][2]
        assert nextdns_step["status"] == "skipped"

    async def test_trace_no_plugins_at_all(self) -> None:
        """Without any plugins, all steps are skipped."""
        with patch(
            "netex.tools.dns_tools._build_registry",
            return_value=_make_empty_registry(),
        ):
            result = await netex__dns__trace_enhanced("example.com")

        assert result["plugins_available"]["gateway"] is False
        assert result["plugins_available"]["dns"] is False
        assert "no vendor plugins installed" in result["summary"]


# ---------------------------------------------------------------------------
# Test 4: Verify profiles -- all matched (verified)
# ---------------------------------------------------------------------------


class TestVerifyProfilesAllMatched:
    async def test_all_vlans_verified(self) -> None:
        """3 VLANs all with matching forwarders and analytics traffic."""
        vlans = [
            {"name": "Trusted", "vlan_id": 10, "subnet": "10.0.10.0/24"},
            {"name": "Kids", "vlan_id": 60, "subnet": "10.0.60.0/24"},
            {"name": "IoT", "vlan_id": 50, "subnet": "10.0.50.0/24"},
        ]
        forwarders = [
            {
                "domain": "",
                "server": "dns.nextdns.io/abc123",
                "description": "10.0.10.0/24 trusted",
            },
            {
                "domain": "",
                "server": "dns.nextdns.io/def456",
                "description": "10.0.60.0/24 kids",
            },
            {
                "domain": "",
                "server": "dns.nextdns.io/ghi789",
                "description": "10.0.50.0/24 iot",
            },
        ]
        profiles = [
            {"id": "abc123", "name": "Trusted"},
            {"id": "def456", "name": "Kids"},
            {"id": "ghi789", "name": "IoT"},
        ]
        analytics_ips = {
            "abc123": [{"ip": "10.0.10.15", "queries": 500}],
            "def456": [{"ip": "10.0.60.42", "queries": 200}],
            "ghi789": [{"ip": "10.0.50.8", "queries": 300}],
        }

        result = await verify_profiles_with_data(
            vlans, forwarders, profiles, analytics_ips
        )

        assert result["vlans_checked"] == 3
        assert result["verified"] == 3
        assert result["mismatches"] == []
        assert all(
            r["status"] == "verified" for r in result["results"]
        )


# ---------------------------------------------------------------------------
# Test 5: Verify profiles -- missing forwarder
# ---------------------------------------------------------------------------


class TestVerifyProfilesMissingForwarder:
    async def test_one_vlan_no_forwarder(self) -> None:
        """One VLAN has no forwarder configured -> no_forwarder status."""
        vlans = [
            {"name": "Trusted", "vlan_id": 10, "subnet": "10.0.10.0/24"},
            {"name": "Guest", "vlan_id": 30, "subnet": "10.0.30.0/24"},
        ]
        # Only one forwarder for a specific domain (not catch-all),
        # so Guest has no matching forwarder.
        forwarders = [
            {
                "domain": "trusted.local",
                "server": "dns.nextdns.io/abc123",
                "description": "10.0.10.0/24 trusted",
            },
        ]
        profiles = [{"id": "abc123", "name": "Trusted"}]
        analytics_ips = {
            "abc123": [{"ip": "10.0.10.15", "queries": 500}],
        }

        result = await verify_profiles_with_data(
            vlans, forwarders, profiles, analytics_ips
        )

        assert result["vlans_checked"] == 2
        # Trusted matches by description, Guest has no match
        assert result["verified"] == 1
        assert len(result["mismatches"]) == 1
        assert "Guest" in result["mismatches"][0]
        assert "no DNS forwarder" in result["mismatches"][0]

        # Check individual results
        guest_result = next(
            r for r in result["results"] if r["vlan_name"] == "Guest"
        )
        assert guest_result["status"] == "no_forwarder"


# ---------------------------------------------------------------------------
# Test 6: Verify profiles -- no traffic
# ---------------------------------------------------------------------------


class TestVerifyProfilesNoTraffic:
    async def test_forwarder_configured_but_no_traffic(self) -> None:
        """Forwarder configured but no analytics traffic from subnet."""
        vlans = [
            {"name": "Kids", "vlan_id": 60, "subnet": "10.0.60.0/24"},
        ]
        forwarders = [
            {
                "domain": "",
                "server": "dns.nextdns.io/def456",
                "description": "10.0.60.0/24 kids",
            },
        ]
        profiles = [{"id": "def456", "name": "Kids"}]
        # Analytics shows IPs from a DIFFERENT subnet
        analytics_ips = {
            "def456": [{"ip": "192.168.1.50", "queries": 100}],
        }

        result = await verify_profiles_with_data(
            vlans, forwarders, profiles, analytics_ips
        )

        assert result["vlans_checked"] == 1
        assert result["verified"] == 0
        assert len(result["mismatches"]) == 1
        assert "no traffic" in result["mismatches"][0]

        kids_result = result["results"][0]
        assert kids_result["status"] == "no_traffic"
        assert kids_result["forwarder_configured"] is True
        assert kids_result["nextdns_profile"] == "def456"


# ---------------------------------------------------------------------------
# Test 7: Verify profiles -- mixed results
# ---------------------------------------------------------------------------


class TestVerifyProfilesMixed:
    async def test_mixed_verified_and_mismatched(self) -> None:
        """Mix of verified, no_forwarder, no_traffic, and non_nextdns."""
        vlans = [
            {"name": "Trusted", "vlan_id": 10, "subnet": "10.0.10.0/24"},
            {"name": "Kids", "vlan_id": 60, "subnet": "10.0.60.0/24"},
            {"name": "Guest", "vlan_id": 30, "subnet": "10.0.30.0/24"},
            {"name": "IoT", "vlan_id": 50, "subnet": "10.0.50.0/24"},
        ]
        # Use non-catch-all domains so Guest gets no match.
        # Each forwarder is specific to a subnet via its description.
        forwarders = [
            {
                "domain": "trusted.zone",
                "server": "dns.nextdns.io/abc123",
                "description": "10.0.10.0/24 trusted",
            },
            {
                "domain": "kids.zone",
                "server": "dns.nextdns.io/def456",
                "description": "10.0.60.0/24 kids",
            },
            # IoT forwards to Google DNS (non-NextDNS)
            {
                "domain": "iot.zone",
                "server": "8.8.8.8",
                "description": "10.0.50.0/24 iot",
            },
            # Guest has no forwarder entry
        ]
        profiles = [
            {"id": "abc123", "name": "Trusted"},
            {"id": "def456", "name": "Kids"},
        ]
        analytics_ips = {
            "abc123": [{"ip": "10.0.10.15", "queries": 500}],
            # Kids profile has traffic but from wrong subnet
            "def456": [{"ip": "192.168.1.50", "queries": 100}],
        }

        result = await verify_profiles_with_data(
            vlans, forwarders, profiles, analytics_ips
        )

        assert result["vlans_checked"] == 4
        assert result["verified"] == 1  # Only Trusted

        # Check statuses
        status_map = {
            r["vlan_name"]: r["status"] for r in result["results"]
        }
        assert status_map["Trusted"] == "verified"
        assert status_map["Kids"] == "no_traffic"
        assert status_map["IoT"] == "non_nextdns"
        assert status_map["Guest"] == "no_forwarder"

        # Mismatches should report Kids (no_traffic) and Guest (no_forwarder)
        assert len(result["mismatches"]) == 2


# ---------------------------------------------------------------------------
# Test 8: Cross-profile summary -- computed correctly
# ---------------------------------------------------------------------------


class TestCrossProfileSummary:
    def test_two_profiles(self) -> None:
        """Summary computes correct totals across 2 profiles."""
        profiles = [
            {"id": "abc123", "name": "Home"},
            {"id": "def456", "name": "Kids"},
        ]
        status_data = {
            "abc123": [
                {"status": "default", "queries": 8000},
                {"status": "blocked", "queries": 1500},
                {"status": "allowed", "queries": 500},
            ],
            "def456": [
                {"status": "default", "queries": 3000},
                {"status": "blocked", "queries": 2000},
            ],
        }
        encryption_data = {
            "abc123": {
                "encrypted": 9500,
                "unencrypted": 500,
                "total": 10000,
                "unencrypted_percentage": 5.0,
            },
            "def456": {
                "encrypted": 4800,
                "unencrypted": 200,
                "total": 5000,
                "unencrypted_percentage": 4.0,
            },
        }

        result = compute_cross_profile_summary(
            profiles, status_data, encryption_data
        )

        # Total queries: 10000 + 5000 = 15000
        assert result["total_queries"] == 15000
        # Total blocked: 1500 + 2000 = 3500
        assert result["total_blocked"] == 3500
        # Block rate: 3500 / 15000 * 100 = 23.3%
        assert result["overall_block_rate"] == 23.3

        # Per-profile checks
        assert len(result["profiles"]) == 2

        home = result["profiles"][0]
        assert home["profile_id"] == "abc123"
        assert home["profile_name"] == "Home"
        assert home["total_queries"] == 10000
        assert home["blocked_queries"] == 1500
        assert home["block_rate"] == 15.0
        assert home["encrypted_percentage"] == 95.0

        kids = result["profiles"][1]
        assert kids["profile_id"] == "def456"
        assert kids["total_queries"] == 5000
        assert kids["blocked_queries"] == 2000
        assert kids["block_rate"] == 40.0
        assert kids["encrypted_percentage"] == 96.0


# ---------------------------------------------------------------------------
# Test 9: Cross-profile summary -- empty (no profiles)
# ---------------------------------------------------------------------------


class TestCrossProfileSummaryEmpty:
    def test_no_profiles(self) -> None:
        """Empty profiles list returns zero totals."""
        result = compute_cross_profile_summary([], {}, {})

        assert result["total_queries"] == 0
        assert result["total_blocked"] == 0
        assert result["overall_block_rate"] == 0.0
        assert result["profiles"] == []

    def test_profile_with_no_analytics(self) -> None:
        """Profile with no analytics data returns zeros."""
        profiles = [{"id": "abc123", "name": "Home"}]
        result = compute_cross_profile_summary(profiles, {}, {})

        assert result["total_queries"] == 0
        assert result["total_blocked"] == 0
        assert len(result["profiles"]) == 1
        assert result["profiles"][0]["total_queries"] == 0
        assert result["profiles"][0]["blocked_queries"] == 0
        assert result["profiles"][0]["block_rate"] == 0.0
        assert result["profiles"][0]["encrypted_percentage"] == 100.0


# ---------------------------------------------------------------------------
# Test: MCP tool -- netex__dns__verify_profiles (plugin checks)
# ---------------------------------------------------------------------------


class TestVerifyProfilesMCPTool:
    async def test_no_plugins(self) -> None:
        """Without gateway or dns plugins, returns error."""
        with patch(
            "netex.tools.dns_tools._build_registry",
            return_value=_make_empty_registry(),
        ):
            result = await netex__dns__verify_profiles()

        assert result["error"] == "missing_plugins"
        assert result["vlans_checked"] == 0

    async def test_missing_gateway(self) -> None:
        """Without gateway plugin, returns missing_gateway error."""
        with patch(
            "netex.tools.dns_tools._build_registry",
            return_value=_make_dns_only_registry(),
        ):
            result = await netex__dns__verify_profiles()

        assert result["error"] == "missing_gateway"

    async def test_full_registry_reports_tools(self) -> None:
        """With all plugins, reports required tools."""
        with patch(
            "netex.tools.dns_tools._build_registry",
            return_value=_make_full_registry(),
        ):
            result = await netex__dns__verify_profiles()

        assert result["plugins"]["gateway"] == "opnsense"
        assert result["plugins"]["dns"] == "nextdns"
        assert result["plugins"]["edge"] == "unifi"
        assert "opnsense__services__get_dns_forwarders" in result["tools_required"]
        assert "nextdns__profiles__list_profiles" in result["tools_required"]


# ---------------------------------------------------------------------------
# Test: MCP tool -- netex__dns__get_cross_profile_summary (plugin checks)
# ---------------------------------------------------------------------------


class TestCrossProfileSummaryMCPTool:
    async def test_no_dns_plugin(self) -> None:
        """Without dns plugin, returns error."""
        with patch(
            "netex.tools.dns_tools._build_registry",
            return_value=_make_empty_registry(),
        ):
            result = await netex__dns__get_cross_profile_summary()

        assert result["error"] == "missing_dns_plugin"
        assert result["total_queries"] == 0

    async def test_with_dns_plugin(self) -> None:
        """With dns plugin, returns tool requirements and time range."""
        with patch(
            "netex.tools.dns_tools._build_registry",
            return_value=_make_full_registry(),
        ):
            result = await netex__dns__get_cross_profile_summary(
                from_time="-24h", to_time="now"
            )

        assert result["plugins"]["dns"] == "nextdns"
        assert "nextdns__analytics__get_status" in result["tools_required"]
        assert result["time_range"]["from"] == "-24h"
        assert result["time_range"]["to"] == "now"


# ---------------------------------------------------------------------------
# Test: _find_forwarder_for_subnet
# ---------------------------------------------------------------------------


class TestFindForwarderForSubnet:
    def test_match_by_description(self) -> None:
        """Forwarder matched by subnet reference in description."""
        forwarders = [
            {"domain": "", "server": "dns.nextdns.io/abc123", "description": "10.0.10.0/24"},
            {"domain": "", "server": "dns.nextdns.io/def456", "description": "10.0.60.0/24"},
        ]
        result = _find_forwarder_for_subnet(forwarders, "10.0.60.0/24")
        assert result is not None
        assert result["server"] == "dns.nextdns.io/def456"

    def test_match_by_network_address(self) -> None:
        """Forwarder matched by network address in description."""
        forwarders = [
            {"domain": "", "server": "8.8.8.8", "description": "10.0.60.0 kids network"},
        ]
        result = _find_forwarder_for_subnet(forwarders, "10.0.60.0/24")
        assert result is not None
        assert result["server"] == "8.8.8.8"

    def test_fallback_to_catchall(self) -> None:
        """Falls back to catch-all forwarder (domain='') when no specific match."""
        forwarders = [
            {"domain": "", "server": "dns.nextdns.io/abc123", "description": "default"},
        ]
        result = _find_forwarder_for_subnet(forwarders, "10.0.99.0/24")
        assert result is not None
        assert result["server"] == "dns.nextdns.io/abc123"

    def test_no_match(self) -> None:
        """No forwarder matches and no catch-all returns None."""
        forwarders = [
            {"domain": "example.com", "server": "8.8.8.8", "description": ""},
        ]
        result = _find_forwarder_for_subnet(forwarders, "10.0.99.0/24")
        assert result is None

    def test_empty_forwarders(self) -> None:
        """Empty forwarder list returns None."""
        assert _find_forwarder_for_subnet([], "10.0.60.0/24") is None

    def test_none_subnet(self) -> None:
        """None subnet falls back to catch-all."""
        forwarders = [
            {"domain": ".", "server": "dns.nextdns.io/abc123", "description": ""},
        ]
        result = _find_forwarder_for_subnet(forwarders, None)
        assert result is not None
