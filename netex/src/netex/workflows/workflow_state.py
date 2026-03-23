"""Workflow state machine for multi-step cross-vendor operations.

Implements the three-phase workflow model from PRD Section 10.2 (Decision D15):

    CREATED -> RESOLVING -> PLANNING -> AWAITING_CONFIRMATION
            -> EXECUTING -> step_N_complete -> COMPLETED
                                            -> FAILED -> ROLLING_BACK -> ROLLED_BACK
                                                      -> ROLLBACK_FAILED
            -> CANCELLED (from any pre-execution state)

Each workflow instance tracks:
    - Current state
    - Step log with timestamps
    - Accumulated data (findings, plan steps, etc.)

State persistence is via JSON serialization for debugging and recovery.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from netex.errors import WorkflowError

# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------


class WorkflowState(StrEnum):
    """Valid states in the workflow state machine.

    Follows the three-phase model from PRD Section 10.2:
        Phase 1: RESOLVING (gather state, resolve assumptions)
        Phase 2: PLANNING -> AWAITING_CONFIRMATION (present plan)
        Phase 3: EXECUTING (execute with operator confirmation)
    """

    CREATED = "created"
    RESOLVING = "resolving"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"
    CANCELLED = "cancelled"


# Valid state transitions -- maps current state to allowed next states.
VALID_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.CREATED: frozenset(
        {
            WorkflowState.RESOLVING,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.RESOLVING: frozenset(
        {
            WorkflowState.PLANNING,
            WorkflowState.CANCELLED,
            WorkflowState.FAILED,
        }
    ),
    WorkflowState.PLANNING: frozenset(
        {
            WorkflowState.AWAITING_CONFIRMATION,
            WorkflowState.CANCELLED,
            WorkflowState.FAILED,
        }
    ),
    WorkflowState.AWAITING_CONFIRMATION: frozenset(
        {
            WorkflowState.EXECUTING,
            WorkflowState.PLANNING,  # Re-plan after operator modification
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.EXECUTING: frozenset(
        {
            WorkflowState.COMPLETED,
            WorkflowState.FAILED,
        }
    ),
    WorkflowState.FAILED: frozenset(
        {
            WorkflowState.ROLLING_BACK,
        }
    ),
    WorkflowState.ROLLING_BACK: frozenset(
        {
            WorkflowState.ROLLED_BACK,
            WorkflowState.ROLLBACK_FAILED,
        }
    ),
    # Terminal states -- no transitions out
    WorkflowState.COMPLETED: frozenset(),
    WorkflowState.ROLLED_BACK: frozenset(),
    WorkflowState.ROLLBACK_FAILED: frozenset(),
    WorkflowState.CANCELLED: frozenset(),
}

# States that are considered terminal (workflow is finished).
TERMINAL_STATES: frozenset[WorkflowState] = frozenset(
    {
        WorkflowState.COMPLETED,
        WorkflowState.ROLLED_BACK,
        WorkflowState.ROLLBACK_FAILED,
        WorkflowState.CANCELLED,
    }
)


# ---------------------------------------------------------------------------
# Step log entry
# ---------------------------------------------------------------------------


@dataclass
class StepLogEntry:
    """A single entry in the workflow step log.

    Records what happened, when, and the state transition.
    """

    timestamp: float
    from_state: str
    to_state: str
    message: str
    step_number: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON persistence."""
        result: dict[str, Any] = {
            "timestamp": self.timestamp,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "message": self.message,
        }
        if self.step_number is not None:
            result["step_number"] = self.step_number
        if self.data:
            result["data"] = self.data
        return result

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StepLogEntry:
        """Deserialize from a plain dict."""
        return cls(
            timestamp=d["timestamp"],
            from_state=d["from_state"],
            to_state=d["to_state"],
            message=d["message"],
            step_number=d.get("step_number"),
            data=d.get("data", {}),
        )


# ---------------------------------------------------------------------------
# Workflow instance
# ---------------------------------------------------------------------------


class Workflow:
    """A single workflow instance with state machine enforcement.

    Parameters
    ----------
    workflow_id:
        Unique identifier for this workflow. Auto-generated if not provided.
    workflow_type:
        Type of workflow (e.g., ``"vlan_configure"``, ``"policy_sync"``).
    description:
        Human-readable description of what this workflow does.

    Usage::

        wf = Workflow(workflow_type="vlan_configure", description="Create VLAN 50")
        wf.transition(WorkflowState.RESOLVING, "Gathering VLAN state from plugins")
        wf.transition(WorkflowState.PLANNING, "Building cross-vendor plan")
        wf.transition(WorkflowState.AWAITING_CONFIRMATION, "Plan ready for review")
        wf.transition(WorkflowState.EXECUTING, "Operator confirmed")
        wf.log_step(1, "Created VLAN interface on gateway")
        wf.log_step(2, "Created network object on edge")
        wf.transition(WorkflowState.COMPLETED, "All steps executed successfully")
    """

    def __init__(
        self,
        workflow_id: str | None = None,
        workflow_type: str = "",
        description: str = "",
    ) -> None:
        self.workflow_id = workflow_id or str(uuid.uuid4())
        self.workflow_type = workflow_type
        self.description = description
        self.state = WorkflowState.CREATED
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.step_log: list[StepLogEntry] = []
        self.data: dict[str, Any] = {}
        self.total_steps: int = 0
        self.completed_steps: int = 0
        self.error: str | None = None

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def transition(
        self,
        new_state: WorkflowState,
        message: str = "",
        *,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Transition to a new state, recording the transition in the step log.

        Parameters
        ----------
        new_state:
            The target state.
        message:
            Human-readable description of why this transition is happening.
        data:
            Optional structured data to attach to the log entry.

        Raises
        ------
        WorkflowError
            If the transition is not valid from the current state.
        """
        allowed = VALID_TRANSITIONS.get(self.state, frozenset())
        if new_state not in allowed:
            raise WorkflowError(
                f"Invalid transition: {self.state.value} -> {new_state.value}. "
                f"Allowed: {sorted(s.value for s in allowed)}",
                workflow_id=self.workflow_id,
                current_state=self.state.value,
                attempted_state=new_state.value,
            )

        old_state = self.state
        self.state = new_state
        self.updated_at = time.time()

        if new_state == WorkflowState.FAILED and message:
            self.error = message

        entry = StepLogEntry(
            timestamp=self.updated_at,
            from_state=old_state.value,
            to_state=new_state.value,
            message=message,
            data=data or {},
        )
        self.step_log.append(entry)

    def log_step(
        self,
        step_number: int,
        message: str,
        *,
        data: dict[str, Any] | None = None,
        success: bool = True,
    ) -> None:
        """Log an execution step within the EXECUTING state.

        Parameters
        ----------
        step_number:
            1-based step number.
        message:
            Description of what this step did.
        data:
            Optional structured data about the step result.
        success:
            Whether the step succeeded.

        Raises
        ------
        WorkflowError
            If the workflow is not in the EXECUTING or ROLLING_BACK state.
        """
        if self.state not in (WorkflowState.EXECUTING, WorkflowState.ROLLING_BACK):
            raise WorkflowError(
                f"Cannot log steps in state '{self.state.value}'. "
                "Workflow must be in 'executing' or 'rolling_back' state.",
                workflow_id=self.workflow_id,
                current_state=self.state.value,
            )

        entry = StepLogEntry(
            timestamp=time.time(),
            from_state=self.state.value,
            to_state=self.state.value,
            message=message,
            step_number=step_number,
            data={**(data or {}), "success": success},
        )
        self.step_log.append(entry)

        if success and self.state == WorkflowState.EXECUTING:
            self.completed_steps = max(self.completed_steps, step_number)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        """Whether the workflow has reached a terminal state."""
        return self.state in TERMINAL_STATES

    @property
    def duration_seconds(self) -> float:
        """Total elapsed time from creation to last update."""
        return self.updated_at - self.created_at

    @property
    def progress(self) -> str:
        """Human-readable progress string."""
        if self.total_steps > 0:
            return f"{self.completed_steps}/{self.total_steps} steps"
        return self.state.value

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the workflow to a plain dict for JSON persistence."""
        return {
            "workflow_id": self.workflow_id,
            "workflow_type": self.workflow_type,
            "description": self.description,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "error": self.error,
            "data": self.data,
            "step_log": [entry.to_dict() for entry in self.step_log],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Workflow:
        """Deserialize a workflow from a plain dict.

        Parameters
        ----------
        d:
            Dict as produced by ``to_dict()``.

        Returns
        -------
        Workflow
            Restored workflow instance.
        """
        wf = cls(
            workflow_id=d["workflow_id"],
            workflow_type=d.get("workflow_type", ""),
            description=d.get("description", ""),
        )
        wf.state = WorkflowState(d["state"])
        wf.created_at = d["created_at"]
        wf.updated_at = d["updated_at"]
        wf.total_steps = d.get("total_steps", 0)
        wf.completed_steps = d.get("completed_steps", 0)
        wf.error = d.get("error")
        wf.data = d.get("data", {})
        wf.step_log = [StepLogEntry.from_dict(e) for e in d.get("step_log", [])]
        return wf

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> Workflow:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    def save(self, path: str | Path) -> None:
        """Persist the workflow state to a JSON file.

        Parameters
        ----------
        path:
            File path to write the JSON state to.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())

    @classmethod
    def load(cls, path: str | Path) -> Workflow:
        """Load a workflow from a JSON file.

        Parameters
        ----------
        path:
            File path to read the JSON state from.

        Returns
        -------
        Workflow
            Restored workflow instance.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        """
        path = Path(path)
        return cls.from_json(path.read_text())
