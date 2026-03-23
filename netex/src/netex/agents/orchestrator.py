# SPDX-License-Identifier: MIT
"""Orchestrator -- cross-vendor intent routing and workflow coordination.

The Orchestrator is the central coordination layer of the netex umbrella.
It receives operator intents (expressed as MCP tool calls), determines
whether the intent targets a single vendor or spans multiple vendors, and
routes accordingly:

    Single-vendor intent:
        Route directly to the vendor plugin's tool via the Plugin Registry.

    Cross-vendor intent:
        Execute an umbrella workflow using the three-phase confirmation
        model (PRD Section 10.2):
            Phase 1 "Gather & Resolve" -- identify ambiguities, batch
                AskUserQuestion, run OutageRiskAgent + NetworkSecurityAgent.
            Phase 2 "Build & Present" -- construct ordered change plan as
                [OUTAGE RISK] -> [SECURITY] -> [CHANGE PLAN] -> [ROLLBACK].
            Phase 3 "Single Confirmation" -- one AskUserQuestion.

    On failure during execution:
        Use the workflow state machine to execute rollback in reverse order,
        then report final state.

Decision D15 (PRD 10.2): The Orchestrator never hardcodes vendor names.
It discovers plugins via the Plugin Registry and resolves capabilities
by role and skill.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from netex.agents.network_security_agent import NetworkSecurityAgent
from netex.agents.outage_risk_agent import OutageRiskAgent, RiskTier
from netex.ask import (
    Assumption,
    PlanStep,
    format_assumption_resolution,
    format_critical_risk_confirmation,
    format_execution_failure,
    format_plan_confirmation,
)
from netex.errors import PluginNotFoundError
from netex.workflows.workflow_state import Workflow, WorkflowState

if TYPE_CHECKING:
    from netex.registry.plugin_registry import PluginRegistry

logger = logging.getLogger("netex.orchestrator")


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------


class IntentType:
    """Classification of operator intents."""

    SINGLE_VENDOR = "single_vendor"
    CROSS_VENDOR = "cross_vendor"


def classify_intent(
    required_roles: list[str],
    required_skills: list[str],
    registry: PluginRegistry,
) -> dict[str, Any]:
    """Classify an intent as single-vendor or cross-vendor.

    Examines which plugins can satisfy the required roles and skills.
    If all requirements are met by a single plugin, the intent is
    single-vendor.  Otherwise, it is cross-vendor.

    Parameters
    ----------
    required_roles:
        Roles needed for this operation (e.g. ``["gateway"]``).
    required_skills:
        Skills needed for this operation (e.g. ``["firewall", "topology"]``).
    registry:
        The plugin registry to query.

    Returns
    -------
    dict
        Classification result with keys:
        - ``intent_type``: ``"single_vendor"`` or ``"cross_vendor"``.
        - ``plugins``: dict mapping plugin name to its matching
          roles/skills.
        - ``missing_roles``: roles not satisfied by any plugin.
        - ``missing_skills``: skills not satisfied by any plugin.
    """
    plugin_matches: dict[str, dict[str, list[str]]] = {}
    all_matching_plugins: set[str] = set()

    for role in required_roles:
        plugins = registry.plugins_with_role(role)
        for p in plugins:
            name = p["name"]
            plugin_matches.setdefault(name, {"roles": [], "skills": []})
            plugin_matches[name]["roles"].append(role)
            all_matching_plugins.add(name)

    for skill in required_skills:
        plugins = registry.plugins_with_skill(skill)
        for p in plugins:
            name = p["name"]
            plugin_matches.setdefault(name, {"roles": [], "skills": []})
            plugin_matches[name]["skills"].append(skill)
            all_matching_plugins.add(name)

    # Check for missing roles/skills
    satisfied_roles = set()
    satisfied_skills = set()
    for match in plugin_matches.values():
        satisfied_roles.update(match["roles"])
        satisfied_skills.update(match["skills"])

    missing_roles = [r for r in required_roles if r not in satisfied_roles]
    missing_skills = [s for s in required_skills if s not in satisfied_skills]

    # Determine if single-vendor can satisfy everything.
    # Edge case: if no roles and no skills are required, any single plugin
    # trivially satisfies the empty requirement set -> SINGLE_VENDOR.
    if not required_roles and not required_skills:
        intent_type = IntentType.SINGLE_VENDOR
    else:
        intent_type = IntentType.CROSS_VENDOR
        for _name, match in plugin_matches.items():
            if set(required_roles).issubset(set(match["roles"])) and set(required_skills).issubset(
                set(match["skills"])
            ):
                intent_type = IntentType.SINGLE_VENDOR
                break

    return {
        "intent_type": intent_type,
        "plugins": plugin_matches,
        "missing_roles": missing_roles,
        "missing_skills": missing_skills,
    }


def resolve_plugin_for_role(
    role: str,
    registry: PluginRegistry,
) -> str:
    """Resolve a single plugin name for a given role.

    Parameters
    ----------
    role:
        The role to resolve (e.g. ``"gateway"``, ``"edge"``).
    registry:
        The plugin registry.

    Returns
    -------
    str
        Name of the plugin that provides this role.

    Raises
    ------
    PluginNotFoundError
        If no plugin provides the requested role.
    """
    plugins = registry.plugins_with_role(role)
    if not plugins:
        raise PluginNotFoundError(
            f"No plugin provides the '{role}' role. Install a compatible vendor plugin.",
            required_role=role,
        )
    result: str = plugins[0]["name"]
    return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Cross-vendor workflow orchestrator.

    Coordinates the three-phase confirmation model for operations that
    span multiple vendor plugins.  Uses the Plugin Registry to discover
    plugins, the OutageRiskAgent for pre-change risk assessment, and the
    NetworkSecurityAgent for security review.

    The Orchestrator never hardcodes vendor names -- it resolves plugins
    by role and skill via the registry.

    Parameters
    ----------
    registry:
        The plugin registry for discovering installed vendor plugins.
    """

    def __init__(self, registry: PluginRegistry) -> None:
        self.registry = registry
        self.outage_agent = OutageRiskAgent()
        self.security_agent = NetworkSecurityAgent()

    # ------------------------------------------------------------------
    # Intent routing (Task 129)
    # ------------------------------------------------------------------

    def route_intent(
        self,
        required_roles: list[str],
        required_skills: list[str],
    ) -> dict[str, Any]:
        """Route an operator intent to the appropriate execution path.

        Single-vendor intents are routed directly to the vendor plugin.
        Cross-vendor intents trigger the umbrella workflow.

        Parameters
        ----------
        required_roles:
            Roles needed for this operation.
        required_skills:
            Skills needed for this operation.

        Returns
        -------
        dict
            Routing decision with keys:
            - ``intent_type``: ``"single_vendor"`` or ``"cross_vendor"``.
            - ``plugins``: participating plugins and their roles/skills.
            - ``target_plugin``: for single-vendor, the plugin name.
            - ``missing_roles``: unsatisfied roles.
            - ``missing_skills``: unsatisfied skills.

        Raises
        ------
        PluginNotFoundError
            If required roles or skills cannot be satisfied by any
            installed plugin.
        """
        classification = classify_intent(
            required_roles,
            required_skills,
            self.registry,
        )

        if classification["missing_roles"] or classification["missing_skills"]:
            missing_parts: list[str] = []
            if classification["missing_roles"]:
                missing_parts.append(f"roles: {', '.join(classification['missing_roles'])}")
            if classification["missing_skills"]:
                missing_parts.append(f"skills: {', '.join(classification['missing_skills'])}")
            raise PluginNotFoundError(
                f"Cannot satisfy intent -- missing {'; '.join(missing_parts)}. "
                "Install additional vendor plugins.",
            )

        result = dict(classification)

        if classification["intent_type"] == IntentType.SINGLE_VENDOR:
            # Find the single plugin that can handle everything
            for name, match in classification["plugins"].items():
                if set(required_roles).issubset(set(match["roles"])) and set(
                    required_skills
                ).issubset(set(match["skills"])):
                    result["target_plugin"] = name
                    break
        else:
            result["target_plugin"] = None

        return result

    # ------------------------------------------------------------------
    # Three-phase confirmation (Task 130)
    # ------------------------------------------------------------------

    async def phase1_gather_and_resolve(
        self,
        workflow: Workflow,
        change_steps: list[dict[str, Any]],
        assumptions: list[Assumption] | None = None,
        *,
        operator_ip: str | None = None,
    ) -> dict[str, Any]:
        """Phase 1: Gather state, resolve assumptions, run risk agents.

        Identifies ambiguities via AskUserQuestion, runs the
        OutageRiskAgent and NetworkSecurityAgent, and returns the
        gathered context for Phase 2.

        Parameters
        ----------
        workflow:
            The workflow instance tracking this operation.
        change_steps:
            Proposed change steps with subsystem/action/target keys.
        assumptions:
            Optional list of assumptions that may need operator
            clarification.
        operator_ip:
            Operator IP for outage risk assessment.

        Returns
        -------
        dict
            Phase 1 results with keys:
            - ``assumption_prompt``: formatted assumption resolution text
              (or ``None`` if all resolved).
            - ``risk_assessment``: OutageRiskAgent result.
            - ``security_findings``: list of SecurityFinding objects.
            - ``unresolved_assumptions``: count of unresolved assumptions.
        """
        workflow.transition(
            WorkflowState.RESOLVING,
            "Phase 1: Gathering state and resolving assumptions",
        )

        # Resolve assumptions
        assumption_list = assumptions or []
        unresolved = [a for a in assumption_list if a.determined_value is None]
        assumption_prompt: str | None = None
        if unresolved:
            assumption_prompt = format_assumption_resolution(assumption_list)

        # Run OutageRiskAgent
        risk_assessment = await self.outage_agent.assess(
            change_steps,
            self.registry,
            operator_ip=operator_ip,
        )

        # Run NetworkSecurityAgent
        security_findings = await self.security_agent.review_plan(
            change_steps,
            self.registry,
        )

        result = {
            "assumption_prompt": assumption_prompt,
            "risk_assessment": risk_assessment,
            "security_findings": security_findings,
            "unresolved_assumptions": len(unresolved),
        }

        workflow.data["phase1"] = {
            "risk_tier": str(risk_assessment["risk_tier"]),
            "risk_description": risk_assessment["description"],
            "security_finding_count": len(security_findings),
            "unresolved_assumptions": len(unresolved),
        }

        return result

    async def phase2_build_and_present(
        self,
        workflow: Workflow,
        plan_steps: list[PlanStep],
        risk_assessment: dict[str, Any],
        security_findings: list[Any],
        rollback_descriptions: list[str] | None = None,
    ) -> str:
        """Phase 2: Build and present the ordered change plan.

        Constructs the plan in the PRD-specified order:
        [OUTAGE RISK] -> [SECURITY] -> [CHANGE PLAN] -> [ROLLBACK]

        Parameters
        ----------
        workflow:
            The workflow instance tracking this operation.
        plan_steps:
            Ordered list of PlanStep objects for the change plan.
        risk_assessment:
            OutageRiskAgent result from Phase 1.
        security_findings:
            SecurityFinding objects from Phase 1.
        rollback_descriptions:
            Human-readable rollback step descriptions.

        Returns
        -------
        str
            The formatted change plan ready for operator review.
        """
        workflow.transition(
            WorkflowState.PLANNING,
            "Phase 2: Building and presenting change plan",
        )

        # Format outage risk
        risk_tier = risk_assessment.get("risk_tier", RiskTier.LOW)
        risk_desc = risk_assessment.get("description", "")
        outage_risk_text = f"**{risk_tier}** -- {risk_desc}"

        # Format security findings
        security_texts: list[str] = []
        for finding in security_findings:
            if hasattr(finding, "format_for_report"):
                security_texts.append(finding.format_for_report())
            else:
                security_texts.append(str(finding))

        # Build the plan confirmation text
        plan_text = format_plan_confirmation(
            steps=plan_steps,
            outage_risk=outage_risk_text,
            security_findings=security_texts if security_texts else None,
            rollback_steps=rollback_descriptions,
        )

        # Handle CRITICAL outage risk -- requires extra confirmation
        if risk_tier == RiskTier.CRITICAL:
            affected = risk_assessment.get("affected_path", "unknown")
            critical_text = format_critical_risk_confirmation(
                risk_description=risk_desc,
                affected_path=str(affected),
            )
            plan_text = critical_text + "\n\n---\n\n" + plan_text

        workflow.total_steps = len(plan_steps)
        workflow.data["phase2"] = {
            "step_count": len(plan_steps),
            "rollback_step_count": len(rollback_descriptions) if rollback_descriptions else 0,
        }

        workflow.transition(
            WorkflowState.AWAITING_CONFIRMATION,
            "Plan ready for operator review",
        )

        return plan_text

    async def phase3_execute(
        self,
        workflow: Workflow,
        execute_fn: Any,
    ) -> dict[str, Any]:
        """Phase 3: Execute the plan after operator confirmation.

        Calls the provided execution function within the workflow state
        machine.  On failure, transitions to FAILED (rollback is
        handled separately via ``rollback()``).

        Parameters
        ----------
        workflow:
            The workflow instance tracking this operation.
        execute_fn:
            Async callable that performs the actual execution.
            Must accept ``(workflow)`` and return a result dict.

        Returns
        -------
        dict
            Execution result with keys:
            - ``success``: whether all steps completed.
            - ``completed_steps``: number of steps completed.
            - ``total_steps``: total number of steps.
            - ``error``: error message if failed.
            - ``result``: the execution function's return value.
        """
        workflow.transition(
            WorkflowState.EXECUTING,
            "Phase 3: Executing change plan",
        )

        try:
            result = await execute_fn(workflow)

            workflow.transition(
                WorkflowState.COMPLETED,
                "All steps executed successfully",
            )

            return {
                "success": True,
                "completed_steps": workflow.completed_steps,
                "total_steps": workflow.total_steps,
                "error": None,
                "result": result,
            }

        except Exception as exc:
            error_msg = str(exc)
            workflow.transition(
                WorkflowState.FAILED,
                f"Execution failed: {error_msg}",
            )

            return {
                "success": False,
                "completed_steps": workflow.completed_steps,
                "total_steps": workflow.total_steps,
                "error": error_msg,
                "result": None,
            }

    # ------------------------------------------------------------------
    # Rollback coordination (Task 131)
    # ------------------------------------------------------------------

    async def rollback(
        self,
        workflow: Workflow,
        rollback_fns: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute rollback in reverse order after a failure.

        Iterates through rollback functions in reverse, executing each
        and recording results.  If a rollback step itself fails, the
        workflow transitions to ROLLBACK_FAILED.

        Parameters
        ----------
        workflow:
            The workflow instance (must be in FAILED state).
        rollback_fns:
            List of dicts with keys:
            - ``description``: human-readable step description.
            - ``fn``: async callable to execute the rollback step.
            - ``step_number``: original forward step number being undone.

        Returns
        -------
        dict
            Rollback result with keys:
            - ``success``: whether all rollback steps completed.
            - ``rolled_back_steps``: number of rollback steps completed.
            - ``total_rollback_steps``: total rollback steps attempted.
            - ``error``: error message if rollback failed.
            - ``step_results``: per-step success/failure details.
        """
        workflow.transition(
            WorkflowState.ROLLING_BACK,
            "Initiating rollback in reverse order",
        )

        step_results: list[dict[str, Any]] = []
        rolled_back = 0
        rollback_error: str | None = None

        # Execute in reverse order
        for i, rb in enumerate(reversed(rollback_fns), start=1):
            description = rb.get("description", f"Rollback step {i}")
            step_number = rb.get("step_number", i)
            fn = rb.get("fn")

            try:
                if fn is not None:
                    await fn()

                workflow.log_step(
                    step_number,
                    f"Rolled back: {description}",
                    data={"rollback": True},
                    success=True,
                )
                step_results.append(
                    {
                        "step_number": step_number,
                        "description": description,
                        "success": True,
                    }
                )
                rolled_back += 1

            except Exception as exc:
                rollback_error = f"Rollback step {i} failed: {exc}"
                workflow.log_step(
                    step_number,
                    f"Rollback FAILED: {description} -- {exc}",
                    data={"rollback": True, "error": str(exc)},
                    success=False,
                )
                step_results.append(
                    {
                        "step_number": step_number,
                        "description": description,
                        "success": False,
                        "error": str(exc),
                    }
                )
                break

        # Transition to final state
        if rollback_error:
            workflow.transition(
                WorkflowState.ROLLBACK_FAILED,
                rollback_error,
            )
        else:
            workflow.transition(
                WorkflowState.ROLLED_BACK,
                f"Successfully rolled back {rolled_back} step(s)",
            )

        return {
            "success": rollback_error is None,
            "rolled_back_steps": rolled_back,
            "total_rollback_steps": len(rollback_fns),
            "error": rollback_error,
            "step_results": step_results,
        }

    # ------------------------------------------------------------------
    # Convenience: full three-phase workflow
    # ------------------------------------------------------------------

    def create_workflow(
        self,
        workflow_type: str,
        description: str,
    ) -> Workflow:
        """Create a new Workflow instance for tracking an operation.

        Parameters
        ----------
        workflow_type:
            Type identifier (e.g. ``"vlan_configure"``).
        description:
            Human-readable description of the operation.

        Returns
        -------
        Workflow
            A new workflow in the CREATED state.
        """
        return Workflow(
            workflow_type=workflow_type,
            description=description,
        )

    def format_execution_failure_report(
        self,
        completed: list[PlanStep],
        failed: PlanStep,
        error: str,
    ) -> str:
        """Format a mid-execution failure report for the operator.

        Parameters
        ----------
        completed:
            Steps that completed successfully before the failure.
        failed:
            The step that failed.
        error:
            The error message from the failed step.

        Returns
        -------
        str
            Formatted failure report.
        """
        return format_execution_failure(completed, failed, error)
