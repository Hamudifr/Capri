import hashlib
import hmac
import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from capri_runtime.tools import (
    ApprovalGrant,
    ApprovalMacProvider,
    ExecutionContext,
    HmacApprovalAuthority,
    HmacApprovalKeyRing,
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

    def test_key_ring_rotation_verifies_old_key_by_explicit_id(self):
        old_ring = HmacApprovalKeyRing({"old-v1": b"o" * 32}, active_key_id="old-v1")
        old_authority = HmacApprovalAuthority(old_ring, clock=lambda: self.now)
        grant = old_authority.issue(
            "alice", "delete_record", argument_digest(self.arguments), ttl_seconds=120
        )
        self.assertEqual(grant.key_id, "old-v1")

        rotated = HmacApprovalAuthority(
            HmacApprovalKeyRing(
                {"old-v1": b"o" * 32, "new-v2": b"n" * 32},
                active_key_id="new-v2",
            ),
            clock=lambda: self.now,
        )
        self.assertTrue(rotated.verify(grant))
        new_grant = rotated.issue(
            "alice", "delete_record", argument_digest(self.arguments), ttl_seconds=120
        )
        self.assertEqual(new_grant.key_id, "new-v2")
        self.assertTrue(rotated.verify(new_grant))

        retired = HmacApprovalAuthority(
            HmacApprovalKeyRing({"new-v2": b"n" * 32}, active_key_id="new-v2"),
            clock=lambda: self.now,
        )
        self.assertFalse(retired.verify(grant))

    def test_key_id_tampering_and_unknown_ids_fail_closed(self):
        ring = HmacApprovalKeyRing(
            {"active": b"a" * 32, "other": b"b" * 32}, active_key_id="active"
        )
        authority = HmacApprovalAuthority(ring, clock=lambda: self.now)
        grant = authority.issue(
            "alice", "delete_record", argument_digest(self.arguments), ttl_seconds=120
        )
        self.assertFalse(authority.verify(replace(grant, key_id="other")))
        self.assertFalse(authority.verify(replace(grant, key_id="unknown")))
        self.assertFalse(authority.verify(replace(grant, key_id=None)))

    def test_non_exportable_mac_provider_signs_and_verifies_exact_key_id(self):
        class RemoteMacProvider:
            active_key_id = "kms-key-version-7"

            def __init__(self):
                self.__secret = b"remote-provider-secret" * 2
                self.signed = []
                self.verified = []

            def sign(self, key_id, payload):
                self.signed.append(key_id)
                return hmac.new(self.__secret, payload, hashlib.sha256).digest()

            def verify(self, key_id, payload, signature):
                self.verified.append(key_id)
                expected = hmac.new(self.__secret, payload, hashlib.sha256).digest()
                return hmac.compare_digest(expected, signature)

        provider = RemoteMacProvider()
        authority = HmacApprovalAuthority(provider, clock=lambda: self.now)
        grant = authority.issue(
            "alice", "delete_record", argument_digest(self.arguments), ttl_seconds=120
        )
        self.assertEqual(grant.key_id, "kms-key-version-7")
        self.assertEqual(provider.signed, ["kms-key-version-7"])
        self.assertTrue(authority.verify(grant))
        self.assertEqual(provider.verified, ["kms-key-version-7"])
        self.assertIsNone(authority._legacy_key)

    def test_mac_provider_failures_are_closed(self):
        class BrokenProvider:
            active_key_id = "remote-v1"
            def sign(self, key_id, payload):
                raise RuntimeError("provider detail")
            def verify(self, key_id, payload, signature):
                raise RuntimeError("provider detail")

        authority = HmacApprovalAuthority(BrokenProvider(), clock=lambda: self.now)
        with self.assertRaises(ToolValidationError) as raised:
            authority.issue(
                "alice", "delete_record", argument_digest(self.arguments), ttl_seconds=120
            )
        self.assertNotIn("provider detail", str(raised.exception))
        grant = ApprovalGrant(
            "g", "alice", "delete_record", argument_digest(self.arguments),
            "2026-11-06T13:00:00+00:00", "0" * 64, "remote-v1",
        )
        self.assertFalse(authority.verify(grant))

    def test_key_ring_rejects_invalid_configuration(self):
        for keys, active in (
            ({}, "missing"),
            ({"active": b"short"}, "active"),
            ({"bad/id": b"a" * 32}, "bad/id"),
            ({"active": b"a" * 32}, "missing"),
        ):
            with self.subTest(keys=keys, active=active):
                with self.assertRaises(ToolValidationError):
                    HmacApprovalKeyRing(keys, active_key_id=active)

    def test_signing_key_and_ttl_are_bounded(self):
        with self.assertRaises(ToolValidationError):
            HmacApprovalAuthority(b"short")
        with self.assertRaises(ToolValidationError):
            self.authority.issue("alice", "delete_record", argument_digest(self.arguments), ttl_seconds=3601)
        with self.assertRaises(ToolValidationError):
            ToolExecutor(
                ToolRegistry(), InMemoryAuditSink(), require_signed_approvals=True
            )


if __name__ == "__main__":
    unittest.main()
