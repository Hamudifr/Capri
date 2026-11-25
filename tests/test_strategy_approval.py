import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from capri_runtime.strategy_approval import (
    HostStrategyApprovalAuthority,
    StrategyApprovalIdentity,
    StrategyApprovalRequest,
)
from capri_runtime.strategy_store import (
    SQLiteStrategyStore,
    StrategyAuthorizationError,
)
from capri_runtime.tasks import SQLiteTaskStore
from capri_runtime.tools import HmacApprovalKeyRing


class HostStrategyApprovalAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
        self.keyring = HmacApprovalKeyRing(
            {"k1": b"x" * 32, "k2": b"y" * 32}, active_key_id="k1",
        )
        self.identity = StrategyApprovalIdentity("alice", "owner-1")
        self.authorized = True
        self.authority = HostStrategyApprovalAuthority(
            self.keyring,
            authenticate_approver=lambda credential: self.identity if credential == "valid" else None,
            authorize_approver=lambda identity, request: self.authorized,
            clock=lambda: self.now,
            max_ttl_seconds=300,
        )
        self.request = StrategyApprovalRequest(
            principal_id="alice",
            strategy_class="reasoning",
            strategy_id="candidate",
            version="2.0",
            evaluation_sha256="a" * 64,
            config_sha256="b" * 64,
            expected_generation=3,
            action="activate",
        )

    def test_issue_and_verify_exact_grant(self):
        grant = self.authority.issue_grant("valid", self.request, ttl_seconds=120)
        self.assertTrue(self.authority.verify(grant))
        self.assertEqual(grant.principal_id, "alice")
        self.assertEqual(grant.approver_id, "owner-1")
        self.assertEqual(grant.signature.split(":", 1)[0], "k1")

    def test_every_bound_field_is_authenticated(self):
        grant = self.authority.issue_grant("valid", self.request)
        changes = {
            "principal_id": "mallory",
            "strategy_class": "formatting",
            "strategy_id": "other",
            "version": "9.0",
            "evaluation_sha256": "c" * 64,
            "config_sha256": "d" * 64,
            "expected_generation": 4,
            "action": "rollback",
            "issued_at": (self.now - timedelta(seconds=1)).isoformat(),
            "expires_at": (self.now + timedelta(seconds=400)).isoformat(),
            "approver_id": "other-owner",
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                self.assertFalse(self.authority.verify(replace(grant, **{field: value})))

    def test_unhashable_action_fails_with_typed_validation_error(self):
        malformed = replace(self.request, action=[])
        with self.assertRaises(StrategyAuthorizationError):
            self.authority.issue_grant("valid", malformed)

    def test_invalid_credentials_fail_closed(self):
        with self.assertRaises(StrategyAuthorizationError):
            self.authority.issue_grant("invalid", self.request)

    def test_cross_principal_grant_is_denied(self):
        request = replace(self.request, principal_id="bob")
        with self.assertRaises(StrategyAuthorizationError):
            self.authority.issue_grant("valid", request)

    def test_policy_must_return_exact_true(self):
        self.authorized = 1
        with self.assertRaises(StrategyAuthorizationError):
            self.authority.issue_grant("valid", self.request)

    def test_verifier_enforces_its_own_maximum_ttl(self):
        wider = HostStrategyApprovalAuthority(
            self.keyring,
            authenticate_approver=lambda credential: self.identity,
            authorize_approver=lambda identity, request: True,
            clock=lambda: self.now,
            max_ttl_seconds=900,
        )
        grant = wider.issue_grant("valid", self.request, ttl_seconds=600)
        self.assertFalse(self.authority.verify(grant))

    def test_ttl_is_bounded(self):
        with self.assertRaises(StrategyAuthorizationError):
            self.authority.issue_grant("valid", self.request, ttl_seconds=301)

    def test_store_contract_validation_precedes_signing(self):
        malformed = replace(self.request, strategy_class="not a valid identifier")
        with self.assertRaises(StrategyAuthorizationError):
            self.authority.issue_grant("valid", malformed)

    def test_clock_failure_fails_closed(self):
        authority = HostStrategyApprovalAuthority(
            self.keyring,
            authenticate_approver=lambda credential: self.identity,
            authorize_approver=lambda identity, request: True,
            clock=lambda: (_ for _ in ()).throw(RuntimeError("clock unavailable")),
        )
        with self.assertRaisesRegex(StrategyAuthorizationError, "clock is unavailable"):
            authority.issue_grant("valid", self.request)

    def test_key_rotation_keeps_old_grant_verifiable(self):
        grant = self.authority.issue_grant("valid", self.request)
        rotated = HmacApprovalKeyRing(
            {"k1": b"x" * 32, "k2": b"y" * 32}, active_key_id="k2",
        )
        authority = HostStrategyApprovalAuthority(
            rotated,
            authenticate_approver=lambda credential: self.identity if credential == "valid" else None,
            authorize_approver=lambda identity, request: True,
            clock=lambda: self.now,
        )
        self.assertTrue(authority.verify(grant))
        newer = authority.issue_grant("valid", self.request)
        self.assertEqual(newer.signature.split(":", 1)[0], "k2")
        self.assertTrue(authority.verify(newer))

    def test_oversized_or_malformed_grants_fail_closed(self):
        grant = self.authority.issue_grant("valid", self.request)
        self.assertFalse(self.authority.verify(replace(grant, signature="x" * 2049)))
        self.assertFalse(self.authority.verify(replace(grant, action=[])))

    def test_tampered_signature_is_rejected(self):
        grant = self.authority.issue_grant("valid", self.request)
        self.assertFalse(self.authority.verify(replace(grant, signature="k1:" + "0" * 64)))

    def test_grant_is_accepted_by_strategy_store(self):
        with tempfile.TemporaryDirectory() as directory:
            task_store = SQLiteTaskStore(f"{directory}/tasks.sqlite3")
            store = SQLiteStrategyStore(
                task_store, approval_verifier=self.authority.verify,
                evidence_verifier=lambda context: True,
                clock=lambda: self.now,
            )
            baseline = store.register_baseline_for_principal(
                "alice", "reasoning", "baseline", "1.0", {"mode": "standard"},
            )
            request = StrategyApprovalRequest(
                principal_id="alice",
                strategy_class="reasoning",
                strategy_id="baseline",
                version="1.0",
                evaluation_sha256=None,
                config_sha256=baseline.config_sha256,
                expected_generation=0,
                action="activate",
            )
            grant = self.authority.issue_grant("valid", request)
            active = store.activate_for_principal("alice", grant)
            self.assertEqual(active.strategy_id, "baseline")
            self.assertEqual(active.config_sha256, baseline.config_sha256)


if __name__ == "__main__":
    unittest.main()
