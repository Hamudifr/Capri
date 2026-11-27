import os
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from capri_core.strategy import StrategyObservation, evaluate_strategies
from capri_runtime.tasks import SQLiteTaskStore
from capri_runtime.strategy_store import (
    SQLiteStrategyStore,
    StrategyActivationRequest,
    StrategyAuthorizationError,
    StrategyConflictError,
    StrategyIntegrityError,
    StrategyNotFoundError,
    StrategyStoreError,
)


def make_observations(count=20):
    records = []
    for index in range(count):
        task_id = f"task-{index:03d}"
        common = {
            "task_id": task_id,
            "scenario": "research",
            "evidence_ref": f"test://evidence/{task_id}",
            "strategy_version": "1.0",
            "tool_calls": 5,
            "context_tokens": 1000,
            "estimated_cost_units": 100,
            "latency_ms": 2000,
        }
        records.append(StrategyObservation(
            strategy_id="baseline", outcome="verified_success", **common,
        ))
        records.append(StrategyObservation(
            strategy_id="candidate", outcome="verified_success",
            estimated_cost_units=90, **{k: v for k, v in common.items() if k != "estimated_cost_units"},
        ))
    return tuple(records)


class SQLiteStrategyStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.task_store = SQLiteTaskStore(os.path.join(self.temp.name, "tasks.sqlite3"))
        self.store = SQLiteStrategyStore(
            self.task_store,
            evidence_verifier=lambda context: True,
        )
        self.observations = make_observations()
        self.evaluation = evaluate_strategies("baseline", "candidate", self.observations)
        self.baseline = self.store.register_baseline_for_principal(
            "alice", "reasoning", "baseline", "1.0", {"mode": "standard"},
        )
        self.candidate = self.store.register_candidate_for_principal(
            "alice", "reasoning", "candidate", "1.0",
            {"mode": "efficient", "temperature": 0.1},
            self.evaluation,
            observations=self.observations,
            evidence_manifest_ref="test://manifests/cohort-001",
        )

    def tearDown(self):
        self.temp.cleanup()

    def request(
        self, *, principal="alice", strategy_id="baseline", version="1.0",
        evaluation_sha256=None, config_sha256=None, generation=0,
        action="activate",
    ):
        record = self.baseline if strategy_id == "baseline" else self.candidate
        return StrategyActivationRequest(
            principal_id=principal,
            strategy_class="reasoning",
            strategy_id=strategy_id,
            version=version,
            evaluation_sha256=evaluation_sha256,
            config_sha256=config_sha256 or record.config_sha256,
            expected_generation=generation,
            action=action,
        )

    def activate_baseline(self):
        return self.store.activate_for_principal(
            "alice", self.request(),
        )

    def test_candidate_registration_is_not_activation_and_activation_is_reversible(self):
        self.assertIsNone(self.store.get_active_for_principal("alice", "reasoning"))
        baseline = self.activate_baseline()
        self.assertEqual((baseline.strategy_id, baseline.generation), ("baseline", 1))

        candidate = self.store.activate_for_principal(
            "alice",
            self.request(
                strategy_id="candidate",
                evaluation_sha256=self.evaluation.cohort_sha256,
                generation=1,
            ),
        )
        self.assertEqual((candidate.strategy_id, candidate.generation), ("candidate", 2))
        self.assertEqual(candidate.config, {"mode": "efficient", "temperature": 0.1})

        rollback = self.store.rollback_for_principal(
            "alice", self.request(strategy_id="baseline", generation=2, action="rollback"),
        )
        self.assertEqual((rollback.strategy_id, rollback.generation), ("baseline", 3))
        events = self.store.events_for_principal("alice", "reasoning")
        self.assertEqual([event.action for event in events], ["activate", "activate", "rollback"])
        self.assertEqual([event.generation for event in events], [1, 2, 3])
        self.assertEqual(events[0].previous_hash, "")
        self.assertEqual(events[1].previous_hash, events[0].event_hash)
        self.assertEqual(events[2].previous_hash, events[1].event_hash)

    def test_wrong_principal_or_action_is_rejected(self):
        cases = (
            (self.request(principal="bob"), "alice", "principal"),
            (self.request(action="rollback"), "alice", "action"),
        )
        for request, principal, label in cases:
            with self.subTest(label=label), self.assertRaises(StrategyAuthorizationError):
                self.store.activate_for_principal(principal, request)

    def test_config_and_evaluation_fingerprints_are_bound_to_request(self):
        wrong_config = self.request(config_sha256="0" * 64)
        wrong_evaluation = self.request(
            strategy_id="candidate",
            evaluation_sha256="0" * 64,
            generation=0,
        )
        for grant in (wrong_config, wrong_evaluation):
            with self.subTest(grant=grant), self.assertRaises(StrategyAuthorizationError):
                self.store.activate_for_principal("alice", grant)

    def test_stale_generation_is_rejected(self):
        request = self.request()
        self.store.activate_for_principal("alice", request)
        with self.assertRaises(StrategyConflictError):
            self.store.activate_for_principal("alice", request)

    def test_rollback_target_must_have_been_active_before(self):
        self.activate_baseline()
        grant = self.request(
            strategy_id="candidate",
            evaluation_sha256=self.evaluation.cohort_sha256,
            generation=1,
            action="rollback",
        )
        with self.assertRaises(StrategyConflictError):
            self.store.rollback_for_principal("alice", grant)

    def test_registry_rejects_candidate_version_not_used_in_evaluation(self):
        observations = make_observations()
        changed = tuple(
            replace(record, strategy_version="2.0")
            if record.strategy_id == "candidate" else record
            for record in observations
        )
        evaluation = evaluate_strategies("baseline", "candidate", changed)
        with self.assertRaises(StrategyStoreError):
            self.store.register_candidate_for_principal(
                "alice", "reasoning", "candidate", "1.0", {"mode": "other"},
                evaluation, observations=changed,
                evidence_manifest_ref="test://manifests/wrong-version",
            )

    def test_candidate_evaluation_is_recomputed_from_exact_observations(self):
        forged = replace(self.evaluation, eligible_for_manual_review=False)
        with self.assertRaises(StrategyStoreError):
            self.store.register_candidate_for_principal(
                "alice", "reasoning", "candidate", "2.0", {"mode": "bad"},
                forged, observations=self.observations,
                evidence_manifest_ref="test://manifests/forged",
            )
        changed = list(self.observations)
        changed[0] = replace(changed[0], evidence_ref="test://different")
        with self.assertRaises(StrategyStoreError):
            self.store.register_candidate_for_principal(
                "alice", "reasoning", "candidate", "2.0", {"mode": "bad"},
                self.evaluation, observations=tuple(changed),
                evidence_manifest_ref="test://manifests/changed",
            )

    def test_baseline_must_be_registered_before_candidate(self):
        store = SQLiteStrategyStore(
            self.task_store,
            evidence_verifier=lambda context: True,
        )
        with self.assertRaises(StrategyNotFoundError):
            store.register_candidate_for_principal(
                "bob", "reasoning", "candidate", "1.0", {},
                self.evaluation, observations=self.observations,
                evidence_manifest_ref="test://manifest",
            )

    def test_principals_are_isolated(self):
        self.activate_baseline()
        self.assertIsNone(self.store.get_active_for_principal("bob", "reasoning"))
        with self.assertRaises(StrategyAuthorizationError):
            self.store.activate_for_principal("bob", self.request(principal="alice", generation=1))
        self.assertEqual(
            len(self.store.events_for_principal("bob", "reasoning")), 0,
        )

    def test_data_only_config_rejects_authority_secrets_code_and_bad_values(self):
        invalid = (
            {"permissions": ["admin"]},
            {"nested": {"allowed_tools": ["shell"]}},
            {"api_key": "secret"},
            {"script": "print(1)"},
            {"value": float("nan")},
            {"value": object()},
            {"nested": {"a": {"b": {"c": {"d": {"e": 1}}}}}},
        )
        for config in invalid:
            with self.subTest(config=repr(config)), self.assertRaises(StrategyStoreError):
                self.store.register_baseline_for_principal(
                    "bob", "reasoning", "baseline", "1.0", config,
                )

    def test_strategy_versions_and_evaluations_are_append_only(self):
        connection = self.task_store._connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE strategy_versions SET config_json='{}' "
                    "WHERE principal_id='alice' AND strategy_id='baseline'"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE strategy_evaluations SET summary_json='{}' "
                    "WHERE principal_id='alice'"
                )
        finally:
            connection.close()

    def test_registry_rejects_unversioned_and_unmatched_baseline_versions(self):
        with self.assertRaises(StrategyStoreError):
            self.store.register_baseline_for_principal(
                "bob", "reasoning", "baseline", "unversioned", {},
            )
        self.store.register_baseline_for_principal(
            "bob", "reasoning", "baseline", "2.0", {},
        )
        with self.assertRaises(StrategyNotFoundError):
            self.store.register_candidate_for_principal(
                "bob", "reasoning", "candidate", "1.0", {"mode": "candidate"},
                self.evaluation, observations=self.observations,
                evidence_manifest_ref="test://manifests/wrong-baseline-version",
            )

    def test_baseline_version_is_immutable(self):
        with self.assertRaises(StrategyConflictError):
            self.store.register_baseline_for_principal(
                "alice", "reasoning", "baseline", "1.0", {"mode": "changed"},
            )

    def test_event_rows_are_append_only_and_projection_tampering_is_detected(self):
        self.activate_baseline()
        connection = self.task_store._connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE strategy_events SET approver_id='forged' WHERE generation=1"
                )
            connection.execute(
                "UPDATE strategy_active SET strategy_id='candidate',version='1.0' "
                "WHERE principal_id='alice' AND strategy_class='reasoning'"
            )
        finally:
            connection.close()
        with self.assertRaises(StrategyIntegrityError):
            self.store.get_active_for_principal("alice", "reasoning")

    def test_store_requires_the_exact_task_store_type(self):
        with self.assertRaises(StrategyStoreError):
            SQLiteStrategyStore(object())


    def test_candidate_admission_requires_a_trusted_evidence_verifier(self):
        store = SQLiteStrategyStore(self.task_store)
        store.register_baseline_for_principal(
            "carol", "reasoning", "baseline", "1.0", {"mode": "standard"},
        )
        with self.assertRaisesRegex(StrategyAuthorizationError, "evidence verifier"):
            store.register_candidate_for_principal(
                "carol", "reasoning", "candidate", "1.0", {"mode": "candidate"},
                self.evaluation, observations=self.observations,
                evidence_manifest_ref="test://manifests/cohort-002",
            )
        connection = self.task_store._connect()
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM strategy_evaluations WHERE principal_id='carol'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 0)

    def test_candidate_evidence_verifier_fails_closed(self):
        verifiers = (
            lambda context: False,
            lambda context: 1,
            lambda context: None,
            lambda context: (_ for _ in ()).throw(RuntimeError("unavailable")),
        )
        for index, verifier in enumerate(verifiers):
            principal = f"carol{index}"
            store = SQLiteStrategyStore(self.task_store, evidence_verifier=verifier)
            store.register_baseline_for_principal(
                principal, "reasoning", "baseline", "1.0", {"mode": "standard"},
            )
            with self.subTest(verifier=index), self.assertRaises(StrategyAuthorizationError):
                store.register_candidate_for_principal(
                    principal, "reasoning", "candidate", "1.0", {"mode": "candidate"},
                    self.evaluation, observations=self.observations,
                    evidence_manifest_ref=f"test://manifests/{principal}",
                )
            connection = self.task_store._connect()
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM strategy_evaluations WHERE principal_id=?",
                    (principal,),
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 0)

    def test_candidate_evidence_verifier_receives_exact_immutable_binding(self):
        captured = []
        store = SQLiteStrategyStore(
            self.task_store,
            evidence_verifier=lambda context: captured.append(context) is None,
        )
        store.register_baseline_for_principal(
            "dana", "reasoning", "baseline", "1.0", {"mode": "standard"},
        )
        store.register_candidate_for_principal(
            "dana", "reasoning", "candidate", "1.0", {"mode": "candidate"},
            self.evaluation, observations=self.observations,
            evidence_manifest_ref="test://manifests/dana-cohort",
        )
        self.assertEqual(len(captured), 1)
        context = captured[0]
        self.assertEqual(context.principal_id, "dana")
        self.assertEqual(context.strategy_class, "reasoning")
        self.assertEqual(context.baseline_id, "baseline")
        self.assertEqual(context.baseline_version, "1.0")
        self.assertEqual(context.candidate_id, "candidate")
        self.assertEqual(context.candidate_version, "1.0")
        self.assertEqual(context.cohort_sha256, self.evaluation.cohort_sha256)
        self.assertEqual(context.cohort_schema, self.evaluation.cohort_schema)
        self.assertEqual(context.evidence_manifest_ref, "test://manifests/dana-cohort")
        self.assertEqual(context.matched_pairs, self.evaluation.matched_pairs)
        connection = self.task_store._connect()
        try:
            verified_row = connection.execute(
                "SELECT evidence_verified FROM strategy_evaluations WHERE principal_id='dana'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(verified_row, (1,))
        with self.assertRaises((AttributeError, TypeError)):
            context.cohort_sha256 = "0" * 64


    def test_legacy_strategy_evaluations_migrate_as_unverified(self):
        legacy_path = os.path.join(self.temp.name, "legacy-strategy.sqlite3")
        legacy_tasks = SQLiteTaskStore(legacy_path)
        connection = legacy_tasks._connect()
        try:
            connection.execute("""CREATE TABLE strategy_evaluations (
                evaluation_id TEXT PRIMARY KEY,
                principal_id TEXT NOT NULL,
                strategy_class TEXT NOT NULL,
                baseline_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                cohort_sha256 TEXT NOT NULL,
                matched_pairs INTEGER NOT NULL CHECK(matched_pairs >= 20),
                eligible INTEGER NOT NULL CHECK(eligible=1),
                summary_json TEXT NOT NULL,
                evidence_manifest_ref TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(principal_id, strategy_class, cohort_sha256)
            )""")
            connection.execute(
                """INSERT INTO strategy_evaluations
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                ("legacy-eval", "legacy", "reasoning", "baseline", "candidate",
                 "a" * 64, 20, 1, "{}", "test://legacy", datetime.now(timezone.utc).isoformat()),
            )
        finally:
            connection.close()
        SQLiteStrategyStore(legacy_tasks)
        connection = legacy_tasks._connect()
        try:
            row = connection.execute(
                "SELECT evidence_verified FROM strategy_evaluations WHERE evaluation_id='legacy-eval'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row, (0,))

    def test_legacy_unverified_candidate_cannot_be_activated(self):
        store = SQLiteStrategyStore(self.task_store)
        store.register_baseline_for_principal(
            "legacy", "reasoning", "baseline", "1.0", {"mode": "standard"},
        )
        import hashlib
        import json
        config = {"mode": "candidate"}
        config_json = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        config_hash = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
        summary_json = json.dumps(
            self.evaluation.to_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
        created = datetime.now(timezone.utc).isoformat()
        connection = self.task_store._connect()
        try:
            connection.execute(
                """INSERT INTO strategy_evaluations
                (evaluation_id,principal_id,strategy_class,baseline_id,candidate_id,
                 cohort_sha256,matched_pairs,eligible,evidence_verified,summary_json,
                 evidence_manifest_ref,created_at)
                VALUES(?,?,?,?,?,?,?,1,0,?,?,?)""",
                ("legacy-eval-activation", "legacy", "reasoning", "baseline", "candidate",
                 self.evaluation.cohort_sha256, self.evaluation.matched_pairs,
                 summary_json, "test://legacy/manifest", created),
            )
            connection.execute(
                """INSERT INTO strategy_versions
                (principal_id,strategy_class,strategy_id,version,config_json,
                 config_sha256,is_baseline,evaluation_id,created_at)
                VALUES(?,?,?,?,?,?,0,?,?)""",
                ("legacy", "reasoning", "candidate", "1.0", config_json,
                 config_hash, "legacy-eval-activation", created),
            )
        finally:
            connection.close()
        request = StrategyActivationRequest(
            principal_id="legacy",
            strategy_class="reasoning",
            strategy_id="candidate",
            version="1.0",
            evaluation_sha256=self.evaluation.cohort_sha256,
            config_sha256=config_hash,
            expected_generation=0,
            action="activate",
        )
        with self.assertRaisesRegex(StrategyAuthorizationError, "evidence"):
            store.activate_for_principal("legacy", request)
        self.assertEqual(store.events_for_principal("legacy", "reasoning"), ())


    def test_legacy_active_unverified_candidate_is_not_served_and_baseline_can_be_restored(self):
        import hashlib
        import json
        store = SQLiteStrategyStore(self.task_store)
        baseline = store.register_baseline_for_principal(
            "legacy-active", "reasoning", "baseline", "1.0", {"mode": "standard"},
        )
        config = {"mode": "candidate"}
        config_json = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        config_hash = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
        summary_json = json.dumps(
            self.evaluation.to_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
        created = datetime.now(timezone.utc).isoformat()
        event_id = "legacy-active-event"
        evaluation_id = "legacy-active-evaluation"
        payload = {
            "event_id": event_id,
            "principal_id": "legacy-active",
            "strategy_class": "reasoning",
            "generation": 1,
            "action": "activate",
            "from_strategy_id": None,
            "from_version": None,
            "to_strategy_id": "candidate",
            "to_version": "1.0",
            "to_config_sha256": config_hash,
            "evaluation_id": evaluation_id,
            "approval_id": "legacy-active-approval",
            "approver_id": "owner",
            "created_at": created,
            "previous_hash": "",
        }
        event_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        connection = self.task_store._connect()
        try:
            connection.execute(
                """INSERT INTO strategy_evaluations
                (evaluation_id,principal_id,strategy_class,baseline_id,candidate_id,
                 cohort_sha256,matched_pairs,eligible,evidence_verified,summary_json,
                 evidence_manifest_ref,created_at)
                VALUES(?,?,?,?,?,?,?,1,0,?,?,?)""",
                (evaluation_id, "legacy-active", "reasoning", "baseline", "candidate",
                 self.evaluation.cohort_sha256, self.evaluation.matched_pairs,
                 summary_json, "test://legacy-active/manifest", created),
            )
            connection.execute(
                """INSERT INTO strategy_versions
                (principal_id,strategy_class,strategy_id,version,config_json,
                 config_sha256,is_baseline,evaluation_id,created_at)
                VALUES(?,?,?,?,?,?,0,?,?)""",
                ("legacy-active", "reasoning", "candidate", "1.0", config_json,
                 config_hash, evaluation_id, created),
            )
            connection.execute(
                """INSERT INTO strategy_events
                (event_id,principal_id,strategy_class,generation,action,
                 from_strategy_id,from_version,to_strategy_id,to_version,
                 to_config_sha256,evaluation_id,approval_id,approver_id,
                 created_at,previous_hash,event_hash)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, "legacy-active", "reasoning", 1, "activate",
                 None, None, "candidate", "1.0", config_hash, evaluation_id,
                 "legacy-active-approval", "owner", created, "", event_hash),
            )
            connection.execute(
                """INSERT INTO strategy_active
                (principal_id,strategy_class,strategy_id,version,generation,event_id)
                VALUES(?,?,?,?,?,?)""",
                ("legacy-active", "reasoning", "candidate", "1.0", 1, event_id),
            )
        finally:
            connection.close()
        with self.assertRaisesRegex(StrategyAuthorizationError, "evidence is unverified"):
            store.get_active_for_principal("legacy-active", "reasoning")
        restore = StrategyActivationRequest(
            principal_id="legacy-active",
            strategy_class="reasoning",
            strategy_id="baseline",
            version="1.0",
            evaluation_sha256=None,
            config_sha256=baseline.config_sha256,
            expected_generation=1,
            action="activate",
        )
        store.activate_for_principal("legacy-active", restore)
        active = store.get_active_for_principal("legacy-active", "reasoning")
        self.assertIsNotNone(active)
        self.assertEqual(active.strategy_id, "baseline")
        self.assertEqual(active.version, "1.0")


if __name__ == "__main__":
    unittest.main()
