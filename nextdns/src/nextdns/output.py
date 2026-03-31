"""OX (Operator Experience) output formatting module for DNS data.

All agents and commands in the nextdns plugin use OX formatters to produce
consistent, readable output for Claude conversations. No ad-hoc string
building -- every report, table, detail view, diff, and summary passes
through this module.

The OX pattern ensures:
  - Severity-tiered reports always surface critical findings first.
  - Tables use standard markdown for reliable rendering.
  - DNS-specific data (profiles, analytics, logs, allow/deny lists) is
    formatted for quick operator comprehension.
  - Key-value and diff views are scannable at a glance.

Output is markdown formatted for Claude conversation rendering. Unicode
box-drawing characters are avoided in favor of simple markdown formatting
for maximum compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


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


# ---------------------------------------------------------------------------
# Data classes for structured input
# ---------------------------------------------------------------------------


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


@dataclass
class ProfileSummary:
    """Summary data for a single NextDNS profile.

    Attributes:
        name: Profile display name.
        profile_id: NextDNS profile identifier (e.g. "abc123").
        security_on: Number of security features enabled.
        security_off: Number of security features disabled.
        privacy_blocklists: Number of active privacy blocklists.
        parental_control: Whether parental control is enabled.
    """

    name: str
    profile_id: str
    security_on: int = 0
    security_off: int = 0
    privacy_blocklists: int = 0
    parental_control: bool = False


@dataclass
class AnalyticsSummary:
    """Aggregated analytics data for a NextDNS profile.

    Attributes:
        total_queries: Total DNS queries in the period.
        blocked_queries: Number of blocked queries.
        blocked_percent: Percentage of queries blocked.
        top_domains: List of (domain, count) tuples for top resolved domains.
        top_blocked: List of (domain, count) tuples for top blocked domains.
        devices: List of (device_name, query_count) tuples.
    """

    total_queries: int = 0
    blocked_queries: int = 0
    blocked_percent: float = 0.0
    top_domains: list[tuple[str, int]] = field(default_factory=list)
    top_blocked: list[tuple[str, int]] = field(default_factory=list)
    devices: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class ListEntry:
    """An entry in an allow or deny list.

    Attributes:
        domain: The domain pattern (e.g. "example.com", "*.ads.example.com").
        active: Whether the entry is currently active.
    """

    domain: str
    active: bool = True


@dataclass
class LogEntry:
    """A single DNS query log entry.

    Attributes:
        timestamp: ISO 8601 timestamp of the query.
        domain: The queried domain name.
        status: Resolution status (e.g. "allowed", "blocked", "bypassed").
        device: Device name or IP that made the query.
        protocol: DNS protocol used (e.g. "DoH", "DoT", "UDP").
    """

    timestamp: str
    domain: str
    status: str
    device: str = ""
    protocol: str = ""


@dataclass
class ProfileDiff:
    """Diff between two profile configurations.

    Attributes:
        profile_a_name: Display name of the first profile.
        profile_b_name: Display name of the second profile.
        security_diff: Dict of setting name -> (profile_a_value, profile_b_value).
        privacy_diff: Dict of setting name -> (profile_a_value, profile_b_value).
        parental_diff: Dict of setting name -> (profile_a_value, profile_b_value).
        settings_diff: Dict of setting name -> (profile_a_value, profile_b_value).
    """

    profile_a_name: str
    profile_b_name: str
    security_diff: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    privacy_diff: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    parental_diff: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    settings_diff: dict[str, tuple[Any, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared formatting helpers
# ---------------------------------------------------------------------------


def _format_table(
    headers: list[str],
    rows: list[list[str]],
    title: str | None = None,
) -> str:
    """Format a markdown table with dynamic column widths.

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
        padded_row = list(row) + [""] * max(0, len(headers) - len(row))
        lines.append(_format_row(padded_row[: len(headers)]))

    lines.append("")
    return "\n".join(lines)


def _format_key_value(
    data: dict[str, str],
    title: str | None = None,
) -> str:
    """Format key-value pairs for detail views.

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


# ---------------------------------------------------------------------------
# DNS-specific OX formatters
# ---------------------------------------------------------------------------


def format_profile_summary(profiles: list[ProfileSummary]) -> str:
    """Format a summary table of NextDNS profiles.

    Produces a markdown table with columns: Name, ID, Security (on/off count),
    Privacy (blocklist count), and Parental Control (on/off).

    Args:
        profiles: List of profile summary data.

    Returns:
        A markdown-formatted profile summary table.
    """
    if not profiles:
        return "## Profiles\n\nNo profiles found.\n"

    headers = ["Name", "ID", "Security", "Privacy", "Parental Control"]
    rows: list[list[str]] = []

    for p in profiles:
        security = f"{p.security_on} on / {p.security_off} off"
        privacy = f"{p.privacy_blocklists} blocklist(s)"
        parental = "On" if p.parental_control else "Off"
        rows.append([p.name, p.profile_id, security, privacy, parental])

    return _format_table(headers, rows, title="Profiles")


def format_profile_detail(profile: dict[str, Any]) -> str:
    """Format detailed view of a single NextDNS profile.

    Renders key-value sections for security, privacy, parental control,
    and general settings.

    Args:
        profile: Profile data dict with keys like "name", "id", "security",
            "privacy", "parentalControl", "settings".

    Returns:
        A markdown-formatted profile detail view.
    """
    lines: list[str] = []

    # Header
    name = profile.get("name", "Unknown")
    profile_id = profile.get("id", "?")
    lines.append(f"## Profile: {name} ({profile_id})")
    lines.append("")

    # Security section
    security = profile.get("security", {})
    if security:
        sec_data: dict[str, str] = {}
        for key, value in security.items():
            sec_data[key] = str(value)
        lines.append(_format_key_value(sec_data, title="Security"))

    # Privacy section
    privacy = profile.get("privacy", {})
    if privacy:
        priv_data: dict[str, str] = {}
        blocklists = privacy.get("blocklists", [])
        priv_data["Blocklists"] = (
            str(len(blocklists)) if isinstance(blocklists, list) else str(blocklists)
        )
        for key, value in privacy.items():
            if key != "blocklists":
                priv_data[key] = str(value)
        lines.append(_format_key_value(priv_data, title="Privacy"))

    # Parental Control section
    parental = profile.get("parentalControl", {})
    if parental:
        pc_data: dict[str, str] = {}
        for key, value in parental.items():
            pc_data[key] = str(value)
        lines.append(_format_key_value(pc_data, title="Parental Control"))

    # General settings section
    settings = profile.get("settings", {})
    if settings:
        settings_data: dict[str, str] = {}
        for key, value in settings.items():
            settings_data[key] = str(value)
        lines.append(_format_key_value(settings_data, title="Settings"))

    return "\n".join(lines).rstrip() + "\n"


def format_analytics_summary(analytics: AnalyticsSummary) -> str:
    """Format an analytics summary for a NextDNS profile.

    Includes query counts, top blocked domains, and device activity.

    Args:
        analytics: Aggregated analytics data.

    Returns:
        A markdown-formatted analytics summary.
    """
    lines: list[str] = [
        "## Analytics Summary",
        "",
        f"**Total queries:** {analytics.total_queries:,}",
        f"**Blocked queries:** {analytics.blocked_queries:,} ({analytics.blocked_percent:.1f}%)",
        "",
    ]

    # Top blocked domains
    if analytics.top_blocked:
        lines.append("### Top Blocked Domains")
        lines.append("")
        headers = ["Domain", "Count"]
        rows = [[domain, f"{count:,}"] for domain, count in analytics.top_blocked]
        lines.append(_format_table(headers, rows))

    # Top resolved domains
    if analytics.top_domains:
        lines.append("### Top Resolved Domains")
        lines.append("")
        headers = ["Domain", "Count"]
        rows = [[domain, f"{count:,}"] for domain, count in analytics.top_domains]
        lines.append(_format_table(headers, rows))

    # Device activity
    if analytics.devices:
        lines.append("### Device Activity")
        lines.append("")
        headers = ["Device", "Queries"]
        rows = [[device, f"{count:,}"] for device, count in analytics.devices]
        lines.append(_format_table(headers, rows))

    return "\n".join(lines).rstrip() + "\n"


def format_security_posture(findings: list[Finding]) -> str:
    """Format a severity-tiered security posture report.

    Critical findings appear first, then High, Warning, and Informational.
    Findings are grouped by severity with clear section headers. Empty
    severity tiers are omitted.

    Args:
        findings: List of security findings to include in the report.

    Returns:
        A markdown-formatted severity report string.
    """
    if not findings:
        return "## Security Posture\n\nNo findings.\n"

    # Group findings by severity.
    grouped: dict[Severity, list[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.severity, []).append(finding)

    # Build report in severity order.
    lines: list[str] = ["## Security Posture", ""]

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


def format_denylist(entries: list[ListEntry]) -> str:
    """Format a deny list (blocklist) as a markdown table.

    Args:
        entries: List of deny list entries.

    Returns:
        A markdown-formatted deny list table.
    """
    if not entries:
        return "### Deny List\n\nNo entries.\n"

    headers = ["Domain", "Active"]
    rows = [[e.domain, "Yes" if e.active else "No"] for e in entries]
    return _format_table(headers, rows, title="Deny List")


def format_allowlist(entries: list[ListEntry]) -> str:
    """Format an allow list as a markdown table.

    Args:
        entries: List of allow list entries.

    Returns:
        A markdown-formatted allow list table.
    """
    if not entries:
        return "### Allow List\n\nNo entries.\n"

    headers = ["Domain", "Active"]
    rows = [[e.domain, "Yes" if e.active else "No"] for e in entries]
    return _format_table(headers, rows, title="Allow List")


def format_log_entries(entries: list[LogEntry]) -> str:
    """Format DNS query log entries as a markdown table.

    Args:
        entries: List of log entries.

    Returns:
        A markdown-formatted log table.
    """
    if not entries:
        return "### DNS Query Log\n\nNo log entries.\n"

    headers = ["Timestamp", "Domain", "Status", "Device", "Protocol"]
    rows = [
        [e.timestamp, e.domain, e.status, e.device, e.protocol]
        for e in entries
    ]
    return _format_table(headers, rows, title="DNS Query Log")


def format_profile_comparison(diff: ProfileDiff) -> str:
    """Format a side-by-side comparison of two NextDNS profiles.

    Produces comparison tables for each configuration section (security,
    privacy, parental control, settings) showing differences between
    the two profiles.

    Args:
        diff: Profile diff data containing per-section differences.

    Returns:
        A markdown-formatted profile comparison.
    """
    lines: list[str] = [
        f"## Profile Comparison: {diff.profile_a_name} vs {diff.profile_b_name}",
        "",
    ]

    sections: list[tuple[str, dict[str, tuple[Any, Any]]]] = [
        ("Security", diff.security_diff),
        ("Privacy", diff.privacy_diff),
        ("Parental Control", diff.parental_diff),
        ("Settings", diff.settings_diff),
    ]

    has_any_diff = False

    for section_name, section_diff in sections:
        if not section_diff:
            continue

        has_any_diff = True
        headers = ["Setting", diff.profile_a_name, diff.profile_b_name]
        rows = [
            [setting, str(val_a), str(val_b)]
            for setting, (val_a, val_b) in sorted(section_diff.items())
        ]
        lines.append(_format_table(headers, rows, title=section_name))

    if not has_any_diff:
        lines.append("Profiles are identical.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
