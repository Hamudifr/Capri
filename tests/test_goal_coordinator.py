import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from capri_runtime.goal_coordinator import GoalCoordinator
from capri_runtime.goals import (
    GoalConflictError,
    GoalNotFoundError,
    GoalValidationError,
    GoalPlanProposal,
    SQLiteGoalStore,
)
from capri_runtime.tasks import (
    SQLiteTaskStore,
    TaskEngine,
    TaskNotFoundError,
    RetryableTaskError,
)

NOW = datetime(2026, 11, 25, 7, 0, tzinfo=timezone.utc)
TOOLS = frozenset({"collect"})
PLAN = [{"tool": "collect", "input": {"scope": "public"}, "max_attempts": 1}]


class GoalCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.goal_store = SQLiteGoalStore(os.path.join(self.temp.name, "goals.sqlite3"))
        self.task_store = SQLiteTaskStore(os.path.join(self.temp.name, "tasks.sqlite3"))
        self.coordinator = GoalCoordinator(self.goal_store, self.task_store, TOOLS)

    def tearDown(self):
        self.temp.cleanup()

    def planned_goal(self):
        goal = self.goal_store.create_for_principal(
            "alice", "Prepare a verified report",
            acceptance_criteria=["Sources cited"],
            now=NOW,
        )
        return self.goal_store.save_plan_for_principal(
            goal.goal_id, "alice", GoalPlanProposal(tuple(PLAN)),
            TOOLS, expected_version=goal.version, now=NOW,
        )

    def test_coordinator_rejects_boolean_versions(self):
        goal = self.planned_goal()
        with self.assertRaises(GoalValidationError):
            self.coordinator.prepare(
                goal.goal_id, "alice", expected_version=True, now=NOW,
            )
        execution = self.coordinator.prepare(
            goal.goal_id, "alice", expected_version=goal.version, now=NOW,
        )
        task_engine = TaskEngine(
            self.task_store, {}, "worker",
            principal_handlers={"collect": lambda data, key, principal: {"ok": True}},
        )
        task_engine.run_once(now=NOW)
        awaiting = self.coordinator.reconcile(goal.goal_id, "alice", now=NOW)
        with self.assertRaises(GoalValidationError):
            self.coordinator.verify(
                goal.goal_id, "alice", accepted=True,
                evidence_reference="e" * 64, expected_version=True, now=NOW,
            )
        with self.assertRaises(GoalValidationError):
            self.coordinator.cancel(
                goal.goal_id, "alice", expected_version=True, now=NOW,
            )

    def test_prepare_links_before_activation_and_is_idempotent(self):
        goal = self.planned_goal()
        execution = self.coordinator.prepare(
            goal.goal_id, "alice", expected_version=goal.version, now=NOW,
        )
        self.assertEqual(execution.goal.state, "running")
        self.assertEqual(execution.goal.task_id, execution.task.task_id)
        self.assertEqual(execution.task.state, "queued")
        again = self.coordinator.prepare(
            goal.goal_id, "alice", expected_version=goal.version, now=NOW,
        )
        self.assertEqual(again.task.task_id, execution.task.task_id)
        self.assertEqual(again.goal.version, execution.goal.version)
        self.assertEqual(
            [event["event_type"] for event in self.goal_store.events_for_principal(goal.goal_id, "alice")],
            ["created", "plan_saved", "task_linked"],
        )
        with self.assertRaises(TaskNotFoundError):
            self.task_store.get_for_principal(execution.task.task_id, "bob")

    def test_recovers_crash_after_task_creation_before_goal_link(self):
        goal = self.planned_goal()
        key = f"goal:{goal.goal_id}:v{goal.version}"
        orphan = self.task_store.create_for_principal(
            "alice", list(goal.plan), idempotency_key=key, now=NOW, deferred=True,
        )
        self.assertEqual(orphan.state, "blocked")
        recovered = self.coordinator.prepare(
            goal.goal_id, "alice", expected_version=goal.version, now=NOW,
        )
        self.assertEqual(recovered.task.task_id, orphan.task_id)
        self.assertEqual(recovered.task.state, "queued")
        self.assertEqual(recovered.goal.task_id, orphan.task_id)

    def test_recovers_crash_after_goal_link_before_task_activation(self):
        goal = self.planned_goal()
        key = f"goal:{goal.goal_id}:v{goal.version}"
        deferred = self.task_store.create_for_principal(
            "alice", list(goal.plan), idempotency_key=key, now=NOW, deferred=True,
        )
        linked = self.goal_store.link_task_for_principal(
            goal.goal_id, "alice", deferred.task_id,
            expected_version=goal.version, now=NOW,
        )
        self.assertEqual(linked.state, "running")
        self.assertEqual(self.task_store.get(deferred.task_id).state, "blocked")
        recovered = self.coordinator.prepare(
            goal.goal_id, "alice", expected_version=goal.version, now=NOW,
        )
        self.assertEqual(recovered.task.state, "queued")
        self.assertEqual(recovered.goal.task_id, deferred.task_id)

    def test_goal_and_task_success_reconcile_with_hashed_evidence(self):
        goal = self.planned_goal()
        execution = self.coordinator.prepare(
            goal.goal_id, "alice", expected_version=goal.version, now=NOW,
        )
        engine = TaskEngine(
            self.task_store, {}, "worker",
            principal_handlers={
                "collect": lambda data, key, principal: {
                    "principal": principal, "report": "private raw result",
                },
            },
        )
        task = engine.run_once(now=NOW)
        self.assertEqual(task.state, "succeeded")
        reconciled = self.coordinator.reconcile(goal.goal_id, "alice", now=NOW)
        self.assertEqual(reconciled.goal.state, "awaiting_verification")
        self.assertEqual(reconciled.task.state, "succeeded")
        self.assertEqual(len(reconciled.goal.evidence), 1)
        evidence = reconciled.goal.evidence[0]
        self.assertEqual(evidence["evidence_type"], "task_step_result_sha256")
        self.assertEqual(len(evidence["reference"]), 64)
        self.assertNotIn("private raw result", repr(evidence))
        again = self.coordinator.reconcile(goal.goal_id, "alice", now=NOW)
        self.assertEqual(again.goal.state, "awaiting_verification")
        accepted = self.coordinator.verify(
            goal.goal_id, "alice", accepted=True,
            evidence_reference="b" * 64,
            expected_version=again.goal.version, now=NOW,
        )
        self.assertEqual(accepted.state, "succeeded")
        self.assertEqual(len(accepted.evidence), 2)
        self.assertEqual(accepted.evidence[-1]["evidence_type"], "acceptance_accepted")
        with self.assertRaises(GoalConflictError):
            self.coordinator.verify(
                goal.goal_id, "alice", accepted=True,
                evidence_reference="c" * 64,
                expected_version=again.goal.version, now=NOW,
            )

    def test_completion_report_requires_owner_acceptance_and_never_returns_raw_results(self):
        goal = self.planned_goal()
        self.coordinator.prepare(
            goal.goal_id, "alice", expected_version=goal.version, now=NOW,
        )
        engine = TaskEngine(
            self.task_store, {}, "worker",
            principal_handlers={
                "collect": lambda data, key, principal: {
                    "private": "raw provider/tool output must not appear",
                },
            },
        )
        task = engine.run_once(now=NOW)
        self.assertEqual(task.state, "succeeded")
        awaiting = self.coordinator.reconcile(goal.goal_id, "alice", now=NOW)

        report = self.coordinator.completion_report(goal.goal_id, "alice")
        self.assertEqual(report.completion_status, "awaiting_owner_acceptance")
        self.assertEqual(report.acceptance_status, "pending")
        self.assertTrue(report.owner_action_required)
        self.assertEqual(report.task_state, "succeeded")
        self.assertEqual(report.task_total_steps, 1)
        self.assertEqual(report.task_completed_steps, 1)
        self.assertEqual(report.evidence[0].evidence_type, "task_step_result_sha256")
        self.assertTrue(report.evidence[0].reference.startswith("sha256:"))
        self.assertNotIn("raw provider/tool output", str(report.as_dict()))
        self.assertIn("awaiting_verification", [event.state for event in report.goal_events])
        self.assertTrue(report.task_events)
        with self.assertRaises(GoalNotFoundError):
            self.coordinator.completion_report(goal.goal_id, "bob")

        self.coordinator.verify(
            goal.goal_id, "alice", accepted=True,
            evidence_reference="owner-proof://acceptance-1",
            expected_version=awaiting.goal.version, now=NOW,
        )
        accepted = self.coordinator.completion_report(goal.goal_id, "alice")
        self.assertEqual(accepted.completion_status, "accepted")
        self.assertEqual(accepted.acceptance_status, "accepted")
        self.assertFalse(accepted.owner_action_required)
        self.assertEqual(
            accepted.evidence[-1].evidence_type, "acceptance_accepted",
        )
        self.assertEqual(accepted.as_dict()["goal_id"], goal.goal_id)

    def test_completion_report_distinguishes_partial_failure_and_uncertain_side_effects(self):
        goal = self.goal_store.create_for_principal(
            "alice", "Complete two bounded steps",
            acceptance_criteria=["Both steps completed"],
            now=NOW,
        )
        plan = (
            {"tool": "collect", "input": {"step": 1}, "max_attempts": 1},
            {"tool": "collect", "input": {"step": 2}, "max_attempts": 1},
        )
        goal = self.goal_store.save_plan_for_principal(
            goal.goal_id, "alice", GoalPlanProposal(plan),
            TOOLS, expected_version=goal.version, now=NOW,
        )
        self.coordinator.prepare(
            goal.goal_id, "alice", expected_version=goal.version, now=NOW,
        )
        calls = {"count": 0}

        def fail_second_step(data, key, principal):
            calls["count"] += 1
            if calls["count"] == 1:
                return {"private": "first step raw output"}
            raise RetryableTaskError("known no-side-effect failure")

        engine = TaskEngine(
            self.task_store, {}, "worker",
            principal_handlers={"collect": fail_second_step},
        )
        engine.run_once(now=NOW)
        failed = engine.run_once(now=NOW)
        self.assertEqual(failed.state, "failed")
        self.coordinator.reconcile(goal.goal_id, "alice", now=NOW)
        partial = self.coordinator.completion_report(goal.goal_id, "alice")
        self.assertEqual(partial.completion_status, "partial")
        self.assertEqual(partial.task_completed_steps, 1)
        self.assertEqual(partial.task_total_steps, 2)
        self.assertTrue(partial.owner_action_required)
        self.assertNotIn("first step raw output", str(partial.as_dict()))

        uncertain_goal = self.planned_goal()
        self.coordinator.prepare(
            uncertain_goal.goal_id, "alice",
            expected_version=uncertain_goal.version, now=NOW,
        )
        def uncertain_handler(data, key, principal):
            raise RuntimeError("external effect uncertain")

        uncertain_engine = TaskEngine(
            self.task_store, {}, "uncertain-worker",
            principal_handlers={"collect": uncertain_handler},
        )
        uncertain_task = uncertain_engine.run_once(now=NOW)
        self.assertEqual(uncertain_task.state, "reconciliation_required")
        self.coordinator.reconcile(uncertain_goal.goal_id, "alice", now=NOW)
        uncertain = self.coordinator.completion_report(
            uncertain_goal.goal_id, "alice",
        )
        self.assertEqual(uncertain.completion_status, "uncertain")
        self.assertEqual(uncertain.next_action, "owner_or_host_reconciliation_required")
        self.assertTrue(uncertain.owner_action_required)

    def test_uncertain_handler_outcome_quarantines_goal_for_reconciliation(self):
        goal = self.planned_goal()
        self.coordinator.prepare(goal.goal_id, "alice", expected_version=goal.version, now=NOW)

        def uncertain(data, key, principal):
            raise RuntimeError("the external side effect may have happened")

        engine = TaskEngine(
            self.task_store, {}, "worker", principal_handlers={"collect": uncertain},
        )
        task = engine.run_once(now=NOW)
        self.assertEqual(task.state, "reconciliation_required")
        reconciled = self.coordinator.reconcile(goal.goal_id, "alice", now=NOW)
        self.assertEqual(reconciled.goal.state, "reconciliation_required")
        # A later reconcile does not silently resolve an uncertain side effect.
        again = self.coordinator.reconcile(goal.goal_id, "alice", now=NOW)
        self.assertEqual(again.goal.state, "reconciliation_required")

    def test_failed_task_reconciles_to_failed_goal(self):
        goal = self.planned_goal()
        self.coordinator.prepare(goal.goal_id, "alice", expected_version=goal.version, now=NOW)

        def fail(data, key, principal):
            raise RetryableTaskError("known no-side-effect failure")

        engine = TaskEngine(
            self.task_store, {}, "worker", principal_handlers={"collect": fail},
        )
        task = engine.run_once(now=NOW)
        self.assertEqual(task.state, "failed")
        reconciled = self.coordinator.reconcile(goal.goal_id, "alice", now=NOW)
        self.assertEqual(reconciled.goal.state, "failed")

    def test_cancel_queued_task_and_goal_together(self):
        goal = self.planned_goal()
        execution = self.coordinator.prepare(
            goal.goal_id, "alice", expected_version=goal.version, now=NOW,
        )
        cancelled = self.coordinator.cancel(
            goal.goal_id, "alice", expected_version=execution.goal.version, now=NOW,
        )
        self.assertEqual(cancelled.goal.state, "cancelled")
        self.assertEqual(cancelled.task.state, "cancelled")
        self.assertIsNone(self.task_store.claim_next(
            "worker", now=NOW, principal_tools=TOOLS,
        ))

    def test_cancel_running_task_is_a_request_until_worker_confirms(self):
        goal = self.planned_goal()
        execution = self.coordinator.prepare(
            goal.goal_id, "alice", expected_version=goal.version, now=NOW,
        )
        claim = self.task_store.claim_next(
            "worker", now=NOW, principal_tools=TOOLS,
        )
        self.assertEqual(claim.task_id, execution.task.task_id)
        cancelling = self.coordinator.cancel(
            goal.goal_id, "alice", expected_version=execution.goal.version, now=NOW,
        )
        self.assertEqual(cancelling.goal.state, "cancelling")
        self.assertEqual(cancelling.task.state, "running")
        self.assertTrue(cancelling.task.cancel_requested)
        finished = self.task_store.finish_step(claim, {"done": True}, now=NOW)
        self.assertEqual(finished.state, "cancelled")
        reconciled = self.coordinator.reconcile(goal.goal_id, "alice", now=NOW)
        self.assertEqual(reconciled.goal.state, "cancelled")
        retried = self.coordinator.cancel(
            goal.goal_id, "alice", expected_version=execution.goal.version, now=NOW,
        )
        self.assertEqual(retried.goal.state, "cancelled")

    def test_goal_events_and_evidence_are_append_only(self):
        goal = self.planned_goal()
        execution = self.coordinator.prepare(
            goal.goal_id, "alice", expected_version=goal.version, now=NOW,
        )
        self.goal_store.record_evidence_for_principal(
            goal.goal_id, "alice", "test_digest", "f" * 64, 0, now=NOW,
        )
        connection = sqlite3.connect(self.goal_store.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE goal_events SET event_type='rewritten' WHERE goal_id=?",
                    (goal.goal_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM goal_evidence WHERE goal_id=?",
                    (goal.goal_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE goal_task_links SET task_id='replacement' WHERE goal_id=?",
                    (goal.goal_id,),
                )
        finally:
            connection.close()

    def test_link_and_evidence_are_owner_scoped_and_backup_safe(self):
        goal = self.planned_goal()
        execution = self.coordinator.prepare(
            goal.goal_id, "alice", expected_version=goal.version, now=NOW,
        )
        with self.assertRaises(GoalConflictError):
            self.goal_store.link_task_for_principal(
                goal.goal_id, "alice", "different-task",
                expected_version=execution.goal.version, now=NOW,
            )
        with self.assertRaises(GoalNotFoundError):
            self.goal_store.evidence_for_principal(goal.goal_id, "bob")
        self.goal_store.record_evidence_for_principal(
            goal.goal_id, "alice", "test_digest", "a" * 64, 0, now=NOW,
        )
        backup = os.path.join(self.temp.name, "coordinated-backup.sqlite3")
        self.goal_store.backup_to(backup)
        restored = SQLiteGoalStore(backup)
        record = restored.get_for_principal(goal.goal_id, "alice")
        self.assertEqual(record.task_id, execution.task.task_id)
        self.assertEqual(record.evidence[0]["reference"], "a" * 64)
        self.assertEqual(restored.integrity_check(), "ok")


if __name__ == "__main__":
    unittest.main()
