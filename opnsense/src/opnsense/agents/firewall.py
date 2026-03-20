# SPDX-License-Identifier: MIT
"""Firewall agent -- firewall rule audit report.

Produces a severity-tiered OX report auditing firewall rules, aliases,
and NAT rules on the OPNsense firewall. Identifies security issues such
as overly permissive rules, disabled rules, shadow rules, and rules
without logging.
"""

from __future__ import annotations

import logging
from typing import Any

from opnsense.output import Finding, Severity, format_severity_report, format_table
from opnsense.tools.firewall import (
    opnsense__firewall__list_aliases,
    opnsense__firewall__list_nat_rules,
    opnsense__firewall__list_rules,
)

logger = logging.getLogger(__name__)


def _check_overly_permissive(rule: dict[str, Any]) -> Finding | None:
    """Check if a rule is overly permissive (any -> any pass)."""
    if (
        rule.get("action") == "pass"
        and rule.get("source") == "any"
        and rule.get("destination") == "any"
        and rule.get("protocol", "any") == "any"
        and rule.get("enabled", True)
    ):
        return Finding(
            severity=Severity.HIGH,
            title=f"Overly permissive rule: '{rule.get('description', rule.get('uuid', ''))}'",
            detail=(
                f"Rule {rule.get('uuid', '')} on interface '{rule.get('interface', '')}' "
                "allows all traffic from any source to any destination. "
                "This effectively disables filtering on this interface."
            ),
            recommendation=(
                "Restrict the source, destination, or protocol to follow "
                "the principle of least privilege."
            ),
        )
    return None


def _check_disabled_rule(rule: dict[str, Any]) -> Finding | None:
    """Check for disabled rules that may indicate configuration drift."""
    if not rule.get("enabled", True):
        return Finding(
            severity=Severity.INFORMATIONAL,
            title=f"Disabled rule: '{rule.get('description', rule.get('uuid', ''))}'",
            detail=(
                f"Rule {rule.get('uuid', '')} on interface '{rule.get('interface', '')}' "
                "is disabled. Disabled rules may indicate incomplete changes or "
                "configuration drift."
            ),
            recommendation="Review and either re-enable or delete the rule.",
        )
    return None


def _check_no_logging(rule: dict[str, Any]) -> Finding | None:
    """Check for block/reject rules without logging enabled."""
    if (
        rule.get("action") in ("block", "reject")
        and not rule.get("log", False)
        and rule.get("enabled", True)
    ):
        return Finding(
            severity=Severity.WARNING,
            title=f"Block rule without logging: '{rule.get('description', rule.get('uuid', ''))}'",
            detail=(
                f"Rule {rule.get('uuid', '')} blocks traffic on "
                f"'{rule.get('interface', '')}' but logging is disabled. "
                "Without logging, blocked traffic cannot be investigated."
            ),
            recommendation="Enable logging on block/reject rules for visibility.",
        )
    return None


async def run_firewall_audit() -> str:
    """Generate a firewall rule audit report.

    Fetches all firewall rules, aliases, and NAT rules, then produces
    a formatted report with:
    - Rule inventory table
    - Alias inventory table
    - NAT rule summary
    - Security findings (overly permissive, disabled, no logging)

    Returns:
        A markdown-formatted audit report string.
    """
    # Fetch data from tools
    rules = await opnsense__firewall__list_rules()
    aliases = await opnsense__firewall__list_aliases()
    nat_rules = await opnsense__firewall__list_nat_rules()

    findings: list[Finding] = []
    sections: list[str] = []

    # --- Rule inventory table ---
    if rules:
        rule_headers = ["Pos", "Action", "Interface", "Source", "Destination", "Proto", "Log", "Description"]
        rule_rows: list[list[str]] = []
        for rule in rules:
            enabled_marker = "" if rule.get("enabled", True) else "[disabled] "
            log_marker = "yes" if rule.get("log", False) else "no"
            rule_rows.append([
                str(rule.get("position", "")),
                rule.get("action", ""),
                rule.get("interface", ""),
                rule.get("source", ""),
                rule.get("destination", ""),
                rule.get("protocol", ""),
                log_marker,
                f"{enabled_marker}{rule.get('description', '')}",
            ])

            # Run security checks
            finding = _check_overly_permissive(rule)
            if finding:
                findings.append(finding)

            finding = _check_disabled_rule(rule)
            if finding:
                findings.append(finding)

            finding = _check_no_logging(rule)
            if finding:
                findings.append(finding)

        sections.append(format_table(rule_headers, rule_rows, title="Firewall Rules"))

        # Check for rules per interface distribution
        interfaces: dict[str, int] = {}
        for rule in rules:
            iface = rule.get("interface", "unknown")
            interfaces[iface] = interfaces.get(iface, 0) + 1

        # Flag interfaces with no block rules
        for iface, count in interfaces.items():
            has_block = any(
                r.get("interface") == iface and r.get("action") in ("block", "reject")
                for r in rules
            )
            if not has_block:
                findings.append(Finding(
                    severity=Severity.WARNING,
                    title=f"Interface '{iface}' has no block/reject rules",
                    detail=(
                        f"Interface '{iface}' has {count} rule(s) but none of them "
                        "block or reject traffic. This may indicate a missing "
                        "default deny policy."
                    ),
                    recommendation="Add a default deny rule at the end of the chain.",
                ))
    else:
        findings.append(Finding(
            severity=Severity.HIGH,
            title="No firewall rules found",
            detail="The API returned no firewall rules. This is unusual.",
            recommendation="Verify API connectivity and permissions.",
        ))

    # --- Alias inventory table ---
    if aliases:
        alias_headers = ["Name", "Type", "Content", "Description"]
        alias_rows: list[list[str]] = []
        for alias in aliases:
            content = alias.get("content", "")
            # Truncate long content for table display
            if len(content) > 40:
                content = content[:37] + "..."
            alias_rows.append([
                alias.get("name", ""),
                alias.get("alias_type", ""),
                content.replace("\n", ", "),
                alias.get("description", ""),
            ])

        sections.append(format_table(alias_headers, alias_rows, title="Firewall Aliases"))

    # --- NAT rule summary ---
    if nat_rules:
        nat_headers = ["Interface", "Source", "Destination", "Target", "Proto", "Description"]
        nat_rows: list[list[str]] = []
        for nat_rule in nat_rules:
            nat_rows.append([
                nat_rule.get("interface", ""),
                nat_rule.get("source", ""),
                nat_rule.get("destination", ""),
                nat_rule.get("target", ""),
                nat_rule.get("protocol", ""),
                nat_rule.get("description", ""),
            ])

        sections.append(format_table(nat_headers, nat_rows, title="NAT Rules"))

    # --- Build report ---
    report_body = "\n".join(sections)

    enabled_rules = [r for r in rules if r.get("enabled", True)]
    disabled_rules = [r for r in rules if not r.get("enabled", True)]

    stats_line = (
        f"**{len(enabled_rules)} active rules** | "
        f"**{len(disabled_rules)} disabled** | "
        f"**{len(aliases)} aliases** | "
        f"**{len(nat_rules)} NAT rules**"
    )

    findings_report = format_severity_report("Firewall Audit Findings", findings)

    full_report = f"## Firewall Audit Report\n\n{stats_line}\n\n{report_body}\n{findings_report}"

    logger.info(
        "Generated firewall audit: %d rules, %d aliases, %d NAT rules, %d findings",
        len(rules), len(aliases), len(nat_rules), len(findings),
        extra={"component": "agents.firewall"},
    )

    return full_report
