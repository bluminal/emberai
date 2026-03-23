# SPDX-License-Identifier: MIT
"""Tests for the site manifest model and YAML parsing."""

from __future__ import annotations

import textwrap

import pytest
from pydantic import ValidationError

from netex.models.manifest import (
    AccessPolicyRule,
    PolicyAction,
    PortProfileDefinition,
    SiteManifest,
    VLANDefinition,
    WiFiDefinition,
    WiFiSecurity,
    parse_manifest,
    parse_manifest_file,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_MANIFEST = textwrap.dedent("""\
    vlans:
      - vlan_id: 10
        name: management
        subnet: 10.10.0.0/24
""")

FULL_MANIFEST = textwrap.dedent("""\
    name: Ridgeline
    description: 7-VLAN home network
    vlans:
      - vlan_id: 10
        name: management
        subnet: 10.10.0.0/24
        gateway: 10.10.0.1
        dhcp_enabled: true
        dhcp_range_start: 10.10.0.100
        dhcp_range_end: 10.10.0.254
        purpose: mgmt
        parent_interface: igc0
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
      - source: guest
        destination: wan
        action: allow
        protocol: tcp
        port: "80,443"
        description: Guest can browse only
    wifi:
      - ssid: Home-WiFi
        vlan_name: trusted
        security: wpa3
      - ssid: Guest-WiFi
        vlan_name: guest
        security: wpa2-wpa3
        hidden: false
        band: both
    port_profiles:
      - name: Trunk-All
        tagged_vlans:
          - management
          - trusted
          - guest
        poe_enabled: true
      - name: Access-Trusted
        native_vlan: trusted
        poe_enabled: false
""")


# ---------------------------------------------------------------------------
# VLANDefinition tests
# ---------------------------------------------------------------------------

class TestVLANDefinition:
    def test_valid_vlan(self) -> None:
        vlan = VLANDefinition(
            vlan_id=10,
            name="management",
            subnet="10.10.0.0/24",
        )
        assert vlan.vlan_id == 10
        assert vlan.name == "management"
        assert vlan.dhcp_enabled is True  # default

    def test_vlan_id_range_low(self) -> None:
        with pytest.raises(ValidationError):
            VLANDefinition(vlan_id=0, name="bad", subnet="10.0.0.0/24")

    def test_vlan_id_range_high(self) -> None:
        with pytest.raises(ValidationError):
            VLANDefinition(vlan_id=4095, name="bad", subnet="10.0.0.0/24")

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            VLANDefinition(vlan_id=10, name="", subnet="10.0.0.0/24")

    def test_full_vlan_definition(self) -> None:
        vlan = VLANDefinition(
            vlan_id=50,
            name="guest",
            subnet="10.50.0.0/24",
            gateway="10.50.0.1",
            dhcp_enabled=True,
            dhcp_range_start="10.50.0.100",
            dhcp_range_end="10.50.0.254",
            purpose="guest",
            parent_interface="igc0",
        )
        assert vlan.gateway == "10.50.0.1"
        assert vlan.parent_interface == "igc0"


# ---------------------------------------------------------------------------
# AccessPolicyRule tests
# ---------------------------------------------------------------------------

class TestAccessPolicyRule:
    def test_allow_rule(self) -> None:
        rule = AccessPolicyRule(
            source="trusted",
            destination="wan",
            action=PolicyAction.ALLOW,
        )
        assert rule.action == PolicyAction.ALLOW
        assert rule.protocol == "any"  # default

    def test_block_rule(self) -> None:
        rule = AccessPolicyRule(
            source="guest",
            destination="trusted",
            action=PolicyAction.BLOCK,
        )
        assert rule.action == PolicyAction.BLOCK

    def test_with_port(self) -> None:
        rule = AccessPolicyRule(
            source="guest",
            destination="wan",
            action=PolicyAction.ALLOW,
            protocol="tcp",
            port="80,443",
        )
        assert rule.protocol == "tcp"
        assert rule.port == "80,443"


# ---------------------------------------------------------------------------
# WiFiDefinition tests
# ---------------------------------------------------------------------------

class TestWiFiDefinition:
    def test_defaults(self) -> None:
        wifi = WiFiDefinition(ssid="Test", vlan_name="trusted")
        assert wifi.security == WiFiSecurity.WPA2_WPA3
        assert wifi.hidden is False
        assert wifi.band == "both"

    def test_wpa3(self) -> None:
        wifi = WiFiDefinition(
            ssid="Secure",
            vlan_name="mgmt",
            security=WiFiSecurity.WPA3,
        )
        assert wifi.security == WiFiSecurity.WPA3


# ---------------------------------------------------------------------------
# PortProfileDefinition tests
# ---------------------------------------------------------------------------

class TestPortProfileDefinition:
    def test_trunk_profile(self) -> None:
        profile = PortProfileDefinition(
            name="Trunk-All",
            tagged_vlans=["mgmt", "trusted", "guest"],
        )
        assert len(profile.tagged_vlans) == 3
        assert profile.poe_enabled is True  # default

    def test_access_profile(self) -> None:
        profile = PortProfileDefinition(
            name="Access-Trusted",
            native_vlan="trusted",
            poe_enabled=False,
        )
        assert profile.native_vlan == "trusted"
        assert profile.poe_enabled is False


# ---------------------------------------------------------------------------
# SiteManifest tests
# ---------------------------------------------------------------------------

class TestSiteManifest:
    def test_minimal_manifest(self) -> None:
        manifest = SiteManifest(
            vlans=[
                VLANDefinition(vlan_id=10, name="mgmt", subnet="10.10.0.0/24"),
            ],
        )
        assert len(manifest.vlans) == 1
        assert manifest.access_policy == []
        assert manifest.wifi == []
        assert manifest.port_profiles == []

    def test_empty_vlans_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SiteManifest(vlans=[])

    def test_duplicate_vlan_ids_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Duplicate VLAN IDs"):
            SiteManifest(
                vlans=[
                    VLANDefinition(vlan_id=10, name="a", subnet="10.10.0.0/24"),
                    VLANDefinition(vlan_id=10, name="b", subnet="10.20.0.0/24"),
                ],
            )

    def test_duplicate_vlan_names_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Duplicate VLAN names"):
            SiteManifest(
                vlans=[
                    VLANDefinition(vlan_id=10, name="mgmt", subnet="10.10.0.0/24"),
                    VLANDefinition(vlan_id=20, name="mgmt", subnet="10.20.0.0/24"),
                ],
            )

    def test_vlan_by_name(self) -> None:
        manifest = SiteManifest(
            vlans=[
                VLANDefinition(vlan_id=10, name="mgmt", subnet="10.10.0.0/24"),
                VLANDefinition(vlan_id=20, name="trusted", subnet="10.20.0.0/24"),
            ],
        )
        assert manifest.vlan_by_name("mgmt") is not None
        assert manifest.vlan_by_name("mgmt").vlan_id == 10  # type: ignore[union-attr]
        assert manifest.vlan_by_name("missing") is None

    def test_vlan_by_id(self) -> None:
        manifest = SiteManifest(
            vlans=[
                VLANDefinition(vlan_id=10, name="mgmt", subnet="10.10.0.0/24"),
            ],
        )
        assert manifest.vlan_by_id(10) is not None
        assert manifest.vlan_by_id(99) is None

    def test_vlan_names(self) -> None:
        manifest = SiteManifest(
            vlans=[
                VLANDefinition(vlan_id=10, name="mgmt", subnet="10.10.0.0/24"),
                VLANDefinition(vlan_id=20, name="trusted", subnet="10.20.0.0/24"),
            ],
        )
        assert manifest.vlan_names() == ["mgmt", "trusted"]


# ---------------------------------------------------------------------------
# parse_manifest tests
# ---------------------------------------------------------------------------

class TestParseManifest:
    def test_minimal_yaml(self) -> None:
        manifest = parse_manifest(MINIMAL_MANIFEST)
        assert len(manifest.vlans) == 1
        assert manifest.vlans[0].name == "management"

    def test_full_yaml(self) -> None:
        manifest = parse_manifest(FULL_MANIFEST)
        assert manifest.name == "Ridgeline"
        assert len(manifest.vlans) == 3
        assert len(manifest.access_policy) == 3
        assert len(manifest.wifi) == 2
        assert len(manifest.port_profiles) == 2

    def test_full_yaml_vlan_details(self) -> None:
        manifest = parse_manifest(FULL_MANIFEST)
        mgmt = manifest.vlan_by_name("management")
        assert mgmt is not None
        assert mgmt.vlan_id == 10
        assert mgmt.gateway == "10.10.0.1"
        assert mgmt.dhcp_range_start == "10.10.0.100"

    def test_full_yaml_policy(self) -> None:
        manifest = parse_manifest(FULL_MANIFEST)
        block_rules = [
            r for r in manifest.access_policy
            if r.action == PolicyAction.BLOCK
        ]
        assert len(block_rules) == 1
        assert block_rules[0].source == "guest"
        assert block_rules[0].destination == "trusted"

    def test_full_yaml_wifi(self) -> None:
        manifest = parse_manifest(FULL_MANIFEST)
        guest_wifi = [w for w in manifest.wifi if w.ssid == "Guest-WiFi"]
        assert len(guest_wifi) == 1
        assert guest_wifi[0].vlan_name == "guest"
        assert guest_wifi[0].security == WiFiSecurity.WPA2_WPA3

    def test_invalid_yaml_raises(self) -> None:
        with pytest.raises(ValueError, match="YAML mapping"):
            parse_manifest("just a string")

    def test_missing_vlans_raises(self) -> None:
        with pytest.raises(ValidationError):
            parse_manifest("name: test\n")

    def test_invalid_vlan_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            parse_manifest(textwrap.dedent("""\
                vlans:
                  - vlan_id: 9999
                    name: bad
                    subnet: 10.0.0.0/24
            """))


class TestParseManifestFile:
    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            parse_manifest_file("/nonexistent/manifest.yaml")

    def test_valid_file(self, tmp_path: pytest.TempPathFactory) -> None:
        manifest_file = tmp_path / "test.yaml"  # type: ignore[operator]
        manifest_file.write_text(MINIMAL_MANIFEST)
        manifest = parse_manifest_file(str(manifest_file))
        assert len(manifest.vlans) == 1
