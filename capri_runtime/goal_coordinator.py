"""Crash-recoverable coordination between durable goals and principal tasks."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from .goals import (
    GoalConflictError,
    GoalPlanProposal,
    GoalRecord,
    GoalValidationError,
    SQLiteGoalStore,
    validate_goal_plan,
)
from .tasks import (
    SQLiteTaskStore,
    TaskNotFoundError,
    TaskRecord,
)


@dataclass(frozen=True, slots=True)
class GoalExecution:
    goal: GoalRecord
    task: TaskRecord


@dataclass(frozen=True, slots=True)
class GoalEvidenceSummary:
    evidence_type: str
    reference: str
    step_index: int
    created_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_type": self.evidence_type,
            "reference": self.reference,
            "step_index": self.step_index,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class GoalEventSummary:
    timestamp: str
    state: str
    version: int
    event_type: str

    def as_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "state": self.state,
            "version": self.version,
            "event_type": self.event_type,
        }


@dataclass(frozen=True, slots=True)
class TaskEventSummary:
    timestamp: str
    state: str
    step_index: int
    attempt: int
    error_code: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "state": self.state,
            "step_index": self.step_index,
            "attempt": self.attempt,
            "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class GoalCompletionReport:
    """Owner-scoped completion summary; raw task results are deliberately omitted."""

    goal_id: str
    outcome: str
    goal_state: str
    goal_version: int
    goal_created_at: str
    goal_updated_at: str
    acceptance_criteria: tuple[str, ...]
    acceptance_status: str
    completion_status: str
    next_action: str
    owner_action_required: bool
    task_id: str | None
    task_state: str | None
    task_current_step: int | None
    task_total_steps: int
    task_completed_steps: int
    task_attempts: int
    task_cancel_requested: bool
    task_failure_code: str | None
    task_created_at: str | None
    task_updated_at: str | None
    evidence: tuple[GoalEvidenceSummary, ...]
    goal_events: tuple[GoalEventSummary, ...]
    task_events: tuple[TaskEventSummary, ...]
    generated_at: str

    def as_dict(self) -> dict[str, object]:
        """Return JSON-safe owner-facing data without raw tool outputs or plan inputs."""
        return {
            "goal_id": self.goal_id,
            "outcome": self.outcome,
            "goal_state": self.goal_state,
            "goal_version": self.goal_version,
            "goal_created_at": self.goal_created_at,
            "goal_updated_at": self.goal_updated_at,
            "acceptance_criteria": list(self.acceptance_criteria),
            "acceptance_status": self.acceptance_status,
            "completion_status": self.completion_status,
            "next_action": self.next_action,
            "owner_action_required": self.owner_action_required,
            "task_id": self.task_id,
            "task_state": self.task_state,
            "task_current_step": self.task_current_step,
            "task_total_steps": self.task_total_steps,
            "task_completed_steps": self.task_completed_steps,
            "task_attempts": self.task_attempts,
            "task_cancel_requested": self.task_cancel_requested,
            "task_failure_code": self.task_failure_code,
            "task_created_at": self.task_created_at,
            "task_updated_at": self.task_updated_at,
            "evidence": [item.as_dict() for item in self.evidence],
            "goal_events": [item.as_dict() for item in self.goal_events],
            "task_events": [item.as_dict() for item in self.task_events],
            "generated_at": self.generated_at,
        }


class GoalCoordinator:
    """Coordinates goals and tasks with deferred activation and idempotent recovery.

    Goal and task stores may be separate SQLite databases. The task is first
    created in a non-claimable blocked state, then linked durably to its goal,
    and only then activated. A retry after any interruption reuses the same
    principal-scoped idempotency key and task link.
    """

    def __init__(
        self,
        goal_store: SQLiteGoalStore,
        task_store: SQLiteTaskStore,
        allowed_tools: frozenset[str],
    ) -> None:
        if not isinstance(goal_store, SQLiteGoalStore):
            raise GoalValidationError("goal_store must be a SQLiteGoalStore")
        if not isinstance(task_store, SQLiteTaskStore):
            raise GoalValidationError("task_store must be a SQLiteTaskStore")
        if type(allowed_tools) is not frozenset:
            raise GoalValidationError("allowed_tools must be a frozenset")
        self.goal_store = goal_store
        self.task_store = task_store
        self.allowed_tools = allowed_tools

    def prepare(
        self, goal_id: str, principal_id: str, *,
        expected_version: int, now: datetime | None = None,
    ) -> GoalExecution:
        if type(expected_version) is not int or expected_version < 1:
            raise GoalValidationError("expected_version must be a positive integer")
        goal = self.goal_store.get_for_principal(goal_id, principal_id)
        if goal.task_id is not None:
            task = self.task_store.get_for_principal(goal.task_id, principal_id)
            if task.state == "blocked":
                task = self.task_store.activate_for_principal(
                    task.task_id, principal_id, now=now,
                )
            return GoalExecution(self.goal_store.get_for_principal(goal_id, principal_id), task)
        if goal.state != "planned" or goal.version != expected_version:
            raise GoalConflictError("goal must be at the expected planned version")
        steps = validate_goal_plan(
            GoalPlanProposal(tuple(goal.plan)), self.allowed_tools,
        )
        idempotency_key = f"goal:{goal.goal_id}:v{goal.version}"
        task = self.task_store.create_for_principal(
            principal_id, list(steps), idempotency_key=idempotency_key,
            now=now, deferred=True,
        )
        try:
            linked = self.goal_store.link_task_for_principal(
                goal.goal_id, principal_id, task.task_id,
                expected_version=goal.version, now=now,
            )
        except Exception:
            # The task is still blocked and cannot be claimed. If the goal changed
            # before the durable link, cancel the orphan rather than release it.
            try:
                self.task_store.request_cancel_for_principal(
                    task.task_id, principal_id, now=now,
                )
            except TaskNotFoundError:
                pass
            raise
        activated = self.task_store.activate_for_principal(
            task.task_id, principal_id, now=now,
        )
        return GoalExecution(linked, activated)

    @staticmethod
    def _result_reference(task_id: str, step_index: int, result: object) -> str:
        try:
            payload = json.dumps(
                {"task_id": task_id, "step_index": step_index, "result": result},
                ensure_ascii=False, allow_nan=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8", errors="strict")
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
            raise GoalValidationError("task result cannot be safely fingerprinted") from None
        return hashlib.sha256(payload).hexdigest()

    def reconcile(
        self, goal_id: str, principal_id: str, *,
        now: datetime | None = None,
    ) -> GoalExecution:
        goal = self.goal_store.get_for_principal(goal_id, principal_id)
        if goal.task_id is None:
            raise GoalConflictError("goal has no linked task to reconcile")
        task = self.task_store.get_for_principal(goal.task_id, principal_id)
        if goal.state in {"succeeded", "failed", "cancelled"}:
            return GoalExecution(goal, task)
        if goal.state == "awaiting_verification" and task.state == "succeeded":
            return GoalExecution(goal, task)
        if task.state in {"blocked", "queued", "retry_wait", "running"}:
            return GoalExecution(goal, task)
        for index, result in enumerate(task.result):
            reference = self._result_reference(task.task_id, index, result)
            goal = self.goal_store.record_evidence_for_principal(
                goal_id, principal_id, "task_step_result_sha256",
                reference, index, now=now,
            )
        target = {
            "succeeded": "awaiting_verification",
            "failed": "failed",
            "cancelled": "cancelled",
            "reconciliation_required": "reconciliation_required",
        }.get(task.state)
        if target is None:
            raise GoalConflictError("task state cannot be reconciled into a goal")
        if goal.state == "reconciliation_required":
            # Uncertain external side effects need explicit human/host resolution.
            return GoalExecution(goal, task)
        if goal.state == "cancelling" and target == "awaiting_verification":
            # The task may have completed just before cancellation was observed.
            pass
        elif goal.state not in {"running", "cancelling"}:
            raise GoalConflictError("goal is not in a reconcilable lifecycle state")
        if goal.state != target:
            goal = self.goal_store.transition_for_principal(
                goal_id, principal_id, target,
                expected_version=goal.version, now=now,
            )
        return GoalExecution(goal, task)

    def completion_report(
        self, goal_id: str, principal_id: str,
    ) -> GoalCompletionReport:
        """Build a stable owner-scoped report without returning raw task results.

        Goal and task data live in separate SQLite stores, so this method checks
        both records again after reading their event/evidence histories. If either
        record changes during report construction, the caller must retry.
        """
        goal = self.goal_store.get_for_principal(goal_id, principal_id)
        task = (
            self.task_store.get_for_principal(goal.task_id, principal_id)
            if goal.task_id is not None else None
        )
        goal_events_raw = self.goal_store.events_for_principal(goal_id, principal_id)
        task_events_raw = (
            self.task_store.events_for_principal(task.task_id, principal_id)
            if task is not None else ()
        )

        latest_goal = self.goal_store.get_for_principal(goal_id, principal_id)
        latest_task = (
            self.task_store.get_for_principal(task.task_id, principal_id)
            if task is not None else None
        )
        if goal != latest_goal or task != latest_task:
            raise GoalConflictError("goal or task changed while the completion report was being built")

        evidence = tuple(
            GoalEvidenceSummary(
                item["evidence_type"], item["reference"],
                item["step_index"], item["created_at"],
            )
            for item in goal.evidence
        )
        goal_events = tuple(
            GoalEventSummary(
                item["timestamp"], item["state"],
                item["version"], item["event_type"],
            )
            for item in goal_events_raw
        )
        task_events = tuple(
            TaskEventSummary(
                item["timestamp"], item["state"],
                item["step_index"], item["attempt"], item["error_code"],
            )
            for item in task_events_raw
        )

        total_steps = len(goal.plan)
        completed_steps = min(len(task.result), total_steps) if task is not None else 0
        evidence_types = {item.evidence_type for item in evidence}
        if "acceptance_accepted" in evidence_types:
            acceptance_status = "accepted"
        elif "acceptance_rejected" in evidence_types:
            acceptance_status = "rejected"
        elif goal.state == "awaiting_verification":
            acceptance_status = "pending"
        else:
            acceptance_status = "not_requested"

        if goal.state == "succeeded":
            completion_status = (
                "accepted" if acceptance_status == "accepted" else "inconsistent"
            )
        elif goal.state == "failed":
            if acceptance_status == "rejected":
                completion_status = "rejected"
            elif completed_steps:
                completion_status = "partial"
            else:
                completion_status = "failed"
        elif goal.state == "reconciliation_required" or (
            task is not None and task.state == "reconciliation_required"
        ):
            completion_status = "uncertain"
        elif goal.state == "awaiting_verification":
            completion_status = "awaiting_owner_acceptance"
        elif goal.state == "cancelling":
            completion_status = "cancellation_pending"
        elif goal.state == "cancelled":
            completion_status = "cancelled"
        elif goal.state == "paused":
            completion_status = "paused"
        elif task is not None and task.state in {"succeeded", "failed", "cancelled"}:
            completion_status = "reconciliation_pending"
        elif task is not None:
            completion_status = "in_progress"
        else:
            completion_status = "not_started"

        next_action = {
            "awaiting_owner_acceptance": "owner_acceptance_required",
            "uncertain": "owner_or_host_reconciliation_required",
            "reconciliation_pending": "host_reconciliation_required",
            "partial": "owner_review_required",
            "failed": "owner_review_required",
            "inconsistent": "owner_review_required",
            "cancellation_pending": "cancellation_reconciliation_required",
            "paused": "owner_resume_or_cancel",
            "in_progress": "execution_in_progress",
        }.get(completion_status, "none")
        owner_action_required = next_action in {
            "owner_acceptance_required",
            "owner_or_host_reconciliation_required",
            "owner_review_required",
            "cancellation_reconciliation_required",
            "owner_resume_or_cancel",
        }

        return GoalCompletionReport(
            goal_id=goal.goal_id,
            outcome=goal.outcome,
            goal_state=goal.state,
            goal_version=goal.version,
            goal_created_at=goal.created_at,
            goal_updated_at=goal.updated_at,
            acceptance_criteria=goal.acceptance_criteria,
            acceptance_status=acceptance_status,
            completion_status=completion_status,
            next_action=next_action,
            owner_action_required=owner_action_required,
            task_id=goal.task_id,
            task_state=task.state if task is not None else None,
            task_current_step=task.current_step if task is not None else None,
            task_total_steps=total_steps,
            task_completed_steps=completed_steps,
            task_attempts=task.attempts if task is not None else 0,
            task_cancel_requested=task.cancel_requested if task is not None else False,
            task_failure_code=task.error_code if task is not None else None,
            task_created_at=task.created_at if task is not None else None,
            task_updated_at=task.updated_at if task is not None else None,
            evidence=evidence,
            goal_events=goal_events,
            task_events=task_events,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def verify(
        self, goal_id: str, principal_id: str, *, accepted: bool,
        evidence_reference: str, expected_version: int,
        now: datetime | None = None,
    ) -> GoalRecord:
        """Record an explicit owner acceptance decision after task execution.

        Task completion alone never marks the user's outcome successful. The
        authenticated owner must explicitly accept the stated criteria and
        provide a durable evidence reference.
        """
        if type(accepted) is not bool:
            raise GoalValidationError("accepted must be a boolean")
        if type(expected_version) is not int or expected_version < 1:
            raise GoalValidationError("expected_version must be a positive integer")
        goal = self.goal_store.get_for_principal(goal_id, principal_id)
        if goal.state != "awaiting_verification" or goal.version != expected_version:
            raise GoalConflictError("goal is not awaiting verification at the expected version")
        goal = self.goal_store.record_evidence_for_principal(
            goal_id, principal_id,
            "acceptance_accepted" if accepted else "acceptance_rejected",
            evidence_reference, -1, now=now,
        )
        return self.goal_store.transition_for_principal(
            goal_id, principal_id, "succeeded" if accepted else "failed",
            expected_version=goal.version, now=now,
        )

    def cancel(
        self, goal_id: str, principal_id: str, *,
        expected_version: int, now: datetime | None = None,
    ) -> GoalExecution | GoalRecord:
        if type(expected_version) is not int or expected_version < 1:
            raise GoalValidationError("expected_version must be a positive integer")
        goal = self.goal_store.get_for_principal(goal_id, principal_id)
        if goal.state in {"succeeded", "failed", "cancelled"}:
            if goal.task_id is None:
                return goal
            return GoalExecution(
                goal, self.task_store.get_for_principal(goal.task_id, principal_id)
            )
        if goal.version != expected_version and goal.state != "cancelling":
            raise GoalConflictError("goal version changed")
        if goal.task_id is None:
            return self.goal_store.transition_for_principal(
                goal_id, principal_id, "cancelled",
                expected_version=expected_version, now=now,
            )
        task = self.task_store.get_for_principal(goal.task_id, principal_id)
        if task.state not in {"succeeded", "failed", "cancelled", "reconciliation_required"}:
            task = self.task_store.request_cancel_for_principal(
                task.task_id, principal_id, now=now,
            )
        if task.state in {"cancelled", "failed", "succeeded", "reconciliation_required"}:
            reconciled = self.reconcile(goal_id, principal_id, now=now)
            if reconciled.goal.state == "awaiting_verification":
                cancelled = self.goal_store.transition_for_principal(
                    goal_id, principal_id, "cancelled",
                    expected_version=reconciled.goal.version, now=now,
                )
                return GoalExecution(cancelled, task)
            return reconciled
        if goal.state == "running":
            goal = self.goal_store.transition_for_principal(
                goal_id, principal_id, "cancelling",
                expected_version=goal.version, now=now,
            )
        return GoalExecution(goal, task)
