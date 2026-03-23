# SPDX-License-Identifier: MIT
"""Site manifest models for ``netex network provision-site``.

A site manifest is a structured YAML document that describes the complete
network configuration for a site.  It contains:

- ``vlans[]`` -- VLAN definitions with IDs, names, subnets, DHCP ranges
- ``access_policy[]`` -- expected connectivity matrix (allow / block)
- ``wifi[]`` -- WiFi SSID definitions with VLAN bindings
- ``port_profiles[]`` -- switch port profile definitions

The manifest is the single source of truth for ``provision-site``,
``verify-policy``, and ``vlan provision-batch`` commands.
"""

from __future__ import annotations

from enum import StrEnum

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PolicyAction(StrEnum):
    """Expected connectivity outcome in an access policy rule."""

    ALLOW = "allow"
    BLOCK = "block"


class WiFiSecurity(StrEnum):
    """WiFi security mode."""

    OPEN = "open"
    WPA2 = "wpa2"
    WPA3 = "wpa3"
    WPA2_WPA3 = "wpa2-wpa3"


# ---------------------------------------------------------------------------
# Manifest section models
# ---------------------------------------------------------------------------

class VLANDefinition(BaseModel):
    """A single VLAN definition in the site manifest."""

    model_config = ConfigDict(populate_by_name=True)

    vlan_id: int = Field(ge=1, le=4094, description="802.1Q VLAN ID")
    name: str = Field(min_length=1, description="Human-readable name")
    subnet: str = Field(description="CIDR notation (e.g. 10.50.0.0/24)")
    gateway: str | None = Field(default=None, description="Gateway IP (defaults to .1)")
    dhcp_enabled: bool = Field(default=True, description="Enable DHCP server")
    dhcp_range_start: str | None = Field(
        default=None, description="DHCP range start IP"
    )
    dhcp_range_end: str | None = Field(
        default=None, description="DHCP range end IP"
    )
    purpose: str = Field(default="", description="VLAN purpose (e.g. iot, guest, mgmt)")
    parent_interface: str | None = Field(
        default=None, description="Parent interface for VLAN tagging"
    )


class AccessPolicyRule(BaseModel):
    """A single access policy rule defining expected connectivity."""

    model_config = ConfigDict(populate_by_name=True)

    source: str = Field(description="Source VLAN name or 'wan'")
    destination: str = Field(description="Destination VLAN name or 'wan'")
    action: PolicyAction = Field(description="Expected action (allow/block)")
    protocol: str = Field(default="any", description="Protocol (any, tcp, udp, icmp)")
    port: str = Field(default="any", description="Port or port range")
    description: str = Field(default="", description="Rule description")


class WiFiDefinition(BaseModel):
    """A WiFi SSID definition in the site manifest."""

    model_config = ConfigDict(populate_by_name=True)

    ssid: str = Field(min_length=1, description="SSID name")
    vlan_name: str = Field(description="VLAN to bind this SSID to (by name)")
    security: WiFiSecurity = Field(
        default=WiFiSecurity.WPA2_WPA3, description="Security mode"
    )
    hidden: bool = Field(default=False, description="Hide SSID from broadcast")
    band: str = Field(default="both", description="Radio band (2.4, 5, both)")


class PortProfileDefinition(BaseModel):
    """A switch port profile definition in the site manifest."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, description="Profile name")
    native_vlan: str | None = Field(
        default=None, description="Native (untagged) VLAN name"
    )
    tagged_vlans: list[str] = Field(
        default_factory=list, description="Tagged VLAN names"
    )
    poe_enabled: bool = Field(default=True, description="Power over Ethernet")


# ---------------------------------------------------------------------------
# Top-level manifest
# ---------------------------------------------------------------------------

class SiteManifest(BaseModel):
    """Complete site manifest for ``netex network provision-site``.

    Parsed from a YAML file. All sections are optional except ``vlans``,
    which must contain at least one entry.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(default="", description="Site name for logging")
    description: str = Field(default="", description="Site description")
    vlans: list[VLANDefinition] = Field(
        min_length=1, description="VLAN definitions"
    )
    access_policy: list[AccessPolicyRule] = Field(
        default_factory=list, description="Access policy matrix"
    )
    wifi: list[WiFiDefinition] = Field(
        default_factory=list, description="WiFi SSID definitions"
    )
    port_profiles: list[PortProfileDefinition] = Field(
        default_factory=list, description="Switch port profile definitions"
    )

    @field_validator("vlans")
    @classmethod
    def validate_unique_vlan_ids(
        cls, v: list[VLANDefinition],
    ) -> list[VLANDefinition]:
        """Ensure all VLAN IDs are unique within the manifest."""
        ids = [vlan.vlan_id for vlan in v]
        if len(ids) != len(set(ids)):
            duplicates = [vid for vid in ids if ids.count(vid) > 1]
            raise ValueError(f"Duplicate VLAN IDs in manifest: {sorted(set(duplicates))}")
        return v

    @field_validator("vlans")
    @classmethod
    def validate_unique_vlan_names(
        cls, v: list[VLANDefinition],
    ) -> list[VLANDefinition]:
        """Ensure all VLAN names are unique within the manifest."""
        names = [vlan.name for vlan in v]
        if len(names) != len(set(names)):
            duplicates = [n for n in names if names.count(n) > 1]
            raise ValueError(f"Duplicate VLAN names in manifest: {sorted(set(duplicates))}")
        return v

    def vlan_by_name(self, name: str) -> VLANDefinition | None:
        """Look up a VLAN definition by name."""
        for vlan in self.vlans:
            if vlan.name == name:
                return vlan
        return None

    def vlan_by_id(self, vlan_id: int) -> VLANDefinition | None:
        """Look up a VLAN definition by ID."""
        for vlan in self.vlans:
            if vlan.vlan_id == vlan_id:
                return vlan
        return None

    def vlan_names(self) -> list[str]:
        """Return all VLAN names in definition order."""
        return [v.name for v in self.vlans]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_manifest(yaml_content: str) -> SiteManifest:
    """Parse a YAML string into a validated SiteManifest.

    Parameters
    ----------
    yaml_content:
        Raw YAML content as a string.

    Returns
    -------
    SiteManifest
        Validated manifest object.

    Raises
    ------
    ValueError
        If the YAML is invalid or fails validation.
    yaml.YAMLError
        If the YAML syntax is malformed.
    """
    data = yaml.safe_load(yaml_content)
    if not isinstance(data, dict):
        raise ValueError(
            f"Manifest must be a YAML mapping, got {type(data).__name__}"
        )
    return SiteManifest.model_validate(data)


def parse_manifest_file(path: str) -> SiteManifest:
    """Parse a YAML file into a validated SiteManifest.

    Parameters
    ----------
    path:
        File path to the YAML manifest.

    Returns
    -------
    SiteManifest
        Validated manifest object.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the YAML is invalid or fails validation.
    """
    from pathlib import Path

    manifest_path = Path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {path}")

    return parse_manifest(manifest_path.read_text(encoding="utf-8"))
