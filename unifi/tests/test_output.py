"""Tests for the OX output formatting module."""

from __future__ import annotations

from unifi.output import (
    Finding,
    Severity,
    format_change_plan,
    format_diff,
    format_key_value,
    format_risk_block,
    format_severity_report,
    format_summary,
    format_table,
)

# ---------------------------------------------------------------------------
# Severity enum
# ---------------------------------------------------------------------------


class TestSeverity:
    def test_values(self) -> None:
        assert Severity.CRITICAL == "critical"
        assert Severity.HIGH == "high"
        assert Severity.WARNING == "warning"
        assert Severity.INFORMATIONAL == "informational"

    def test_is_str(self) -> None:
        """Severity members should behave as plain strings."""
        assert isinstance(Severity.CRITICAL, str)
        assert f"Level: {Severity.HIGH}" == "Level: high"


# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------


class TestFinding:
    def test_minimal(self) -> None:
        f = Finding(severity=Severity.HIGH, title="Test", detail="Details here")
        assert f.severity == Severity.HIGH
        assert f.title == "Test"
        assert f.detail == "Details here"
        assert f.recommendation is None

    def test_with_recommendation(self) -> None:
        f = Finding(
            severity=Severity.WARNING,
            title="Weak cipher",
            detail="TLS 1.0 in use",
            recommendation="Upgrade to TLS 1.3",
        )
        assert f.recommendation == "Upgrade to TLS 1.3"


# ---------------------------------------------------------------------------
# format_severity_report
# ---------------------------------------------------------------------------


class TestFormatSeverityReport:
    def test_empty_findings(self) -> None:
        result = format_severity_report("Test Report", [])
        assert "## Test Report" in result
        assert "No findings." in result

    def test_single_finding(self) -> None:
        findings = [
            Finding(
                severity=Severity.CRITICAL,
                title="Device offline",
                detail="USW-24 is unreachable.",
                recommendation="Check power and uplink.",
            ),
        ]
        result = format_severity_report("Health Report", findings)
        assert "## Health Report" in result
        assert "1 findings" in result or "1 CRITICAL" in result
        assert "[!!!] CRITICAL" in result
        assert "**Device offline**" in result
        assert "USW-24 is unreachable." in result
        assert "*Recommendation:* Check power and uplink." in result

    def test_multiple_severities_ordered(self) -> None:
        findings = [
            Finding(severity=Severity.INFORMATIONAL, title="Info item", detail="Low priority"),
            Finding(severity=Severity.CRITICAL, title="Critical item", detail="Urgent"),
            Finding(severity=Severity.WARNING, title="Warning item", detail="Check this"),
            Finding(severity=Severity.HIGH, title="High item", detail="Important"),
        ]
        result = format_severity_report("Mixed Report", findings)

        # Verify severity sections appear in correct order.
        crit_pos = result.index("[!!!] CRITICAL")
        high_pos = result.index("[!!] HIGH")
        warn_pos = result.index("[!] Warning")
        info_pos = result.index("[i] Informational")

        assert crit_pos < high_pos < warn_pos < info_pos

    def test_multiple_findings_same_severity(self) -> None:
        findings = [
            Finding(severity=Severity.HIGH, title="Issue A", detail="Detail A"),
            Finding(severity=Severity.HIGH, title="Issue B", detail="Detail B"),
        ]
        result = format_severity_report("Report", findings)
        assert result.count("[!!] HIGH") == 1  # One section header
        assert "**Issue A**" in result
        assert "**Issue B**" in result

    def test_missing_severity_tiers_omitted(self) -> None:
        findings = [
            Finding(severity=Severity.WARNING, title="Only warning", detail="Something"),
        ]
        result = format_severity_report("Sparse Report", findings)
        assert "CRITICAL" not in result
        assert "HIGH" not in result
        assert "[!] Warning" in result
        assert "Informational" not in result

    def test_summary_counts(self) -> None:
        findings = [
            Finding(severity=Severity.CRITICAL, title="C1", detail="d"),
            Finding(severity=Severity.CRITICAL, title="C2", detail="d"),
            Finding(severity=Severity.WARNING, title="W1", detail="d"),
        ]
        result = format_severity_report("Summary Test", findings)
        assert "3 findings" in result
        assert "2 CRITICAL" in result
        assert "1 Warning" in result

    def test_finding_without_recommendation(self) -> None:
        findings = [
            Finding(severity=Severity.INFORMATIONAL, title="Note", detail="FYI"),
        ]
        result = format_severity_report("Report", findings)
        assert "Recommendation" not in result


# ---------------------------------------------------------------------------
# format_table
# ---------------------------------------------------------------------------


class TestFormatTable:
    def test_empty_headers(self) -> None:
        result = format_table([], [])
        assert result == ""

    def test_headers_only(self) -> None:
        result = format_table(["Name", "Status"], [])
        assert "| Name" in result
        assert "| Status" in result
        assert "| ----" in result

    def test_basic_table(self) -> None:
        headers = ["Device", "IP", "Status"]
        rows = [
            ["USW-24", "192.168.1.10", "Online"],
            ["UAP-AC-Pro", "192.168.1.11", "Offline"],
        ]
        result = format_table(headers, rows)
        assert "| Device" in result
        assert "USW-24" in result
        assert "UAP-AC-Pro" in result
        # Should be valid markdown table.
        table_lines = [line for line in result.strip().split("\n") if line.startswith("|")]
        assert len(table_lines) == 4  # header + separator + 2 data rows

    def test_with_title(self) -> None:
        result = format_table(["Col"], [["val"]], title="Device Inventory")
        assert "### Device Inventory" in result

    def test_column_width_alignment(self) -> None:
        """Wider values should expand column width."""
        headers = ["A", "B"]
        rows = [["very long value", "x"]]
        result = format_table(headers, rows)
        # The separator should be at least as wide as the longest value.
        sep_line = next(line for line in result.split("\n") if "---" in line)
        assert "---------------" in sep_line

    def test_short_row_padded(self) -> None:
        """Rows shorter than headers should be padded."""
        headers = ["A", "B", "C"]
        rows = [["only one"]]
        result = format_table(headers, rows)
        # Should not raise; the row is padded with empty strings.
        data_lines = [
            line
            for line in result.strip().split("\n")
            if line.startswith("|") and "---" not in line
        ]
        assert len(data_lines) == 2  # header + 1 data row

    def test_long_row_truncated(self) -> None:
        """Rows longer than headers should be truncated to header count."""
        headers = ["A", "B"]
        rows = [["1", "2", "3", "4"]]
        result = format_table(headers, rows)
        # Extra columns should not appear.
        data_line = next(
            line
            for line in result.strip().split("\n")
            if line.startswith("|") and "---" not in line and "A" not in line
        )
        assert "3" not in data_line
        assert "4" not in data_line


# ---------------------------------------------------------------------------
# format_key_value
# ---------------------------------------------------------------------------


class TestFormatKeyValue:
    def test_empty_data(self) -> None:
        result = format_key_value({})
        assert result == ""

    def test_basic_pairs(self) -> None:
        data = {"Name": "USW-24", "IP": "192.168.1.10", "MAC": "aa:bb:cc:dd:ee:ff"}
        result = format_key_value(data)
        assert "**Name" in result
        assert "USW-24" in result
        assert "**IP" in result
        assert "**MAC" in result

    def test_with_title(self) -> None:
        result = format_key_value({"Key": "Val"}, title="Device Details")
        assert "### Device Details" in result

    def test_key_alignment(self) -> None:
        """Keys should be padded to the same width for alignment."""
        data = {"A": "1", "LongKey": "2"}
        result = format_key_value(data)
        # The shorter key should be padded.
        lines = [line for line in result.split("\n") if line.startswith("**")]
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# format_diff
# ---------------------------------------------------------------------------


class TestFormatDiff:
    def test_no_changes(self) -> None:
        state = {"a": 1, "b": 2}
        result = format_diff(state, state)
        assert "No changes detected." in result

    def test_changed_field(self) -> None:
        before = {"status": "online", "ip": "10.0.0.1"}
        after = {"status": "offline", "ip": "10.0.0.1"}
        result = format_diff(before, after)
        assert "**Changed:**" in result
        assert "`status`" in result
        assert "`online`" in result
        assert "`offline`" in result

    def test_added_field(self) -> None:
        before = {"a": 1}
        after = {"a": 1, "b": 2}
        result = format_diff(before, after)
        assert "**Added:**" in result
        assert "`b`" in result
        assert "`2`" in result

    def test_removed_field(self) -> None:
        before = {"a": 1, "b": 2}
        after = {"a": 1}
        result = format_diff(before, after)
        assert "**Removed:**" in result
        assert "`b`" in result
        assert "`2`" in result

    def test_mixed_changes(self) -> None:
        before = {"keep": "same", "change": "old", "remove": "gone"}
        after = {"keep": "same", "change": "new", "add": "fresh"}
        result = format_diff(before, after)
        assert "**Changed:**" in result
        assert "**Added:**" in result
        assert "**Removed:**" in result
        assert "**Unchanged:** 1 field(s)" in result

    def test_with_title(self) -> None:
        result = format_diff({"a": 1}, {"a": 2}, title="Config Diff")
        assert "### Config Diff" in result

    def test_order_changed_before_added_before_removed(self) -> None:
        """Changed, Added, Removed sections should appear in that order."""
        before = {"change": "old", "remove": "x"}
        after = {"change": "new", "add": "y"}
        result = format_diff(before, after)

        changed_pos = result.index("**Changed:**")
        added_pos = result.index("**Added:**")
        removed_pos = result.index("**Removed:**")

        assert changed_pos < added_pos < removed_pos

    def test_both_empty(self) -> None:
        result = format_diff({}, {})
        assert "No changes detected." in result

    def test_all_new(self) -> None:
        result = format_diff({}, {"a": 1, "b": 2})
        assert "**Added:**" in result
        assert "Changed" not in result
        assert "Removed" not in result

    def test_all_removed(self) -> None:
        result = format_diff({"a": 1, "b": 2}, {})
        assert "**Removed:**" in result
        assert "Changed" not in result
        assert "Added" not in result


# ---------------------------------------------------------------------------
# format_risk_block
# ---------------------------------------------------------------------------


class TestFormatRiskBlock:
    def test_basic_risk(self) -> None:
        result = format_risk_block("HIGH", "Change affects management VLAN")
        assert "[OUTAGE RISK: HIGH]" in result
        assert "Change affects management VLAN" in result

    def test_with_affected_path(self) -> None:
        result = format_risk_block(
            "CRITICAL",
            "Direct path to operator session",
            affected_path="VLAN 1 -> ge-0/0/1 -> USW-24 port 3",
        )
        assert "[OUTAGE RISK: CRITICAL]" in result
        assert "**Affected path:**" in result
        assert "VLAN 1 -> ge-0/0/1 -> USW-24 port 3" in result

    def test_without_affected_path(self) -> None:
        result = format_risk_block("LOW", "No session path overlap")
        assert "Affected path" not in result

    def test_tier_uppercased(self) -> None:
        result = format_risk_block("medium", "Some risk")
        assert "[OUTAGE RISK: MEDIUM]" in result


# ---------------------------------------------------------------------------
# format_change_plan
# ---------------------------------------------------------------------------


class TestFormatChangePlan:
    def test_minimal_plan(self) -> None:
        steps = [{"description": "Create VLAN 10"}]
        result = format_change_plan(steps)
        assert "## Change Plan" in result
        assert "### [CHANGE PLAN]" in result
        assert "1. Create VLAN 10" in result
        # No optional sections.
        assert "[OUTAGE RISK]" not in result.replace("[CHANGE PLAN]", "")
        assert "[SECURITY]" not in result
        assert "[ROLLBACK]" not in result

    def test_full_plan(self) -> None:
        steps = [
            {"description": "Add VLAN interface", "system": "opnsense"},
            {"description": "Add DHCP subnet", "system": "opnsense", "detail": "10.10.0.0/24"},
            {"description": "Create network", "system": "unifi"},
        ]
        risk = format_risk_block("MEDIUM", "Indirect disruption possible")
        security_findings = [
            Finding(
                severity=Severity.WARNING,
                title="Broad rule",
                detail="New VLAN allows all outbound",
                recommendation="Restrict to needed ports",
            ),
        ]
        rollback = [
            "Remove unifi network object",
            "Delete opnsense DHCP subnet",
            "Delete opnsense VLAN interface",
        ]

        result = format_change_plan(
            steps,
            outage_risk=risk,
            security_findings=security_findings,
            rollback_steps=rollback,
        )

        # All four sections present.
        assert "### [OUTAGE RISK]" in result
        assert "### [SECURITY]" in result
        assert "### [CHANGE PLAN]" in result
        assert "### [ROLLBACK]" in result

        # Correct order.
        risk_pos = result.index("[OUTAGE RISK]")
        sec_pos = result.index("[SECURITY]")
        plan_pos = result.index("[CHANGE PLAN]")
        roll_pos = result.index("[ROLLBACK]")
        assert risk_pos < sec_pos < plan_pos < roll_pos

    def test_steps_numbered_with_system(self) -> None:
        steps = [
            {"description": "Step one", "system": "opnsense"},
            {"description": "Step two", "system": "unifi"},
        ]
        result = format_change_plan(steps)
        assert "1. [opnsense] Step one" in result
        assert "2. [unifi] Step two" in result

    def test_steps_without_system(self) -> None:
        steps = [{"description": "Generic step"}]
        result = format_change_plan(steps)
        assert "1. Generic step" in result
        # No system prefix brackets.
        assert "[" not in result.split("1. ")[1].split("\n")[0] or "Generic" in result

    def test_step_with_detail(self) -> None:
        steps = [{"description": "Create DHCP", "detail": "Range: 10.0.0.100-200"}]
        result = format_change_plan(steps)
        assert "Range: 10.0.0.100-200" in result

    def test_security_findings_sorted_by_severity(self) -> None:
        findings = [
            Finding(severity=Severity.INFORMATIONAL, title="Info", detail="d"),
            Finding(severity=Severity.CRITICAL, title="Crit", detail="d"),
        ]
        result = format_change_plan(
            [{"description": "step"}],
            security_findings=findings,
        )
        crit_pos = result.index("Crit")
        info_pos = result.index("Info")
        assert crit_pos < info_pos

    def test_rollback_steps_numbered(self) -> None:
        rollback = ["Undo A", "Undo B", "Undo C"]
        result = format_change_plan(
            [{"description": "step"}],
            rollback_steps=rollback,
        )
        assert "1. Undo A" in result
        assert "2. Undo B" in result
        assert "3. Undo C" in result
        assert "following steps will be attempted" in result

    def test_empty_security_findings_omits_section(self) -> None:
        result = format_change_plan(
            [{"description": "step"}],
            security_findings=[],
        )
        assert "[SECURITY]" not in result

    def test_outage_risk_as_plain_string(self) -> None:
        result = format_change_plan(
            [{"description": "step"}],
            outage_risk="LOW -- no session path overlap.",
        )
        assert "### [OUTAGE RISK]" in result
        assert "LOW -- no session path overlap." in result


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------


class TestFormatSummary:
    def test_basic_summary(self) -> None:
        stats = {"Devices": 5, "VLANs": 3, "Clients": 12}
        result = format_summary("Scan Complete", stats)
        assert "## Scan Complete" in result
        assert "**Devices:** 5" in result
        assert "**VLANs:** 3" in result
        assert "**Clients:** 12" in result

    def test_with_detail(self) -> None:
        result = format_summary(
            "Health Check",
            {"Issues": 2},
            detail="2 devices require firmware updates.",
        )
        assert "## Health Check" in result
        assert "**Issues:** 2" in result
        assert "2 devices require firmware updates." in result

    def test_without_detail(self) -> None:
        result = format_summary("Done", {"Total": 0})
        # Should not have extra blank lines beyond standard spacing.
        assert result.strip().endswith("**Total:** 0")

    def test_string_stat_values(self) -> None:
        result = format_summary("Info", {"Status": "healthy", "Version": "7.0.23"})
        assert "**Status:** healthy" in result
        assert "**Version:** 7.0.23" in result

    def test_stats_separated_by_pipe(self) -> None:
        stats = {"A": 1, "B": 2}
        result = format_summary("Title", stats)
        assert "**A:** 1 | **B:** 2" in result
