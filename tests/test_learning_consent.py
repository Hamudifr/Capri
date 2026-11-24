import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import replace

from capri_core.learning import LearningConsent, LearningStore
from capri_runtime.learning_consent import (
    HostLearningConsentAuthority,
    LearningConsentAuthorityError,
)


class HostLearningConsentAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.calls = []
        self.authority = HostLearningConsentAuthority(
            b"k" * 32,
            authenticate=lambda credential: "principal-1" if credential == "valid" else None,
            confirm_explicit_consent=lambda principal, scope, policy: (
                self.calls.append((principal, scope, policy)) or True
            ),
            clock=lambda: datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
        )

    def tearDown(self):
        self.temp.cleanup()

    def issue(self, **kwargs):
        return self.authority.issue(
            "valid",
            consent_id="consent-001",
            policy_version="learning-consent-v1",
            **kwargs,
        )

    def test_authenticated_explicit_grant_is_verifiable_by_learning_store(self):
        consent = self.issue()
        self.assertTrue(self.authority.verify(consent))
        self.assertEqual(self.calls, [(
            "principal-1", "curated_training_examples", "learning-consent-v1"
        )])
        store = LearningStore(
            self.root / "learning.sqlite3",
            consent_verifier=self.authority.verify,
        )
        store.record_consent(consent)
        self.assertEqual(store.counts(), {})

    def test_invalid_authentication_never_reaches_confirmation(self):
        with self.assertRaisesRegex(LearningConsentAuthorityError, "authentication failed"):
            self.authority.issue(
                "invalid", consent_id="consent-001",
                policy_version="learning-consent-v1",
            )
        self.assertEqual(self.calls, [])

    def test_confirmation_must_return_literal_true(self):
        for result in (False, None, 1, "true"):
            authority = HostLearningConsentAuthority(
                b"k" * 32, lambda credential: "principal-1",
                lambda *args: result,
            )
            with self.subTest(result=result):
                with self.assertRaises(LearningConsentAuthorityError):
                    authority.issue(
                        "valid", consent_id="consent-001",
                        policy_version="learning-consent-v1",
                    )

    def test_confirmation_callback_failure_fails_closed(self):
        authority = HostLearningConsentAuthority(
            b"k" * 32, lambda credential: "principal-1",
            lambda *args: (_ for _ in ()).throw(RuntimeError("private detail")),
        )
        with self.assertRaisesRegex(LearningConsentAuthorityError, "confirmation failed") as caught:
            authority.issue(
                "valid", consent_id="consent-001",
                policy_version="learning-consent-v1",
            )
        self.assertNotIn("private detail", str(caught.exception))

    def test_tampering_with_any_signed_field_is_rejected(self):
        consent = self.issue()
        changed = (
            replace(consent, consent_id="consent-002"),
            replace(consent, scope="other_scope"),
            replace(consent, policy_version="learning-consent-v2"),
            replace(consent, granted_at="2026-11-25T12:00:00+00:00"),
            replace(consent, evidence_ref=consent.evidence_ref[:-1] + "0"),
        )
        for record in changed:
            with self.subTest(record=record):
                self.assertFalse(self.authority.verify(record))

    def test_other_signing_key_cannot_verify_evidence(self):
        consent = self.issue()
        other = HostLearningConsentAuthority(
            b"x" * 32, lambda credential: "principal-1",
            lambda *args: True,
        )
        self.assertFalse(other.verify(consent))

    def test_exact_replay_is_rejected_by_learning_store(self):
        consent = self.issue()
        store = LearningStore(
            self.root / "learning.sqlite3",
            consent_verifier=self.authority.verify,
        )
        store.record_consent(consent)
        with self.assertRaises(sqlite3.IntegrityError):
            store.record_consent(consent)

    def test_subject_identity_is_not_embedded_in_evidence(self):
        consent = self.issue()
        self.assertNotIn("principal-1", consent.evidence_ref)
        self.assertLessEqual(len(consent.evidence_ref), 256)

    def test_invalid_key_and_missing_callbacks_are_rejected(self):
        with self.assertRaises(LearningConsentAuthorityError):
            HostLearningConsentAuthority(b"short", lambda value: "p", lambda *args: True)
        with self.assertRaises(LearningConsentAuthorityError):
            HostLearningConsentAuthority(b"k" * 32, None, lambda *args: True)
        with self.assertRaises(LearningConsentAuthorityError):
            HostLearningConsentAuthority(b"k" * 32, lambda value: "p", None)

    def test_naive_clock_fails_closed(self):
        authority = HostLearningConsentAuthority(
            b"k" * 32, lambda credential: "principal-1",
            lambda *args: True,
            clock=lambda: datetime(2026, 11, 24, 12, 0),
        )
        with self.assertRaisesRegex(LearningConsentAuthorityError, "clock is invalid"):
            authority.issue(
                "valid", consent_id="consent-001",
                policy_version="learning-consent-v1",
            )


if __name__ == "__main__":
    unittest.main()
