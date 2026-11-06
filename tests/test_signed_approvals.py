import hashlib
import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from capri_runtime.tools import (
    ApprovalGrant,
    ExecutionContext,
    HmacApprovalAuthority,
    InMemoryAuditSink,
    ToolExecutor,
    ToolRegistry,
    ToolSpec,
    ToolValidationError,
    ApprovalRequiredError,
)


SCHEMA = {"type": "object", "properties": {"record_id": {"type": "string", "minLength": 1, "maxLength": 64}}, "required": ["record_id"], "additionalProperties": False}


def argument_digest(arguments):
    encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SignedApprovalTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
        self.authority = HmacApprovalAuthority(b"k" * 32, clock=lambda: self.now)
        self.calls = []
        registry = ToolRegistry()
        registry.register(
            ToolSpec("delete_record", "records:delete", SCHEMA, requires_approval=True),
            lambda arguments: self.calls.append(arguments) or {"deleted": True},
        )
        self.executor = ToolExecutor(
            registry,
            InMemoryAuditSink(),
            clock=lambda: self.now,
            approval_verifier=self.authority.verify,
            require_signed_approvals=True,
        )
        self.arguments = {"record_id": "record-123"}

    def context_with(self, grant):
        return ExecutionContext("alice", frozenset({"records:delete"}), (grant,))

    def test_signed_grant_is_bound_and_consumed_once(self):
        grant = self.authority.issue(
            "alice", "delete_record", argument_digest(self.arguments), ttl_seconds=120
        )
        self.assertTrue(self.authority.verify(grant))
        self.assertEqual(self.executor.execute("delete_record", self.arguments, self.context_with(grant)), {"deleted": True})
        with self.assertRaises(ApprovalRequiredError):
            self.executor.execute("delete_record", self.arguments, self.context_with(grant))
        self.assertEqual(self.calls, [self.arguments])

    def test_tampering_principal_tool_digest_or_expiry_invalidates_signature(self):
        grant = self.authority.issue(
            "alice", "delete_record", argument_digest(self.arguments), ttl_seconds=120
        )
        for tampered in (
            replace(grant, principal_id="bob"),
            replace(grant, tool_name="other_tool"),
            replace(grant, argument_digest="f" * 64),
            replace(grant, expires_at="2026-11-06T13:00:00+00:00"),
        ):
            with self.subTest(tampered=tampered):
                self.assertFalse(self.authority.verify(tampered))
                with self.assertRaises(ApprovalRequiredError):
                    self.executor.execute("delete_record", self.arguments, self.context_with(tampered))
        self.assertEqual(self.calls, [])

    def test_unsigned_legacy_grant_is_rejected_when_signed_mode_is_required(self):
        grant = ApprovalGrant(
            "legacy-grant", "alice", "delete_record",
            argument_digest(self.arguments), "2026-11-06T13:00:00+00:00",
        )
        with self.assertRaises(ApprovalRequiredError):
            self.executor.execute("delete_record", self.arguments, self.context_with(grant))
        self.assertEqual(self.calls, [])

    def test_signing_key_and_ttl_are_bounded(self):
        with self.assertRaises(ToolValidationError):
            HmacApprovalAuthority(b"short")
        with self.assertRaises(ToolValidationError):
            self.authority.issue("alice", "delete_record", argument_digest(self.arguments), ttl_seconds=1200)
        with self.assertRaises(ToolValidationError):
            ToolExecutor(
                ToolRegistry(), InMemoryAuditSink(), require_signed_approvals=True
            )


if __name__ == "__main__":
    unittest.main()
