# SPDX-License-Identifier: MIT
"""Command-level MCP tools -- thin wrappers that delegate to agent orchestrators.

These tools represent the user-facing ``unifi scan``, ``unifi health``,
``unifi clients``, ``unifi diagnose``, ``unifi wifi``, ``unifi optimize``,
``unifi secure``, ``unifi config``, ``unifi port-profile create``, and
``unifi port-profile assign`` commands.  Each is a minimal shim that forwards
to the corresponding agent function, keeping the tool surface lean and the
business logic testable independently.

The port-profile commands implement the three-phase confirmation model:

1. **Phase 1 -- Verification:** Validate inputs, verify VLANs exist, look up
   devices and profiles from the API.
2. **Phase 2 -- Plan presentation:** Format a structured change plan using
   ``format_plan_confirmation()`` from ``unifi.ask`` and return it for operator
   review.
3. **Phase 3 -- Execution:** When ``apply=True`` and the write gate passes,
   delegate to the underlying write tools.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from unifi.server import mcp_server

logger = logging.getLogger(__name__)


@mcp_server.tool()
async def unifi_scan(site_id: str = "default") -> str:
    """Discover and map the full network topology for a UniFi site.

    Shows all devices (switches, APs, gateways), VLANs, and uplink
    connections in a formatted report.

    Phase 1 scope: single-site only. Multi-site selection added in Phase 2.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    from unifi.agents.topology import scan_site

    return await scan_site(site_id)


@mcp_server.tool()
async def unifi_health(site_id: str = "default") -> str:
    """Run a comprehensive health check with severity-tiered findings.

    Checks subsystem status, recent events, firmware updates, and ISP
    metrics. Returns findings grouped by severity (Critical > Warning >
    Informational).

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    from unifi.agents.health import check_health

    return await check_health(site_id)


@mcp_server.tool()
async def unifi_clients(
    site_id: str = "default",
    vlan_id: str | None = None,
    ap_id: str | None = None,
) -> str:
    """Inventory all connected clients, optionally filtered.

    Shows hostname/MAC, IP, VLAN, AP/port, connection type, signal quality,
    and traffic summary for each connected client.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
        vlan_id: Filter by VLAN/network ID.
        ap_id: Filter by access point MAC address.
    """
    from unifi.agents.clients import list_clients_report

    return await list_clients_report(site_id, vlan_id=vlan_id, ap_id=ap_id)


@mcp_server.tool()
async def unifi_diagnose(target: str, site_id: str = "default") -> str:
    """Root-cause analysis for a device or client.

    Searches for the target by MAC, hostname, IP, or name. If the target
    is ambiguous (matches multiple devices or clients), prompts for
    clarification. Correlates health data, events, and topology to
    produce a diagnostic report with findings and recommendations.

    Phase 1 scope: correlates health events + client data + topology.
    Security correlation added in Phase 2.

    Args:
        target: Device MAC/name/IP or client MAC/hostname/IP to diagnose.
        site_id: The UniFi site ID. Defaults to "default".
    """
    from unifi.agents.diagnose import diagnose_target

    return await diagnose_target(target, site_id=site_id)


@mcp_server.tool()
async def unifi_wifi(site_id: str = "default") -> str:
    """Analyze the wireless RF environment.

    Channel utilization, neighboring SSIDs, roaming stats, and
    per-AP RF scan results. Returns severity-tiered findings for
    issues like high channel utilization or dense neighbor environments.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    from unifi.agents.wifi import analyze_wifi

    return await analyze_wifi(site_id)


@mcp_server.tool()
async def unifi_optimize(site_id: str = "default", apply: bool = False) -> str:
    """Generate prioritized improvement recommendations.

    Aggregates data from WiFi, traffic, security, and config agents to
    produce actionable optimization recommendations ranked by impact.

    Without ``apply``: read-only recommendations only (plan-only mode).
    With ``apply=True``: presents a full change plan for operator
    confirmation before executing. Requires ``UNIFI_WRITE_ENABLED=true``.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
        apply: If True, present a change plan for confirmation and
            execute approved recommendations. Requires UNIFI_WRITE_ENABLED=true.
    """
    from unifi.agents.optimize import apply_optimizations, generate_recommendations

    if not apply:
        return await generate_recommendations(site_id)
    return await apply_optimizations(site_id, apply=apply)


@mcp_server.tool()
async def unifi_secure(site_id: str = "default") -> str:
    """Security posture audit. Read-only.

    Analyzes firewall rules, zone-based firewall policies, ACLs,
    port forwards, and IDS/IPS alerts. Returns a risk-ranked report
    with severity-tiered findings (Critical > High > Warning > Informational).

    Args:
        site_id: The UniFi site ID. Defaults to "default".
    """
    from unifi.agents.security import security_audit

    return await security_audit(site_id)


@mcp_server.tool()
async def unifi_config(site_id: str = "default", drift: bool = False) -> str:
    """Config state review.

    Reviews current configuration state including network count, WLAN count,
    firewall rule count, and backup status.

    With ``drift=True``, diffs the current configuration against a stored
    baseline and reports any added, removed, or modified items.

    Args:
        site_id: The UniFi site ID. Defaults to "default".
        drift: If True, diff against stored baseline. Defaults to False.
    """
    from unifi.agents.config import config_review

    return await config_review(site_id, drift=drift)


# ---------------------------------------------------------------------------
# Port-profile commands (three-phase confirmation model)
# ---------------------------------------------------------------------------


async def _verify_vlans_exist(
    native_vlan: int,
    tagged_vlans_str: str,
    site_id: str,
) -> tuple[list[dict[str, Any]], list[int]]:
    """Phase 1: Verify that all referenced VLANs exist on the controller.

    Returns a tuple of (existing_vlans, missing_vlan_ids).  Each item in
    ``existing_vlans`` is a dict with ``id`` and ``name`` fields.
    """
    from unifi.tools.topology import unifi__topology__get_vlans

    vlans = await unifi__topology__get_vlans(site_id)

    # Build lookup by VLAN tag ID
    vlan_by_id: dict[int, dict[str, Any]] = {}
    for v in vlans:
        tag = v.get("vlan_id") or v.get("vlan")
        if tag is not None:
            vlan_by_id[int(tag)] = v
        # Default LAN (no VLAN tag) is conventionally VLAN 1
        if not v.get("vlan_enabled", False):
            vlan_by_id[1] = v

    # Collect all VLAN IDs we need to verify
    from unifi.tools.config import _parse_tagged_vlans

    requested_ids: list[int] = [native_vlan]
    for tag_str in _parse_tagged_vlans(tagged_vlans_str):
        with contextlib.suppress(ValueError):
            requested_ids.append(int(tag_str))

    existing: list[dict[str, Any]] = []
    missing: list[int] = []
    for vid in requested_ids:
        if vid in vlan_by_id:
            vlan_info = vlan_by_id[vid]
            existing.append({"id": vid, "name": vlan_info.get("name", f"VLAN {vid}")})
        else:
            missing.append(vid)

    return existing, missing


async def _lookup_switch(
    switch: str,
    site_id: str,
) -> dict[str, Any] | None:
    """Look up a switch device by name, MAC address, or device ID.

    Returns the device dict if found, or ``None``.
    """
    from unifi.tools.topology import unifi__topology__list_devices

    devices = await unifi__topology__list_devices(site_id)

    switch_lower = switch.lower().strip()
    for device in devices:
        # Match by _id, MAC, or name (case-insensitive)
        if (
            device.get("device_id", "").lower() == switch_lower
            or device.get("mac", "").lower() == switch_lower
            or device.get("name", "").lower() == switch_lower
        ):
            return device

    return None


async def _lookup_profile(
    profile_name: str,
    site_id: str,
) -> dict[str, Any] | None:
    """Look up a port profile by name.

    Returns a dict with ``_id`` and ``name``, or ``None``.
    """
    from unifi.tools.config import _get_client

    client = _get_client()
    try:
        portconf_resp = await client.get_normalized(
            f"/api/s/{site_id}/rest/portconf",
        )
    finally:
        await client.close()

    for profile in portconf_resp.data:
        if profile.get("name", "").strip().lower() == profile_name.strip().lower():
            return profile

    return None


@mcp_server.tool()
async def unifi_port_profile_create(
    name: str,
    native_vlan: int,
    tagged_vlans: str = "",
    poe: bool = False,
    site_id: str = "default",
    apply: bool = False,
) -> str:
    """Create a named switch port profile.

    Three-phase confirmation model:

    - **Phase 1:** Verify that the referenced VLANs exist on the controller.
    - **Phase 2:** Present a structured change plan for operator review.
    - **Phase 3:** Execute on confirmation (requires ``apply=True`` and
      ``UNIFI_WRITE_ENABLED=true``).

    Without ``apply``: returns a plan-only preview showing what would be
    created and whether VLANs exist.

    Args:
        name: Profile name (e.g., "Trunk-AP").
        native_vlan: Native/untagged VLAN ID (1-4094).
        tagged_vlans: Comma-separated tagged VLAN IDs (e.g., "30,50,60").
        poe: Enable PoE on ports using this profile.
        site_id: UniFi site ID. Defaults to "default".
        apply: If True, execute the write. Requires UNIFI_WRITE_ENABLED=true.
    """
    from unifi.ask import PlanStep, format_plan_confirmation
    from unifi.safety import check_write_enabled
    from unifi.tools.config import _parse_tagged_vlans

    # --- Phase 1: Verify VLANs exist ---
    existing_vlans, missing_vlans = await _verify_vlans_exist(
        native_vlan, tagged_vlans, site_id,
    )

    if missing_vlans:
        missing_str = ", ".join(str(v) for v in missing_vlans)
        return (
            f"## VLAN Verification Failed\n\n"
            f"The following VLAN IDs do not exist on the controller: "
            f"**{missing_str}**\n\n"
            f"Create these VLANs first, then retry."
        )

    # --- Phase 2: Present change plan ---
    tagged_list = _parse_tagged_vlans(tagged_vlans)
    tagged_display = ", ".join(tagged_list) if tagged_list else "(none)"
    vlan_names = {v["id"]: v["name"] for v in existing_vlans}
    native_name = vlan_names.get(native_vlan, f"VLAN {native_vlan}")

    steps = [
        PlanStep(
            number=1,
            system="unifi",
            action="Create port profile",
            detail=(
                f"Name: {name}, Native VLAN: {native_vlan} ({native_name}), "
                f"Tagged VLANs: {tagged_display}, PoE: {'enabled' if poe else 'disabled'}"
            ),
            expected_outcome=f"Port profile '{name}' available for assignment to switch ports.",
        ),
    ]

    plan = format_plan_confirmation(steps)

    if not apply:
        write_status = (
            "Write operations are enabled. Re-run with apply=True to execute."
            if check_write_enabled("UNIFI")
            else "Write operations are disabled. Set UNIFI_WRITE_ENABLED=true and use apply=True."
        )
        return f"{plan}\n\n---\n*Plan-only mode.* {write_status}"

    # --- Phase 3: Execute ---
    from unifi.tools.config import unifi__config__create_port_profile

    result = await unifi__config__create_port_profile(
        name=name,
        native_vlan=native_vlan,
        tagged_vlans=tagged_vlans,
        poe=poe,
        site_id=site_id,
        apply=True,
    )

    logger.info(
        "Port profile '%s' created via command layer (id=%s)",
        name,
        result.get("profile_id", ""),
        extra={"component": "commands"},
    )

    return (
        f"## Port Profile Created\n\n"
        f"- **Name:** {result['name']}\n"
        f"- **Profile ID:** {result['profile_id']}\n"
        f"- **Native VLAN:** {result['native_vlan']}\n"
        f"- **Tagged VLANs:** {', '.join(result['tagged_vlans']) or '(none)'}\n"
        f"- **PoE:** {'enabled' if result['poe'] else 'disabled'}\n"
        f"- **Site:** {result['site_id']}"
    )


@mcp_server.tool()
async def unifi_port_profile_assign(
    switch: str,
    port: str,
    profile: str,
    site_id: str = "default",
    apply: bool = False,
) -> str:
    """Assign a port profile to a specific switch port.

    Three-phase confirmation model:

    - **Phase 1:** Look up the switch device by name/MAC/ID and the profile
      by name. Determine the current profile assigned to the port.
    - **Phase 2:** Present a change plan showing current -> new profile.
      Includes an outage risk warning when the netex umbrella plugin is not
      installed.
    - **Phase 3:** Execute on confirmation (requires ``apply=True`` and
      ``UNIFI_WRITE_ENABLED=true``).

    WARNING: OutageRiskAgent assessment is unavailable when the netex umbrella
    plugin is not installed. The operator must manually ensure the target port
    does not carry their management session.

    Args:
        switch: Switch name, MAC address, or device ID.
        port: Port index (1-based) on the switch.
        profile: Name of the port profile to assign.
        site_id: UniFi site ID. Defaults to "default".
        apply: If True, execute the write. Requires UNIFI_WRITE_ENABLED=true.
    """
    from unifi.ask import PlanStep, format_plan_confirmation
    from unifi.errors import ValidationError
    from unifi.safety import check_write_enabled

    # --- Input validation ---
    try:
        port_idx = int(port)
    except (ValueError, TypeError) as exc:
        raise ValidationError(
            f"Invalid port: '{port}'. Must be a positive integer (1-based port index).",
            details={"field": "port", "value": str(port)},
        ) from exc

    if port_idx < 1:
        raise ValidationError(
            f"Invalid port: {port_idx}. Port indices are 1-based.",
            details={"field": "port", "value": port_idx},
        )

    # --- Phase 1: Look up switch and profile ---
    device = await _lookup_switch(switch, site_id)
    if device is None:
        return (
            f"## Switch Not Found\n\n"
            f"No switch matching '{switch}' was found on site '{site_id}'.\n\n"
            f"Use `unifi_scan` to list available devices."
        )

    device_id = device.get("device_id", "")
    device_name = device.get("name", device.get("mac", "unknown"))

    profile_data = await _lookup_profile(profile, site_id)
    if profile_data is None:
        return (
            f"## Profile Not Found\n\n"
            f"No port profile matching '{profile}' was found on site '{site_id}'.\n\n"
            f"Use `unifi_port_profile_create` to create one first."
        )

    profile_name = profile_data.get("name", profile)

    # Determine current profile for this port
    port_overrides = device.get("port_overrides", [])
    current_profile = "All (default)"
    for override in port_overrides:
        if override.get("port_idx") == port_idx:
            current_portconf_id = override.get("portconf_id", "")
            current_profile = current_portconf_id or "All (default)"
            break

    # --- Phase 2: Present change plan ---
    outage_warning = (
        "OutageRiskAgent assessment unavailable -- netex umbrella plugin not "
        "installed. Ensure this port does not carry your management session."
    )

    steps = [
        PlanStep(
            number=1,
            system="unifi",
            action="Assign port profile",
            detail=(
                f"Switch: {device_name}, Port: {port_idx}, "
                f"Current profile: {current_profile} -> New profile: {profile_name}"
            ),
            expected_outcome=(
                f"Port {port_idx} on {device_name} will use profile '{profile_name}'."
            ),
        ),
    ]

    plan = format_plan_confirmation(
        steps,
        outage_risk=outage_warning,
    )

    if not apply:
        write_status = (
            "Write operations are enabled. Re-run with apply=True to execute."
            if check_write_enabled("UNIFI")
            else "Write operations are disabled. Set UNIFI_WRITE_ENABLED=true and use apply=True."
        )
        return f"{plan}\n\n---\n*Plan-only mode.* {write_status}"

    # --- Phase 3: Execute ---
    from unifi.tools.topology import unifi__topology__assign_port_profile

    result = await unifi__topology__assign_port_profile(
        device_id=device_id,
        port_idx=port_idx,
        profile_name=profile_name,
        site_id=site_id,
        apply=True,
    )

    logger.info(
        "Port profile '%s' assigned to port %d on %s via command layer",
        profile_name,
        port_idx,
        device_name,
        extra={"component": "commands"},
    )

    return (
        f"## Port Profile Assigned\n\n"
        f"- **Switch:** {device_name}\n"
        f"- **Port:** {result['port_idx']}\n"
        f"- **Profile:** {result['profile_applied']}\n"
        f"- **Profile ID:** {result['profile_id']}\n"
        f"- **Site:** {result['site_id']}"
    )
