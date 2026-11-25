"""Crash-recoverable coordination between durable goals and principal tasks."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

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
