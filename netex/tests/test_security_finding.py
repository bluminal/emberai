# SPDX-License-Identifier: MIT
"""Tests for the SecurityFinding model."""

from __future__ import annotations

from netex.models.security_finding import (
    FindingCategory,
    FindingSeverity,
    SecurityFinding,
    group_findings_by_category,
    sort_findings,
)

# ---------------------------------------------------------------------------
# SecurityFinding construction
# ---------------------------------------------------------------------------

class TestSecurityFinding:
    def test_minimal_construction(self) -> None:
        finding = SecurityFinding(
            severity=FindingSeverity.HIGH,
            category=FindingCategory.FIREWALL_POLICY,
            description="Overly broad allow rule",
        )
        assert finding.severity == FindingSeverity.HIGH
        assert finding.category == FindingCategory.FIREWALL_POLICY
        assert finding.description == "Overly broad allow rule"
        assert finding.why_it_matters == ""
        assert finding.recommendation == ""

    def test_full_construction(self) -> None:
        finding = SecurityFinding(
            severity=FindingSeverity.CRITICAL,
            category=FindingCategory.MANAGEMENT_EXPOSURE,
            description="OPNsense UI reachable from untrusted VLAN",
            why_it_matters="Attackers on the guest network could access the firewall admin",
            recommendation="Add deny rule for guest VLAN to management interface",
            source_plugin="opnsense",
            source_tool="opnsense__firewall__list_rules",
            affected_resource="rule-uuid-abc",
            metadata={"vlan_id": 50},
        )
        assert finding.source_plugin == "opnsense"
        assert finding.source_tool == "opnsense__firewall__list_rules"
        assert finding.affected_resource == "rule-uuid-abc"
        assert finding.metadata["vlan_id"] == 50

    def test_format_for_report_minimal(self) -> None:
        finding = SecurityFinding(
            severity=FindingSeverity.LOW,
            category=FindingCategory.GENERAL,
            description="Minor issue",
        )
        report = finding.format_for_report()
        assert "**Severity:** LOW" in report
        assert "**Issue:** Minor issue" in report
        assert "**Why it matters:**" not in report

    def test_format_for_report_full(self) -> None:
        finding = SecurityFinding(
            severity=FindingSeverity.HIGH,
            category=FindingCategory.VLAN_ISOLATION,
            description="Missing isolation rule",
            why_it_matters="VLAN 30 can reach VLAN 10",
            recommendation="Add deny rule between VLANs",
            source_plugin="opnsense",
            source_tool="opnsense__firewall__list_rules",
            affected_resource="vlan-30-to-10",
        )
        report = finding.format_for_report()
        assert "**Severity:** HIGH" in report
        assert "**Why it matters:** VLAN 30 can reach VLAN 10" in report
        assert "**Recommendation:** Add deny rule" in report
        assert "**Source:** opnsense (opnsense__firewall__list_rules)" in report
        assert "**Affected resource:** vlan-30-to-10" in report

    def test_serialization_roundtrip(self) -> None:
        finding = SecurityFinding(
            severity=FindingSeverity.MEDIUM,
            category=FindingCategory.DNS_SECURITY,
            description="DNS forwarder without DoT",
            source_plugin="opnsense",
        )
        data = finding.model_dump()
        restored = SecurityFinding.model_validate(data)
        assert restored.severity == FindingSeverity.MEDIUM
        assert restored.category == FindingCategory.DNS_SECURITY

    def test_json_roundtrip(self) -> None:
        finding = SecurityFinding(
            severity=FindingSeverity.HIGH,
            category=FindingCategory.FIREWALL_POLICY,
            description="Test",
        )
        json_str = finding.model_dump_json()
        restored = SecurityFinding.model_validate_json(json_str)
        assert restored.severity == FindingSeverity.HIGH


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

class TestSortFindings:
    def test_sort_by_severity(self) -> None:
        findings = [
            SecurityFinding(
                severity=FindingSeverity.LOW,
                category=FindingCategory.GENERAL,
                description="low",
            ),
            SecurityFinding(
                severity=FindingSeverity.CRITICAL,
                category=FindingCategory.GENERAL,
                description="critical",
            ),
            SecurityFinding(
                severity=FindingSeverity.HIGH,
                category=FindingCategory.GENERAL,
                description="high",
            ),
            SecurityFinding(
                severity=FindingSeverity.MEDIUM,
                category=FindingCategory.GENERAL,
                description="medium",
            ),
        ]
        sorted_f = sort_findings(findings)
        assert [f.severity for f in sorted_f] == [
            FindingSeverity.CRITICAL,
            FindingSeverity.HIGH,
            FindingSeverity.MEDIUM,
            FindingSeverity.LOW,
        ]

    def test_stable_sort_within_severity(self) -> None:
        findings = [
            SecurityFinding(
                severity=FindingSeverity.HIGH,
                category=FindingCategory.GENERAL,
                description="first",
            ),
            SecurityFinding(
                severity=FindingSeverity.HIGH,
                category=FindingCategory.GENERAL,
                description="second",
            ),
        ]
        sorted_f = sort_findings(findings)
        assert sorted_f[0].description == "first"
        assert sorted_f[1].description == "second"

    def test_empty_list(self) -> None:
        assert sort_findings([]) == []


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

class TestGroupFindings:
    def test_group_by_category(self) -> None:
        findings = [
            SecurityFinding(
                severity=FindingSeverity.HIGH,
                category=FindingCategory.FIREWALL_POLICY,
                description="fw1",
            ),
            SecurityFinding(
                severity=FindingSeverity.LOW,
                category=FindingCategory.FIREWALL_POLICY,
                description="fw2",
            ),
            SecurityFinding(
                severity=FindingSeverity.MEDIUM,
                category=FindingCategory.DNS_SECURITY,
                description="dns1",
            ),
        ]
        grouped = group_findings_by_category(findings)
        assert FindingCategory.FIREWALL_POLICY in grouped
        assert FindingCategory.DNS_SECURITY in grouped
        assert len(grouped[FindingCategory.FIREWALL_POLICY]) == 2
        assert len(grouped[FindingCategory.DNS_SECURITY]) == 1

    def test_groups_sorted_by_severity(self) -> None:
        findings = [
            SecurityFinding(
                severity=FindingSeverity.LOW,
                category=FindingCategory.FIREWALL_POLICY,
                description="low",
            ),
            SecurityFinding(
                severity=FindingSeverity.CRITICAL,
                category=FindingCategory.FIREWALL_POLICY,
                description="critical",
            ),
        ]
        grouped = group_findings_by_category(findings)
        fw_group = grouped[FindingCategory.FIREWALL_POLICY]
        assert fw_group[0].severity == FindingSeverity.CRITICAL
        assert fw_group[1].severity == FindingSeverity.LOW

    def test_empty_list(self) -> None:
        assert group_findings_by_category([]) == {}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TestEnums:
    def test_severity_values(self) -> None:
        assert FindingSeverity.CRITICAL == "critical"
        assert FindingSeverity.HIGH == "high"
        assert FindingSeverity.MEDIUM == "medium"
        assert FindingSeverity.LOW == "low"
        assert FindingSeverity.INFORMATIONAL == "informational"

    def test_category_values(self) -> None:
        assert FindingCategory.FIREWALL_POLICY == "firewall_policy"
        assert FindingCategory.VLAN_ISOLATION == "vlan_isolation"
        assert FindingCategory.CROSS_LAYER == "cross_layer"
