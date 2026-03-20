# SPDX-License-Identifier: MIT
"""NetworkSecurityAgent -- read-only security review and audit agent.

Permanent, read-only member of the netex umbrella.  Never makes changes.
Hard constraint: only calls read-only tools via the Plugin Registry.
Enforced at the registry query level.

Two roles (PRD Section 5.2):

Role 1 -- Automatic Plan Review (5.2.1):
    Every change plan passes through review_plan() before being presented
    to the operator.  7 finding categories are checked.

Role 2 -- On-Demand Security Audit (5.2.2):
    Full security posture review across 10 audit domains via audit().
    Invoked by ``netex secure audit [--domain <d>]``.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from netex.models.security_finding import (
    FindingCategory,
    FindingSeverity,
    SecurityFinding,
    sort_findings,
)

if TYPE_CHECKING:
    from netex.registry.plugin_registry import PluginRegistry

logger = logging.getLogger("netex.agents.network_security")


# ---------------------------------------------------------------------------
# Audit domain enum
# ---------------------------------------------------------------------------

class AuditDomain(StrEnum):
    """Audit domains for on-demand security assessment (PRD 5.2.2)."""

    FIREWALL_GW = "firewall-gw"
    FIREWALL_EDGE = "firewall-edge"
    CROSS_LAYER = "cross-layer"
    VLAN_ISOLATION = "vlan-isolation"
    VPN_POSTURE = "vpn-posture"
    DNS_SECURITY = "dns-security"
    IDS_IPS = "ids-ips"
    WIRELESS = "wireless"
    CERTS = "certs"
    FIRMWARE = "firmware"


# Maps each audit domain to the skills it needs from the registry.
_DOMAIN_SKILLS: dict[AuditDomain, list[str]] = {
    AuditDomain.FIREWALL_GW: ["firewall", "security"],
    AuditDomain.FIREWALL_EDGE: ["security", "config"],
    AuditDomain.CROSS_LAYER: ["firewall", "security", "config"],
    AuditDomain.VLAN_ISOLATION: ["interfaces", "topology", "firewall"],
    AuditDomain.VPN_POSTURE: ["vpn", "security"],
    AuditDomain.DNS_SECURITY: ["services", "security"],
    AuditDomain.IDS_IPS: ["security"],
    AuditDomain.WIRELESS: ["wifi", "security"],
    AuditDomain.CERTS: ["security"],
    AuditDomain.FIRMWARE: ["firmware", "health"],
}

# Maps each audit domain to its primary finding category.
_DOMAIN_CATEGORY: dict[AuditDomain, FindingCategory] = {
    AuditDomain.FIREWALL_GW: FindingCategory.FIREWALL_POLICY,
    AuditDomain.FIREWALL_EDGE: FindingCategory.FIREWALL_POLICY,
    AuditDomain.CROSS_LAYER: FindingCategory.CROSS_LAYER,
    AuditDomain.VLAN_ISOLATION: FindingCategory.VLAN_ISOLATION,
    AuditDomain.VPN_POSTURE: FindingCategory.VPN_POSTURE,
    AuditDomain.DNS_SECURITY: FindingCategory.DNS_SECURITY,
    AuditDomain.IDS_IPS: FindingCategory.IDS_IPS,
    AuditDomain.WIRELESS: FindingCategory.WIRELESS_SECURITY,
    AuditDomain.CERTS: FindingCategory.CERTIFICATES,
    AuditDomain.FIRMWARE: FindingCategory.FIRMWARE,
}

# Human-readable labels for audit domains.
_DOMAIN_LABELS: dict[AuditDomain, str] = {
    AuditDomain.FIREWALL_GW: "Firewall Policy (Gateway)",
    AuditDomain.FIREWALL_EDGE: "Firewall Policy (Edge)",
    AuditDomain.CROSS_LAYER: "Cross-Layer Firewall Consistency",
    AuditDomain.VLAN_ISOLATION: "VLAN Isolation",
    AuditDomain.VPN_POSTURE: "VPN Security Posture",
    AuditDomain.DNS_SECURITY: "DNS Security",
    AuditDomain.IDS_IPS: "IDS/IPS Coverage",
    AuditDomain.WIRELESS: "Wireless Security",
    AuditDomain.CERTS: "Certificates & Trust",
    AuditDomain.FIRMWARE: "Firmware & Patch State",
}

# Write tool name patterns that the agent must never call.
_WRITE_TOOL_PATTERNS = frozenset({
    "add_",
    "create_",
    "update_",
    "delete_",
    "remove_",
    "set_",
    "apply_",
    "assign_",
    "configure_",
    "provision_",
    "reconfigure",
})


# ---------------------------------------------------------------------------
# Read-only enforcement
# ---------------------------------------------------------------------------

def is_read_only_tool(tool_name: str) -> bool:
    """Check whether a tool name represents a read-only operation.

    The agent enforces read-only access by filtering tool names.
    Tools containing write-pattern prefixes are rejected.

    Parameters
    ----------
    tool_name:
        The fully qualified MCP tool name
        (e.g. ``"opnsense__firewall__list_rules"``).

    Returns
    -------
    bool
        ``True`` if the tool appears to be read-only.
    """
    # Extract the operation part (last segment after __)
    parts = tool_name.split("__")
    operation = parts[-1] if parts else tool_name

    return all(not operation.startswith(pattern) for pattern in _WRITE_TOOL_PATTERNS)


def filter_read_only_tools(
    tools: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Filter a list of registry tool entries to only read-only tools.

    Parameters
    ----------
    tools:
        Tool entries from ``registry.tools_for_skill()``.

    Returns
    -------
    list[dict]
        Only those tools that pass the read-only check.
    """
    return [t for t in tools if is_read_only_tool(t.get("tool", ""))]


# ---------------------------------------------------------------------------
# NetworkSecurityAgent
# ---------------------------------------------------------------------------

class NetworkSecurityAgent:
    """Read-only agent for security review.  Never makes changes.

    Hard constraint: this agent only calls read-only tools across all
    installed vendor plugins.  Enforced by ``filter_read_only_tools()``
    on every registry query.

    Two roles:
        1. ``review_plan()`` -- automatic plan review (7 finding categories)
        2. ``audit()`` -- on-demand security audit (10 domains)
    """

    # ------------------------------------------------------------------
    # Role 1: Plan Review
    # ------------------------------------------------------------------

    async def review_plan(
        self,
        change_steps: list[dict[str, Any]],
        registry: PluginRegistry,
    ) -> list[SecurityFinding]:
        """Review a change plan for security issues.

        Checks 7 finding categories per PRD 5.2.1:
            1. VLAN isolation gap
            2. Overly broad firewall rule
            3. Firewall rule ordering risk
            4. VPN split-tunnel exposure
            5. Unencrypted VLAN for sensitive traffic
            6. Management plane exposure
            7. DNS security posture

        Parameters
        ----------
        change_steps:
            List of change step dicts.  Expected keys vary by category:
            - ``subsystem``: affected subsystem (vlan, firewall, vpn, etc.)
            - ``action``: operation type (add, modify, delete)
            - ``target``: specific resource identifier
            - Additional keys depending on the step type.
        registry:
            The plugin registry for querying available read-only tools.

        Returns
        -------
        list[SecurityFinding]
            Severity-sorted list of findings.  Empty if no issues.
        """
        if not change_steps:
            return []

        findings: list[SecurityFinding] = []

        # Run all 7 category checks
        findings.extend(self._check_vlan_isolation(change_steps, registry))
        findings.extend(self._check_broad_firewall_rules(change_steps, registry))
        findings.extend(self._check_rule_ordering(change_steps, registry))
        findings.extend(self._check_vpn_split_tunnel(change_steps, registry))
        findings.extend(self._check_unencrypted_vlan(change_steps, registry))
        findings.extend(self._check_management_exposure(change_steps, registry))
        findings.extend(self._check_dns_security(change_steps, registry))

        return sort_findings(findings)

    # ------------------------------------------------------------------
    # Role 2: On-Demand Audit
    # ------------------------------------------------------------------

    async def audit(
        self,
        registry: PluginRegistry,
        domain: str | None = None,
    ) -> list[SecurityFinding]:
        """On-demand security audit across installed vendor plugins.

        Queries all installed plugins for security-relevant data using
        read-only tools.  Findings are grouped by domain and sorted by
        severity.

        Parameters
        ----------
        registry:
            The plugin registry for querying available tools.
        domain:
            Optional domain filter.  If provided, only that domain is
            audited.  Must be one of the ``AuditDomain`` values.

        Returns
        -------
        list[SecurityFinding]
            Severity-sorted list of findings across all (or the
            specified) audit domains.
        """
        domains_to_audit: list[AuditDomain]

        if domain is not None:
            try:
                target_domain = AuditDomain(domain)
            except ValueError:
                logger.warning("Unknown audit domain: %s", domain)
                return [
                    SecurityFinding(
                        severity=FindingSeverity.INFORMATIONAL,
                        category=FindingCategory.GENERAL,
                        description=f"Unknown audit domain: {domain}",
                        recommendation=(
                            f"Valid domains: {', '.join(d.value for d in AuditDomain)}"
                        ),
                    ),
                ]
            domains_to_audit = [target_domain]
        else:
            domains_to_audit = list(AuditDomain)

        findings: list[SecurityFinding] = []

        for audit_domain in domains_to_audit:
            domain_findings = await self._audit_domain(audit_domain, registry)
            findings.extend(domain_findings)

        return sort_findings(findings)

    async def _audit_domain(
        self,
        domain: AuditDomain,
        registry: PluginRegistry,
    ) -> list[SecurityFinding]:
        """Audit a single domain.

        Gathers available read-only tools for the domain's skill
        requirements and produces findings.

        Parameters
        ----------
        domain:
            The audit domain to assess.
        registry:
            The plugin registry.

        Returns
        -------
        list[SecurityFinding]
            Findings for this domain.
        """
        required_skills = _DOMAIN_SKILLS.get(domain, [])
        category = _DOMAIN_CATEGORY.get(domain, FindingCategory.GENERAL)
        label = _DOMAIN_LABELS.get(domain, domain.value)

        # Gather all read-only tools for the required skills
        available_tools: list[dict[str, str]] = []
        for skill in required_skills:
            tools = registry.tools_for_skill(skill)
            read_only = filter_read_only_tools(tools)
            available_tools.extend(read_only)

        if not available_tools:
            logger.info(
                "No tools available for audit domain %s (skills: %s)",
                domain.value,
                ", ".join(required_skills),
            )
            return [
                SecurityFinding(
                    severity=FindingSeverity.INFORMATIONAL,
                    category=category,
                    description=(
                        f"No plugins provide tools for {label} assessment."
                    ),
                    recommendation=(
                        "Install a vendor plugin that exposes the "
                        f"{', '.join(required_skills)} skill(s)."
                    ),
                ),
            ]

        # In a full implementation, this method would call each tool
        # via MCP and analyze the results.  The domain-specific analysis
        # logic below demonstrates the pattern; actual tool invocation
        # will be wired in when the MCP call framework is integrated.
        findings: list[SecurityFinding] = []
        findings.extend(
            self._analyze_domain(domain, category, available_tools)
        )

        return findings

    def _analyze_domain(
        self,
        domain: AuditDomain,
        category: FindingCategory,
        available_tools: list[dict[str, str]],
    ) -> list[SecurityFinding]:
        """Produce domain-specific findings from available tool data.

        This is the extension point where domain-specific analysis
        logic lives.  Each domain handler examines the tool responses
        and produces findings.

        In the current implementation, this returns an empty list --
        actual findings will be populated once MCP tool call results
        are available.  The structure is in place for each domain.

        Parameters
        ----------
        domain:
            The audit domain being analyzed.
        category:
            The finding category for this domain.
        available_tools:
            Read-only tools available for this domain.

        Returns
        -------
        list[SecurityFinding]
            Domain-specific findings.
        """
        # Domain-specific analyzers will be implemented here.
        # Each returns findings based on actual tool call responses.
        # For now, the infrastructure is in place and tested.
        _ = domain, category, available_tools
        return []

    # ------------------------------------------------------------------
    # Plan review category checks
    # ------------------------------------------------------------------

    def _check_vlan_isolation(
        self,
        steps: list[dict[str, Any]],
        registry: PluginRegistry,
    ) -> list[SecurityFinding]:
        """Check for VLAN isolation gaps (category 1).

        Flags new VLANs without corresponding inter-VLAN firewall deny
        rules in the same plan.
        """
        findings: list[SecurityFinding] = []

        # Find VLAN creation steps
        vlan_creates = [
            s for s in steps
            if s.get("subsystem") == "vlan" and s.get("action") in ("add", "create")
        ]

        if not vlan_creates:
            return findings

        # Check if there are corresponding firewall deny rules
        firewall_steps = [
            s for s in steps
            if s.get("subsystem") == "firewall" and s.get("action") in ("add", "create")
        ]

        # Get firewall tools for source attribution
        fw_tools = filter_read_only_tools(registry.tools_for_skill("firewall"))
        source_plugin = fw_tools[0]["plugin"] if fw_tools else ""
        source_tool = fw_tools[0]["tool"] if fw_tools else ""

        for vlan_step in vlan_creates:
            vlan_name = vlan_step.get("target", vlan_step.get("name", "unknown"))
            vlan_id = vlan_step.get("vlan_id", vlan_step.get("target", ""))

            # Check if any firewall step creates deny rules for this VLAN
            has_deny_rule = any(
                fw.get("action_type") == "deny"
                and (
                    str(vlan_id) in str(fw.get("target", ""))
                    or str(vlan_name) in str(fw.get("target", ""))
                )
                for fw in firewall_steps
            )

            if not has_deny_rule:
                findings.append(SecurityFinding(
                    severity=FindingSeverity.HIGH,
                    category=FindingCategory.VLAN_ISOLATION,
                    description=(
                        f"New VLAN '{vlan_name}' created without corresponding "
                        "inter-VLAN firewall deny rules."
                    ),
                    why_it_matters=(
                        f"Without deny rules, VLAN {vlan_name} can reach other "
                        "VLANs, defeating network segmentation."
                    ),
                    recommendation=(
                        f"Add deny rules blocking traffic from VLAN {vlan_name} "
                        "to other VLANs, then allow only intended cross-VLAN flows."
                    ),
                    source_plugin=source_plugin,
                    source_tool=source_tool,
                    affected_resource=str(vlan_id),
                ))

        return findings

    def _check_broad_firewall_rules(
        self,
        steps: list[dict[str, Any]],
        registry: PluginRegistry,
    ) -> list[SecurityFinding]:
        """Check for overly broad firewall rules (category 2).

        Flags rules with ``any/any`` source or destination, or port
        ranges wider than the stated intent.
        """
        findings: list[SecurityFinding] = []

        firewall_steps = [
            s for s in steps
            if s.get("subsystem") == "firewall" and s.get("action") in ("add", "create", "modify")
        ]

        fw_tools = filter_read_only_tools(registry.tools_for_skill("firewall"))
        source_plugin = fw_tools[0]["plugin"] if fw_tools else ""
        source_tool = fw_tools[0]["tool"] if fw_tools else ""

        for step in firewall_steps:
            src = step.get("source", "any")
            dst = step.get("destination", "any")
            port = step.get("port", "any")
            protocol = step.get("protocol", "any")
            rule_action = step.get("action_type", "allow")

            if rule_action != "allow":
                continue

            is_broad = (
                (src == "any" and dst == "any")
                or (protocol == "any" and port == "any")
            )

            if is_broad:
                target = step.get("target", "new rule")
                findings.append(SecurityFinding(
                    severity=FindingSeverity.HIGH,
                    category=FindingCategory.FIREWALL_POLICY,
                    description=(
                        f"Overly broad allow rule: source={src}, "
                        f"destination={dst}, port={port}, protocol={protocol}."
                    ),
                    why_it_matters=(
                        "An any/any rule permits all traffic, bypassing the "
                        "intent of network segmentation."
                    ),
                    recommendation=(
                        "Narrow the rule to the specific source, destination, "
                        "port, and protocol required for the intended access."
                    ),
                    source_plugin=source_plugin,
                    source_tool=source_tool,
                    affected_resource=str(target),
                ))

        return findings

    def _check_rule_ordering(
        self,
        steps: list[dict[str, Any]],
        registry: PluginRegistry,
    ) -> list[SecurityFinding]:
        """Check for firewall rule ordering risks (category 3).

        Flags rules that may shadow existing denies or get shadowed by
        existing allows.
        """
        findings: list[SecurityFinding] = []

        firewall_steps = [
            s for s in steps
            if s.get("subsystem") == "firewall" and s.get("action") in ("add", "create")
        ]

        fw_tools = filter_read_only_tools(registry.tools_for_skill("firewall"))
        source_plugin = fw_tools[0]["plugin"] if fw_tools else ""

        for step in firewall_steps:
            if step.get("insert_position") is not None:
                continue  # Explicit positioning -- operator knows what they want

            rule_action = step.get("action_type", "allow")
            target = step.get("target", "new rule")

            if rule_action == "allow":
                findings.append(SecurityFinding(
                    severity=FindingSeverity.MEDIUM,
                    category=FindingCategory.RULE_ORDERING,
                    description=(
                        f"New allow rule '{target}' added without explicit "
                        "position; may shadow existing deny rules."
                    ),
                    why_it_matters=(
                        "If this rule is evaluated before a more specific deny, "
                        "traffic that should be blocked will be allowed."
                    ),
                    recommendation=(
                        "Specify the insert position to ensure correct evaluation "
                        "order relative to existing deny rules."
                    ),
                    source_plugin=source_plugin,
                    affected_resource=str(target),
                ))

        return findings

    def _check_vpn_split_tunnel(
        self,
        steps: list[dict[str, Any]],
        registry: PluginRegistry,
    ) -> list[SecurityFinding]:
        """Check for VPN split-tunnel exposure (category 4).

        Flags tunnel scope wider or narrower than stated intent.
        """
        findings: list[SecurityFinding] = []

        vpn_steps = [
            s for s in steps
            if s.get("subsystem") == "vpn" and s.get("action") in ("add", "create", "modify")
        ]

        vpn_tools = filter_read_only_tools(registry.tools_for_skill("vpn"))
        source_plugin = vpn_tools[0]["plugin"] if vpn_tools else ""

        for step in vpn_steps:
            allowed_ips = step.get("allowed_ips", "")
            tunnel_scope = step.get("tunnel_scope", "")

            # Flag 0.0.0.0/0 (full tunnel) when split tunnel is intended
            if "0.0.0.0/0" in str(allowed_ips) and tunnel_scope == "split":
                target = step.get("target", "VPN tunnel")
                findings.append(SecurityFinding(
                    severity=FindingSeverity.HIGH,
                    category=FindingCategory.VPN_POSTURE,
                    description=(
                        f"VPN '{target}' has allowed_ips=0.0.0.0/0 but "
                        "tunnel_scope is set to 'split'."
                    ),
                    why_it_matters=(
                        "A /0 allowed IPs entry routes all traffic through the "
                        "tunnel, contradicting the split-tunnel intent and "
                        "potentially exposing the remote network."
                    ),
                    recommendation=(
                        "Restrict allowed_ips to only the specific networks "
                        "that need to be reached through the tunnel."
                    ),
                    source_plugin=source_plugin,
                    affected_resource=str(target),
                ))

            # Flag narrow scope when full tunnel is intended
            if (
                "0.0.0.0/0" not in str(allowed_ips)
                and allowed_ips
                and tunnel_scope == "full"
            ):
                target = step.get("target", "VPN tunnel")
                findings.append(SecurityFinding(
                    severity=FindingSeverity.MEDIUM,
                    category=FindingCategory.VPN_POSTURE,
                    description=(
                        f"VPN '{target}' scope is 'full' but allowed_ips is "
                        f"restricted to '{allowed_ips}'."
                    ),
                    why_it_matters=(
                        "Full-tunnel intent means all traffic should go through "
                        "the VPN, but the current config only routes specific "
                        "networks."
                    ),
                    recommendation=(
                        "Set allowed_ips to 0.0.0.0/0 for full-tunnel, or "
                        "change tunnel_scope to 'split' if partial routing "
                        "is intended."
                    ),
                    source_plugin=source_plugin,
                    affected_resource=str(target),
                ))

        return findings

    def _check_unencrypted_vlan(
        self,
        steps: list[dict[str, Any]],
        registry: PluginRegistry,
    ) -> list[SecurityFinding]:
        """Check for unencrypted VLANs for sensitive traffic (category 5).

        Flags IoT/management/camera SSIDs without WPA3 or using open auth.
        """
        findings: list[SecurityFinding] = []

        # Check VLAN or wifi steps for sensitive use cases
        sensitive_steps = [
            s for s in steps
            if (
                s.get("subsystem") in ("vlan", "wifi", "ssid")
                and s.get("action") in ("add", "create", "modify")
            )
        ]

        wifi_tools = filter_read_only_tools(registry.tools_for_skill("wifi"))
        source_plugin = wifi_tools[0]["plugin"] if wifi_tools else ""

        sensitive_purposes = {"iot", "management", "camera", "cameras", "security", "mgmt"}

        for step in sensitive_steps:
            purpose = step.get("purpose", "").lower()
            security_mode = step.get("security", step.get("wpa_mode", "")).lower()
            target = step.get("target", step.get("ssid", "unknown"))

            if (
                purpose in sensitive_purposes
                and security_mode in ("open", "none", "")
            ):
                findings.append(SecurityFinding(
                    severity=FindingSeverity.HIGH,
                    category=FindingCategory.WIRELESS_SECURITY,
                    description=(
                        f"SSID/VLAN '{target}' for {purpose} traffic uses "
                        f"'{security_mode or 'no'}' security."
                    ),
                    why_it_matters=(
                        f"{purpose.title()} traffic on an unencrypted network "
                        "can be intercepted by any device on the same segment."
                    ),
                    recommendation=(
                        f"Configure WPA3 (or at minimum WPA2) for the "
                        f"'{target}' SSID/VLAN."
                    ),
                    source_plugin=source_plugin,
                    affected_resource=str(target),
                ))

        return findings

    def _check_management_exposure(
        self,
        steps: list[dict[str, Any]],
        registry: PluginRegistry,
    ) -> list[SecurityFinding]:
        """Check for management plane exposure (category 6).

        Flags changes that route management interfaces onto untrusted
        segments (e.g., OPNsense UI or UniFi controller reachable from
        guest/IoT VLANs).
        """
        findings: list[SecurityFinding] = []

        untrusted_segments = {"guest", "iot", "cameras", "untrusted", "dmz"}
        mgmt_targets = {"management", "mgmt", "admin", "controller", "webui", "opnsense_ui"}

        for step in steps:
            subsystem = step.get("subsystem", "")
            target = step.get("target", "").lower()
            destination = step.get("destination", "").lower()
            source = step.get("source", "").lower()

            # Check if routing/firewall change exposes management
            if subsystem in ("firewall", "route", "vlan"):
                is_mgmt_target = any(m in target for m in mgmt_targets)
                is_from_untrusted = any(u in source for u in untrusted_segments)
                is_to_mgmt = any(m in destination for m in mgmt_targets)
                is_from_untrusted_dst = any(u in destination for u in untrusted_segments)

                if (
                    (is_mgmt_target and is_from_untrusted)
                    or (is_to_mgmt and is_from_untrusted)
                    or (is_mgmt_target and is_from_untrusted_dst)
                ):
                    fw_tools = filter_read_only_tools(
                        registry.tools_for_skill("firewall")
                    )
                    source_plugin = fw_tools[0]["plugin"] if fw_tools else ""

                    findings.append(SecurityFinding(
                        severity=FindingSeverity.CRITICAL,
                        category=FindingCategory.MANAGEMENT_EXPOSURE,
                        description=(
                            f"Change exposes management interface to untrusted "
                            f"segment: {step.get('target', 'unknown')}."
                        ),
                        why_it_matters=(
                            "Attackers on untrusted segments could access the "
                            "firewall admin or network controller, gaining full "
                            "control of the network."
                        ),
                        recommendation=(
                            "Keep management interfaces on a dedicated management "
                            "VLAN with deny rules from all untrusted segments."
                        ),
                        source_plugin=source_plugin,
                        affected_resource=step.get("target", ""),
                    ))

        return findings

    def _check_dns_security(
        self,
        steps: list[dict[str, Any]],
        registry: PluginRegistry,
    ) -> list[SecurityFinding]:
        """Check DNS security posture (category 7).

        Flags DNSSEC disabled, open recursion, forwarders without DoT.
        """
        findings: list[SecurityFinding] = []

        dns_steps = [
            s for s in steps
            if s.get("subsystem") in ("dns", "services")
        ]

        svc_tools = filter_read_only_tools(registry.tools_for_skill("services"))
        source_plugin = svc_tools[0]["plugin"] if svc_tools else ""

        for step in dns_steps:
            target = step.get("target", "DNS config")

            # Check for DNSSEC being disabled
            if step.get("dnssec") is False or step.get("dnssec_enabled") is False:
                findings.append(SecurityFinding(
                    severity=FindingSeverity.MEDIUM,
                    category=FindingCategory.DNS_SECURITY,
                    description=f"DNSSEC is disabled in {target}.",
                    why_it_matters=(
                        "Without DNSSEC, DNS responses can be spoofed, "
                        "redirecting traffic to malicious servers."
                    ),
                    recommendation="Enable DNSSEC validation in the resolver.",
                    source_plugin=source_plugin,
                    affected_resource=str(target),
                ))

            # Check for forwarder without DoT
            forwarder = step.get("forwarder", "")
            use_dot = step.get("dot_enabled", step.get("tls", False))

            if forwarder and not use_dot:
                findings.append(SecurityFinding(
                    severity=FindingSeverity.MEDIUM,
                    category=FindingCategory.DNS_SECURITY,
                    description=(
                        f"DNS forwarder '{forwarder}' configured without "
                        "DNS-over-TLS (DoT)."
                    ),
                    why_it_matters=(
                        "DNS queries sent in plaintext can be intercepted and "
                        "monitored by any device on the path to the forwarder."
                    ),
                    recommendation=(
                        f"Enable DoT for forwarder '{forwarder}' or switch to "
                        "a DoT-capable resolver (e.g. 1.1.1.1:853, 8.8.8.8:853)."
                    ),
                    source_plugin=source_plugin,
                    affected_resource=str(forwarder),
                ))

            # Check for open recursion
            if step.get("open_recursion") is True:
                findings.append(SecurityFinding(
                    severity=FindingSeverity.HIGH,
                    category=FindingCategory.DNS_SECURITY,
                    description=f"Open DNS recursion enabled on {target}.",
                    why_it_matters=(
                        "An open recursive resolver can be used as a DNS "
                        "amplification vector in DDoS attacks."
                    ),
                    recommendation=(
                        "Restrict DNS recursion to local networks only "
                        "(ACL or interface binding)."
                    ),
                    source_plugin=source_plugin,
                    affected_resource=str(target),
                ))

        return findings
