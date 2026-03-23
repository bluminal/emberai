"""OX (Operator Experience) output formatting module.

All agents and commands in the netex plugin use OX formatters to produce
consistent, readable output for Claude conversations. No ad-hoc string
building -- every report, table, detail view, diff, and change plan passes
through this module.

Output is markdown formatted for Claude conversation rendering.
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
    Findings are grouped by severity with clear section headers.
    """
    if not findings:
        return f"## {title}\n\nNo findings."

    grouped: dict[Severity, list[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.severity, []).append(finding)

    lines: list[str] = [f"## {title}", ""]

    counts = []
    for sev in Severity:
        group = grouped.get(sev, [])
        if group:
            counts.append(f"{len(group)} {_SEVERITY_LABELS[sev]}")
    lines.append(f"**{len(findings)} findings:** {', '.join(counts)}")
    lines.append("")

    for sev in Severity:
        group = grouped.get(sev, [])
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
    """Format a markdown table."""
    if not headers:
        return ""

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

    lines.append(_format_row(headers))
    separator = "| " + " | ".join("-" * w for w in col_widths) + " |"
    lines.append(separator)

    for row in rows:
        padded_row = list(row) + [""] * max(0, len(headers) - len(row))
        lines.append(_format_row(padded_row[: len(headers)]))

    lines.append("")
    return "\n".join(lines)


def format_key_value(
    data: dict[str, str],
    title: str | None = None,
) -> str:
    """Format key-value pairs for detail views."""
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


def format_change_plan(
    steps: list[dict[str, str]],
    outage_risk: str | None = None,
    security_findings: list[Finding] | None = None,
    rollback_steps: list[str] | None = None,
) -> str:
    """Format a complete change plan for operator review.

    Follows the PRD Section 10.2 Phase 2 plan presentation structure:
    [OUTAGE RISK] -> [SECURITY] -> [CHANGE PLAN] -> [ROLLBACK].
    """
    lines: list[str] = ["## Change Plan", ""]

    if outage_risk is not None:
        lines.append("### [OUTAGE RISK]")
        lines.append("")
        lines.append(outage_risk)
        lines.append("")

    if security_findings:
        lines.append("### [SECURITY]")
        lines.append("")

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

    if rollback_steps:
        lines.append("### [ROLLBACK]")
        lines.append("")
        lines.append("If execution fails, the following steps will be attempted in order:")
        lines.append("")
        for i, step_desc in enumerate(rollback_steps, start=1):
            lines.append(f"{i}. {step_desc}")
        lines.append("")

    return "\n".join(lines)
