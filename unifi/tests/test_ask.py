# SPDX-License-Identifier: MIT
"""Tests for unifi.src.ask — AskUserQuestion formatting utilities."""

from __future__ import annotations

import pytest

from unifi.src.ask import (
    Assumption,
    PlanStep,
    format_assumption_resolution,
    format_critical_risk_confirmation,
    format_execution_failure,
    format_plan_confirmation,
    format_plan_modification,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_assumptions() -> list[Assumption]:
    """Mix of resolved and unresolved assumptions."""
    return [
        Assumption(
            question="Which VLAN ID should be used for IoT devices?",
            implication=(
                "If VLAN 50, the plan will reuse the existing IoT network; "
                "if VLAN 60, a new network will be created."
            ),
        ),
        Assumption(
            question="Is VLAN 10 currently in use?",
            implication="If yes, the plan will skip VLAN 10 creation.",
            determined_value="Yes — 3 clients currently on VLAN 10",
        ),
        Assumption(
            question="Should the guest network use client isolation?",
            implication=(
                "If yes, wireless clients will be isolated from each other; "
                "if no, guests can communicate peer-to-peer."
            ),
        ),
    ]


@pytest.fixture()
def sample_steps() -> list[PlanStep]:
    """A three-step cross-vendor plan."""
    return [
        PlanStep(
            number=1,
            system="opnsense",
            action="Create VLAN interface",
            detail="Create VLAN 50 on igc3 with description 'IoT'",
            expected_outcome="VLAN 50 interface appears in Interfaces > Assignments",
        ),
        PlanStep(
            number=2,
            system="opnsense",
            action="Add firewall rule",
            detail="Block VLAN 50 -> VLAN 1 on all ports",
            expected_outcome="Rule appears in Firewall > Rules > VLAN50",
        ),
        PlanStep(
            number=3,
            system="unifi",
            action="Create network",
            detail="Create 'IoT' network on VLAN 50, subnet 10.0.50.0/24",
            expected_outcome="Network visible in UniFi > Settings > Networks",
        ),
    ]


# ---------------------------------------------------------------------------
# Scenario 1: Assumption resolution
# ---------------------------------------------------------------------------

class TestFormatAssumptionResolution:
    """Tests for format_assumption_resolution."""

    def test_header_present(self, sample_assumptions: list[Assumption]) -> None:
        result = format_assumption_resolution(sample_assumptions)
        assert "## Assumption Resolution" in result

    def test_resolved_assumptions_shown(
        self, sample_assumptions: list[Assumption]
    ) -> None:
        result = format_assumption_resolution(sample_assumptions)
        assert "### Already Determined" in result
        assert "VLAN 10" in result
        assert "determined from API" in result

    def test_unresolved_assumptions_as_questions(
        self, sample_assumptions: list[Assumption]
    ) -> None:
        result = format_assumption_resolution(sample_assumptions)
        assert "### Questions" in result
        assert "Which VLAN ID should be used for IoT devices?" in result
        assert "Should the guest network use client isolation?" in result

    def test_implications_included(
        self, sample_assumptions: list[Assumption]
    ) -> None:
        result = format_assumption_resolution(sample_assumptions)
        assert "If VLAN 50" in result
        assert "If yes, wireless clients" in result

    def test_resolved_facts_parameter(self) -> None:
        assumptions = [
            Assumption(
                question="Use DHCP?",
                implication="If yes, DHCP scope created; if no, static only.",
            ),
        ]
        facts = ["Interface igc3 is currently unused", "No VLAN 50 conflicts"]
        result = format_assumption_resolution(assumptions, resolved_facts=facts)
        assert "Interface igc3 is currently unused" in result
        assert "No VLAN 50 conflicts" in result

    def test_all_resolved_no_questions(self) -> None:
        assumptions = [
            Assumption(
                question="Is VLAN 10 in use?",
                implication="If yes, skip creation.",
                determined_value="No — VLAN 10 is free",
            ),
        ]
        result = format_assumption_resolution(assumptions)
        assert "### Questions" not in result
        assert "All assumptions resolved from the API" in result

    def test_empty_assumptions(self) -> None:
        result = format_assumption_resolution([])
        assert "## Assumption Resolution" in result
        assert "All assumptions resolved" in result

    def test_numbering_of_questions(self) -> None:
        assumptions = [
            Assumption(question="Q1?", implication="Impl 1"),
            Assumption(question="Q2?", implication="Impl 2"),
            Assumption(question="Q3?", implication="Impl 3"),
        ]
        result = format_assumption_resolution(assumptions)
        assert "**1. Q1?**" in result
        assert "**2. Q2?**" in result
        assert "**3. Q3?**" in result


# ---------------------------------------------------------------------------
# Scenario 2: Plan confirmation
# ---------------------------------------------------------------------------

class TestFormatPlanConfirmation:
    """Tests for format_plan_confirmation."""

    def test_header_present(self, sample_steps: list[PlanStep]) -> None:
        result = format_plan_confirmation(sample_steps)
        assert "## Change Plan" in result

    def test_all_steps_rendered(self, sample_steps: list[PlanStep]) -> None:
        result = format_plan_confirmation(sample_steps)
        assert "[opnsense]" in result
        assert "[unifi]" in result
        assert "Create VLAN interface" in result
        assert "Add firewall rule" in result
        assert "Create network" in result

    def test_expected_outcomes_shown(self, sample_steps: list[PlanStep]) -> None:
        result = format_plan_confirmation(sample_steps)
        assert "Expected outcome:" in result
        assert "VLAN 50 interface appears" in result

    def test_confirmation_prompt(self, sample_steps: list[PlanStep]) -> None:
        result = format_plan_confirmation(sample_steps)
        assert "3 step(s) across [opnsense, unifi]" in result
        assert "Confirm to proceed, or tell me what to change." in result

    def test_outage_risk_at_top(self, sample_steps: list[PlanStep]) -> None:
        result = format_plan_confirmation(
            sample_steps,
            outage_risk="LOW — no infrastructure in the operator's session path is affected.",
        )
        assert "### Outage Risk Assessment" in result
        assert "LOW" in result
        # Risk should appear before the step list
        risk_pos = result.index("Outage Risk Assessment")
        steps_pos = result.index("Execution Steps")
        assert risk_pos < steps_pos

    def test_security_findings(self, sample_steps: list[PlanStep]) -> None:
        result = format_plan_confirmation(
            sample_steps,
            security_findings=[
                "VLAN 50 has no egress filtering — consider adding outbound rules.",
                "Default DHCP range exposes .1 gateway address.",
            ],
        )
        assert "### Security Review" in result
        assert "egress filtering" in result
        assert "Default DHCP range" in result

    def test_rollback_steps(self, sample_steps: list[PlanStep]) -> None:
        result = format_plan_confirmation(
            sample_steps,
            rollback_steps=[
                "Delete 'IoT' network from UniFi",
                "Remove VLAN 50 firewall rule from OPNsense",
                "Delete VLAN 50 interface from OPNsense",
            ],
        )
        assert "### Rollback Plan" in result
        assert "1. Delete 'IoT' network" in result
        assert "3. Delete VLAN 50 interface" in result

    def test_no_optional_sections(self, sample_steps: list[PlanStep]) -> None:
        result = format_plan_confirmation(sample_steps)
        assert "Outage Risk Assessment" not in result
        assert "Security Review" not in result
        assert "Rollback Plan" not in result

    def test_single_system_label(self) -> None:
        steps = [
            PlanStep(
                number=1,
                system="unifi",
                action="Update SSID",
                detail="Change password for 'Guest' SSID",
                expected_outcome="SSID password updated",
            ),
        ]
        result = format_plan_confirmation(steps)
        assert "1 step(s) across [unifi]" in result


# ---------------------------------------------------------------------------
# Scenario 3: CRITICAL risk confirmation
# ---------------------------------------------------------------------------

class TestFormatCriticalRiskConfirmation:
    """Tests for format_critical_risk_confirmation."""

    def test_critical_warning_callout(self) -> None:
        result = format_critical_risk_confirmation(
            risk_description="This change modifies VLAN 1 on igc0.",
            affected_path="VLAN 1 on igc0 — management session path",
        )
        assert "> **CRITICAL OUTAGE RISK**" in result

    def test_risk_description_included(self) -> None:
        result = format_critical_risk_confirmation(
            risk_description="Reconfiguring the management interface.",
            affected_path="igc0 — primary management interface",
        )
        assert "Reconfiguring the management interface." in result

    def test_affected_path_included(self) -> None:
        result = format_critical_risk_confirmation(
            risk_description="VLAN change on management path.",
            affected_path="VLAN 1 on igc0",
        )
        assert "**Affected path:** VLAN 1 on igc0" in result

    def test_generic_yes_not_sufficient(self) -> None:
        result = format_critical_risk_confirmation(
            risk_description="Risk.",
            affected_path="path",
        )
        assert 'generic "yes" is NOT sufficient' in result

    def test_out_of_band_access_request(self) -> None:
        result = format_critical_risk_confirmation(
            risk_description="Risk.",
            affected_path="path",
        )
        assert "out-of-band access method" in result
        assert "serial console" in result
        assert "IPMI" in result
        assert "physical access" in result
        assert "management VLAN" in result

    def test_visually_distinct_from_standard(self) -> None:
        """CRITICAL prompt uses blockquote callouts (>), unlike standard prompts."""
        result = format_critical_risk_confirmation(
            risk_description="Risk.",
            affected_path="path",
        )
        # Blockquote lines indicate visual distinction
        blockquote_lines = [
            line for line in result.splitlines() if line.startswith(">")
        ]
        assert len(blockquote_lines) >= 3


# ---------------------------------------------------------------------------
# Scenario 4: Execution failure
# ---------------------------------------------------------------------------

class TestFormatExecutionFailure:
    """Tests for format_execution_failure."""

    def test_execution_stopped_callout(
        self, sample_steps: list[PlanStep]
    ) -> None:
        result = format_execution_failure(
            completed_steps=sample_steps[:2],
            failed_step=sample_steps[2],
            error="Connection refused",
        )
        assert "> **EXECUTION STOPPED**" in result

    def test_completed_steps_shown(
        self, sample_steps: list[PlanStep]
    ) -> None:
        result = format_execution_failure(
            completed_steps=sample_steps[:2],
            failed_step=sample_steps[2],
            error="Connection refused",
        )
        assert "### Completed Steps" in result
        assert "[x] Step 1" in result
        assert "[x] Step 2" in result

    def test_failed_step_shown(self, sample_steps: list[PlanStep]) -> None:
        result = format_execution_failure(
            completed_steps=sample_steps[:2],
            failed_step=sample_steps[2],
            error="Connection refused: 10.0.1.1:443",
        )
        assert "### Failed Step" in result
        assert "[ ] Step 3" in result
        assert "[unifi]" in result
        assert "Connection refused: 10.0.1.1:443" in result

    def test_no_completed_steps(self, sample_steps: list[PlanStep]) -> None:
        result = format_execution_failure(
            completed_steps=[],
            failed_step=sample_steps[0],
            error="Auth failed",
        )
        assert "No steps completed before the failure." in result
        assert "### Completed Steps" not in result

    def test_rollback_prompt(self, sample_steps: list[PlanStep]) -> None:
        result = format_execution_failure(
            completed_steps=sample_steps[:1],
            failed_step=sample_steps[1],
            error="Rule conflict",
        )
        assert "attempt rollback" in result
        assert "leave the current state" in result
        assert "assess manually" in result

    def test_failed_step_detail_included(
        self, sample_steps: list[PlanStep]
    ) -> None:
        result = format_execution_failure(
            completed_steps=[],
            failed_step=sample_steps[0],
            error="Timeout",
        )
        assert sample_steps[0].detail in result


# ---------------------------------------------------------------------------
# Scenario 5: Plan modification
# ---------------------------------------------------------------------------

class TestFormatPlanModification:
    """Tests for format_plan_modification."""

    def test_header_present(self, sample_steps: list[PlanStep]) -> None:
        result = format_plan_modification(
            original_steps=sample_steps,
            modified_steps=sample_steps,
            reason="No changes requested",
        )
        assert "## Modified Plan" in result

    def test_reason_shown(self, sample_steps: list[PlanStep]) -> None:
        result = format_plan_modification(
            original_steps=sample_steps,
            modified_steps=sample_steps,
            reason="Operator requested VLAN 60 instead of VLAN 50",
        )
        assert "Reason for modification:" in result
        assert "VLAN 60 instead of VLAN 50" in result

    def test_changed_step_highlighted(self) -> None:
        original = [
            PlanStep(
                number=1,
                system="opnsense",
                action="Create VLAN",
                detail="Create VLAN 50 on igc3",
                expected_outcome="VLAN 50 interface created",
            ),
        ]
        modified = [
            PlanStep(
                number=1,
                system="opnsense",
                action="Create VLAN",
                detail="Create VLAN 60 on igc3",
                expected_outcome="VLAN 60 interface created",
            ),
        ]
        result = format_plan_modification(
            original_steps=original,
            modified_steps=modified,
            reason="Changed VLAN ID",
        )
        assert "Step 1 (modified)" in result
        assert "Was: Create VLAN 50 on igc3" in result
        assert "Now: Create VLAN 60 on igc3" in result

    def test_added_step_shown(self, sample_steps: list[PlanStep]) -> None:
        added_step = PlanStep(
            number=4,
            system="unifi",
            action="Create WiFi SSID",
            detail="Create 'IoT-WiFi' SSID on VLAN 50",
            expected_outcome="SSID visible in WiFi settings",
        )
        result = format_plan_modification(
            original_steps=sample_steps,
            modified_steps=sample_steps + [added_step],
            reason="Added WiFi SSID",
        )
        assert "Step 4 (added)" in result
        assert "IoT-WiFi" in result

    def test_removed_step_shown(self, sample_steps: list[PlanStep]) -> None:
        result = format_plan_modification(
            original_steps=sample_steps,
            modified_steps=sample_steps[:2],
            reason="Removed UniFi network creation",
        )
        assert "Step 3 (removed)" in result
        assert "Was:" in result

    def test_unchanged_steps_count(self, sample_steps: list[PlanStep]) -> None:
        # Modify only step 2, leave 1 and 3 unchanged
        modified = list(sample_steps)
        modified[1] = PlanStep(
            number=2,
            system="opnsense",
            action="Add firewall rule",
            detail="Allow VLAN 50 -> WAN on port 443 only",
            expected_outcome="Rule appears in Firewall > Rules > VLAN50",
        )
        result = format_plan_modification(
            original_steps=sample_steps,
            modified_steps=modified,
            reason="Restricted firewall rule",
        )
        assert "2 step(s) unchanged" in result

    def test_fresh_confirmation_prompt(
        self, sample_steps: list[PlanStep]
    ) -> None:
        result = format_plan_modification(
            original_steps=sample_steps,
            modified_steps=sample_steps,
            reason="No changes",
        )
        assert "Confirm to proceed, or tell me what to change." in result

    def test_updated_execution_steps_section(
        self, sample_steps: list[PlanStep]
    ) -> None:
        result = format_plan_modification(
            original_steps=sample_steps,
            modified_steps=sample_steps,
            reason="No changes",
        )
        assert "### Updated Execution Steps" in result

    def test_systems_label_in_confirmation(self) -> None:
        steps = [
            PlanStep(
                number=1,
                system="opnsense",
                action="Do thing",
                detail="Detail",
                expected_outcome="Outcome",
            ),
        ]
        result = format_plan_modification(
            original_steps=steps,
            modified_steps=steps,
            reason="Test",
        )
        assert "1 step(s) across [opnsense]" in result


# ---------------------------------------------------------------------------
# Data structure tests
# ---------------------------------------------------------------------------

class TestDataStructures:
    """Tests for Assumption and PlanStep dataclasses."""

    def test_assumption_defaults(self) -> None:
        a = Assumption(question="Q?", implication="Imp")
        assert a.question == "Q?"
        assert a.implication == "Imp"
        assert a.determined_value is None

    def test_assumption_with_determined_value(self) -> None:
        a = Assumption(
            question="Q?",
            implication="Imp",
            determined_value="Yes",
        )
        assert a.determined_value == "Yes"

    def test_plan_step_fields(self) -> None:
        s = PlanStep(
            number=1,
            system="unifi",
            action="Create network",
            detail="VLAN 50",
            expected_outcome="Network created",
        )
        assert s.number == 1
        assert s.system == "unifi"
        assert s.action == "Create network"
        assert s.detail == "VLAN 50"
        assert s.expected_outcome == "Network created"
