"""SecurityFinding model for cross-vendor security audit results.

Used by the NetworkSecurityAgent to report security findings during
automatic plan reviews and on-demand audits (``netex secure audit``).

Each finding carries its severity, category, description, recommendation,
and the source plugin/tool that produced it, enabling consistent reporting
across all vendor security data.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FindingSeverity(StrEnum):
    """Severity levels for security findings, ordered most to least severe."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class FindingCategory(StrEnum):
    """Security finding categories for grouping in audit reports."""

    FIREWALL_POLICY = "firewall_policy"
    VLAN_ISOLATION = "vlan_isolation"
    RULE_ORDERING = "rule_ordering"
    VPN_POSTURE = "vpn_posture"
    DNS_SECURITY = "dns_security"
    WIRELESS_SECURITY = "wireless_security"
    IDS_IPS = "ids_ips"
    CERTIFICATES = "certificates"
    FIRMWARE = "firmware"
    MANAGEMENT_EXPOSURE = "management_exposure"
    CROSS_LAYER = "cross_layer"
    CONFIGURATION = "configuration"
    GENERAL = "general"


# Ordering used for sorting findings by severity (most severe first).
SEVERITY_ORDER: dict[FindingSeverity, int] = {
    FindingSeverity.CRITICAL: 0,
    FindingSeverity.HIGH: 1,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.LOW: 3,
    FindingSeverity.INFORMATIONAL: 4,
}


class SecurityFinding(BaseModel):
    """A single security finding from a cross-vendor audit or plan review.

    Produced by the NetworkSecurityAgent during:
    - Automatic plan reviews (before every write plan)
    - On-demand audits (``netex secure audit``)

    Output format per PRD C.5:
        Severity: CRITICAL | HIGH | MEDIUM | LOW
        Issue: one sentence description
        Why it matters here: specific to this plan, not generic
        Alternative: concrete option achieving the same goal more securely

    Attributes
    ----------
    severity:
        Severity level of the finding.
    category:
        Security domain this finding belongs to.
    description:
        One-sentence description of the security issue.
    why_it_matters:
        Specific explanation of why this matters in the current context.
    recommendation:
        Concrete remediation guidance (never includes --apply).
    source_plugin:
        Name of the vendor plugin that provided the data for this finding.
    source_tool:
        MCP tool name that was called to obtain the data
        (e.g. ``opnsense__firewall__list_rules``).
    affected_resource:
        Identifier of the specific resource affected (rule UUID, interface
        name, VLAN ID, etc.).
    metadata:
        Additional structured context for programmatic consumers.
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    severity: FindingSeverity = Field(
        description="Severity level (critical, high, medium, low, informational)",
    )
    category: FindingCategory = Field(
        description="Security domain category",
    )
    description: str = Field(
        description="One-sentence description of the security issue",
    )
    why_it_matters: str = Field(
        default="",
        description="Specific explanation of why this matters in context",
    )
    recommendation: str = Field(
        default="",
        description="Concrete remediation guidance (never includes --apply)",
    )
    source_plugin: str = Field(
        default="",
        description="Vendor plugin that provided the source data",
    )
    source_tool: str = Field(
        default="",
        description="MCP tool name that produced the source data",
    )
    affected_resource: str = Field(
        default="",
        description="Identifier of the specific affected resource",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured context",
    )

    def format_for_report(self) -> str:
        """Format this finding as a markdown block for inclusion in reports.

        Returns
        -------
        str
            Markdown-formatted finding block.
        """
        lines: list[str] = [
            f"**Severity:** {self.severity.value.upper()}",
            f"**Issue:** {self.description}",
        ]
        if self.why_it_matters:
            lines.append(f"**Why it matters:** {self.why_it_matters}")
        if self.recommendation:
            lines.append(f"**Recommendation:** {self.recommendation}")
        if self.source_plugin:
            source = self.source_plugin
            if self.source_tool:
                source += f" ({self.source_tool})"
            lines.append(f"**Source:** {source}")
        if self.affected_resource:
            lines.append(f"**Affected resource:** {self.affected_resource}")

        return "\n".join(lines)


def sort_findings(findings: list[SecurityFinding]) -> list[SecurityFinding]:
    """Sort findings by severity (most severe first).

    Within the same severity level, findings are kept in their original
    order (stable sort).
    """
    return sorted(
        findings,
        key=lambda f: SEVERITY_ORDER.get(f.severity, 99),
    )


def group_findings_by_category(
    findings: list[SecurityFinding],
) -> dict[FindingCategory, list[SecurityFinding]]:
    """Group findings by category, each group sorted by severity.

    Returns
    -------
    dict
        Mapping of category to sorted findings list.
    """
    grouped: dict[FindingCategory, list[SecurityFinding]] = {}
    for finding in findings:
        grouped.setdefault(finding.category, []).append(finding)

    # Sort each group by severity
    return {
        category: sort_findings(group)
        for category, group in grouped.items()
    }
