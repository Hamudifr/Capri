import hashlib
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from capri_runtime import (
    ApprovalChallenge,
    ExecutionContext,
    HmacApprovalAuthority,
    HostApprovalService,
    HostAuthorityError,
    SQLiteApprovalChallengeStore,
    SQLiteSecurityStore,
    ToolCallOutcome,
    ToolValidationError,
)


def digest(arguments):
    raw = json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class ApprovalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "security.sqlite3")
        self.now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
        self.security = SQLiteSecurityStore(self.path)
        self.challenge_store = SQLiteApprovalChallengeStore(self.security)
        self.signer = HmacApprovalAuthority(b"k" * 32, clock=lambda: self.now)
        self.service = HostApprovalService(
            self.challenge_store,
            self.signer,
            lambda credential: {"approver-token": "reviewer", "bad-token": None}.get(credential),
            lambda approver, challenge: approver == "reviewer" and challenge.principal_id == "alice",
            clock=lambda: self.now,
        )
        self.context = ExecutionContext("alice", frozenset({"records:delete"}))
        self.outcome = ToolCallOutcome(
            "call-1", "delete_record", "approval_required",
            error_code="approval_required", argument_digest=digest({"record_id": "r-1"}),
        )

    def tearDown(self):
        self.temp.cleanup()

    def create(self, operation_id="session-1:call-1"):
        return self.service.create_challenge(self.context, self.outcome, operation_id)

    def test_challenge_creation_is_idempotent_and_bound_to_operation(self):
        first = self.create()
        second = self.create()
        self.assertEqual(first.challenge_id, second.challenge_id)
        changed = ToolCallOutcome(
            "call-1", "delete_record", "approval_required",
            argument_digest=digest({"record_id": "r-2"}),
        )
        with self.assertRaises(ToolValidationError):
            self.service.create_challenge(self.context, changed, "session-1:call-1")

    def test_only_approval_required_outcomes_can_create_challenges(self):
        with self.assertRaises(ToolValidationError):
            self.service.create_challenge(
                self.context,
                ToolCallOutcome("call-1", "delete_record", "succeeded"),
                "session-1:call-2",
            )

    def test_unauthenticated_or_unauthorized_decisions_fail_closed(self):
        challenge = self.create()
        with self.assertRaises(HostAuthorityError):
            self.service.approve("bad-token", challenge.challenge_id)
        self.assertEqual(self.challenge_store.get(challenge.challenge_id, self.now).status, "pending")

    def test_approval_issues_exact_signed_grant_and_is_idempotent(self):
        challenge = self.create()
        approved = self.service.approve("approver-token", challenge.challenge_id)
        self.assertEqual(approved.status, "approved")
        self.assertEqual(approved.approver_id, "reviewer")
        self.assertTrue(self.signer.verify(approved.grant))
        self.assertEqual(approved.grant.principal_id, "alice")
        self.assertEqual(approved.grant.tool_name, "delete_record")
        self.assertEqual(approved.grant.argument_digest, self.outcome.argument_digest)
        repeated = self.service.approve("approver-token", challenge.challenge_id)
        self.assertEqual(repeated.grant, approved.grant)

    def test_grant_survives_store_reopen_and_lost_response_retry(self):
        challenge = self.create()
        approved = self.service.approve("approver-token", challenge.challenge_id)
        reopened = SQLiteApprovalChallengeStore(SQLiteSecurityStore(self.path))
        restarted_service = HostApprovalService(
            reopened, self.signer,
            lambda credential: "reviewer" if credential == "approver-token" else None,
            lambda approver, item: approver == "reviewer",
            clock=lambda: self.now,
        )
        recovered = restarted_service.approve("approver-token", challenge.challenge_id)
        self.assertEqual(recovered.grant, approved.grant)
        self.assertTrue(self.signer.verify(recovered.grant))

    def test_self_approval_is_denied_by_default(self):
        challenge = self.create()
        self_approver = HostApprovalService(
            self.challenge_store, self.signer,
            lambda credential: "alice" if credential == "self-token" else None,
            lambda approver, item: True,
            clock=lambda: self.now,
        )
        with self.assertRaises(HostAuthorityError):
            self_approver.approve("self-token", challenge.challenge_id)
        self.assertEqual(self.challenge_store.get(challenge.challenge_id, self.now).status, "pending")

    def test_rejection_is_terminal_and_never_mints_a_grant(self):
        challenge = self.create()
        rejected = self.service.reject("approver-token", challenge.challenge_id)
        self.assertEqual(rejected.status, "rejected")
        self.assertIsNone(rejected.grant)
        with self.assertRaises(ToolValidationError):
            self.service.approve("approver-token", challenge.challenge_id)

    def test_expired_challenge_cannot_be_approved(self):
        challenge = self.create()
        later = self.now + timedelta(seconds=301)
        with self.assertRaises(ToolValidationError):
            self.challenge_store.decide(
                challenge.challenge_id, "reviewer", "approve", later,
                lambda item: self.signer.issue(item.principal_id, item.tool_name, item.argument_digest),
            )
        self.assertEqual(self.challenge_store.get(challenge.challenge_id, later).status, "expired")

    def test_concurrent_duplicate_approvals_return_one_identical_grant(self):
        challenge = self.create()
        stores = [SQLiteApprovalChallengeStore(SQLiteSecurityStore(self.path)) for _ in range(4)]
        services = [
            HostApprovalService(
                store, self.signer,
                lambda credential: "reviewer" if credential == "approver-token" else None,
                lambda approver, item: approver == "reviewer",
                clock=lambda: self.now,
            )
            for store in stores
        ]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(
                lambda service: service.approve("approver-token", challenge.challenge_id),
                services,
            ))
        self.assertEqual({result.grant.grant_id for result in results}, {results[0].grant.grant_id})
        self.assertEqual(sum(result.status == "approved" for result in results), 4)

    def test_audit_contains_decision_metadata_not_credentials_or_arguments(self):
        challenge = self.create()
        self.service.approve("approver-token", challenge.challenge_id)
        events = self.security.events()
        self.assertEqual(events[-1].status, "approval_approved")
        serialized = repr(events)
        self.assertNotIn("approver-token", serialized)
        self.assertNotIn("record_id", serialized)
        self.assertNotIn("r-1", serialized)


if __name__ == "__main__":
    unittest.main()
