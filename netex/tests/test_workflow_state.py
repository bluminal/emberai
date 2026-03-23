# SPDX-License-Identifier: MIT
"""Tests for the workflow state machine."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from netex.errors import WorkflowError
from netex.workflows.workflow_state import (
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    StepLogEntry,
    Workflow,
    WorkflowState,
)

# ---------------------------------------------------------------------------
# WorkflowState enum
# ---------------------------------------------------------------------------

class TestWorkflowState:
    def test_all_states_exist(self) -> None:
        expected = [
            "created", "resolving", "planning", "awaiting_confirmation",
            "executing", "completed", "failed", "rolling_back",
            "rolled_back", "rollback_failed", "cancelled",
        ]
        for state_value in expected:
            assert WorkflowState(state_value) is not None

    def test_terminal_states(self) -> None:
        assert WorkflowState.COMPLETED in TERMINAL_STATES
        assert WorkflowState.ROLLED_BACK in TERMINAL_STATES
        assert WorkflowState.ROLLBACK_FAILED in TERMINAL_STATES
        assert WorkflowState.CANCELLED in TERMINAL_STATES
        assert WorkflowState.EXECUTING not in TERMINAL_STATES

    def test_all_states_have_transitions(self) -> None:
        for state in WorkflowState:
            assert state in VALID_TRANSITIONS


# ---------------------------------------------------------------------------
# Workflow construction
# ---------------------------------------------------------------------------

class TestWorkflowConstruction:
    def test_default_construction(self) -> None:
        wf = Workflow()
        assert wf.workflow_id  # auto-generated UUID
        assert wf.state == WorkflowState.CREATED
        assert wf.workflow_type == ""
        assert wf.description == ""
        assert wf.step_log == []
        assert wf.total_steps == 0
        assert wf.completed_steps == 0
        assert wf.error is None

    def test_custom_id(self) -> None:
        wf = Workflow(workflow_id="custom-123")
        assert wf.workflow_id == "custom-123"

    def test_with_metadata(self) -> None:
        wf = Workflow(
            workflow_type="vlan_configure",
            description="Create VLAN 50 across gateway and edge",
        )
        assert wf.workflow_type == "vlan_configure"
        assert wf.description == "Create VLAN 50 across gateway and edge"


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

class TestTransitions:
    def test_valid_happy_path(self) -> None:
        """Full happy path: created -> resolving -> planning ->
        awaiting -> executing -> completed."""
        wf = Workflow(workflow_type="test")
        wf.transition(WorkflowState.RESOLVING, "Gathering state")
        assert wf.state == WorkflowState.RESOLVING

        wf.transition(WorkflowState.PLANNING, "Building plan")
        assert wf.state == WorkflowState.PLANNING

        wf.transition(WorkflowState.AWAITING_CONFIRMATION, "Plan ready")
        assert wf.state == WorkflowState.AWAITING_CONFIRMATION

        wf.transition(WorkflowState.EXECUTING, "Operator confirmed")
        assert wf.state == WorkflowState.EXECUTING

        wf.transition(WorkflowState.COMPLETED, "All steps done")
        assert wf.state == WorkflowState.COMPLETED

    def test_cancel_from_created(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.CANCELLED, "User cancelled")
        assert wf.state == WorkflowState.CANCELLED

    def test_cancel_from_resolving(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.CANCELLED, "User cancelled")
        assert wf.state == WorkflowState.CANCELLED

    def test_cancel_from_planning(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.PLANNING)
        wf.transition(WorkflowState.CANCELLED, "User cancelled")
        assert wf.state == WorkflowState.CANCELLED

    def test_cancel_from_awaiting(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.PLANNING)
        wf.transition(WorkflowState.AWAITING_CONFIRMATION)
        wf.transition(WorkflowState.CANCELLED, "User cancelled")
        assert wf.state == WorkflowState.CANCELLED

    def test_failure_path(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.PLANNING)
        wf.transition(WorkflowState.AWAITING_CONFIRMATION)
        wf.transition(WorkflowState.EXECUTING)
        wf.transition(WorkflowState.FAILED, "Step 3 failed: timeout")
        assert wf.state == WorkflowState.FAILED
        assert wf.error == "Step 3 failed: timeout"

    def test_rollback_path(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.PLANNING)
        wf.transition(WorkflowState.AWAITING_CONFIRMATION)
        wf.transition(WorkflowState.EXECUTING)
        wf.transition(WorkflowState.FAILED, "Step failed")
        wf.transition(WorkflowState.ROLLING_BACK, "Rolling back")
        assert wf.state == WorkflowState.ROLLING_BACK

        wf.transition(WorkflowState.ROLLED_BACK, "Rollback complete")
        assert wf.state == WorkflowState.ROLLED_BACK

    def test_rollback_failure_path(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.PLANNING)
        wf.transition(WorkflowState.AWAITING_CONFIRMATION)
        wf.transition(WorkflowState.EXECUTING)
        wf.transition(WorkflowState.FAILED, "Step failed")
        wf.transition(WorkflowState.ROLLING_BACK, "Attempting rollback")
        wf.transition(WorkflowState.ROLLBACK_FAILED, "Rollback also failed")
        assert wf.state == WorkflowState.ROLLBACK_FAILED

    def test_re_plan_after_modification(self) -> None:
        """Operator modifies plan -> back to planning -> new confirmation."""
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.PLANNING)
        wf.transition(WorkflowState.AWAITING_CONFIRMATION)
        wf.transition(WorkflowState.PLANNING, "Operator requested changes")
        assert wf.state == WorkflowState.PLANNING

    def test_invalid_transition_raises(self) -> None:
        wf = Workflow()
        with pytest.raises(WorkflowError, match="Invalid transition"):
            wf.transition(WorkflowState.COMPLETED)

    def test_invalid_transition_from_terminal(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.CANCELLED)
        with pytest.raises(WorkflowError):
            wf.transition(WorkflowState.RESOLVING)

    def test_cannot_skip_resolving(self) -> None:
        wf = Workflow()
        with pytest.raises(WorkflowError):
            wf.transition(WorkflowState.PLANNING)

    def test_cannot_execute_without_confirmation(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.PLANNING)
        with pytest.raises(WorkflowError):
            wf.transition(WorkflowState.EXECUTING)

    def test_transition_records_log_entry(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING, "Starting phase 1")
        assert len(wf.step_log) == 1
        entry = wf.step_log[0]
        assert entry.from_state == "created"
        assert entry.to_state == "resolving"
        assert entry.message == "Starting phase 1"
        assert entry.timestamp > 0

    def test_transition_with_data(self) -> None:
        wf = Workflow()
        wf.transition(
            WorkflowState.RESOLVING,
            "Gathering state",
            data={"plugins_queried": ["unifi", "opnsense"]},
        )
        assert wf.step_log[0].data["plugins_queried"] == ["unifi", "opnsense"]


# ---------------------------------------------------------------------------
# Step logging
# ---------------------------------------------------------------------------

class TestStepLogging:
    def test_log_step_in_executing(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.PLANNING)
        wf.transition(WorkflowState.AWAITING_CONFIRMATION)
        wf.transition(WorkflowState.EXECUTING)

        wf.log_step(1, "Created VLAN interface on gateway")
        wf.log_step(2, "Created network object on edge")

        assert wf.completed_steps == 2
        # 4 transition entries + 2 step entries
        assert len(wf.step_log) == 6

    def test_log_step_not_in_executing_raises(self) -> None:
        wf = Workflow()
        with pytest.raises(WorkflowError, match="executing"):
            wf.log_step(1, "Should fail")

    def test_log_step_with_data(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.PLANNING)
        wf.transition(WorkflowState.AWAITING_CONFIRMATION)
        wf.transition(WorkflowState.EXECUTING)

        wf.log_step(1, "Created VLAN", data={"vlan_id": 50})
        entry = wf.step_log[-1]
        assert entry.step_number == 1
        assert entry.data["vlan_id"] == 50
        assert entry.data["success"] is True

    def test_log_step_failure(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.PLANNING)
        wf.transition(WorkflowState.AWAITING_CONFIRMATION)
        wf.transition(WorkflowState.EXECUTING)

        wf.log_step(1, "Failed to create VLAN", success=False)
        entry = wf.step_log[-1]
        assert entry.data["success"] is False

    def test_log_step_during_rollback(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.PLANNING)
        wf.transition(WorkflowState.AWAITING_CONFIRMATION)
        wf.transition(WorkflowState.EXECUTING)
        wf.transition(WorkflowState.FAILED, "Step 2 failed")
        wf.transition(WorkflowState.ROLLING_BACK)

        wf.log_step(1, "Rolled back step 1")
        assert wf.step_log[-1].message == "Rolled back step 1"


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_is_terminal(self) -> None:
        wf = Workflow()
        assert wf.is_terminal is False
        wf.transition(WorkflowState.CANCELLED)
        assert wf.is_terminal is True

    def test_duration(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        assert wf.duration_seconds >= 0

    def test_progress_with_steps(self) -> None:
        wf = Workflow()
        wf.total_steps = 5
        wf.completed_steps = 3
        assert wf.progress == "3/5 steps"

    def test_progress_without_steps(self) -> None:
        wf = Workflow()
        assert wf.progress == "created"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict(self) -> None:
        wf = Workflow(
            workflow_id="wf-123",
            workflow_type="vlan_configure",
            description="Test workflow",
        )
        wf.transition(WorkflowState.RESOLVING, "Phase 1")
        d = wf.to_dict()

        assert d["workflow_id"] == "wf-123"
        assert d["workflow_type"] == "vlan_configure"
        assert d["state"] == "resolving"
        assert len(d["step_log"]) == 1

    def test_from_dict_roundtrip(self) -> None:
        wf = Workflow(workflow_id="wf-456", workflow_type="test")
        wf.transition(WorkflowState.RESOLVING, "Start")
        wf.transition(WorkflowState.PLANNING, "Plan")
        wf.data["key"] = "value"

        d = wf.to_dict()
        restored = Workflow.from_dict(d)

        assert restored.workflow_id == "wf-456"
        assert restored.state == WorkflowState.PLANNING
        assert len(restored.step_log) == 2
        assert restored.data["key"] == "value"

    def test_json_roundtrip(self) -> None:
        wf = Workflow(workflow_id="wf-789", workflow_type="test")
        wf.transition(WorkflowState.RESOLVING)
        wf.total_steps = 5

        json_str = wf.to_json()
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["workflow_id"] == "wf-789"

        restored = Workflow.from_json(json_str)
        assert restored.workflow_id == "wf-789"
        assert restored.total_steps == 5

    def test_save_and_load(self) -> None:
        wf = Workflow(workflow_id="wf-save", workflow_type="persist-test")
        wf.transition(WorkflowState.RESOLVING, "Start")
        wf.transition(WorkflowState.PLANNING, "Plan")
        wf.data["test"] = True

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "workflow.json"
            wf.save(path)

            assert path.exists()

            loaded = Workflow.load(path)
            assert loaded.workflow_id == "wf-save"
            assert loaded.state == WorkflowState.PLANNING
            assert loaded.data["test"] is True
            assert len(loaded.step_log) == 2

    def test_save_creates_parent_dirs(self) -> None:
        wf = Workflow(workflow_id="wf-nested")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sub" / "dir" / "workflow.json"
            wf.save(path)
            assert path.exists()

    def test_load_nonexistent_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            Workflow.load("/nonexistent/path/workflow.json")

    def test_error_preserved_in_serialization(self) -> None:
        wf = Workflow()
        wf.transition(WorkflowState.RESOLVING)
        wf.transition(WorkflowState.FAILED, "Something broke")

        d = wf.to_dict()
        restored = Workflow.from_dict(d)
        assert restored.error == "Something broke"


# ---------------------------------------------------------------------------
# StepLogEntry
# ---------------------------------------------------------------------------

class TestStepLogEntry:
    def test_to_dict(self) -> None:
        entry = StepLogEntry(
            timestamp=1234567890.0,
            from_state="created",
            to_state="resolving",
            message="Starting",
            step_number=None,
        )
        d = entry.to_dict()
        assert d["timestamp"] == 1234567890.0
        assert d["from_state"] == "created"
        assert "step_number" not in d  # None excluded

    def test_to_dict_with_step(self) -> None:
        entry = StepLogEntry(
            timestamp=1234567890.0,
            from_state="executing",
            to_state="executing",
            message="Step done",
            step_number=3,
            data={"vlan_id": 50},
        )
        d = entry.to_dict()
        assert d["step_number"] == 3
        assert d["data"]["vlan_id"] == 50

    def test_from_dict(self) -> None:
        d = {
            "timestamp": 100.0,
            "from_state": "resolving",
            "to_state": "planning",
            "message": "Done resolving",
        }
        entry = StepLogEntry.from_dict(d)
        assert entry.from_state == "resolving"
        assert entry.to_state == "planning"
        assert entry.step_number is None
        assert entry.data == {}

    def test_roundtrip(self) -> None:
        entry = StepLogEntry(
            timestamp=999.0,
            from_state="a",
            to_state="b",
            message="test",
            step_number=5,
            data={"key": "val"},
        )
        restored = StepLogEntry.from_dict(entry.to_dict())
        assert restored.timestamp == 999.0
        assert restored.step_number == 5
        assert restored.data["key"] == "val"
