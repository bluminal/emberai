# SPDX-License-Identifier: MIT
"""AskUserQuestion utility -- structured prompt templates for operator interaction.

Implements the five interaction scenarios defined in PRD Section 10.4
for the netex umbrella plugin.  Since this is an MCP server plugin running
inside Claude, "asking the user" means returning structured prompts that
Claude will present to the operator.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Assumption:
    """A single assumption that may need operator clarification."""

    question: str
    implication: str
    determined_value: str | None = None


@dataclass
class PlanStep:
    """A single step in an ordered change plan."""

    number: int
    system: str
    action: str
    detail: str
    expected_outcome: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_step(step: PlanStep) -> str:
    """Render a single plan step as a numbered markdown line."""
    return (
        f"{step.number}. **[{step.system}]** {step.action}\n"
        f"   {step.detail}\n"
        f"   *Expected outcome:* {step.expected_outcome}"
    )


def _collect_systems(steps: list[PlanStep]) -> list[str]:
    """Return a deduplicated, order-preserving list of system names."""
    seen: set[str] = set()
    systems: list[str] = []
    for step in steps:
        if step.system not in seen:
            seen.add(step.system)
            systems.append(step.system)
    return systems


# ---------------------------------------------------------------------------
# Scenario 1: Assumption resolution (Phase 1)
# ---------------------------------------------------------------------------

def format_assumption_resolution(
    assumptions: list[Assumption],
    resolved_facts: list[str] | None = None,
) -> str:
    """Format Phase 1 assumption resolution into a single prompt."""
    sections: list[str] = ["## Assumption Resolution"]

    resolved_items: list[str] = list(resolved_facts or [])
    unresolved: list[Assumption] = []

    for assumption in assumptions:
        if assumption.determined_value is not None:
            resolved_items.append(
                f"{assumption.question} -- **{assumption.determined_value}** "
                f"(determined from API)"
            )
        else:
            unresolved.append(assumption)

    if resolved_items:
        sections.append("### Already Determined")
        sections.append(
            "The following were resolved from the current system state:"
        )
        sections.append("")
        for item in resolved_items:
            sections.append(f"- {item}")

    if unresolved:
        sections.append("")
        sections.append("### Questions")
        sections.append(
            "I need your input on the following before building the plan:"
        )
        sections.append("")
        for i, assumption in enumerate(unresolved, start=1):
            sections.append(f"**{i}. {assumption.question}**")
            sections.append(f"   {assumption.implication}")
            sections.append("")
    else:
        sections.append("")
        sections.append(
            "All assumptions resolved from the API.  No questions needed."
        )

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Scenario 2: Plan presentation with single confirmation (Phase 2 -> 3)
# ---------------------------------------------------------------------------

def format_plan_confirmation(
    steps: list[PlanStep],
    outage_risk: str | None = None,
    security_findings: list[str] | None = None,
    rollback_steps: list[str] | None = None,
) -> str:
    """Format a complete change plan with a single confirmation prompt."""
    sections: list[str] = ["## Change Plan"]

    if outage_risk:
        sections.append("")
        sections.append("### Outage Risk Assessment")
        sections.append("")
        sections.append(outage_risk)

    if security_findings:
        sections.append("")
        sections.append("### Security Review")
        sections.append("")
        for finding in security_findings:
            sections.append(f"- {finding}")

    sections.append("")
    sections.append("### Execution Steps")
    sections.append("")
    for step in steps:
        sections.append(_format_step(step))
        sections.append("")

    if rollback_steps:
        sections.append("### Rollback Plan")
        sections.append("")
        sections.append(
            "If any step fails, the following rollback procedure is available:"
        )
        sections.append("")
        for i, rollback in enumerate(rollback_steps, start=1):
            sections.append(f"{i}. {rollback}")
        sections.append("")

    systems = _collect_systems(steps)
    systems_label = ", ".join(systems)
    sections.append("---")
    sections.append("")
    sections.append(
        f"**{len(steps)} step(s) across [{systems_label}].** "
        "Confirm to proceed, or tell me what to change."
    )

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Scenario 3: CRITICAL outage risk confirmation
# ---------------------------------------------------------------------------

def format_critical_risk_confirmation(
    risk_description: str,
    affected_path: str,
) -> str:
    """Format a CRITICAL outage risk prompt requiring out-of-band confirmation."""
    lines: list[str] = [
        "> **CRITICAL OUTAGE RISK**",
        ">",
        f"> {risk_description}",
        ">",
        f"> **Affected path:** {affected_path}",
        "",
        "---",
        "",
        "This change directly modifies the interface, VLAN, or route that "
        "your current management session traverses.  If this change fails or "
        "misconfigures the path, you may lose connectivity to the device and "
        "be unable to roll back remotely.",
        "",
        "**A generic \"yes\" is NOT sufficient to proceed.**",
        "",
        "Please describe your out-of-band access method (serial console, "
        "IPMI, physical access, separate management VLAN on a different "
        "physical interface) so I can confirm you have a recovery path "
        "before executing.",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scenario 4: Mid-execution failure
# ---------------------------------------------------------------------------

def format_execution_failure(
    completed_steps: list[PlanStep],
    failed_step: PlanStep,
    error: str,
) -> str:
    """Format a mid-execution failure report."""
    sections: list[str] = [
        "> **EXECUTION STOPPED**",
        ">",
        f"> Step {failed_step.number} failed.  "
        "All subsequent steps have been skipped.",
    ]

    if completed_steps:
        sections.append("")
        sections.append("### Completed Steps")
        sections.append("")
        for step in completed_steps:
            sections.append(
                f"- [x] Step {step.number}: **[{step.system}]** {step.action}"
            )
    else:
        sections.append("")
        sections.append("No steps completed before the failure.")

    sections.append("")
    sections.append("### Failed Step")
    sections.append("")
    sections.append(
        f"- [ ] Step {failed_step.number}: "
        f"**[{failed_step.system}]** {failed_step.action}"
    )
    sections.append(f"  {failed_step.detail}")
    sections.append("")
    sections.append(f"**Error:** {error}")

    sections.append("")
    sections.append("---")
    sections.append("")
    sections.append(
        "Should I attempt rollback of the completed steps, or leave the "
        "current state for you to assess manually?"
    )

    return "\n".join(sections)
