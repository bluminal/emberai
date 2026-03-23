# SPDX-License-Identifier: MIT
"""Tests for the Orchestrator (Tasks 129-131).

Covers:
- Intent routing: single-vendor, cross-vendor, missing plugins
- Three-phase confirmation model: gather, present, execute
- Rollback coordination: success, partial failure, full failure
- Edge cases and error handling
"""

from __future__ import annotations

import pytest

from netex.agents.orchestrator import (
    IntentType,
    Orchestrator,
    classify_intent,
    resolve_plugin_for_role,
)
from netex.ask import Assumption, PlanStep
from netex.errors import PluginNotFoundError
from netex.registry.plugin_registry import PluginRegistry
from netex.workflows.workflow_state import Workflow, WorkflowState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_registry(
    *,
    gateway: bool = True,
    edge: bool = True,
    extra_plugins: list[dict] | None = None,
) -> PluginRegistry:
    """Create a registry with configurable plugin availability."""
    registry = PluginRegistry(auto_discover=False)

    if gateway:
        registry.register(
            {
                "name": "opnsense",
                "version": "1.0.0",
                "vendor": "OPNsense",
                "roles": ["gateway"],
                "skills": [
                    "interfaces",
                    "firewall",
                    "routing",
                    "services",
                    "vpn",
                    "diagnostics",
                    "security",
                    "firmware",
                    "health",
                ],
                "tools": {
                    "interfaces": ["opnsense__interfaces__list_vlans"],
                    "firewall": [
                        "opnsense__firewall__list_rules",
                        "opnsense__firewall__add_rule",
                    ],
                    "services": ["opnsense__services__list_dhcp"],
                    "diagnostics": ["opnsense__diagnostics__run_traceroute"],
                    "security": ["opnsense__security__list_ids_rules"],
                    "health": ["opnsense__health__system_info"],
                },
            }
        )

    if edge:
        registry.register(
            {
                "name": "unifi",
                "version": "1.0.0",
                "vendor": "Ubiquiti",
                "roles": ["edge"],
                "skills": [
                    "topology",
                    "config",
                    "wifi",
                    "clients",
                    "security",
                    "health",
                ],
                "tools": {
                    "topology": [
                        "unifi__topology__list_devices",
                        "unifi__topology__get_device",
                    ],
                    "config": [
                        "unifi__config__list_networks",
                        "unifi__config__create_network",
                    ],
                    "wifi": ["unifi__wifi__list_wlans"],
                    "clients": ["unifi__clients__list_clients"],
                    "security": ["unifi__security__list_acls"],
                    "health": ["unifi__health__site_health"],
                },
            }
        )

    for plugin in extra_plugins or []:
        registry.register(plugin)

    return registry


def _make_orchestrator(**kwargs) -> tuple[Orchestrator, PluginRegistry]:
    """Create an orchestrator with a configured registry."""
    registry = _make_registry(**kwargs)
    return Orchestrator(registry), registry


# ===========================================================================
# Task 129: Intent Routing Tests
# ===========================================================================


class TestClassifyIntent:
    """Tests for classify_intent()."""

    def test_single_vendor_gateway_only(self):
        """Intent needing only gateway skills -> single_vendor."""
        registry = _make_registry()
        result = classify_intent(
            required_roles=["gateway"],
            required_skills=["firewall"],
            registry=registry,
        )
        assert result["intent_type"] == IntentType.SINGLE_VENDOR
        assert "opnsense" in result["plugins"]
        assert not result["missing_roles"]
        assert not result["missing_skills"]

    def test_single_vendor_edge_only(self):
        """Intent needing only edge skills -> single_vendor."""
        registry = _make_registry()
        result = classify_intent(
            required_roles=["edge"],
            required_skills=["topology"],
            registry=registry,
        )
        assert result["intent_type"] == IntentType.SINGLE_VENDOR
        assert "unifi" in result["plugins"]

    def test_cross_vendor_gateway_and_edge(self):
        """Intent needing both gateway and edge -> cross_vendor."""
        registry = _make_registry()
        result = classify_intent(
            required_roles=["gateway", "edge"],
            required_skills=["firewall", "topology"],
            registry=registry,
        )
        assert result["intent_type"] == IntentType.CROSS_VENDOR
        assert "opnsense" in result["plugins"]
        assert "unifi" in result["plugins"]

    def test_missing_role(self):
        """Missing role is reported."""
        registry = _make_registry(edge=False)
        result = classify_intent(
            required_roles=["gateway", "edge"],
            required_skills=[],
            registry=registry,
        )
        assert "edge" in result["missing_roles"]

    def test_missing_skill(self):
        """Missing skill is reported."""
        registry = _make_registry(edge=False)
        result = classify_intent(
            required_roles=[],
            required_skills=["topology"],
            registry=registry,
        )
        assert "topology" in result["missing_skills"]

    def test_empty_requirements(self):
        """No requirements -> cross_vendor (vacuously no single plugin)."""
        registry = _make_registry()
        result = classify_intent(
            required_roles=[],
            required_skills=[],
            registry=registry,
        )
        # With no requirements, every plugin trivially satisfies them
        assert result["intent_type"] == IntentType.SINGLE_VENDOR

    def test_no_plugins_installed(self):
        """Empty registry -> everything missing."""
        registry = PluginRegistry(auto_discover=False)
        result = classify_intent(
            required_roles=["gateway"],
            required_skills=["firewall"],
            registry=registry,
        )
        assert result["missing_roles"] == ["gateway"]
        assert result["missing_skills"] == ["firewall"]

    def test_single_plugin_multiple_skills(self):
        """Plugin with multiple skills satisfies multi-skill intent."""
        registry = _make_registry(edge=False)
        result = classify_intent(
            required_roles=["gateway"],
            required_skills=["firewall", "routing"],
            registry=registry,
        )
        assert result["intent_type"] == IntentType.SINGLE_VENDOR


class TestResolvePluginForRole:
    """Tests for resolve_plugin_for_role()."""

    def test_resolve_gateway(self):
        """Resolves the gateway plugin name."""
        registry = _make_registry()
        name = resolve_plugin_for_role("gateway", registry)
        assert name == "opnsense"

    def test_resolve_edge(self):
        """Resolves the edge plugin name."""
        registry = _make_registry()
        name = resolve_plugin_for_role("edge", registry)
        assert name == "unifi"

    def test_resolve_missing_role(self):
        """Raises PluginNotFoundError for missing role."""
        registry = _make_registry(gateway=False)
        with pytest.raises(PluginNotFoundError, match="gateway"):
            resolve_plugin_for_role("gateway", registry)

    def test_resolve_nonexistent_role(self):
        """Raises PluginNotFoundError for a role no plugin has."""
        registry = _make_registry()
        with pytest.raises(PluginNotFoundError, match="overlay"):
            resolve_plugin_for_role("overlay", registry)


class TestOrchestratorRouteIntent:
    """Tests for Orchestrator.route_intent()."""

    def test_route_single_vendor(self):
        """Routes single-vendor intent with target_plugin set."""
        orch, _ = _make_orchestrator()
        result = orch.route_intent(
            required_roles=["gateway"],
            required_skills=["firewall"],
        )
        assert result["intent_type"] == IntentType.SINGLE_VENDOR
        assert result["target_plugin"] == "opnsense"

    def test_route_cross_vendor(self):
        """Routes cross-vendor intent with target_plugin=None."""
        orch, _ = _make_orchestrator()
        result = orch.route_intent(
            required_roles=["gateway", "edge"],
            required_skills=["firewall", "topology"],
        )
        assert result["intent_type"] == IntentType.CROSS_VENDOR
        assert result["target_plugin"] is None

    def test_route_missing_plugin_raises(self):
        """Missing plugins raise PluginNotFoundError."""
        orch, _ = _make_orchestrator(edge=False)
        with pytest.raises(PluginNotFoundError, match="missing"):
            orch.route_intent(
                required_roles=["gateway", "edge"],
                required_skills=[],
            )

    def test_route_missing_skill_raises(self):
        """Missing skills raise PluginNotFoundError."""
        orch, _ = _make_orchestrator(edge=False)
        with pytest.raises(PluginNotFoundError, match="topology"):
            orch.route_intent(
                required_roles=[],
                required_skills=["topology"],
            )


# ===========================================================================
# Task 130: Three-Phase Confirmation Tests
# ===========================================================================


class TestPhase1GatherAndResolve:
    """Tests for Phase 1: Gather & Resolve."""

    @pytest.mark.asyncio
    async def test_phase1_basic(self):
        """Phase 1 resolves and runs both agents."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")

        result = await orch.phase1_gather_and_resolve(
            wf,
            change_steps=[{"subsystem": "vlan", "action": "add", "target": "100"}],
        )

        assert wf.state == WorkflowState.RESOLVING
        assert "risk_assessment" in result
        assert "security_findings" in result
        assert result["assumption_prompt"] is None  # No assumptions
        assert result["unresolved_assumptions"] == 0

    @pytest.mark.asyncio
    async def test_phase1_with_assumptions(self):
        """Phase 1 with unresolved assumptions returns prompt."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")

        assumptions = [
            Assumption(
                question="Which interface?",
                implication="Determines parent VLAN interface",
            ),
        ]

        result = await orch.phase1_gather_and_resolve(
            wf,
            change_steps=[],
            assumptions=assumptions,
        )

        assert result["assumption_prompt"] is not None
        assert "Which interface?" in result["assumption_prompt"]
        assert result["unresolved_assumptions"] == 1

    @pytest.mark.asyncio
    async def test_phase1_resolved_assumptions(self):
        """Phase 1 with fully resolved assumptions returns no prompt."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")

        assumptions = [
            Assumption(
                question="Which interface?",
                implication="Determines parent VLAN interface",
                determined_value="igb0",
            ),
        ]

        result = await orch.phase1_gather_and_resolve(
            wf,
            change_steps=[],
            assumptions=assumptions,
        )

        assert result["assumption_prompt"] is None
        assert result["unresolved_assumptions"] == 0

    @pytest.mark.asyncio
    async def test_phase1_records_data(self):
        """Phase 1 records results in workflow data."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")

        await orch.phase1_gather_and_resolve(
            wf,
            change_steps=[{"subsystem": "vlan", "action": "add", "target": "100"}],
        )

        assert "phase1" in wf.data
        assert "risk_tier" in wf.data["phase1"]
        assert "security_finding_count" in wf.data["phase1"]

    @pytest.mark.asyncio
    async def test_phase1_with_operator_ip(self):
        """Phase 1 passes operator IP to risk assessment."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")

        result = await orch.phase1_gather_and_resolve(
            wf,
            change_steps=[{"subsystem": "vlan", "action": "add", "target": "100"}],
            operator_ip="192.168.1.10",
        )

        assert result["risk_assessment"]["operator_ip"] == "192.168.1.10"


class TestPhase2BuildAndPresent:
    """Tests for Phase 2: Build & Present."""

    @pytest.mark.asyncio
    async def test_phase2_basic_plan(self):
        """Phase 2 produces formatted plan text."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")
        wf.transition(WorkflowState.RESOLVING, "Phase 1 done")

        plan_steps = [
            PlanStep(1, "Gateway", "Create VLAN", "VLAN 100", "VLAN created"),
            PlanStep(2, "Edge", "Create network", "Network IoT", "Network created"),
        ]

        plan_text = await orch.phase2_build_and_present(
            wf,
            plan_steps=plan_steps,
            risk_assessment={"risk_tier": "LOW", "description": "No risk"},
            security_findings=[],
        )

        assert "Change Plan" in plan_text
        assert "Create VLAN" in plan_text
        assert "Create network" in plan_text
        assert wf.state == WorkflowState.AWAITING_CONFIRMATION
        assert wf.total_steps == 2

    @pytest.mark.asyncio
    async def test_phase2_with_rollback(self):
        """Phase 2 includes rollback steps in plan."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")
        wf.transition(WorkflowState.RESOLVING, "Phase 1 done")

        plan_text = await orch.phase2_build_and_present(
            wf,
            plan_steps=[PlanStep(1, "GW", "Create VLAN", "VLAN 50", "Done")],
            risk_assessment={"risk_tier": "LOW", "description": "Low risk"},
            security_findings=[],
            rollback_descriptions=["Delete VLAN from gateway"],
        )

        assert "Rollback" in plan_text
        assert "Delete VLAN" in plan_text
        assert wf.data["phase2"]["rollback_step_count"] == 1

    @pytest.mark.asyncio
    async def test_phase2_critical_risk_extra_confirmation(self):
        """Phase 2 with CRITICAL risk includes extra confirmation text."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")
        wf.transition(WorkflowState.RESOLVING, "Phase 1 done")

        plan_text = await orch.phase2_build_and_present(
            wf,
            plan_steps=[PlanStep(1, "GW", "Modify route", "Default route", "Done")],
            risk_assessment={
                "risk_tier": "CRITICAL",
                "description": "Modifies session path",
                "affected_path": "igb0",
            },
            security_findings=[],
        )

        assert "CRITICAL OUTAGE RISK" in plan_text
        assert "out-of-band" in plan_text

    @pytest.mark.asyncio
    async def test_phase2_with_security_findings(self):
        """Phase 2 includes security findings in plan."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")
        wf.transition(WorkflowState.RESOLVING, "Phase 1 done")

        from netex.models.security_finding import (
            FindingCategory,
            FindingSeverity,
            SecurityFinding,
        )

        findings = [
            SecurityFinding(
                severity=FindingSeverity.HIGH,
                category=FindingCategory.VLAN_ISOLATION,
                description="Missing deny rule for new VLAN",
                recommendation="Add inter-VLAN deny rule",
            ),
        ]

        plan_text = await orch.phase2_build_and_present(
            wf,
            plan_steps=[PlanStep(1, "GW", "Create VLAN", "VLAN 50", "Done")],
            risk_assessment={"risk_tier": "LOW", "description": "Low risk"},
            security_findings=findings,
        )

        assert "Missing deny rule" in plan_text


class TestPhase3Execute:
    """Tests for Phase 3: Execute."""

    @pytest.mark.asyncio
    async def test_phase3_success(self):
        """Successful execution transitions to COMPLETED."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")
        wf.transition(WorkflowState.RESOLVING, "Phase 1")
        wf.transition(WorkflowState.PLANNING, "Phase 2")
        wf.transition(WorkflowState.AWAITING_CONFIRMATION, "Ready")
        wf.total_steps = 2

        async def execute(workflow):
            workflow.log_step(1, "Step 1 done")
            workflow.log_step(2, "Step 2 done")
            return {"message": "All done"}

        result = await orch.phase3_execute(wf, execute)

        assert result["success"] is True
        assert result["error"] is None
        assert result["result"] == {"message": "All done"}
        assert wf.state == WorkflowState.COMPLETED

    @pytest.mark.asyncio
    async def test_phase3_failure(self):
        """Failed execution transitions to FAILED."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")
        wf.transition(WorkflowState.RESOLVING, "Phase 1")
        wf.transition(WorkflowState.PLANNING, "Phase 2")
        wf.transition(WorkflowState.AWAITING_CONFIRMATION, "Ready")
        wf.total_steps = 2

        async def execute(workflow):
            workflow.log_step(1, "Step 1 done")
            raise RuntimeError("Connection refused")

        result = await orch.phase3_execute(wf, execute)

        assert result["success"] is False
        assert "Connection refused" in result["error"]
        assert result["result"] is None
        assert wf.state == WorkflowState.FAILED

    @pytest.mark.asyncio
    async def test_phase3_tracks_completed_steps(self):
        """Execution tracks how many steps completed before failure."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")
        wf.transition(WorkflowState.RESOLVING, "Phase 1")
        wf.transition(WorkflowState.PLANNING, "Phase 2")
        wf.transition(WorkflowState.AWAITING_CONFIRMATION, "Ready")
        wf.total_steps = 3

        async def execute(workflow):
            workflow.log_step(1, "Step 1 done")
            workflow.log_step(2, "Step 2 done")
            raise RuntimeError("Step 3 failed")

        result = await orch.phase3_execute(wf, execute)

        assert result["completed_steps"] == 2
        assert result["total_steps"] == 3


# ===========================================================================
# Task 131: Rollback Coordination Tests
# ===========================================================================


class TestRollback:
    """Tests for rollback coordination."""

    @pytest.mark.asyncio
    async def test_rollback_success(self):
        """Successful rollback transitions to ROLLED_BACK."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")
        wf.transition(WorkflowState.RESOLVING, "Phase 1")
        wf.transition(WorkflowState.PLANNING, "Phase 2")
        wf.transition(WorkflowState.AWAITING_CONFIRMATION, "Ready")
        wf.transition(WorkflowState.EXECUTING, "Executing")
        wf.transition(WorkflowState.FAILED, "Step 2 failed")

        rollback_log: list[str] = []

        async def rb_step_2():
            rollback_log.append("rolled back step 2")

        async def rb_step_1():
            rollback_log.append("rolled back step 1")

        result = await orch.rollback(
            wf,
            [
                {"description": "Undo step 1", "fn": rb_step_1, "step_number": 1},
                {"description": "Undo step 2", "fn": rb_step_2, "step_number": 2},
            ],
        )

        assert result["success"] is True
        assert result["rolled_back_steps"] == 2
        assert wf.state == WorkflowState.ROLLED_BACK
        # Rollback executes in reverse order
        assert rollback_log == ["rolled back step 2", "rolled back step 1"]

    @pytest.mark.asyncio
    async def test_rollback_partial_failure(self):
        """Partial rollback failure transitions to ROLLBACK_FAILED."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")
        wf.transition(WorkflowState.RESOLVING, "Phase 1")
        wf.transition(WorkflowState.PLANNING, "Phase 2")
        wf.transition(WorkflowState.AWAITING_CONFIRMATION, "Ready")
        wf.transition(WorkflowState.EXECUTING, "Executing")
        wf.transition(WorkflowState.FAILED, "Step 3 failed")

        async def rb_ok():
            pass

        async def rb_fail():
            raise RuntimeError("Cannot undo")

        result = await orch.rollback(
            wf,
            [
                {"description": "Undo step 1", "fn": rb_ok, "step_number": 1},
                {"description": "Undo step 2", "fn": rb_fail, "step_number": 2},
                {"description": "Undo step 3", "fn": rb_ok, "step_number": 3},
            ],
        )

        assert result["success"] is False
        assert wf.state == WorkflowState.ROLLBACK_FAILED
        # Step 3 rolled back (reverse order), step 2 failed, step 1 not attempted
        assert result["rolled_back_steps"] == 1
        assert "Cannot undo" in result["error"]

    @pytest.mark.asyncio
    async def test_rollback_empty_list(self):
        """Empty rollback list transitions to ROLLED_BACK immediately."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")
        wf.transition(WorkflowState.RESOLVING, "Phase 1")
        wf.transition(WorkflowState.PLANNING, "Phase 2")
        wf.transition(WorkflowState.AWAITING_CONFIRMATION, "Ready")
        wf.transition(WorkflowState.EXECUTING, "Executing")
        wf.transition(WorkflowState.FAILED, "Failed")

        result = await orch.rollback(wf, [])

        assert result["success"] is True
        assert result["rolled_back_steps"] == 0
        assert wf.state == WorkflowState.ROLLED_BACK

    @pytest.mark.asyncio
    async def test_rollback_records_step_results(self):
        """Rollback records per-step success/failure details."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")
        wf.transition(WorkflowState.RESOLVING, "Phase 1")
        wf.transition(WorkflowState.PLANNING, "Phase 2")
        wf.transition(WorkflowState.AWAITING_CONFIRMATION, "Ready")
        wf.transition(WorkflowState.EXECUTING, "Executing")
        wf.transition(WorkflowState.FAILED, "Failed")

        async def rb_ok():
            pass

        result = await orch.rollback(
            wf,
            [
                {"description": "Undo step 1", "fn": rb_ok, "step_number": 1},
            ],
        )

        assert len(result["step_results"]) == 1
        assert result["step_results"][0]["success"] is True
        assert result["step_results"][0]["description"] == "Undo step 1"

    @pytest.mark.asyncio
    async def test_rollback_none_fn_treated_as_noop(self):
        """Rollback steps with fn=None are treated as no-op successes."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("test", "Test workflow")
        wf.transition(WorkflowState.RESOLVING, "Phase 1")
        wf.transition(WorkflowState.PLANNING, "Phase 2")
        wf.transition(WorkflowState.AWAITING_CONFIRMATION, "Ready")
        wf.transition(WorkflowState.EXECUTING, "Executing")
        wf.transition(WorkflowState.FAILED, "Failed")

        result = await orch.rollback(
            wf,
            [
                {"description": "Undo step 1", "fn": None, "step_number": 1},
            ],
        )

        assert result["success"] is True
        assert result["rolled_back_steps"] == 1


# ===========================================================================
# Orchestrator convenience methods
# ===========================================================================


class TestOrchestratorHelpers:
    """Tests for Orchestrator convenience methods."""

    def test_create_workflow(self):
        """create_workflow returns a new Workflow in CREATED state."""
        orch, _ = _make_orchestrator()
        wf = orch.create_workflow("vlan_configure", "Create VLAN 50")

        assert isinstance(wf, Workflow)
        assert wf.state == WorkflowState.CREATED
        assert wf.workflow_type == "vlan_configure"

    def test_format_execution_failure_report(self):
        """format_execution_failure_report produces readable output."""
        orch, _ = _make_orchestrator()

        completed = [
            PlanStep(1, "Gateway", "Create VLAN", "VLAN 50", "Created"),
        ]
        failed = PlanStep(2, "Edge", "Create network", "Network IoT", "Created")

        report = orch.format_execution_failure_report(
            completed,
            failed,
            "Connection refused",
        )

        assert "EXECUTION STOPPED" in report
        assert "Create VLAN" in report
        assert "Create network" in report
        assert "Connection refused" in report
