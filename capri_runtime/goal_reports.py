"""Read-only, principal-scoped goal status reports."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .goals import GoalRecord, GoalValidationError
from .tasks import TaskRecord


_MAX_EVIDENCE_ITEMS = 64
_GOAL_STATES = frozenset({
    "accepted", "planning", "planned", "running", "paused", "cancelling",
    "awaiting_verification", "succeeded", "failed", "cancelled",
    "reconciliation_required",
})
_TASK_STATES = frozenset({
    "blocked", "queued", "budget_wait", "running", "retry_wait",
    "succeeded", "failed", "cancelled", "reconciliation_required",
})


@dataclass(frozen=True, slots=True)
class GoalEvidenceReport:
    evidence_type: str
    reference: str
    step_index: int
    created_at: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "evidence_type": self.evidence_type,
            "reference": self.reference,
            "step_index": self.step_index,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class GoalReport:
    """Sanitized status projection; task results and plan inputs are never included."""

    report_version: int
    generated_at: str
    goal_id: str
    outcome: str
    goal_state: str
    goal_version: int
    created_at: str
    updated_at: str
    deadline: str | None
    acceptance_criteria: tuple[str, ...]
    completion_status: str
    owner_acceptance_status: str
    partial: bool
    uncertain: bool
    uncertainty_code: str | None
    task_id: str | None
    task_state: str | None
    task_available: bool | None
    steps_completed: int
    steps_total: int
    cancellation_requested: bool
    evidence: tuple[GoalEvidenceReport, ...]
    evidence_truncated: bool

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe summary without raw task payloads or constraints."""
        return {
            "report_version": self.report_version,
            "generated_at": self.generated_at,
            "goal_id": self.goal_id,
            "outcome": self.outcome,
            "goal_state": self.goal_state,
            "goal_version": self.goal_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deadline": self.deadline,
            "acceptance_criteria": list(self.acceptance_criteria),
            "completion_status": self.completion_status,
            "owner_acceptance_status": self.owner_acceptance_status,
            "partial": self.partial,
            "uncertain": self.uncertain,
            "uncertainty_code": self.uncertainty_code,
            "task_id": self.task_id,
            "task_state": self.task_state,
            "task_available": self.task_available,
            "steps_completed": self.steps_completed,
            "steps_total": self.steps_total,
            "cancellation_requested": self.cancellation_requested,
            "evidence": [item.as_dict() for item in self.evidence],
            "evidence_truncated": self.evidence_truncated,
        }


def _owner_acceptance_status(
    goal_state: str, evidence: tuple[GoalEvidenceReport, ...],
) -> str:
    decision = next(
        (
            item.evidence_type for item in reversed(evidence)
            if item.evidence_type in {"acceptance_accepted", "acceptance_rejected"}
        ),
        None,
    )
    if decision == "acceptance_accepted":
        if goal_state == "succeeded":
            return "accepted"
        if goal_state == "awaiting_verification":
            return "accepted_pending_transition"
        return "decision_state_mismatch"
    if decision == "acceptance_rejected":
        if goal_state == "failed":
            return "rejected"
        if goal_state == "awaiting_verification":
            return "rejected_pending_transition"
        return "decision_state_mismatch"
    if goal_state == "awaiting_verification":
        return "pending"
    return "not_recorded"


def build_goal_report(
    goal: GoalRecord, task: TaskRecord | None = None,
) -> GoalReport:
    """Build a bounded, read-only report from owner-scoped persisted records.

    The caller must retrieve both records through the authenticated principal's
    stores. A missing linked task is reported as uncertain, never as success.
    """
    if not isinstance(goal, GoalRecord):
        raise GoalValidationError("goal must be a GoalRecord")
    if (
        type(goal.state) is not str
        or type(goal.task_id) not in (str, type(None))
        or type(goal.plan) is not tuple
        or type(goal.evidence) is not tuple
    ):
        raise GoalValidationError("goal report source record is invalid")
    if task is not None:
        if not isinstance(task, TaskRecord):
            raise GoalValidationError("task must be a TaskRecord")
        if goal.task_id is None or task.task_id != goal.task_id:
            raise GoalValidationError("task does not match the goal's immutable link")
        if (
            type(task.state) is not str
            or type(task.result) is not tuple
            or type(task.cancel_requested) is not bool
        ):
            raise GoalValidationError("task report source record is invalid")

    evidence_rows: list[GoalEvidenceReport] = []
    for row in goal.evidence:
        if type(row) is not dict:
            raise GoalValidationError("persisted goal evidence is invalid")
        evidence_type = row.get("evidence_type")
        reference = row.get("reference")
        step_index = row.get("step_index")
        created_at = row.get("created_at")
        if (
            type(evidence_type) is not str or not evidence_type or len(evidence_type) > 64
            or type(reference) is not str or not reference or len(reference) > 512
            or type(step_index) is not int or not -1 <= step_index < 32
            or type(created_at) is not str or not created_at or len(created_at) > 64
        ):
            raise GoalValidationError("persisted goal evidence is invalid")
        evidence_rows.append(GoalEvidenceReport(
            evidence_type, reference, step_index, created_at,
        ))

    evidence_truncated = len(evidence_rows) > _MAX_EVIDENCE_ITEMS
    first_recent_index = max(0, len(evidence_rows) - _MAX_EVIDENCE_ITEMS)
    selected_indices = list(range(first_recent_index, len(evidence_rows)))
    latest_decision_index = next(
        (
            index for index in range(len(evidence_rows) - 1, -1, -1)
            if evidence_rows[index].evidence_type in {
                "acceptance_accepted", "acceptance_rejected",
            }
        ),
        None,
    )
    if (
        evidence_truncated
        and latest_decision_index is not None
        and latest_decision_index < first_recent_index
    ):
        selected_indices = [latest_decision_index] + selected_indices[
            -(_MAX_EVIDENCE_ITEMS - 1):
        ]
        selected_indices.sort()
    bounded_evidence = tuple(evidence_rows[index] for index in selected_indices)
    raw_goal_state = goal.state
    goal_state = raw_goal_state if raw_goal_state in _GOAL_STATES else "unknown"
    task_state = None
    if task is not None:
        task_state = task.state if task.state in _TASK_STATES else "unknown"

    steps_total = len(goal.plan)
    raw_steps_completed = len(task.result) if task is not None else 0
    steps_completed = min(raw_steps_completed, steps_total)
    acceptance_status = _owner_acceptance_status(raw_goal_state, tuple(evidence_rows))
    linked_task_missing = goal.task_id is not None and task is None

    completion_status = "uncertain"
    uncertainty_code: str | None = None

    if linked_task_missing:
        uncertainty_code = "linked_task_unavailable"
    elif goal_state == "unknown":
        uncertainty_code = "unknown_goal_state"
    elif task is not None and task_state == "unknown":
        uncertainty_code = "unknown_task_state"
    elif task is not None and raw_steps_completed > steps_total:
        uncertainty_code = "task_progress_mismatch"
    elif goal_state == "reconciliation_required" or task_state == "reconciliation_required":
        uncertainty_code = "task_outcome_uncertain"
    elif acceptance_status == "decision_state_mismatch":
        uncertainty_code = "acceptance_state_mismatch"
    elif goal.task_id is None and goal_state in {
        "running", "cancelling", "awaiting_verification",
    }:
        uncertainty_code = "missing_task_link"
    elif task is not None and goal_state == "awaiting_verification" and task_state != "succeeded":
        uncertainty_code = "goal_task_state_mismatch"
    elif task is not None and goal_state == "succeeded" and task_state != "succeeded":
        uncertainty_code = "goal_task_state_mismatch"
    elif task is not None and goal_state == "succeeded" and acceptance_status != "accepted":
        uncertainty_code = "acceptance_evidence_missing"
    elif (
        task is not None and goal_state == "failed" and task_state == "succeeded"
        and acceptance_status != "rejected"
    ):
        uncertainty_code = "acceptance_evidence_missing"
    elif task is not None and goal_state == "failed" and task_state not in {"failed", "succeeded"}:
        uncertainty_code = "goal_task_state_mismatch"
    elif task is not None and goal_state == "cancelled" and task_state not in {"cancelled", "succeeded"}:
        uncertainty_code = "goal_task_state_mismatch"
    elif goal_state == "awaiting_verification":
        if acceptance_status in {"accepted_pending_transition", "rejected_pending_transition"}:
            completion_status = "acceptance_transition_pending"
        else:
            completion_status = "awaiting_owner_verification"
    elif goal_state == "succeeded":
        completion_status = "completed"
    elif goal_state == "failed":
        completion_status = "failed"
    elif goal_state == "cancelled":
        completion_status = "cancelled"
    elif task is not None and task_state in {"succeeded", "failed", "cancelled"}:
        completion_status = "reconciliation_pending"
    elif goal_state == "cancelling" or (task is not None and task.cancel_requested):
        completion_status = "cancellation_pending"
    elif task is not None and task_state == "blocked":
        completion_status = "activation_pending"
    elif task is not None and task_state == "budget_wait":
        completion_status = "waiting_for_budget"
    elif task is not None and task_state in {"queued", "running", "retry_wait"}:
        completion_status = "in_progress"
    elif goal_state == "paused":
        completion_status = "paused"
    elif goal_state == "planned":
        completion_status = "ready"
    elif goal_state == "planning":
        completion_status = "planning"
    elif goal_state == "accepted":
        completion_status = "not_started"
    else:
        uncertainty_code = uncertainty_code or "unknown_goal_state"

    return GoalReport(
        report_version=1,
        generated_at=datetime.now(timezone.utc).isoformat(),
        goal_id=goal.goal_id,
        outcome=goal.outcome,
        goal_state=goal_state,
        goal_version=goal.version,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
        deadline=goal.deadline,
        acceptance_criteria=goal.acceptance_criteria,
        completion_status=completion_status,
        owner_acceptance_status=acceptance_status,
        partial=0 < steps_completed < steps_total,
        uncertain=completion_status == "uncertain",
        uncertainty_code=uncertainty_code,
        task_id=goal.task_id,
        task_state=task_state,
        task_available=None if goal.task_id is None else task is not None,
        steps_completed=steps_completed,
        steps_total=steps_total,
        cancellation_requested=bool(task and task.cancel_requested),
        evidence=bounded_evidence,
        evidence_truncated=evidence_truncated,
    )
