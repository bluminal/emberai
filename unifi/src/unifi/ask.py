# SPDX-License-Identifier: MIT
"""AskUserQuestion utility — structured prompt templates for operator interaction.

Implements the five interaction scenarios defined in PRD Section 10.4
(``AskUserQuestion Implementation Patterns``).  Since this is an MCP server
plugin running inside Claude, "asking the user" means returning structured
prompts that Claude will present to the operator.  This module formats those
prompts consistently.

Scenarios
---------
1. **Assumption resolution** (Phase 1) — batch unresolvable ambiguities into a
   single prompt, state what was already determined from the API, frame each
   question with its implication.
2. **Plan confirmation** (Phase 2 -> 3) — full ordered plan, OutageRiskAgent
   assessment, single confirmation prompt.
3. **Critical risk confirmation** — CRITICAL outage risk requiring explicit
   out-of-band access confirmation.  A generic "yes" is NOT sufficient.
4. **Execution failure** — mid-execution failure report with rollback prompt.
5. **Plan modification** — re-confirmation after operator modifies the plan.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Assumption:
    """A single assumption that may need operator clarification.

    Parameters
    ----------
    question:
        The question to present to the operator.
    implication:
        Explains how each possible answer changes the plan.
        Format: "If X, the plan will do A; if Y, it will do B."
    determined_value:
        When the assumption was pre-resolved from the API, store the
        resolved value here.  It will be displayed to the operator for
        transparency but NOT asked as a question.
    """

    question: str
    implication: str
    determined_value: str | None = None


@dataclass
class PlanStep:
    """A single step in an ordered change plan.

    Parameters
    ----------
    number:
        1-based step number in the execution sequence.
    system:
        Plugin name that owns this step (e.g. ``"opnsense"``, ``"unifi"``).
    action:
        Short verb phrase describing the operation (e.g. ``"Create VLAN"``).
    detail:
        Full description of what will be changed, on which resource.
    expected_outcome:
        What the operator should observe after this step succeeds.
    """

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
    """Format Phase 1 assumption resolution into a single prompt.

    Groups all unresolvable ambiguities into one question block.  States what
    was already determined from the API.  Frames each remaining question with
    its implication so the operator understands how their answer shapes the
    plan.

    Parameters
    ----------
    assumptions:
        All assumptions gathered during Phase 1.  Assumptions with a
        non-``None`` ``determined_value`` are displayed as resolved facts
        rather than asked as questions.
    resolved_facts:
        Additional facts already determined from the API that the operator
        should be aware of but does not need to answer.

    Returns
    -------
    str
        Markdown-formatted prompt ready for Claude to present.
    """
    sections: list[str] = ["## Assumption Resolution"]

    # --- Resolved facts (from API + pre-determined assumptions) ---
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

    # --- Unresolved questions ---
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
    """Format a complete change plan with a single confirmation prompt.

    Follows the PRD Section 10.2 structure:
    ``[OUTAGE RISK] -> [SECURITY] -> [CHANGE PLAN] -> [ROLLBACK]``

    Parameters
    ----------
    steps:
        Ordered list of plan steps to execute.
    outage_risk:
        OutageRiskAgent assessment text.  Placed at the top of the plan.
    security_findings:
        NetworkSecurityAgent findings, if any.
    rollback_steps:
        Ordered rollback procedure, if the changes are reversible.

    Returns
    -------
    str
        Markdown-formatted plan with a single confirmation prompt at the end.
    """
    sections: list[str] = ["## Change Plan"]

    # --- Outage risk assessment ---
    if outage_risk:
        sections.append("")
        sections.append("### Outage Risk Assessment")
        sections.append("")
        sections.append(outage_risk)

    # --- Security findings ---
    if security_findings:
        sections.append("")
        sections.append("### Security Review")
        sections.append("")
        for finding in security_findings:
            sections.append(f"- {finding}")

    # --- Steps ---
    sections.append("")
    sections.append("### Execution Steps")
    sections.append("")
    for step in steps:
        sections.append(_format_step(step))
        sections.append("")

    # --- Rollback ---
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

    # --- Single confirmation ---
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
    """Format a CRITICAL outage risk prompt requiring out-of-band confirmation.

    This prompt is visually distinct from standard confirmations.  A generic
    "yes" is NOT sufficient -- the operator must describe their out-of-band
    access method.

    Parameters
    ----------
    risk_description:
        Detailed description of the CRITICAL risk identified by the
        OutageRiskAgent.
    affected_path:
        The specific network path, interface, VLAN, or route at risk
        (e.g. ``"VLAN 1 on port eth0 — management session path"``).

    Returns
    -------
    str
        Markdown-formatted prompt with warning callouts.
    """
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
    """Format a mid-execution failure report.

    Reports exactly which steps completed successfully and which step failed,
    then asks the operator whether to attempt rollback or leave the current
    state for manual assessment.

    Parameters
    ----------
    completed_steps:
        Steps that executed successfully before the failure.
    failed_step:
        The step that failed.
    error:
        Error message or description of what went wrong.

    Returns
    -------
    str
        Markdown-formatted failure report with rollback prompt.
    """
    sections: list[str] = [
        "> **EXECUTION STOPPED**",
        ">",
        f"> Step {failed_step.number} failed.  "
        "All subsequent steps have been skipped.",
    ]

    # --- Completed steps ---
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

    # --- Failed step ---
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

    # --- Prompt ---
    sections.append("")
    sections.append("---")
    sections.append("")
    sections.append(
        "Should I attempt rollback of the completed steps, or leave the "
        "current state for you to assess manually?"
    )

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Scenario 5: Plan modification re-confirmation
# ---------------------------------------------------------------------------

def format_plan_modification(
    original_steps: list[PlanStep],
    modified_steps: list[PlanStep],
    reason: str,
) -> str:
    """Format a modified plan for fresh confirmation.

    Shows what changed compared to the original plan.  Only steps that
    differ are highlighted.  Presents the updated plan for a fresh
    confirmation — unchanged steps are not re-asked about.

    Parameters
    ----------
    original_steps:
        The plan steps as originally presented.
    modified_steps:
        The updated plan steps after the operator's modification.
    reason:
        Explanation of why the plan was modified (usually the operator's
        request).

    Returns
    -------
    str
        Markdown-formatted modified plan with fresh confirmation prompt.
    """
    sections: list[str] = ["## Modified Plan"]
    sections.append("")
    sections.append(f"**Reason for modification:** {reason}")

    # --- Build lookup of original steps by number for diffing ---
    original_by_number: dict[int, PlanStep] = {
        step.number: step for step in original_steps
    }

    # --- Identify changes ---
    added: list[PlanStep] = []
    changed: list[tuple[PlanStep, PlanStep]] = []  # (original, modified)
    unchanged: list[PlanStep] = []
    removed: list[PlanStep] = []

    modified_numbers: set[int] = {step.number for step in modified_steps}

    for step in modified_steps:
        original = original_by_number.get(step.number)
        if original is None:
            added.append(step)
        elif (
            original.system != step.system
            or original.action != step.action
            or original.detail != step.detail
            or original.expected_outcome != step.expected_outcome
        ):
            changed.append((original, step))
        else:
            unchanged.append(step)

    for step in original_steps:
        if step.number not in modified_numbers:
            removed.append(step)

    # --- Changes summary ---
    if added or changed or removed:
        sections.append("")
        sections.append("### What Changed")
        sections.append("")

        for original, modified in changed:
            sections.append(
                f"- **Step {modified.number} (modified):** "
                f"[{modified.system}] {modified.action}"
            )
            sections.append(f"  Was: {original.detail}")
            sections.append(f"  Now: {modified.detail}")

        for step in added:
            sections.append(
                f"- **Step {step.number} (added):** "
                f"[{step.system}] {step.action}"
            )
            sections.append(f"  {step.detail}")

        for step in removed:
            sections.append(
                f"- **Step {step.number} (removed):** "
                f"[{step.system}] {step.action}"
            )
            sections.append(f"  Was: {step.detail}")

    if unchanged:
        sections.append("")
        sections.append(
            f"*{len(unchanged)} step(s) unchanged from the original plan.*"
        )

    # --- Full updated plan ---
    sections.append("")
    sections.append("### Updated Execution Steps")
    sections.append("")
    for step in modified_steps:
        sections.append(_format_step(step))
        sections.append("")

    # --- Fresh confirmation ---
    systems = _collect_systems(modified_steps)
    systems_label = ", ".join(systems)
    sections.append("---")
    sections.append("")
    sections.append(
        f"**{len(modified_steps)} step(s) across [{systems_label}].** "
        "Confirm to proceed, or tell me what to change."
    )

    return "\n".join(sections)
