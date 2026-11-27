"""Composite audit checkpoint contract, binding, and adversarial tests.

Covers phases 2-3 of docs/NEXUS_PROTECTED_AUDIT_CHECKPOINTS.md: envelope
validation, canonical signing, verifier-first local-chain binding, generation
history continuity, compare-and-swap store semantics, and integration with the
real SQLite security store and worker registry. Deterministic offline adapters
only; no real keys, network, or paid services.
"""

import hashlib
import os
import sqlite3
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timezone

from capri_runtime.audit_checkpoints import (
    ALGORITHM_ED25519,
    ALGORITHM_HMAC_SHA256,
    CHECKPOINT_DOMAIN_SEPARATOR,
    CHECKPOINT_FORMAT_VERSION,
    CheckpointConflictError,
    CheckpointEnvelopeError,
    CheckpointError,
    CheckpointVerificationError,
    CompositeCheckpoint,
    HmacCheckpointSigner,
    HmacCheckpointVerifier,
    InMemoryCheckpointStore,
    LocalChainState,
    SignedCheckpoint,
    StoredCheckpoint,
    StreamPosition,
    previous_checkpoint_digest,
    sign_checkpoint,
    verify_checkpoint_history,
    verify_composite_checkpoint,
    verify_latest_checkpoint,
)
from capri_runtime.security_store import SQLiteSecurityStore
from capri_runtime.sqlite_worker_registry import SQLiteWorkerRegistry
from capri_runtime.tasks import SQLiteTaskStore
from capri_runtime.tools import AuditEvent, ToolValidationError
from capri_runtime.worker_registry import WorkerDescriptor, WorkerRegistryError

SCOPE = "nexus-worker-lifecycle-v1"
KEY = b"0123456789abcdef0123456789abcdef"
REGISTRY_DB = str(uuid.UUID("11111111-2222-4333-8444-555555555555"))
LIFECYCLE_DB = str(uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"))
ISSUED_AT = 1_700_000_000


def _signer(key_id="key-1", key=KEY):
    return HmacCheckpointSigner(key, key_id)


def _verifier(key_id="key-1", key=KEY):
    return HmacCheckpointVerifier(key, key_id)


def _registry_position(sequence=3, head="a" * 64, database_id=REGISTRY_DB, schema_version=2):
    return StreamPosition(database_id, schema_version, sequence, head)


def _lifecycle_position(sequence=5, head="b" * 64, database_id=LIFECYCLE_DB, schema_version=1):
    return StreamPosition(database_id, schema_version, sequence, head)


def _checkpoint(registry=None, lifecycle=None, *, generation=1, previous=None,
                fencing_epoch=0, scope=SCOPE, key_id="key-1",
                algorithm=ALGORITHM_HMAC_SHA256, issued_at=ISSUED_AT):
    return CompositeCheckpoint(
        format_version=CHECKPOINT_FORMAT_VERSION,
        scope_id=scope,
        generation=generation,
        previous_checkpoint_sha256=previous,
        registry=registry or _registry_position(),
        lifecycle=lifecycle or _lifecycle_position(),
        supervisor_fencing_epoch=fencing_epoch,
        key_id=key_id,
        algorithm=algorithm,
        issued_at=issued_at,
    )


def _state(sequence=3, head="a" * 64, schema_version=2, head_at_anchor=None):
    return LocalChainState(schema_version, sequence, head, head_at_anchor)


class EnvelopeTests(unittest.TestCase):
    def test_dict_round_trip(self):
        checkpoint = _checkpoint()
        restored = CompositeCheckpoint.from_dict(checkpoint.to_dict())
        self.assertEqual(restored, checkpoint)
        self.assertEqual(restored.canonical_bytes(), checkpoint.canonical_bytes())

    def test_canonical_bytes_deterministic_and_domain_separated(self):
        first = _checkpoint().canonical_bytes()
        second = _checkpoint().canonical_bytes()
        self.assertEqual(first, second)
        self.assertTrue(first.startswith(CHECKPOINT_DOMAIN_SEPARATOR))
        self.assertNotEqual(first, _checkpoint(scope="other-scope-1").canonical_bytes())
        self.assertNotEqual(first, _checkpoint(registry=_registry_position(sequence=4)).canonical_bytes())
        self.assertNotEqual(first, _checkpoint(fencing_epoch=1).canonical_bytes())

    def test_unknown_field_rejected(self):
        payload = _checkpoint().to_dict()
        payload["extra"] = 1
        with self.assertRaises(CheckpointEnvelopeError):
            CompositeCheckpoint.from_dict(payload)

    def test_missing_field_rejected(self):
        payload = _checkpoint().to_dict()
        del payload["issued_at"]
        with self.assertRaises(CheckpointEnvelopeError):
            CompositeCheckpoint.from_dict(payload)

    def test_non_integer_types_rejected(self):
        payload = _checkpoint().to_dict()
        payload["generation"] = True  # bool must not pass as int
        with self.assertRaises(CheckpointEnvelopeError):
            CompositeCheckpoint.from_dict(payload)
        payload = _checkpoint().to_dict()
        payload["registry_sequence"] = "3"
        with self.assertRaises(CheckpointEnvelopeError):
            CompositeCheckpoint.from_dict(payload)

    def test_unsupported_version_and_algorithm_rejected(self):
        payload = _checkpoint().to_dict()
        payload["format_version"] = 99
        with self.assertRaises(CheckpointEnvelopeError):
            CompositeCheckpoint.from_dict(payload)
        payload = _checkpoint().to_dict()
        payload["algorithm"] = "rot13"
        with self.assertRaises(CheckpointEnvelopeError):
            CompositeCheckpoint.from_dict(payload)

    def test_malformed_identifiers_rejected(self):
        for field, value in (
            ("registry_head_sha256", "not-a-digest"),
            ("lifecycle_database_id", "not-a-uuid"),
            ("scope_id", "bad scope!"),
            ("key_id", ""),
        ):
            payload = _checkpoint().to_dict()
            payload[field] = value
            with self.assertRaises(CheckpointEnvelopeError, msg=field):
                CompositeCheckpoint.from_dict(payload)

    def test_zero_generation_rejected(self):
        with self.assertRaises(CheckpointEnvelopeError):
            _checkpoint(generation=0)

    def test_local_chain_state_validation(self):
        with self.assertRaises(CheckpointEnvelopeError):
            LocalChainState(1, -1, "a" * 64)
        with self.assertRaises(CheckpointEnvelopeError):
            LocalChainState(1, 1, "a" * 64, head_at_anchor="zz")
        with self.assertRaises(CheckpointEnvelopeError):
            LocalChainState(0, 1, "a" * 64)


class SigningTests(unittest.TestCase):
    def test_sign_and_verify(self):
        signed = sign_checkpoint(_signer(), _checkpoint())
        verify_composite_checkpoint(
            signed,
            verifier=_verifier(),
            expected_scope=SCOPE,
            registry=_state(),
            lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
        )

    def test_signer_key_id_mismatch_rejected(self):
        with self.assertRaises(CheckpointError):
            sign_checkpoint(_signer(key_id="other"), _checkpoint())

    def test_signer_algorithm_mismatch_rejected(self):
        with self.assertRaises(CheckpointError):
            sign_checkpoint(_signer(), _checkpoint(algorithm=ALGORITHM_ED25519))

    def test_signer_refuses_unauthorized_key_id(self):
        signer = _signer()
        with self.assertRaises(CheckpointError):
            signer.sign("wrong-key", b"payload")

    def test_wrong_key_fails_verification(self):
        signed = sign_checkpoint(_signer(), _checkpoint())
        with self.assertRaises(CheckpointVerificationError):
            verify_composite_checkpoint(
                signed,
                verifier=_verifier(key=b"f" * 32),
                expected_scope=SCOPE,
                registry=_state(),
                lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
            )

    def test_scope_mismatch_fails_verification(self):
        signed = sign_checkpoint(_signer(), _checkpoint())
        with self.assertRaises(CheckpointVerificationError):
            verify_composite_checkpoint(
                signed,
                verifier=_verifier(),
                expected_scope="different-scope",
                registry=_state(),
                lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
            )

    def test_algorithm_mismatch_fails_verification(self):
        # An envelope claiming Ed25519 cannot be accepted by an HMAC verifier
        # even before the signature bytes are examined.
        signed = SignedCheckpoint(
            checkpoint=_checkpoint(algorithm=ALGORITHM_ED25519),
            signature=b"\x01" * 64,
        )
        with self.assertRaises(CheckpointVerificationError):
            verify_composite_checkpoint(
                signed,
                verifier=_verifier(),
                expected_scope=SCOPE,
                registry=_state(),
                lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
            )

    def test_tampered_signed_fields_fail_verification(self):
        # Sign once, then rebuild the envelope with one mutated field while
        # keeping the original signature: every signed field must break the
        # signature or an explicit verifier expectation.
        original = _checkpoint()
        signed = sign_checkpoint(_signer(), original)
        base = original.to_dict()
        lifecycle_state = _state(sequence=5, head="b" * 64, schema_version=1)
        mutations = {
            "generation": 2,
            "issued_at": ISSUED_AT + 1,
            "supervisor_fencing_epoch": 1,
            "scope_id": "tampered-scope",
            "key_id": "key-2",
            "algorithm": ALGORITHM_ED25519,
            "previous_checkpoint_sha256": "e" * 64,
            "registry_sequence": 4,
            "registry_head_sha256": "c" * 64,
            "registry_schema_version": 1,
            "registry_database_id": str(uuid.uuid4()),
            "lifecycle_sequence": 6,
            "lifecycle_head_sha256": "d" * 64,
            "lifecycle_schema_version": 2,
            "lifecycle_database_id": str(uuid.uuid4()),
        }
        for field, value in mutations.items():
            payload = dict(base)
            payload[field] = value
            tampered = SignedCheckpoint(
                checkpoint=CompositeCheckpoint.from_dict(payload),
                signature=signed.signature,
            )
            with self.assertRaises(CheckpointVerificationError, msg=field):
                verify_composite_checkpoint(
                    tampered,
                    verifier=_verifier(),
                    expected_scope=SCOPE,
                    registry=_state(),
                    lifecycle=lifecycle_state,
                )

    def test_tampered_signature_fails_verification(self):
        signed = sign_checkpoint(_signer(), _checkpoint())
        tampered = SignedCheckpoint(
            checkpoint=signed.checkpoint,
            signature=bytes(byte ^ 0x01 for byte in signed.signature),
        )
        with self.assertRaises(CheckpointVerificationError):
            verify_composite_checkpoint(
                tampered,
                verifier=_verifier(),
                expected_scope=SCOPE,
                registry=_state(),
                lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
            )

    def test_hmac_key_minimum_length(self):
        with self.assertRaises(CheckpointEnvelopeError):
            HmacCheckpointSigner(b"short", "key-1")
        with self.assertRaises(CheckpointEnvelopeError):
            HmacCheckpointVerifier(b"short", "key-1")


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.signed = sign_checkpoint(_signer(), _checkpoint())

    def _verify(self, registry, lifecycle, **kwargs):
        return verify_composite_checkpoint(
            self.signed,
            verifier=_verifier(),
            expected_scope=SCOPE,
            registry=registry,
            lifecycle=lifecycle,
            **kwargs,
        )

    def test_exact_match_reports_zero_tail(self):
        result = self._verify(
            _state(),
            _state(sequence=5, head="b" * 64, schema_version=1),
        )
        self.assertEqual(result.registry_unanchored, 0)
        self.assertEqual(result.lifecycle_unanchored, 0)

    def test_registry_rolled_back_rejected(self):
        with self.assertRaises(CheckpointVerificationError):
            self._verify(
                _state(sequence=2, head="c" * 64),
                _state(sequence=5, head="b" * 64, schema_version=1),
            )

    def test_lifecycle_rolled_back_rejected(self):
        with self.assertRaises(CheckpointVerificationError):
            self._verify(
                _state(),
                _state(sequence=4, head="d" * 64, schema_version=1),
            )

    def test_registry_head_mismatch_at_anchor_rejected(self):
        with self.assertRaises(CheckpointVerificationError):
            self._verify(
                _state(head="c" * 64),
                _state(sequence=5, head="b" * 64, schema_version=1),
            )

    def test_lifecycle_head_mismatch_at_anchor_rejected(self):
        with self.assertRaises(CheckpointVerificationError):
            self._verify(
                _state(),
                _state(sequence=5, head="d" * 64, schema_version=1),
            )

    def test_unanchored_tail_reported_when_anchor_head_matches(self):
        result = self._verify(
            _state(sequence=7, head="e" * 64, head_at_anchor="a" * 64),
            _state(sequence=9, head="f" * 64, schema_version=1, head_at_anchor="b" * 64),
        )
        self.assertEqual(result.registry_unanchored, 4)
        self.assertEqual(result.lifecycle_unanchored, 4)

    def test_tail_without_anchor_head_rejected(self):
        with self.assertRaises(CheckpointVerificationError):
            self._verify(
                _state(sequence=7, head="e" * 64),
                _state(sequence=5, head="b" * 64, schema_version=1),
            )

    def test_tail_with_wrong_anchor_head_rejected(self):
        with self.assertRaises(CheckpointVerificationError):
            self._verify(
                _state(sequence=7, head="e" * 64, head_at_anchor="c" * 64),
                _state(sequence=5, head="b" * 64, schema_version=1),
            )

    def test_genesis_anchor_tail_accepted(self):
        signed = sign_checkpoint(
            _signer(),
            _checkpoint(
                registry=_registry_position(sequence=0, head="0" * 64),
                lifecycle=_lifecycle_position(sequence=0, head="0" * 64, schema_version=1),
            ),
        )
        result = verify_composite_checkpoint(
            signed,
            verifier=_verifier(),
            expected_scope=SCOPE,
            registry=_state(sequence=4, head="e" * 64),
            lifecycle=_state(sequence=6, head="f" * 64, schema_version=1),
        )
        self.assertEqual(result.registry_unanchored, 4)
        self.assertEqual(result.lifecycle_unanchored, 6)

    def test_fencing_epoch_mismatch_rejected(self):
        with self.assertRaises(CheckpointVerificationError):
            self._verify(
                _state(),
                _state(sequence=5, head="b" * 64, schema_version=1),
                expected_fencing_epoch=7,
            )

    def test_invalid_expected_scope_rejected(self):
        with self.assertRaises(CheckpointEnvelopeError):
            verify_composite_checkpoint(
                self.signed,
                verifier=_verifier(),
                expected_scope="bad scope!",
                registry=_state(),
                lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
            )


class HistoryTests(unittest.TestCase):
    def _chain(self, count=2):
        store = InMemoryCheckpointStore(clock=lambda: float(ISSUED_AT))
        signer = _signer()
        previous_digest = None
        for generation in range(1, count + 1):
            checkpoint = _checkpoint(generation=generation, previous=previous_digest)
            signed = sign_checkpoint(signer, checkpoint)
            stored = store.append_if_generation(SCOPE, generation - 1, 0, signed)
            previous_digest = previous_checkpoint_digest(stored)
        return [store.read_checkpoint(SCOPE, g) for g in range(1, count + 1)]

    @staticmethod
    def _with_signed(stored, checkpoint, signature):
        return StoredCheckpoint(
            signed=SignedCheckpoint(checkpoint=checkpoint, signature=signature),
            scope_id=stored.scope_id,
            generation=stored.generation,
            fencing_epoch=stored.fencing_epoch,
            append_timestamp=stored.append_timestamp,
        )

    def test_valid_history_verifies(self):
        verify_checkpoint_history(self._chain(3), verifier=_verifier(), expected_scope=SCOPE)

    def test_empty_history_rejected(self):
        with self.assertRaises(CheckpointVerificationError):
            verify_checkpoint_history([], verifier=_verifier(), expected_scope=SCOPE)

    def test_generation_gap_rejected(self):
        history = self._chain(3)
        with self.assertRaises(CheckpointVerificationError):
            verify_checkpoint_history(
                (history[0], history[2]), verifier=_verifier(), expected_scope=SCOPE,
            )

    def test_broken_previous_link_rejected(self):
        history = list(self._chain(2))
        payload = history[1].signed.checkpoint.to_dict()
        payload["previous_checkpoint_sha256"] = "c" * 64
        history[1] = self._with_signed(
            history[1],
            CompositeCheckpoint.from_dict(payload),
            history[1].signed.signature,
        )
        with self.assertRaises(CheckpointVerificationError):
            verify_checkpoint_history(history, verifier=_verifier(), expected_scope=SCOPE)

    def test_genesis_with_predecessor_link_rejected(self):
        history = list(self._chain(1))
        payload = history[0].signed.checkpoint.to_dict()
        payload["previous_checkpoint_sha256"] = "d" * 64
        history[0] = self._with_signed(
            history[0],
            CompositeCheckpoint.from_dict(payload),
            history[0].signed.signature,
        )
        with self.assertRaises(CheckpointVerificationError):
            verify_checkpoint_history(history, verifier=_verifier(), expected_scope=SCOPE)

    def test_tampered_signature_mid_history_rejected(self):
        history = list(self._chain(2))
        history[0] = self._with_signed(
            history[0],
            history[0].signed.checkpoint,
            bytes(byte ^ 0x80 for byte in history[0].signed.signature),
        )
        with self.assertRaises(CheckpointVerificationError):
            verify_checkpoint_history(history, verifier=_verifier(), expected_scope=SCOPE)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryCheckpointStore(clock=lambda: float(ISSUED_AT))
        self.signer = _signer()

    def _append(self, generation, previous=None, *, fencing_epoch=0, scope=SCOPE,
                expected_generation=None, expected_epoch=None, key=KEY):
        checkpoint = _checkpoint(
            generation=generation, previous=previous, fencing_epoch=fencing_epoch, scope=scope,
        )
        signed = sign_checkpoint(HmacCheckpointSigner(key, "key-1"), checkpoint)
        # The store scope is always SCOPE so a differing envelope scope is a
        # cross-scope substitution attempt.
        return self.store.append_if_generation(
            SCOPE,
            generation - 1 if expected_generation is None else expected_generation,
            fencing_epoch if expected_epoch is None else expected_epoch,
            signed,
        )

    def test_append_and_read(self):
        stored = self._append(1)
        self.assertEqual(stored.generation, 1)
        self.assertIs(self.store.read_latest(SCOPE), stored)
        self.assertIs(self.store.read_checkpoint(SCOPE, 1), stored)
        self.assertIsNone(self.store.read_latest("other-scope"))

    def test_empty_store_latest_is_none(self):
        with self.assertRaises(CheckpointVerificationError):
            verify_latest_checkpoint(
                self.store, verifier=_verifier(), expected_scope=SCOPE,
                registry=_state(),
                lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
            )

    def test_cas_conflict_on_stale_generation(self):
        self._append(1)
        with self.assertRaises(CheckpointConflictError):
            self._append(1)  # envelope says gen1 again; CAS sees latest=1

    def test_envelope_generation_must_match_request(self):
        with self.assertRaises(CheckpointConflictError):
            self._append(2, expected_generation=0)

    def test_scope_mismatch_rejected(self):
        with self.assertRaises(CheckpointEnvelopeError):
            self._append(1, scope="attacker-scope", expected_generation=0)

    def test_fencing_epoch_regression_rejected(self):
        self._append(1, fencing_epoch=5)
        with self.assertRaises(CheckpointConflictError):
            self._append(2, previous=previous_checkpoint_digest(
                self.store.read_checkpoint(SCOPE, 1),
            ), fencing_epoch=3, expected_epoch=3)

    def test_append_request_epoch_must_match_envelope(self):
        with self.assertRaises(CheckpointConflictError):
            self._append(1, fencing_epoch=2, expected_epoch=1)

    def test_previous_link_must_match_store(self):
        self._append(1)
        with self.assertRaises(CheckpointConflictError):
            self._append(2, previous="e" * 64)

    def test_genesis_predecessor_rejected(self):
        with self.assertRaises(CheckpointConflictError):
            self._append(1, previous="e" * 64)

    def test_concurrent_cas_exactly_one_winner(self):
        barrier = threading.Barrier(8)
        outcomes = []

        def contender():
            barrier.wait()
            try:
                self._append(1)
                outcomes.append("won")
            except CheckpointConflictError:
                outcomes.append("lost")

        threads = [threading.Thread(target=contender) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes.count("won"), 1)
        self.assertEqual(outcomes.count("lost"), 7)
        self.assertEqual(self.store.read_latest(SCOPE).generation, 1)

    def test_verify_latest_happy_path_and_presentation(self):
        stored1 = self._append(1)
        stored2 = self._append(2, previous=previous_checkpoint_digest(stored1))
        latest, result = verify_latest_checkpoint(
            self.store, verifier=_verifier(), expected_scope=SCOPE,
            registry=_state(),
            lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
            presented=stored2.signed,
        )
        self.assertIs(latest, stored2)
        self.assertEqual(result.registry_unanchored, 0)

    def test_replayed_older_checkpoint_rejected(self):
        stored1 = self._append(1)
        self._append(2, previous=previous_checkpoint_digest(stored1))
        with self.assertRaises(CheckpointVerificationError):
            verify_latest_checkpoint(
                self.store, verifier=_verifier(), expected_scope=SCOPE,
                registry=_state(),
                lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
                presented=stored1.signed,
            )

    def test_history_gap_detected_via_store_reads(self):
        stored1 = self._append(1)
        self._append(2, previous=previous_checkpoint_digest(stored1))
        # Simulate a missing history row for generation 1.
        del self.store._rows[(SCOPE, 1)]
        with self.assertRaises(CheckpointVerificationError):
            verify_latest_checkpoint(
                self.store, verifier=_verifier(), expected_scope=SCOPE,
                registry=_state(),
                lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
            )


class SecurityStoreIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.path = os.path.join(self.temp.name, "audit.sqlite3")
        self.store = SQLiteSecurityStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _event(event_id, when):
        return AuditEvent(
            event_id,
            when.isoformat(),
            "alice",
            "checkpoint.integration",
            hashlib.sha256(event_id.encode("utf-8")).hexdigest(),
            "success",
        )

    def _checkpoint_for(self, state, generation=1, previous=None):
        signed = sign_checkpoint(
            _signer(),
            _checkpoint(
                generation=generation,
                previous=previous,
                registry=_registry_position(),
                lifecycle=_lifecycle_position(
                    sequence=state.sequence,
                    head=state.head_sha256,
                    schema_version=state.schema_version,
                ),
            ),
        )
        return signed

    def test_chain_state_binds_and_verifies(self):
        when = datetime.now(timezone.utc)
        self.store.write(self._event("evt-1", when))
        self.store.write(self._event("evt-2", when))
        state = self.store.lifecycle_chain_state()
        self.assertEqual(state.sequence, 2)
        signed = self._checkpoint_for(state)
        result = verify_composite_checkpoint(
            signed,
            verifier=_verifier(),
            expected_scope=SCOPE,
            registry=_state(),
            lifecycle=LocalChainState(
                state.schema_version, state.sequence, state.head_sha256,
            ),
        )
        self.assertEqual(result.lifecycle_unanchored, 0)

    def test_unanchored_tail_after_further_events(self):
        when = datetime.now(timezone.utc)
        self.store.write(self._event("evt-1", when))
        anchor = self.store.lifecycle_chain_state()
        signed = self._checkpoint_for(anchor)
        self.store.write(self._event("evt-2", when))
        self.store.write(self._event("evt-3", when))
        advanced = self.store.lifecycle_chain_state(anchor_sequence=anchor.sequence)
        self.assertEqual(advanced.sequence, 3)
        self.assertEqual(advanced.head_at_anchor, anchor.head_sha256)
        result = verify_composite_checkpoint(
            signed,
            verifier=_verifier(),
            expected_scope=SCOPE,
            registry=_state(),
            lifecycle=LocalChainState(
                advanced.schema_version, advanced.sequence, advanced.head_sha256,
                head_at_anchor=advanced.head_at_anchor,
            ),
        )
        self.assertEqual(result.lifecycle_unanchored, 2)

    def test_tampered_lifecycle_row_fails_closed(self):
        when = datetime.now(timezone.utc)
        self.store.write(self._event("evt-1", when))
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TRIGGER audit_events_immutable_update")
            connection.execute("UPDATE audit_events SET status='tampered' WHERE sequence=1")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ToolValidationError):
            self.store.lifecycle_chain_state()

    def test_missing_anchor_event_reports_none(self):
        when = datetime.now(timezone.utc)
        self.store.write(self._event("evt-1", when))
        state = self.store.lifecycle_chain_state(anchor_sequence=99)
        self.assertIsNone(state.head_at_anchor)

    def test_invalid_anchor_sequence_rejected(self):
        with self.assertRaises(ToolValidationError):
            self.store.lifecycle_chain_state(anchor_sequence=-1)


class RegistryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.tasks_path = os.path.join(self.temp.name, "tasks.sqlite3")
        self.task_store = SQLiteTaskStore(self.tasks_path)
        self.registry = SQLiteWorkerRegistry(self.task_store)

    def tearDown(self):
        self.temp.cleanup()

    def test_chain_state_binds_and_verifies(self):
        self.registry.register(
            WorkerDescriptor("worker-1", (1,), ("math.factorial",), max_concurrency=1),
            authenticated_worker_id="worker-1",
        )
        state = self.registry.audit_chain_state()
        self.assertGreaterEqual(state.sequence, 1)
        signed = sign_checkpoint(
            _signer(),
            _checkpoint(
                registry=_registry_position(
                    sequence=state.sequence,
                    head=state.head_sha256,
                    schema_version=state.schema_version,
                ),
            ),
        )
        result = verify_composite_checkpoint(
            signed,
            verifier=_verifier(),
            expected_scope=SCOPE,
            registry=LocalChainState(
                state.schema_version, state.sequence, state.head_sha256,
            ),
            lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
        )
        self.assertEqual(result.registry_unanchored, 0)

    def test_unanchored_tail_after_further_events(self):
        self.registry.register(
            WorkerDescriptor("worker-1", (1,), ("math.factorial",), max_concurrency=1),
            authenticated_worker_id="worker-1",
        )
        anchor = self.registry.audit_chain_state()
        signed = sign_checkpoint(
            _signer(),
            _checkpoint(
                registry=_registry_position(
                    sequence=anchor.sequence,
                    head=anchor.head_sha256,
                    schema_version=anchor.schema_version,
                ),
            ),
        )
        self.registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1", in_flight=0,
        )
        advanced = self.registry.audit_chain_state(anchor_sequence=anchor.sequence)
        self.assertGreater(advanced.sequence, anchor.sequence)
        self.assertEqual(advanced.head_at_anchor, anchor.head_sha256)
        result = verify_composite_checkpoint(
            signed,
            verifier=_verifier(),
            expected_scope=SCOPE,
            registry=LocalChainState(
                advanced.schema_version, advanced.sequence, advanced.head_sha256,
                head_at_anchor=advanced.head_at_anchor,
            ),
            lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
        )
        self.assertGreater(result.registry_unanchored, 0)

    def test_tampered_registry_event_fails_closed(self):
        self.registry.register(
            WorkerDescriptor("worker-1", (1,), ("math.factorial",), max_concurrency=1),
            authenticated_worker_id="worker-1",
        )
        connection = sqlite3.connect(self.tasks_path)
        try:
            connection.execute("DROP TRIGGER worker_registry_events_immutable_update")
            connection.execute(
                "UPDATE worker_registry_events SET event_type='tampered' WHERE sequence=1"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(WorkerRegistryError):
            self.registry.audit_chain_state()

    def test_cross_stream_substitution_rejected(self):
        # A lifecycle position presented as the registry stream must not verify.
        self.registry.register(
            WorkerDescriptor("worker-1", (1,), ("math.factorial",), max_concurrency=1),
            authenticated_worker_id="worker-1",
        )
        state = self.registry.audit_chain_state()
        signed = sign_checkpoint(
            _signer(),
            _checkpoint(
                registry=_registry_position(
                    sequence=state.sequence,
                    head=state.head_sha256,
                    schema_version=state.schema_version,
                ),
            ),
        )
        # Attacker swaps the registry binding for the lifecycle binding.
        payload = signed.checkpoint.to_dict()
        payload["registry_database_id"] = LIFECYCLE_DB
        payload["registry_schema_version"] = 1
        payload["registry_sequence"] = 5
        payload["registry_head_sha256"] = "b" * 64
        forged = SignedCheckpoint(
            checkpoint=CompositeCheckpoint.from_dict(payload),
            signature=signed.signature,
        )
        with self.assertRaises(CheckpointVerificationError):
            verify_composite_checkpoint(
                forged,
                verifier=_verifier(),
                expected_scope=SCOPE,
                registry=LocalChainState(
                    state.schema_version, state.sequence, state.head_sha256,
                ),
                lifecycle=_state(sequence=5, head="b" * 64, schema_version=1),
            )


if __name__ == "__main__":
    unittest.main()
