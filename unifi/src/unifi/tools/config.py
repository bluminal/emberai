# SPDX-License-Identifier: MIT
"""Config skill MCP tools -- config snapshots, baseline diffs, backup state, write ops.

Provides MCP tools for reviewing UniFi site configuration state including
configuration snapshots, baseline comparison, and backup status via the
Local Gateway API.  Also provides write-gated tools for saving baselines
and creating port profiles.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from unifi.api.response import normalize_response
from unifi.errors import ValidationError
from unifi.safety import write_gate
from unifi.server import mcp_server
from unifi.tools._client_factory import get_local_client

if TYPE_CHECKING:
    from unifi.api.local_gateway_client import LocalGatewayClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


_get_client = get_local_client  # Shared factory with credential validation


# ---------------------------------------------------------------------------
# Tool 1: Config Snapshot
# ---------------------------------------------------------------------------


async def _fetch_config_data(
    client: LocalGatewayClient,
    site_id: str,
) -> dict[str, Any]:
    """Fetch configuration data from multiple endpoints and build a snapshot.

    Collects networks, WLANs, and firewall rules into a single summary.
    """
    networks_resp = await client.get_normalized(f"/api/s/{site_id}/rest/networkconf")
    wlans_resp = await client.get_normalized(f"/api/s/{site_id}/rest/wlanconf")
    rules_resp = await client.get_normalized(f"/api/s/{site_id}/rest/firewallrule")

    return {
        "networks": networks_resp.data,
        "wlans": wlans_resp.data,
        "firewall_rules": rules_resp.data,
    }


@mcp_server.tool()
async def unifi__config__get_config_snapshot(
    site_id: str = "default",
) -> dict[str, Any]:
    """Get a configuration snapshot for a site.

    Fetches network, WLAN, and firewall rule configurations and returns
    a summary with counts and the raw configuration data.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        raw_config = await _fetch_config_data(client, site_id)
    finally:
        await client.close()

    snapshot: dict[str, Any] = {
        "site_id": site_id,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "network_count": len(raw_config["networks"]),
        "wlan_count": len(raw_config["wlans"]),
        "rule_count": len(raw_config["firewall_rules"]),
        "raw_config": raw_config,
    }

    logger.info(
        "Config snapshot for site '%s': %d networks, %d WLANs, %d rules",
        site_id,
        snapshot["network_count"],
        snapshot["wlan_count"],
        snapshot["rule_count"],
        extra={"component": "config"},
    )

    return snapshot


# ---------------------------------------------------------------------------
# Tool 2: Diff Baseline
# ---------------------------------------------------------------------------


def _compute_structural_diff(
    current: dict[str, list[dict[str, Any]]],
    baseline: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Compute a structural diff between current config and a stored baseline.

    Compares items by their ``_id`` field across each config section
    (networks, wlans, firewall_rules). Reports added, removed, and
    modified entries.
    """
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []

    for section in ("networks", "wlans", "firewall_rules"):
        current_items = current.get(section, [])
        baseline_items = baseline.get(section, [])

        current_by_id = {item.get("_id", ""): item for item in current_items}
        baseline_by_id = {item.get("_id", ""): item for item in baseline_items}

        current_ids = set(current_by_id.keys())
        baseline_ids = set(baseline_by_id.keys())

        # Items in current but not in baseline
        for item_id in sorted(current_ids - baseline_ids):
            item = current_by_id[item_id]
            added.append(
                {
                    "section": section,
                    "id": item_id,
                    "name": item.get("name", ""),
                }
            )

        # Items in baseline but not in current
        for item_id in sorted(baseline_ids - current_ids):
            item = baseline_by_id[item_id]
            removed.append(
                {
                    "section": section,
                    "id": item_id,
                    "name": item.get("name", ""),
                }
            )

        # Items in both but changed
        for item_id in sorted(current_ids & baseline_ids):
            if current_by_id[item_id] != baseline_by_id[item_id]:
                modified.append(
                    {
                        "section": section,
                        "id": item_id,
                        "name": current_by_id[item_id].get("name", ""),
                    }
                )

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
    }


# Stored baselines (in-memory for now; production would use persistent storage)
_baselines: dict[str, dict[str, list[dict[str, Any]]]] = {}


@mcp_server.tool()
async def unifi__config__diff_baseline(
    site_id: str = "default",
    baseline_id: str = "latest",
) -> dict[str, Any]:
    """Compare current config against a stored baseline.

    Returns a structural diff showing added, removed, and modified
    configuration items across networks, WLANs, and firewall rules.

    If no baseline exists for the given baseline_id, returns an error
    message indicating that a baseline must be saved first.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
        baseline_id: Identifier of the stored baseline to compare against.
            Defaults to "latest".
    """
    baseline_key = f"{site_id}:{baseline_id}"
    baseline = _baselines.get(baseline_key)

    if baseline is None:
        logger.warning(
            "No baseline found for '%s' at site '%s'",
            baseline_id,
            site_id,
            extra={"component": "config"},
        )
        return {
            "error": f"No baseline found for '{baseline_id}' at site '{site_id}'.",
            "hint": "Save a baseline first using the config save_baseline tool.",
            "added": [],
            "removed": [],
            "modified": [],
        }

    client = _get_client()
    try:
        current_config = await _fetch_config_data(client, site_id)
    finally:
        await client.close()

    diff = _compute_structural_diff(current_config, baseline)

    logger.info(
        "Config diff for site '%s' vs baseline '%s': %d added, %d removed, %d modified",
        site_id,
        baseline_id,
        len(diff["added"]),
        len(diff["removed"]),
        len(diff["modified"]),
        extra={"component": "config"},
    )

    return diff


# ---------------------------------------------------------------------------
# Tool 3: Backup State
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def unifi__config__get_backup_state(
    site_id: str = "default",
) -> dict[str, Any]:
    """Get backup status for a site.

    Returns the last backup time, backup type, and whether cloud backup
    is enabled.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    client = _get_client()
    try:
        normalized = await client.get_normalized(f"/api/s/{site_id}/stat/sysinfo")
    finally:
        await client.close()

    # The sysinfo endpoint returns system-level info including backup state
    sysinfo = normalized.data[0] if normalized.data else {}

    # Extract backup-related fields
    autobackup = sysinfo.get("autobackup", False)
    last_backup_time = sysinfo.get("last_backup_time", sysinfo.get("previous_heartbeat_at"))

    # Format the timestamp if present
    formatted_time = ""
    if isinstance(last_backup_time, (int, float)):
        if last_backup_time > 1e12:
            last_backup_time = last_backup_time / 1000
        formatted_time = datetime.fromtimestamp(last_backup_time, tz=UTC).isoformat()
    elif isinstance(last_backup_time, str):
        formatted_time = last_backup_time

    backup_state: dict[str, Any] = {
        "last_backup_time": formatted_time,
        "backup_type": sysinfo.get("backup_type", "auto" if autobackup else "manual"),
        "size_mb": sysinfo.get("backup_size_mb"),
        "cloud_enabled": sysinfo.get("cloud_backup_enabled", sysinfo.get("cloud_key", "") != ""),
    }

    logger.info(
        "Retrieved backup state for site '%s': last=%s, cloud=%s",
        site_id,
        backup_state["last_backup_time"],
        backup_state["cloud_enabled"],
        extra={"component": "config"},
    )

    return backup_state


# ---------------------------------------------------------------------------
# Tool 4: Save Baseline (write-gated)
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("UNIFI")
async def unifi__config__save_baseline(
    site_id: str = "default",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Save current config as a baseline for future drift detection.

    Write-gated: requires UNIFI_WRITE_ENABLED=true and apply=True.

    Takes a configuration snapshot of networks, WLANs, and firewall rules
    and stores it as a named baseline.  The baseline can later be compared
    against the live configuration using the diff_baseline tool.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
        apply: Must be True to execute (write gate).
    """
    client = _get_client()
    try:
        raw_config = await _fetch_config_data(client, site_id)
    finally:
        await client.close()

    timestamp = datetime.now(tz=UTC).isoformat()
    baseline_id = uuid.uuid4().hex[:12]

    # Store under both the specific ID and "latest" alias
    _baselines[f"{site_id}:{baseline_id}"] = raw_config
    _baselines[f"{site_id}:latest"] = raw_config

    logger.info(
        "Saved baseline '%s' for site '%s': %d networks, %d WLANs, %d rules",
        baseline_id,
        site_id,
        len(raw_config.get("networks", [])),
        len(raw_config.get("wlans", [])),
        len(raw_config.get("firewall_rules", [])),
        extra={"component": "config"},
    )

    return {
        "baseline_id": baseline_id,
        "timestamp": timestamp,
        "site_id": site_id,
        "network_count": len(raw_config.get("networks", [])),
        "wlan_count": len(raw_config.get("wlans", [])),
        "rule_count": len(raw_config.get("firewall_rules", [])),
    }


# ---------------------------------------------------------------------------
# Tool 5: Create Port Profile (write-gated)
# ---------------------------------------------------------------------------


def _parse_tagged_vlans(tagged_vlans: str) -> list[str]:
    """Parse a comma-separated string of VLAN IDs into a list.

    Strips whitespace and filters out empty strings.  Returns an empty
    list when given an empty or whitespace-only string.
    """
    if not tagged_vlans or not tagged_vlans.strip():
        return []
    return [v.strip() for v in tagged_vlans.split(",") if v.strip()]


def _validate_vlan_id(vlan_id: int, field_name: str = "native_vlan") -> None:
    """Validate that a VLAN ID is within the allowed range (1-4094)."""
    if not 1 <= vlan_id <= 4094:
        raise ValidationError(
            f"Invalid {field_name}: {vlan_id}. VLAN IDs must be between 1 and 4094.",
            details={"field": field_name, "value": vlan_id},
        )


@mcp_server.tool()
@write_gate("UNIFI")
async def unifi__config__create_port_profile(
    name: str,
    native_vlan: int,
    tagged_vlans: str = "",
    poe: bool = False,
    site_id: str = "default",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Create a named switch port profile.

    Write-gated: requires UNIFI_WRITE_ENABLED=true and apply=True.

    Creates a port profile (portconf) on the UniFi controller that can
    be assigned to individual switch ports.  The profile defines the
    native (untagged) VLAN, optional tagged VLANs, and PoE mode.

    Args:
        name: Profile name (e.g., "Trunk-AP").
        native_vlan: Native/untagged VLAN ID (1-4094).
        tagged_vlans: Comma-separated tagged VLAN IDs (e.g., "30,50,60").
        poe: Enable PoE on ports using this profile.
        site_id: UniFi site ID. Defaults to "default".
        apply: Must be True to execute (write gate).
    """
    # --- Input validation ---
    if not name or not name.strip():
        raise ValidationError(
            "Profile name must not be empty.",
            details={"field": "name"},
        )

    _validate_vlan_id(native_vlan, "native_vlan")

    tagged_list = _parse_tagged_vlans(tagged_vlans)
    for tag_str in tagged_list:
        try:
            tag_int = int(tag_str)
        except ValueError as exc:
            raise ValidationError(
                f"Invalid tagged VLAN ID: '{tag_str}'. Must be an integer.",
                details={"field": "tagged_vlans", "value": tag_str},
            ) from exc
        _validate_vlan_id(tag_int, "tagged_vlans")

    # --- Resolve VLAN tag numbers to network ObjectIDs ---

    client = _get_client()
    try:
        nets_resp = await client.get_normalized(f"/api/s/{site_id}/rest/networkconf")
    finally:
        await client.close()

    # Build tag-to-ObjectID lookup
    tag_to_oid: dict[int, str] = {}
    for net in nets_resp.data:
        oid = net.get("_id", "")
        tag_val = net.get("vlan")
        if tag_val is not None and oid:
            with contextlib.suppress(ValueError, TypeError):
                tag_to_oid[int(tag_val)] = oid
        # Default LAN (no vlan tag) → VLAN 1
        if not net.get("vlan_enabled", False) and oid:
            tag_to_oid[1] = oid

    native_oid = tag_to_oid.get(native_vlan, str(native_vlan))
    tagged_oids = [tag_to_oid.get(int(t), t) for t in tagged_list]

    # --- Build API payload ---
    body: dict[str, Any] = {
        "name": name.strip(),
        "native_networkconf_id": native_oid,
        "tagged_networkconf_ids": tagged_oids,
        "poe_mode": "auto" if poe else "off",
    }

    endpoint = f"/api/s/{site_id}/rest/portconf"

    client = _get_client()
    try:
        raw_response = await client.post(endpoint, data=body)
    finally:
        await client.close()

    # Parse the response envelope to extract the created profile
    normalized = normalize_response(raw_response)

    profile_data = normalized.data[0] if normalized.data else {}
    profile_id = profile_data.get("_id", "")

    logger.info(
        "Created port profile '%s' (id=%s) for site '%s': native_vlan=%d, tagged=%s, poe=%s",
        name,
        profile_id,
        site_id,
        native_vlan,
        tagged_vlans or "(none)",
        poe,
        extra={"component": "config"},
    )

    return {
        "profile_id": profile_id,
        "name": name.strip(),
        "native_vlan": native_vlan,
        "tagged_vlans": tagged_list,
        "poe": poe,
        "site_id": site_id,
    }


# ---------------------------------------------------------------------------
# Tool 6: Create Network (write-gated)
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("UNIFI")
async def unifi__config__create_network(
    name: str,
    vlan_id: int,
    purpose: str = "corporate",
    dhcp_enabled: bool = False,
    igmp_snooping: bool = True,
    site_id: str = "default",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Create a VLAN-tagged network on the UniFi controller.

    Write-gated: requires UNIFI_WRITE_ENABLED=true and apply=True.

    Creates a network (networkconf) that can be associated with switch
    port profiles and WLANs.  DHCP is disabled by default since OPNsense
    typically handles DHCP for the network.

    Args:
        name: Network name (e.g., "Trusted").
        vlan_id: VLAN ID (1-4094).
        purpose: Network purpose ("corporate" or "guest").
        dhcp_enabled: Whether UniFi should run DHCP (usually False when
            OPNsense handles DHCP).
        igmp_snooping: Enable IGMP snooping.
        site_id: UniFi site ID. Defaults to "default".
        apply: Must be True to execute (write gate).
    """
    # --- Input validation ---
    if not name or not name.strip():
        raise ValidationError(
            "Network name must not be empty.",
            details={"field": "name"},
        )

    _validate_vlan_id(vlan_id, "vlan_id")

    # --- Build API payload ---
    body: dict[str, Any] = {
        "name": name.strip(),
        "purpose": purpose.strip(),
        "vlan_enabled": True,
        "vlan": str(vlan_id),
        "dhcpd_enabled": dhcp_enabled,
        "igmp_snooping": igmp_snooping,
    }

    endpoint = f"/api/s/{site_id}/rest/networkconf"

    client = _get_client()
    try:
        raw_response = await client.post(endpoint, data=body)
    finally:
        await client.close()

    # Parse the response envelope to extract the created network
    normalized = normalize_response(raw_response)

    network_data = normalized.data[0] if normalized.data else {}
    network_id = network_data.get("_id", "")

    logger.info(
        "Created network '%s' (id=%s) for site '%s': "
        "vlan_id=%d, purpose=%s, dhcp=%s, igmp_snooping=%s",
        name,
        network_id,
        site_id,
        vlan_id,
        purpose,
        dhcp_enabled,
        igmp_snooping,
        extra={"component": "config"},
    )

    return {
        "network_id": network_id,
        "name": name.strip(),
        "vlan_id": vlan_id,
        "purpose": purpose,
        "dhcp_enabled": dhcp_enabled,
        "site_id": site_id,
    }


# ---------------------------------------------------------------------------
# Tool 7: Create WLAN (write-gated)
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("UNIFI")
async def unifi__config__create_wlan(
    name: str,
    passphrase: str,
    network_id: str,
    security: str = "wpapsk",
    wlan_band: str = "both",
    enabled: bool = True,
    site_id: str = "default",
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Create a wireless network (SSID) on the UniFi controller.

    Write-gated: requires UNIFI_WRITE_ENABLED=true and apply=True.

    Creates a WLAN (wlanconf) associated with an existing network.  The
    network_id should be the ``_id`` returned from ``create_network``.

    Args:
        name: SSID name (e.g., "MyNetwork").
        passphrase: WiFi password (min 8 characters for WPA).
        network_id: The ``_id`` of the network to associate with.
        security: Security mode (e.g., "wpapsk", "wpa3").
        wlan_band: Band ("2g", "5g", "both").
        enabled: Whether SSID is active.
        site_id: UniFi site ID. Defaults to "default".
        apply: Must be True to execute (write gate).
    """
    # --- Input validation ---
    if not name or not name.strip():
        raise ValidationError(
            "WLAN name must not be empty.",
            details={"field": "name"},
        )

    if not passphrase or len(passphrase) < 8:
        raise ValidationError(
            "Passphrase must be at least 8 characters for WPA.",
            details={"field": "passphrase"},
        )

    if not network_id or not network_id.strip():
        raise ValidationError(
            "Network ID must not be empty.",
            details={"field": "network_id"},
        )

    # --- Look up default user group (required for WLAN creation) ---
    client = _get_client()
    try:
        usergroup_resp = await client.get_normalized(
            f"/api/s/{site_id}/rest/usergroup",
        )
        usergroup_id = ""
        for ug in usergroup_resp.data:
            usergroup_id = ug.get("_id", "")
            if ug.get("attr_no_delete"):  # Default user group
                break

        # --- Build API payload ---
        body: dict[str, Any] = {
            "name": name.strip(),
            "x_passphrase": passphrase,
            "networkconf_id": network_id.strip(),
            "security": security.strip(),
            "wpa_enc": "ccmp",
            "wpa_mode": "wpa2",
            "enabled": enabled,
            "wlan_band": "both",
            "wlan_bands": ["2g", "5g"],
            "ap_group_mode": "all",
        }
        if usergroup_id:
            body["usergroup_id"] = usergroup_id
        if wlan_band.strip().lower() == "2g":
            body["wlan_band"] = "2g"
            body["wlan_bands"] = ["2g"]
        elif wlan_band.strip().lower() == "5g":
            body["wlan_band"] = "5g"
            body["wlan_bands"] = ["5g"]

        # Check if WLAN with this name already exists — update instead of create
        existing_wlans = await client.get_normalized(
            f"/api/s/{site_id}/rest/wlanconf",
        )
        existing_wlan_id = None
        for wlan in existing_wlans.data:
            if wlan.get("name", "").strip().lower() == name.strip().lower():
                existing_wlan_id = wlan.get("_id", "")
                break

        if existing_wlan_id:
            # Update existing WLAN via PUT
            endpoint = f"/api/s/{site_id}/rest/wlanconf/{existing_wlan_id}"
            raw_response = await client.put(endpoint, data=body)
        else:
            # Create new WLAN — use an existing WLAN as template if available
            # to ensure all required fields are populated
            template_wlan = None
            for wlan in existing_wlans.data:
                if wlan.get("security") == "wpapsk":
                    template_wlan = dict(wlan)
                    break

            if template_wlan:
                # Remove identity/unique fields from template
                for key in ("_id", "site_id", "external_id", "x_iapp_key"):
                    template_wlan.pop(key, None)
                # Override with our values
                template_wlan.update(body)
                body = template_wlan

            endpoint = f"/api/s/{site_id}/rest/wlanconf"
            raw_response = await client.post(endpoint, data=body)
    finally:
        await client.close()

    # Parse the response envelope to extract the created WLAN
    normalized = normalize_response(raw_response)

    wlan_data = normalized.data[0] if normalized.data else {}
    wlan_id = wlan_data.get("_id", "")

    logger.info(
        "Created WLAN '%s' (id=%s) for site '%s': network=%s, security=%s, band=%s, enabled=%s",
        name,
        wlan_id,
        site_id,
        network_id,
        security,
        wlan_band,
        enabled,
        extra={"component": "config"},
    )

    return {
        "wlan_id": wlan_id,
        "name": name.strip(),
        "network_id": network_id,
        "security": security,
        "wlan_band": wlan_band,
        "enabled": enabled,
        "site_id": site_id,
    }
