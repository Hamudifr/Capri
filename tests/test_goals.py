import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from capri_runtime.goals import (
    GoalConflictError,
    GoalIdempotencyConflict,
    GoalNotFoundError,
    GoalPlanProposal,
    GoalValidationError,
    SQLiteGoalStore,
    validate_goal_plan,
)

NOW = datetime(2026, 11, 25, 6, 0, tzinfo=timezone.utc)
PLAN = GoalPlanProposal((
    {"tool": "collect", "input": {"scope": "public"}, "max_attempts": 2},
    {"tool": "summarize", "input": {}, "max_attempts": 1},
), "Collect and summarize the requested information")


class SQLiteGoalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.path = os.path.join(self.temp.name, "goals.sqlite3")
        self.store = SQLiteGoalStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def create(self, owner="alice", **kwargs):
        return self.store.create_for_principal(
            owner, "Produce a verified report",
            acceptance_criteria=["Sources are cited", "Claims are verified"],
            now=NOW, **kwargs,
        )

    def test_goal_persists_and_reopens_with_owner_and_contract(self):
        goal = self.create(
            constraints={"max_tool_calls": 8, "no_paid_services": True},
            deadline="2026-11-26T12:00:00+01:00",
        )
        reopened = SQLiteGoalStore(self.path).get_for_principal(goal.goal_id, "alice")
        self.assertEqual(reopened, goal)
        self.assertEqual(reopened.state, "accepted")
        self.assertEqual(reopened.version, 1)
        self.assertEqual(reopened.constraints["max_tool_calls"], 8)
        self.assertEqual(reopened.deadline, "2026-11-26T11:00:00+00:00")

    def test_owner_isolation_and_immutable_owner_row(self):
        goal = self.create()
        with self.assertRaises(GoalNotFoundError):
            self.store.get_for_principal(goal.goal_id, "bob")
        connection = sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE goal_owners SET principal_id='bob' WHERE goal_id=?",
                    (goal.goal_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM goal_owners WHERE goal_id=?", (goal.goal_id,))
        finally:
            connection.close()

    def test_idempotency_is_principal_scoped_and_contract_bound(self):
        first = self.create(idempotency_key="request-1")
        again = self.create(idempotency_key="request-1")
        bob = self.create(owner="bob", idempotency_key="request-1")
        self.assertEqual(first.goal_id, again.goal_id)
        self.assertNotEqual(first.goal_id, bob.goal_id)
        with self.assertRaises(GoalIdempotencyConflict):
            self.store.create_for_principal(
                "alice", "Different outcome",
                acceptance_criteria=["Sources are cited"],
                idempotency_key="request-1", now=NOW,
            )

    def test_planner_proposal_is_data_only_and_allowlist_bound(self):
        calls = []
        proposal = GoalPlanProposal((
            {"tool": "collect", "input": {"url": "https://example.test"}, "max_attempts": 1},
        ))
        checked = validate_goal_plan(proposal, frozenset({"collect"}))
        self.assertEqual(checked[0]["tool"], "collect")
        self.assertEqual(calls, [])
        with self.assertRaises(GoalValidationError):
            validate_goal_plan(proposal, frozenset({"summarize"}))
        with self.assertRaises(GoalValidationError):
            validate_goal_plan(
                GoalPlanProposal(({"tool": "admin", "input": {"elevate": True}},)),
                frozenset({"collect"}),
            )
        with self.assertRaises(GoalValidationError):
            validate_goal_plan(
                GoalPlanProposal(({"tool": "collect", "input": {}, "shell": "rm -rf /"},)),
                frozenset({"collect"}),
            )

    def test_plan_persistence_uses_compare_and_swap_and_does_not_execute(self):
        executions = []
        goal = self.create()
        planned = self.store.save_plan_for_principal(
            goal.goal_id, "alice", PLAN, frozenset({"collect", "summarize"}),
            expected_version=1, now=NOW,
        )
        self.assertEqual(planned.state, "planned")
        self.assertEqual(planned.version, 2)
        self.assertEqual([step["tool"] for step in planned.plan], ["collect", "summarize"])
        self.assertEqual(executions, [])
        with self.assertRaises(GoalConflictError):
            self.store.save_plan_for_principal(
                goal.goal_id, "alice", PLAN, frozenset({"collect", "summarize"}),
                expected_version=1, now=NOW,
            )

    def test_lifecycle_transitions_are_versioned_and_terminal_states_stay_terminal(self):
        goal = self.create()
        planning = self.store.transition_for_principal(
            goal.goal_id, "alice", "planning", expected_version=1, now=NOW,
        )
        planned = self.store.save_plan_for_principal(
            goal.goal_id, "alice", PLAN, frozenset({"collect", "summarize"}),
            expected_version=planning.version, now=NOW,
        )
        running = self.store.transition_for_principal(
            goal.goal_id, "alice", "running", expected_version=planned.version, now=NOW,
        )
        succeeded = self.store.transition_for_principal(
            goal.goal_id, "alice", "succeeded", expected_version=running.version, now=NOW,
        )
        with self.assertRaises(GoalConflictError):
            self.store.transition_for_principal(
                goal.goal_id, "alice", "running", expected_version=succeeded.version, now=NOW,
            )
        with self.assertRaises(GoalConflictError):
            self.store.transition_for_principal(
                goal.goal_id, "alice", "failed", expected_version=running.version, now=NOW,
            )

    def test_invalid_contracts_and_naive_deadlines_fail_closed(self):
        with self.assertRaises(GoalValidationError):
            self.store.create_for_principal(
                "alice", " ",
                acceptance_criteria=["done"], now=NOW,
            )
        with self.assertRaises(GoalValidationError):
            self.store.create_for_principal(
                "alice", "outcome",
                acceptance_criteria=[], now=NOW,
            )
        with self.assertRaises(GoalValidationError):
            self.store.create_for_principal(
                "alice", "outcome",
                acceptance_criteria=["done"], deadline="2026-11-26T12:00:00",
                now=NOW,
            )
        with self.assertRaises(GoalValidationError):
            self.store.create_for_principal(
                "alice", "outcome",
                acceptance_criteria=["done"], constraints={"bad": object()},
                now=NOW,
            )

    def test_goal_events_and_private_backup_survive_restore(self):
        goal = self.create()
        planning = self.store.transition_for_principal(
            goal.goal_id, "alice", "planning", expected_version=1, now=NOW,
        )
        planned = self.store.save_plan_for_principal(
            goal.goal_id, "alice", PLAN, frozenset({"collect", "summarize"}),
            expected_version=planning.version, now=NOW,
        )
        events = self.store.events_for_principal(goal.goal_id, "alice")
        self.assertEqual([event["event_type"] for event in events], [
            "created", "transition", "plan_saved",
        ])
        backup = os.path.join(self.temp.name, "goal-backup.sqlite3")
        self.assertEqual(self.store.backup_to(backup), backup)
        if os.name == "posix":
            import stat
            self.assertEqual(stat.S_IMODE(os.stat(backup).st_mode), 0o600)
        restored = SQLiteGoalStore(backup)
        self.assertEqual(restored.integrity_check(), "ok")
        self.assertEqual(restored.get_for_principal(goal.goal_id, "alice"), planned)
        self.assertEqual(restored.events_for_principal(goal.goal_id, "alice"), events)
        with self.assertRaises(GoalValidationError):
            self.store.backup_to(backup)

    def test_goal_database_rejects_permissions_widened_after_open(self):
        goal = self.create()
        if os.name != "posix":
            self.skipTest("POSIX file permissions are unavailable")
        os.chmod(self.path, 0o644)
        with self.assertRaises(GoalValidationError):
            self.store.get_for_principal(goal.goal_id, "alice")

    def test_goal_database_rejects_symlink_path(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        target = os.path.join(self.temp.name, "target.sqlite3")
        SQLiteGoalStore(target)
        alias = os.path.join(self.temp.name, "alias.sqlite3")
        os.symlink(target, alias)
        with self.assertRaises(GoalValidationError):
            SQLiteGoalStore(alias)


if __name__ == "__main__":
    unittest.main()
