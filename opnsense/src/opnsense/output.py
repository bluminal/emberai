"""OX (Operator Experience) output formatting module.

All agents and commands in the opnsense plugin use OX formatters to produce
consistent, readable output for Claude conversations. No ad-hoc string
building -- every report, table, detail view, diff, and change plan passes
through this module.

The OX pattern ensures:
  - Severity-tiered reports always surface critical findings first.
  - Tables use standard markdown for reliable rendering.
  - Change plans follow the PRD Section 10.2 structure:
    [OUTAGE RISK] -> [SECURITY] -> [CHANGE PLAN] -> [ROLLBACK].
  - Risk blocks use clear visual markers so operators never miss them.
  - Key-value and diff views are scannable at a glance.

Output is markdown formatted for Claude conversation rendering. Unicode
box-drawing characters are avoided in favor of simple markdown formatting
for maximum compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    """Severity levels for findings, ordered from most to least severe."""

    CRITICAL = "critical"
    HIGH = "high"
    WARNING = "warning"
    INFORMATIONAL = "informational"


# Ordering used for sorting findings by severity (most severe first).
_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.WARNING: 2,
    Severity.INFORMATIONAL: 3,
}

# Display labels for severity section headers.
_SEVERITY_LABELS: dict[Severity, str] = {
    Severity.CRITICAL: "CRITICAL",
    Severity.HIGH: "HIGH",
    Severity.WARNING: "Warning",
    Severity.INFORMATIONAL: "Informational",
}

# Emoji-free severity markers for clear visual distinction.
_SEVERITY_MARKERS: dict[Severity, str] = {
    Severity.CRITICAL: "[!!!]",
    Severity.HIGH: "[!!]",
    Severity.WARNING: "[!]",
    Severity.INFORMATIONAL: "[i]",
}


@dataclass
class Finding:
    """A single finding in a severity-tiered report.

    Attributes:
        severity: The severity level of this finding.
        title: A short, descriptive title.
        detail: Explanation of the finding and why it matters.
        recommendation: Optional remediation guidance.
    """

    severity: Severity
    title: str
    detail: str
    recommendation: str | None = None


def format_severity_report(title: str, findings: list[Finding]) -> str:
    """Format a severity-tiered report.

    Critical findings appear first, then High, Warning, and Informational.
    Findings are grouped by severity with clear section headers. Empty
    severity tiers are omitted.

    Args:
        title: The report title (e.g., "Firewall Health Report").
        findings: List of findings to include in the report.

    Returns:
        A markdown-formatted severity report string.
    """
    if not findings:
        return f"## {title}\n\nNo findings."

    # Group findings by severity.
    grouped: dict[Severity, list[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.severity, []).append(finding)

    # Build report in severity order.
    lines: list[str] = [f"## {title}", ""]

    # Summary line.
    counts = []
    for sev in Severity:
        group = grouped.get(sev, [])
        if group:
            counts.append(f"{len(group)} {_SEVERITY_LABELS[sev]}")
    lines.append(f"**{len(findings)} findings:** {', '.join(counts)}")
    lines.append("")

    # Render each severity group.
    for sev in Severity:
        group = grouped.get(sev)
        if not group:
            continue

        marker = _SEVERITY_MARKERS[sev]
        label = _SEVERITY_LABELS[sev]
        lines.append(f"### {marker} {label}")
        lines.append("")

        for finding in group:
            lines.append(f"- **{finding.title}**")
            lines.append(f"  {finding.detail}")
            if finding.recommendation:
                lines.append(f"  *Recommendation:* {finding.recommendation}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_table(
    headers: list[str],
    rows: list[list[str]],
    title: str | None = None,
) -> str:
    """Format a markdown table for interface/rule/route inventories.

    Column widths are calculated dynamically based on content for readable
    alignment in monospaced rendering.

    Args:
        headers: Column header labels.
        rows: List of rows, each a list of cell values matching headers length.
        title: Optional title rendered as a heading above the table.

    Returns:
        A markdown-formatted table string.
    """
    if not headers:
        return ""

    # Calculate column widths from headers and data.
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    def _format_row(cells: list[str]) -> str:
        padded = [
            str(cells[i]).ljust(col_widths[i]) if i < len(col_widths) else str(cells[i])
            for i in range(len(cells))
        ]
        return "| " + " | ".join(padded) + " |"

    lines: list[str] = []

    if title:
        lines.append(f"### {title}")
        lines.append("")

    # Header row.
    lines.append(_format_row(headers))

    # Separator row.
    separator = "| " + " | ".join("-" * w for w in col_widths) + " |"
    lines.append(separator)

    # Data rows.
    for row in rows:
        # Pad row to match header count if needed.
        padded_row = list(row) + [""] * max(0, len(headers) - len(row))
        lines.append(_format_row(padded_row[:len(headers)]))

    lines.append("")
    return "\n".join(lines)


def format_key_value(
    data: dict[str, str],
    title: str | None = None,
) -> str:
    """Format key-value pairs for detail views.

    Renders as a definition-style list with bold keys for scannable
    detail views (interface details, rule info, gateway config).

    Args:
        data: Ordered mapping of field names to values.
        title: Optional title rendered as a heading above the pairs.

    Returns:
        A markdown-formatted key-value block string.
    """
    if not data:
        return ""

    lines: list[str] = []

    if title:
        lines.append(f"### {title}")
        lines.append("")

    key_width = max(len(k) for k in data) if data else 0

    for key, value in data.items():
        lines.append(f"**{key.ljust(key_width)}:** {value}")

    lines.append("")
    return "\n".join(lines)


def format_diff(
    before: dict[str, object],
    after: dict[str, object],
    title: str | None = None,
) -> str:
    """Format a diff view showing what changed between two states.

    Compares two dictionaries and produces a clear summary of added,
    removed, and changed fields.

    Args:
        before: The original state as key-value pairs.
        after: The new state as key-value pairs.
        title: Optional title rendered as a heading above the diff.

    Returns:
        A markdown-formatted diff summary string.
    """
    lines: list[str] = []

    if title:
        lines.append(f"### {title}")
        lines.append("")

    before_keys = set(before.keys())
    after_keys = set(after.keys())

    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    common = sorted(before_keys & after_keys)

    changed: list[tuple[str, object, object]] = []
    unchanged: list[str] = []
    for key in common:
        if before[key] != after[key]:
            changed.append((key, before[key], after[key]))
        else:
            unchanged.append(key)

    has_changes = bool(added or removed or changed)

    if not has_changes:
        lines.append("No changes detected.")
        lines.append("")
        return "\n".join(lines)

    if changed:
        lines.append("**Changed:**")
        for key, old_val, new_val in changed:
            lines.append(f"- `{key}`: `{old_val}` -> `{new_val}`")
        lines.append("")

    if added:
        lines.append("**Added:**")
        for key in added:
            lines.append(f"- `{key}`: `{after[key]}`")
        lines.append("")

    if removed:
        lines.append("**Removed:**")
        for key in removed:
            lines.append(f"- `{key}`: `{before[key]}`")
        lines.append("")

    if unchanged:
        lines.append(f"**Unchanged:** {len(unchanged)} field(s)")
        lines.append("")

    return "\n".join(lines)


def format_risk_block(
    risk_tier: str,
    description: str,
    affected_path: str | None = None,
) -> str:
    """Format an outage risk assessment block for change plans.

    Used in the [OUTAGE RISK] section of change plan presentations
    per PRD Section 10.2 Phase 2 plan structure.

    Args:
        risk_tier: One of CRITICAL, HIGH, MEDIUM, LOW.
        description: Explanation of why this risk tier was assigned.
        affected_path: Optional network path at risk (e.g., "VLAN 10 -> WAN gateway").

    Returns:
        A markdown-formatted risk block string.
    """
    tier_upper = risk_tier.upper()

    lines: list[str] = [
        f"**[OUTAGE RISK: {tier_upper}]**",
        "",
        description,
    ]

    if affected_path:
        lines.append("")
        lines.append(f"**Affected path:** {affected_path}")

    lines.append("")
    return "\n".join(lines)


def format_change_plan(
    steps: list[dict[str, str]],
    outage_risk: str | None = None,
    security_findings: list[Finding] | None = None,
    rollback_steps: list[str] | None = None,
) -> str:
    """Format a complete change plan for operator review.

    Follows the PRD Section 10.2 Phase 2 plan presentation structure:
    [OUTAGE RISK] -> [SECURITY] -> [CHANGE PLAN] -> [ROLLBACK].

    Each section is included only when its data is provided, except
    [CHANGE PLAN] which is always present.

    Args:
        steps: Ordered list of change steps. Each dict should have at
            minimum a "description" key. Optional keys: "system" (which
            plugin/system), "detail" (additional context).
        outage_risk: Pre-formatted outage risk block (from format_risk_block),
            or a plain risk description string.
        security_findings: Findings from the NetworkSecurityAgent review.
        rollback_steps: Ordered list of rollback step descriptions.

    Returns:
        A markdown-formatted complete change plan string.
    """
    lines: list[str] = ["## Change Plan", ""]

    # --- [OUTAGE RISK] section ---
    if outage_risk is not None:
        lines.append("### [OUTAGE RISK]")
        lines.append("")
        lines.append(outage_risk)
        lines.append("")

    # --- [SECURITY] section ---
    if security_findings:
        lines.append("### [SECURITY]")
        lines.append("")

        # Sort by severity.
        sorted_findings = sorted(
            security_findings,
            key=lambda f: _SEVERITY_ORDER.get(f.severity, 99),
        )

        for finding in sorted_findings:
            marker = _SEVERITY_MARKERS.get(finding.severity, "[?]")
            lines.append(f"- {marker} **{finding.title}**")
            lines.append(f"  {finding.detail}")
            if finding.recommendation:
                lines.append(f"  *Recommendation:* {finding.recommendation}")
            lines.append("")

    # --- [CHANGE PLAN] section ---
    lines.append("### [CHANGE PLAN]")
    lines.append("")

    for i, step in enumerate(steps, start=1):
        description = step.get("description", "")
        system = step.get("system")
        detail = step.get("detail")

        prefix = f"[{system}] " if system else ""
        lines.append(f"{i}. {prefix}{description}")
        if detail:
            lines.append(f"   {detail}")

    lines.append("")

    # --- [ROLLBACK] section ---
    if rollback_steps:
        lines.append("### [ROLLBACK]")
        lines.append("")
        lines.append("If execution fails, the following steps will be attempted in order:")
        lines.append("")
        for i, step_desc in enumerate(rollback_steps, start=1):
            lines.append(f"{i}. {step_desc}")
        lines.append("")

    return "\n".join(lines)


def format_summary(
    title: str,
    stats: dict[str, int | str],
    detail: str | None = None,
) -> str:
    """Format a summary block.

    Produces a compact summary with key statistics (e.g., "Scan complete:
    5 interfaces, 3 VLANs, 12 rules").

    Args:
        title: Summary heading (e.g., "Scan Complete").
        stats: Key statistics as name-value pairs.
        detail: Optional additional context or notes.

    Returns:
        A markdown-formatted summary block string.
    """
    lines: list[str] = [f"## {title}", ""]

    stat_parts = [f"**{k}:** {v}" for k, v in stats.items()]
    lines.append(" | ".join(stat_parts))

    if detail:
        lines.append("")
        lines.append(detail)

    lines.append("")
    return "\n".join(lines)
