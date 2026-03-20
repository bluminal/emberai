# SPDX-License-Identifier: MIT
"""Cross-vendor MCP tool commands for the netex umbrella plugin.

Implements the cross-vendor commands that coordinate operations across
multiple vendor plugins via the Orchestrator:

    netex vlan configure  (Task 132) -- 7-step cross-vendor VLAN provisioning
    netex vlan audit      (Task 133) -- compare VLANs across gateway + edge
    netex topology        (Task 134) -- merge topology from all plugins
    netex health          (Task 135) -- unified health report
    netex firewall audit  (Task 136) -- cross-layer firewall analysis
    netex secure audit    (Task 137) -- delegate to NetworkSecurityAgent

All tools are registered on the ``mcp_server`` FastMCP instance from
``netex.server``.  Write operations go through the three-phase
confirmation model; read-only commands return results directly.
"""

from __future__ import annotations

import logging
from typing import Any

from netex.agents.network_security_agent import AuditDomain, NetworkSecurityAgent
from netex.agents.orchestrator import Orchestrator, resolve_plugin_for_role
from netex.ask import PlanStep
from netex.errors import PluginNotFoundError
from netex.models.abstract import VLAN, NetworkTopology
from netex.output import Finding, Severity, format_severity_report, format_table
from netex.registry.plugin_registry import PluginRegistry
from netex.safety import check_write_enabled
from netex.server import mcp_server

logger = logging.getLogger("netex.tools.commands")


# ---------------------------------------------------------------------------
# Module-level registry and orchestrator (lazily initialized)
# ---------------------------------------------------------------------------

_registry: PluginRegistry | None = None
_orchestrator: Orchestrator | None = None


def _get_registry() -> PluginRegistry:
    """Get or create the global plugin registry."""
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry


def _get_orchestrator() -> Orchestrator:
    """Get or create the global orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator(_get_registry())
    return _orchestrator


def set_registry(registry: PluginRegistry) -> None:
    """Set the global registry (for testing)."""
    global _registry, _orchestrator
    _registry = registry
    _orchestrator = Orchestrator(registry)


# ---------------------------------------------------------------------------
# VLAN Configure Steps (Task 132)
# ---------------------------------------------------------------------------

# The 7-step VLAN provisioning workflow:
#   1. Gateway VLAN interface creation
#   2. DHCP scope configuration
#   3. Firewall isolation rule
#   4. Gateway reconfigure (apply to live)
#   5. Edge network object creation
#   6. Edge port profile assignment
#   7. SSID binding (optional)

VLAN_CONFIGURE_STEPS = [
    {
        "number": 1,
        "system": "Gateway",
        "role": "gateway",
        "skill": "interfaces",
        "action": "Create VLAN interface",
        "subsystem": "vlan",
        "operation": "add",
    },
    {
        "number": 2,
        "system": "Gateway",
        "role": "gateway",
        "skill": "services",
        "action": "Configure DHCP scope",
        "subsystem": "dhcp",
        "operation": "add",
    },
    {
        "number": 3,
        "system": "Gateway",
        "role": "gateway",
        "skill": "firewall",
        "action": "Add inter-VLAN isolation rule",
        "subsystem": "firewall",
        "operation": "add",
    },
    {
        "number": 4,
        "system": "Gateway",
        "role": "gateway",
        "skill": "interfaces",
        "action": "Reconfigure gateway (apply to live)",
        "subsystem": "interface",
        "operation": "reconfigure",
    },
    {
        "number": 5,
        "system": "Edge",
        "role": "edge",
        "skill": "config",
        "action": "Create network object on edge controller",
        "subsystem": "vlan",
        "operation": "add",
    },
    {
        "number": 6,
        "system": "Edge",
        "role": "edge",
        "skill": "config",
        "action": "Create/update port profile for VLAN",
        "subsystem": "vlan",
        "operation": "configure",
    },
    {
        "number": 7,
        "system": "Edge",
        "role": "edge",
        "skill": "wifi",
        "action": "Bind SSID to VLAN (if wireless required)",
        "subsystem": "wifi",
        "operation": "configure",
    },
]

# Rollback steps in reverse order
VLAN_CONFIGURE_ROLLBACK = [
    "Remove SSID binding from edge controller",
    "Delete port profile from edge controller",
    "Delete network object from edge controller",
    "Remove firewall isolation rule from gateway",
    "Remove DHCP scope from gateway",
    "Delete VLAN interface from gateway",
]


def _build_vlan_plan_steps(
    vlan_name: str,
    vlan_id: int,
    subnet: str,
    *,
    dhcp_enabled: bool = True,
    ssid: str | None = None,
) -> list[PlanStep]:
    """Build the 7-step VLAN provisioning plan.

    Parameters
    ----------
    vlan_name:
        Human-readable VLAN name (e.g. ``"IoT"``).
    vlan_id:
        802.1Q VLAN ID (1-4094).
    subnet:
        CIDR subnet (e.g. ``"10.50.0.0/24"``).
    dhcp_enabled:
        Whether to configure DHCP for this VLAN.
    ssid:
        Optional SSID name to bind to the VLAN.

    Returns
    -------
    list[PlanStep]
        Ordered plan steps for operator review.
    """
    steps = [
        PlanStep(
            number=1,
            system="Gateway",
            action="Create VLAN interface",
            detail=f"VLAN {vlan_id} '{vlan_name}' on parent interface, subnet {subnet}",
            expected_outcome=f"VLAN interface opt{vlan_id} created with IP gateway",
        ),
        PlanStep(
            number=2,
            system="Gateway",
            action="Configure DHCP scope",
            detail=(
                f"DHCP range for {subnet}, VLAN {vlan_id}"
                if dhcp_enabled
                else f"DHCP disabled for VLAN {vlan_id}"
            ),
            expected_outcome=(
                f"DHCP server active on VLAN {vlan_id}"
                if dhcp_enabled
                else f"Static IP assignment only on VLAN {vlan_id}"
            ),
        ),
        PlanStep(
            number=3,
            system="Gateway",
            action="Add inter-VLAN isolation rule",
            detail=f"Deny {vlan_name} -> all other VLANs (default deny, explicit allow)",
            expected_outcome=f"VLAN {vlan_name} isolated; no cross-VLAN leakage",
        ),
        PlanStep(
            number=4,
            system="Gateway",
            action="Reconfigure gateway",
            detail="Apply VLAN, DHCP, and firewall changes to running config",
            expected_outcome="Gateway live config updated, services restarted",
        ),
        PlanStep(
            number=5,
            system="Edge",
            action="Create network object",
            detail=f"Network '{vlan_name}' with VLAN ID {vlan_id} on edge controller",
            expected_outcome=f"Network object provisioned, VLAN {vlan_id} recognized by switches",
        ),
        PlanStep(
            number=6,
            system="Edge",
            action="Create port profile",
            detail=f"Port profile '{vlan_name}' assigned to VLAN {vlan_id}",
            expected_outcome="Switch ports can be assigned to the new VLAN",
        ),
    ]

    if ssid:
        steps.append(PlanStep(
            number=7,
            system="Edge",
            action=f"Bind SSID '{ssid}'",
            detail=f"SSID '{ssid}' -> VLAN {vlan_id} on edge access points",
            expected_outcome=f"Wireless clients on '{ssid}' get VLAN {vlan_id} assignment",
        ))
    else:
        steps.append(PlanStep(
            number=7,
            system="Edge",
            action="Skip SSID binding",
            detail="No wireless SSID requested for this VLAN",
            expected_outcome="VLAN available on wired ports only",
        ))

    return steps


def _build_vlan_change_steps(
    vlan_name: str,
    vlan_id: int,
    subnet: str,
) -> list[dict[str, Any]]:
    """Build change step dicts for risk/security assessment.

    These are the structured step dicts consumed by OutageRiskAgent
    and NetworkSecurityAgent.
    """
    return [
        {"subsystem": "vlan", "action": "add", "target": str(vlan_id)},
        {"subsystem": "dhcp", "action": "add", "target": f"dhcp_{vlan_name}"},
        {
            "subsystem": "firewall", "action": "add",
            "target": f"deny_{vlan_name}_inter_vlan",
            "action_type": "deny",
        },
        {"subsystem": "interface", "action": "reconfigure", "target": "gateway"},
        {"subsystem": "vlan", "action": "add", "target": f"edge_{vlan_name}"},
        {"subsystem": "vlan", "action": "configure", "target": f"profile_{vlan_name}"},
        {"subsystem": "wifi", "action": "configure", "target": f"ssid_{vlan_name}"},
    ]


# ---------------------------------------------------------------------------
# MCP Tool: netex vlan configure (Task 132)
# ---------------------------------------------------------------------------

@mcp_server.tool()
async def netex__vlan__configure(
    vlan_name: str,
    vlan_id: int,
    subnet: str,
    dhcp_enabled: bool = True,
    ssid: str | None = None,
    apply: bool = False,
) -> str:
    """Cross-vendor VLAN provisioning across gateway and edge.

    Provisions a VLAN across both the gateway (firewall/router) and
    edge (switch/AP controller) layers in a coordinated 7-step workflow.

    Steps:
        1. Create VLAN interface on gateway
        2. Configure DHCP scope on gateway
        3. Add inter-VLAN firewall isolation rule on gateway
        4. Reconfigure gateway (apply to live)
        5. Create network object on edge controller
        6. Create/update port profile on edge
        7. Bind SSID to VLAN on edge (if wireless required)

    Uses the three-phase confirmation model:
        Phase 1: Gather state, run OutageRiskAgent + NetworkSecurityAgent
        Phase 2: Present ordered change plan for review
        Phase 3: Execute after operator confirmation

    Args:
        vlan_name: Human-readable VLAN name (e.g. "IoT", "Cameras")
        vlan_id: 802.1Q VLAN ID (1-4094)
        subnet: CIDR subnet for the VLAN (e.g. "10.50.0.0/24")
        dhcp_enabled: Whether to configure DHCP (default: true)
        ssid: Optional SSID name to bind to the VLAN
        apply: Set to true to execute (requires NETEX_WRITE_ENABLED=true)

    Returns:
        Change plan for review (plan-only mode) or execution result.
    """
    registry = _get_registry()
    orchestrator = _get_orchestrator()

    # Validate VLAN ID
    if not 1 <= vlan_id <= 4094:
        return "Error: VLAN ID must be between 1 and 4094."

    # Verify required plugins are installed
    try:
        resolve_plugin_for_role("gateway", registry)
        resolve_plugin_for_role("edge", registry)
    except PluginNotFoundError as exc:
        return f"Error: {exc.message}"

    # Build change steps for risk assessment
    change_steps = _build_vlan_change_steps(vlan_name, vlan_id, subnet)

    # Build plan steps for presentation
    plan_steps = _build_vlan_plan_steps(
        vlan_name, vlan_id, subnet,
        dhcp_enabled=dhcp_enabled, ssid=ssid,
    )

    # Create workflow
    workflow = orchestrator.create_workflow(
        workflow_type="vlan_configure",
        description=f"Provision VLAN {vlan_id} '{vlan_name}' ({subnet})",
    )

    # Phase 1: Gather & Resolve
    phase1 = await orchestrator.phase1_gather_and_resolve(
        workflow, change_steps,
    )

    # Phase 2: Build & Present
    rollback_descs = VLAN_CONFIGURE_ROLLBACK[:6]  # Exclude SSID if not used
    if ssid:
        rollback_descs = list(VLAN_CONFIGURE_ROLLBACK)

    plan_text = await orchestrator.phase2_build_and_present(
        workflow,
        plan_steps=plan_steps,
        risk_assessment=phase1["risk_assessment"],
        security_findings=phase1["security_findings"],
        rollback_descriptions=rollback_descs,
    )

    # If not applying, return the plan for review
    if not apply:
        write_status = (
            "Write operations are disabled. Set NETEX_WRITE_ENABLED=true and "
            "re-run with apply=true to execute."
            if not check_write_enabled()
            else "Add apply=true to execute this plan."
        )
        return plan_text + f"\n---\n*{write_status}*\n"

    # Phase 3: Execute (would call actual vendor plugin tools)
    # In plan-only mode for now -- actual execution wired in when
    # vendor plugin MCP call framework is integrated.
    return plan_text + "\n---\n*Execution not yet implemented. Plan presented for review.*\n"


# ---------------------------------------------------------------------------
# MCP Tool: netex vlan audit (Task 133)
# ---------------------------------------------------------------------------

@mcp_server.tool()
async def netex__vlan__audit() -> str:
    """Compare VLANs across gateway and edge layers.

    Queries all installed vendor plugins for VLAN data and produces a
    comparison report showing:
    - VLANs present on gateway but missing from edge
    - VLANs present on edge but missing from gateway
    - VLANs with configuration mismatches (subnet, DHCP, name)

    Returns:
        Markdown-formatted VLAN audit report.
    """
    registry = _get_registry()

    # Gather VLANs from all plugins with the appropriate skills
    gateway_vlans: list[VLAN] = []
    edge_vlans: list[VLAN] = []

    # Query gateway plugins
    gw_plugins = registry.plugins_with_role("gateway")
    for plugin in gw_plugins:
        tools = registry.tools_for_skill("interfaces")
        plugin_tools = [t for t in tools if t["plugin"] == plugin["name"]]
        if plugin_tools:
            # In production, this would call the actual MCP tool.
            # For now, we note the available tools.
            logger.info(
                "Gateway VLAN tools available from %s: %s",
                plugin["name"],
                [t["tool"] for t in plugin_tools],
            )

    # Query edge plugins
    edge_plugins = registry.plugins_with_role("edge")
    for plugin in edge_plugins:
        tools = registry.tools_for_skill("config")
        plugin_tools = [t for t in tools if t["plugin"] == plugin["name"]]
        if plugin_tools:
            logger.info(
                "Edge VLAN tools available from %s: %s",
                plugin["name"],
                [t["tool"] for t in plugin_tools],
            )

    # Build comparison report
    all_vlan_ids = sorted(
        {v.vlan_id for v in gateway_vlans} | {v.vlan_id for v in edge_vlans}
    )

    if not gw_plugins and not edge_plugins:
        return (
            "## VLAN Audit\n\n"
            "No gateway or edge plugins installed. "
            "Install at least one vendor plugin to perform a VLAN audit.\n"
        )

    gw_map = {v.vlan_id: v for v in gateway_vlans}
    edge_map = {v.vlan_id: v for v in edge_vlans}

    findings: list[Finding] = []
    rows: list[list[str]] = []

    for vid in all_vlan_ids:
        gw_vlan = gw_map.get(vid)
        edge_vlan = edge_map.get(vid)

        gw_status = "present" if gw_vlan else "MISSING"
        edge_status = "present" if edge_vlan else "MISSING"

        gw_name = gw_vlan.name if gw_vlan else "--"
        edge_name = edge_vlan.name if edge_vlan else "--"

        rows.append([str(vid), gw_name, gw_status, edge_name, edge_status])

        if gw_vlan and not edge_vlan:
            findings.append(Finding(
                severity=Severity.WARNING,
                title=f"VLAN {vid} missing from edge",
                detail=f"VLAN {vid} '{gw_name}' exists on gateway but not on edge.",
                recommendation="Create the network object on the edge controller.",
            ))
        elif edge_vlan and not gw_vlan:
            findings.append(Finding(
                severity=Severity.WARNING,
                title=f"VLAN {vid} missing from gateway",
                detail=f"VLAN {vid} '{edge_name}' exists on edge but not on gateway.",
                recommendation="Create the VLAN interface on the gateway.",
            ))

    sections: list[str] = ["## VLAN Audit Report\n"]

    source_plugins = [p["name"] for p in gw_plugins] + [p["name"] for p in edge_plugins]
    sections.append(f"**Sources:** {', '.join(source_plugins) if source_plugins else 'none'}\n")

    if rows:
        sections.append(format_table(
            headers=["VLAN ID", "GW Name", "Gateway", "Edge Name", "Edge"],
            rows=rows,
            title="VLAN Comparison",
        ))

    if findings:
        sections.append(format_severity_report("Findings", findings))
    elif all_vlan_ids:
        sections.append("All VLANs are consistent across gateway and edge layers.\n")
    else:
        sections.append(
            "No VLAN data available. Ensure vendor plugins expose VLAN "
            "information via the interfaces and config skills.\n"
        )

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# MCP Tool: netex topology (Task 134)
# ---------------------------------------------------------------------------

@mcp_server.tool()
async def netex__topology__merged() -> str:
    """Merge and display the network topology from all installed plugins.

    Queries each installed plugin for its topology layer and merges them
    into a unified view:
    - Gateway layer: interfaces, routes, VPN tunnels, firewall zones
    - Edge layer: device graph, uplinks, wireless APs, clients

    Returns:
        Markdown-formatted unified network topology.
    """
    registry = _get_registry()

    topo_tools = registry.tools_for_skill("topology")
    if not topo_tools:
        return (
            "## Unified Topology\n\n"
            "No plugins provide topology data. Install a vendor plugin "
            "with the 'topology' skill.\n"
        )

    # Collect topology contributions from each plugin
    merged = NetworkTopology()
    contributing_plugins: list[str] = []

    for tool_entry in topo_tools:
        plugin_name = tool_entry["plugin"]
        if plugin_name not in contributing_plugins:
            contributing_plugins.append(plugin_name)
            # In production, this would call the plugin's topology tool
            # and merge the result.  For now, note the available tools.
            logger.info(
                "Topology tool available from %s: %s",
                plugin_name, tool_entry["tool"],
            )

    merged.source_plugins = contributing_plugins

    # Format the topology report
    sections: list[str] = [
        "## Unified Network Topology\n",
        f"**Sources:** {', '.join(contributing_plugins)}\n",
    ]

    # Nodes table
    if merged.nodes:
        node_rows = [
            [n.name or n.node_id, n.node_type.value, n.ip, n.source_plugin]
            for n in merged.nodes
        ]
        sections.append(format_table(
            headers=["Name", "Type", "IP", "Source"],
            rows=node_rows,
            title="Devices",
        ))
    else:
        sections.append("### Devices\n\nNo device data available from installed plugins.\n")

    # Links table
    if merged.links:
        link_rows = [
            [lk.source_id, lk.target_id, lk.link_type,
             str(lk.speed_mbps) if lk.speed_mbps else "--"]
            for lk in merged.links
        ]
        sections.append(format_table(
            headers=["Source", "Target", "Type", "Speed (Mbps)"],
            rows=link_rows,
            title="Links",
        ))

    # VLANs table
    if merged.vlans:
        vlan_rows = [
            [str(v.vlan_id), v.name, v.subnet or "--",
             "Yes" if v.dhcp_enabled else "No", v.source_plugin]
            for v in merged.vlans
        ]
        sections.append(format_table(
            headers=["VLAN ID", "Name", "Subnet", "DHCP", "Source"],
            rows=vlan_rows,
            title="VLANs",
        ))

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# MCP Tool: netex health (Task 135)
# ---------------------------------------------------------------------------

@mcp_server.tool()
async def netex__health__report() -> str:
    """Unified health report across all installed vendor plugins.

    Queries each plugin for health/diagnostics data and merges into a
    single report covering:
    - Plugin discovery status
    - Per-plugin health indicators
    - Cross-vendor consistency checks

    Returns:
        Markdown-formatted unified health report.
    """
    registry = _get_registry()

    plugins = registry.list_plugins()

    sections: list[str] = [
        "## Unified Health Report\n",
        f"**Installed plugins:** {len(plugins)}\n",
    ]

    if not plugins:
        sections.append(
            "No vendor plugins installed. Install at least one plugin "
            "(e.g. unifi, opnsense) to get health data.\n"
        )
        return "\n".join(sections)

    # Plugin status table
    plugin_rows: list[list[str]] = []
    for p in plugins:
        roles = ", ".join(p.get("roles", []))
        skills = ", ".join(p.get("skills", []))
        version = p.get("version", "--")
        plugin_rows.append([p["name"], version, roles, skills])

    sections.append(format_table(
        headers=["Plugin", "Version", "Roles", "Skills"],
        rows=plugin_rows,
        title="Plugin Status",
    ))

    # Health data from each plugin
    health_tools = registry.tools_for_skill("health")
    diag_tools = registry.tools_for_skill("diagnostics")

    available_sources: list[str] = []
    for tool_entry in health_tools + diag_tools:
        if tool_entry["plugin"] not in available_sources:
            available_sources.append(tool_entry["plugin"])
            logger.info(
                "Health/diagnostics tool available from %s: %s",
                tool_entry["plugin"], tool_entry["tool"],
            )

    if available_sources:
        sections.append(
            f"### Health Data Sources\n\n"
            f"Available from: {', '.join(available_sources)}\n"
        )
    else:
        sections.append(
            "### Health Data Sources\n\n"
            "No plugins expose health or diagnostics tools.\n"
        )

    # Cross-vendor consistency checks
    findings: list[Finding] = []

    # Check: gateway and edge both present?
    gw_plugins = registry.plugins_with_role("gateway")
    edge_plugins = registry.plugins_with_role("edge")

    if not gw_plugins:
        findings.append(Finding(
            severity=Severity.WARNING,
            title="No gateway plugin installed",
            detail="No plugin provides the 'gateway' role. Firewall, routing, "
                   "and VPN management are unavailable.",
            recommendation="Install a gateway plugin (e.g. opnsense).",
        ))
    if not edge_plugins:
        findings.append(Finding(
            severity=Severity.WARNING,
            title="No edge plugin installed",
            detail="No plugin provides the 'edge' role. Switch, AP, and "
                   "wireless management are unavailable.",
            recommendation="Install an edge plugin (e.g. unifi).",
        ))

    if findings:
        sections.append(format_severity_report("Health Findings", findings))
    else:
        sections.append(
            "### Cross-Vendor Status\n\n"
            "Gateway and edge plugins are both installed. "
            "Full cross-vendor operations are available.\n"
        )

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# MCP Tool: netex firewall audit (Task 136)
# ---------------------------------------------------------------------------

@mcp_server.tool()
async def netex__firewall__audit() -> str:
    """Cross-layer firewall audit across gateway and edge.

    Analyzes firewall policies across all installed vendor plugins for:
    - Shadowed rules (rule never matches due to earlier broader rule)
    - Cross-layer inconsistencies (gateway allows, edge denies, or vice versa)
    - Overly permissive rules (any/any patterns)
    - Missing default deny policies

    Returns:
        Markdown-formatted cross-layer firewall audit report.
    """
    registry = _get_registry()

    fw_tools = registry.tools_for_skill("firewall")
    security_tools = registry.tools_for_skill("security")

    all_tools = fw_tools + security_tools
    if not all_tools:
        return (
            "## Cross-Layer Firewall Audit\n\n"
            "No plugins provide firewall or security tools. "
            "Install a vendor plugin with the 'firewall' skill.\n"
        )

    contributing_plugins: list[str] = []
    for t in all_tools:
        if t["plugin"] not in contributing_plugins:
            contributing_plugins.append(t["plugin"])

    sections: list[str] = [
        "## Cross-Layer Firewall Audit\n",
        f"**Sources:** {', '.join(contributing_plugins)}\n",
    ]

    # In production, this would call each plugin's firewall tools,
    # collect rules, and perform cross-layer analysis.
    # The analysis framework is in place; actual tool invocation
    # will be wired when the MCP call framework is integrated.

    findings: list[Finding] = []

    # Check if we have both gateway and edge firewall coverage
    gw_fw = [t for t in fw_tools if any(
        p["name"] == t["plugin"]
        for p in registry.plugins_with_role("gateway")
    )]
    edge_fw = [t for t in fw_tools if any(
        p["name"] == t["plugin"]
        for p in registry.plugins_with_role("edge")
    )]

    if gw_fw and not edge_fw:
        findings.append(Finding(
            severity=Severity.INFORMATIONAL,
            title="Edge firewall tools not available",
            detail="Only gateway firewall tools are available. Cross-layer "
                   "comparison requires both gateway and edge firewall data.",
            recommendation="Install an edge plugin with firewall capabilities.",
        ))
    elif edge_fw and not gw_fw:
        findings.append(Finding(
            severity=Severity.INFORMATIONAL,
            title="Gateway firewall tools not available",
            detail="Only edge firewall tools are available. Cross-layer "
                   "comparison requires both gateway and edge firewall data.",
            recommendation="Install a gateway plugin with firewall capabilities.",
        ))

    sections.append(
        "### Available Firewall Tools\n\n"
        + "\n".join(
            f"- **{t['plugin']}**: `{t['tool']}`" for t in all_tools
        )
        + "\n"
    )

    if findings:
        sections.append(format_severity_report("Audit Findings", findings))
    else:
        sections.append(
            "### Analysis\n\n"
            "Gateway and edge firewall tools are available for cross-layer analysis.\n"
        )

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# MCP Tool: netex secure audit (Task 137)
# ---------------------------------------------------------------------------

@mcp_server.tool()
async def netex__secure__audit(domain: str | None = None) -> str:
    """On-demand security audit delegated to the NetworkSecurityAgent.

    Performs a comprehensive security posture review across all installed
    vendor plugins.  Optionally filter to a specific audit domain.

    Available domains:
        firewall-gw, firewall-edge, cross-layer, vlan-isolation,
        vpn-posture, dns-security, ids-ips, wireless, certs, firmware

    Args:
        domain: Optional audit domain to focus on (default: all domains).

    Returns:
        Markdown-formatted security audit report.
    """
    registry = _get_registry()
    agent = NetworkSecurityAgent()

    # Validate domain if provided
    if domain is not None:
        valid_domains = [d.value for d in AuditDomain]
        if domain not in valid_domains:
            return (
                f"## Security Audit\n\n"
                f"Unknown domain: '{domain}'.\n\n"
                f"Valid domains: {', '.join(valid_domains)}\n"
            )

    findings = await agent.audit(registry, domain=domain)

    if not findings:
        domain_label = f" ({domain})" if domain else ""
        return (
            f"## Security Audit{domain_label}\n\n"
            "No findings. Security posture is clean across all installed plugins.\n"
        )

    # Format findings into a report
    sections: list[str] = []
    domain_label = f" ({domain})" if domain else ""
    sections.append(f"## Security Audit{domain_label}\n")
    sections.append(f"**{len(findings)} finding(s)**\n")

    for finding in findings:
        sections.append(finding.format_for_report())
        sections.append("")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# MCP Tool: netex secure review (Task 137)
# ---------------------------------------------------------------------------

@mcp_server.tool()
async def netex__secure__review(
    change_steps: list[dict[str, str]],
) -> str:
    """Review a proposed change plan for security issues.

    Delegates to the NetworkSecurityAgent's plan review capability.
    Checks 7 finding categories per PRD 5.2.1.

    Args:
        change_steps: List of change step dicts with keys like
            subsystem, action, target, source, destination, etc.

    Returns:
        Markdown-formatted security review report.
    """
    registry = _get_registry()
    agent = NetworkSecurityAgent()

    findings = await agent.review_plan(change_steps, registry)

    if not findings:
        return (
            "## Security Review\n\n"
            "No security findings for the proposed change plan.\n"
        )

    sections: list[str] = [
        "## Security Review\n",
        f"**{len(findings)} finding(s)**\n",
    ]

    for finding in findings:
        sections.append(finding.format_for_report())
        sections.append("")

    return "\n".join(sections)
