import json
import unittest

from capri_runtime import (
    GoalRecord,
    GoalValidationError,
    TaskRecord,
    build_goal_report,
)

NOW = "2026-11-25T07:00:00+00:00"
PLAN = (
    {"tool": "collect", "input": {"scope": "public"}},
    {"tool": "summarize", "input": {}},
)


def make_goal(*, state="accepted", task_id=None, plan=(), evidence=()):
    return GoalRecord(
        "goal-1", "alice", "Produce a verified report",
        {"private_constraint": "do not expose"}, None,
        ("Sources are checked", "Claims are supported"),
        state, 2, NOW, NOW, tuple(plan), task_id, tuple(evidence),
    )


def make_task(*, state="queued", task_id="task-1", result=(), cancel_requested=False):
    return TaskRecord(
        task_id, None, state, NOW, NOW, len(result), 0, NOW,
        cancel_requested, tuple(result), None,
    )


def evidence(kind, reference="a" * 64, step_index=-1):
    return {
        "evidence_type": kind,
        "reference": reference,
        "step_index": step_index,
        "created_at": NOW,
    }


class GoalReportTests(unittest.TestCase):
    def test_unstarted_goal_is_reported_without_a_task(self):
        report = build_goal_report(make_goal())
        self.assertEqual(report.completion_status, "not_started")
        self.assertEqual(report.owner_acceptance_status, "not_recorded")
        self.assertIsNone(report.task_available)
        self.assertFalse(report.uncertain)
        json.dumps(report.as_dict())

    def test_active_partial_report_never_exposes_raw_task_or_plan_data(self):
        secret_result = {"private": "raw task result"}
        secret_input = {"credential": "plan input secret"}
        plan = (
            {"tool": "collect", "input": secret_input},
            {"tool": "summarize", "input": {}},
        )
        report = build_goal_report(
            make_goal(state="running", task_id="task-1", plan=plan),
            make_task(state="running", result=(secret_result,)),
        )
        encoded = json.dumps(report.as_dict())
        self.assertEqual(report.completion_status, "in_progress")
        self.assertTrue(report.partial)
        self.assertEqual((report.steps_completed, report.steps_total), (1, 2))
        self.assertNotIn("raw task result", encoded)
        self.assertNotIn("plan input secret", encoded)
        self.assertNotIn("private_constraint", encoded)

    def test_task_completion_waits_for_reconciliation_and_owner_acceptance(self):
        completed_task = make_task(state="succeeded", result=({"ok": True}, {"ok": True}))
        running_goal = make_goal(state="running", task_id="task-1", plan=PLAN)
        pending = build_goal_report(running_goal, completed_task)
        self.assertEqual(pending.completion_status, "reconciliation_pending")
        self.assertEqual(pending.owner_acceptance_status, "not_recorded")

        awaiting_goal = make_goal(
            state="awaiting_verification", task_id="task-1", plan=PLAN,
            evidence=(evidence("task_step_result_sha256", step_index=0),),
        )
        awaiting = build_goal_report(awaiting_goal, completed_task)
        self.assertEqual(awaiting.completion_status, "awaiting_owner_verification")
        self.assertEqual(awaiting.owner_acceptance_status, "pending")

        accepted_after_evidence = make_goal(
            state="awaiting_verification", task_id="task-1", plan=PLAN,
            evidence=(
                evidence("task_step_result_sha256", step_index=0),
                evidence("acceptance_accepted"),
            ),
        )
        transition_pending = build_goal_report(accepted_after_evidence, completed_task)
        self.assertEqual(transition_pending.completion_status, "acceptance_transition_pending")
        self.assertEqual(transition_pending.owner_acceptance_status, "accepted_pending_transition")

        accepted = build_goal_report(
            make_goal(
                state="succeeded", task_id="task-1", plan=PLAN,
                evidence=(
                    evidence("task_step_result_sha256", step_index=0),
                    evidence("acceptance_accepted"),
                ),
            ),
            completed_task,
        )
        self.assertEqual(accepted.completion_status, "completed")
        self.assertEqual(accepted.owner_acceptance_status, "accepted")

    def test_partial_failure_and_rejection_are_distinguished(self):
        failed = build_goal_report(
            make_goal(state="failed", task_id="task-1", plan=PLAN),
            make_task(state="failed", result=({"completed": True},)),
        )
        self.assertEqual(failed.completion_status, "failed")
        self.assertTrue(failed.partial)
        self.assertEqual(failed.owner_acceptance_status, "not_recorded")

        rejected = build_goal_report(
            make_goal(
                state="failed", task_id="task-1", plan=PLAN,
                evidence=(evidence("acceptance_rejected"),),
            ),
            make_task(state="succeeded", result=({"done": True}, {"done": True})),
        )
        self.assertEqual(rejected.completion_status, "failed")
        self.assertEqual(rejected.owner_acceptance_status, "rejected")

    def test_uncertain_and_missing_linked_task_never_appear_complete(self):
        uncertain = build_goal_report(
            make_goal(state="reconciliation_required", task_id="task-1", plan=PLAN),
            make_task(state="reconciliation_required", result=({"prior": True},)),
        )
        self.assertTrue(uncertain.uncertain)
        self.assertEqual(uncertain.completion_status, "uncertain")
        self.assertEqual(uncertain.uncertainty_code, "task_outcome_uncertain")
        self.assertTrue(uncertain.partial)

        missing = build_goal_report(
            make_goal(state="running", task_id="task-1", plan=PLAN),
        )
        self.assertTrue(missing.uncertain)
        self.assertEqual(missing.uncertainty_code, "linked_task_unavailable")
        self.assertFalse(missing.task_available)

    def test_cancelled_goal_and_cancel_request_are_visible(self):
        cancelled = build_goal_report(
            make_goal(state="cancelled", task_id="task-1", plan=PLAN),
            make_task(state="cancelled", result=({"done": True},)),
        )
        self.assertEqual(cancelled.completion_status, "cancelled")
        self.assertTrue(cancelled.partial)

        cancelling = build_goal_report(
            make_goal(state="cancelling", task_id="task-1", plan=PLAN),
            make_task(state="running", result=(), cancel_requested=True),
        )
        self.assertEqual(cancelling.completion_status, "cancellation_pending")
        self.assertTrue(cancelling.cancellation_requested)

    def test_inconsistent_task_binding_or_progress_fails_closed(self):
        with self.assertRaises(GoalValidationError):
            build_goal_report(
                make_goal(state="running", task_id="task-1", plan=PLAN),
                make_task(task_id="other-task"),
            )

        mismatch = build_goal_report(
            make_goal(state="running", task_id="task-1", plan=PLAN[:1]),
            make_task(state="running", result=({"one": 1}, {"two": 2})),
        )
        self.assertTrue(mismatch.uncertain)
        self.assertEqual(mismatch.uncertainty_code, "task_progress_mismatch")

    def test_evidence_is_bounded_and_latest_acceptance_decision_is_retained(self):
        later_rows = tuple(
            evidence("followup_note", f"{index:064x}")
            for index in range(70)
        )
        cases = (
            ("succeeded", "acceptance_accepted", "accepted"),
            ("failed", "acceptance_rejected", "rejected"),
        )
        for state, decision, expected_status in cases:
            with self.subTest(decision=decision):
                rows = (evidence(decision, "f" * 64),) + later_rows
                report = build_goal_report(make_goal(state=state, evidence=rows))
                self.assertTrue(report.evidence_truncated)
                self.assertEqual(len(report.evidence), 64)
                self.assertEqual(report.owner_acceptance_status, expected_status)
                self.assertEqual(report.evidence[0].evidence_type, decision)
                self.assertEqual(report.evidence[0].reference, "f" * 64)
                self.assertEqual(report.evidence[1].reference, f"{7:064x}")
                self.assertEqual(report.evidence[-1].reference, f"{69:064x}")


if __name__ == "__main__":
    unittest.main()
