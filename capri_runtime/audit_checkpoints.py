"""Independently protected composite audit checkpoints (Nexus phases 2-3).

Implements the typed signer/verifier/checkpoint-store contracts, the immutable
domain-separated composite envelope, and the verifier-first checks described in
``docs/NEXUS_PROTECTED_AUDIT_CHECKPOINTS.md``. The envelope binds the durable
worker-registry event chain and the host lifecycle audit chain under one scope
so neither stream can be substituted for the other.

Trust boundaries (unchanged from the specification):

- Signing keys are host-supplied and never stored in this module, the
  repository, or either SQLite database. This repository provisions no keys.
- The checkpoint store is an independently administered monotonic store outside
  the application databases; ``InMemoryCheckpointStore`` is a process-local
  reference implementation of the compare-and-swap contract and must never be
  treated as an independent trust root.
- A signature authenticates the configured signer's authorization of the exact
  envelope bytes; it does not prove the payload was truthful.

Phases 4-6 (checkpoint writer cadence, host fencing integration, key rotation
and restore validation) are not implemented here. Until they are configured,
the audit mode remains host-local consistency only.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import struct
import threading
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

CHECKPOINT_FORMAT_VERSION = 1
CHECKPOINT_DOMAIN_SEPARATOR = b"capri:nexus:audit-checkpoint:v1\x00"
ALGORITHM_HMAC_SHA256 = "HMAC-SHA256"
ALGORITHM_ED25519 = "Ed25519"
SUPPORTED_ALGORITHMS = frozenset({ALGORITHM_HMAC_SHA256, ALGORITHM_ED25519})

_SCOPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_MAX_SEQUENCE = 2**63 - 1
_MAX_SCHEMA_VERSION = 2**31 - 1
_MAX_SIGNATURE_BYTES = 512
_GENESIS_HEAD = "0" * 64

_ENVELOPE_KEYS = frozenset({
    "format_version", "scope_id", "generation", "previous_checkpoint_sha256",
    "registry_database_id", "registry_schema_version", "registry_sequence",
    "registry_head_sha256", "lifecycle_database_id", "lifecycle_schema_version",
    "lifecycle_sequence", "lifecycle_head_sha256", "supervisor_fencing_epoch",
    "key_id", "algorithm", "issued_at",
})


class CheckpointError(Exception):
    """Base class for composite audit-checkpoint failures."""


class CheckpointEnvelopeError(CheckpointError):
    """The checkpoint envelope is malformed, unsupported, or inconsistently bound."""


class CheckpointVerificationError(CheckpointError):
    """Signature, scope, fencing, history, or local-chain binding verification failed."""


class CheckpointConflictError(CheckpointError):
    """Generation compare-and-swap or fencing-epoch monotonicity rejected the append."""


def _require_int(value: object, label: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CheckpointEnvelopeError(f"{label} must be an integer in [{minimum}, {maximum}]")
    return value


def _require_text(value: object, label: str, pattern: re.Pattern[str], limit: int) -> str:
    if (
        type(value) is not str
        or not pattern.fullmatch(value)
        or len(value) > limit
    ):
        raise CheckpointEnvelopeError(f"{label} is not a valid bounded identifier")
    return value


def _require_digest(value: object, label: str) -> str:
    if type(value) is not str or not _DIGEST_RE.fullmatch(value):
        raise CheckpointEnvelopeError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


@dataclass(frozen=True)
class StreamPosition:
    """One local audit stream's identity and chain position."""

    database_id: str
    schema_version: int
    sequence: int
    head_sha256: str

    def __post_init__(self) -> None:
        _require_text(self.database_id, "database_id", _UUID_RE, 36)
        _require_int(self.schema_version, "schema_version", minimum=1, maximum=_MAX_SCHEMA_VERSION)
        _require_int(self.sequence, "sequence", minimum=0, maximum=_MAX_SEQUENCE)
        _require_digest(self.head_sha256, "head_sha256")


@dataclass(frozen=True)
class LocalChainState:
    """Structurally validated local chain state read from one store.

    ``head_at_anchor`` is the stored event hash at the checkpoint's anchor
    sequence when the local chain has advanced past it; it is required by the
    verifier to detect tampering inside the anchored prefix of an unanchored
    tail. ``genesis`` anchors (sequence 0) carry the fixed genesis head.
    """

    schema_version: int
    sequence: int
    head_sha256: str
    head_at_anchor: str | None = None

    def __post_init__(self) -> None:
        _require_int(self.schema_version, "schema_version", minimum=1, maximum=_MAX_SCHEMA_VERSION)
        _require_int(self.sequence, "sequence", minimum=0, maximum=_MAX_SEQUENCE)
        _require_digest(self.head_sha256, "head_sha256")
        if self.head_at_anchor is not None:
            _require_digest(self.head_at_anchor, "head_at_anchor")


@dataclass(frozen=True)
class CompositeCheckpoint:
    """Versioned, domain-separated composite envelope over both audit streams."""

    format_version: int
    scope_id: str
    generation: int
    previous_checkpoint_sha256: str | None
    registry: StreamPosition
    lifecycle: StreamPosition
    supervisor_fencing_epoch: int
    key_id: str
    algorithm: str
    issued_at: int

    def __post_init__(self) -> None:
        if type(self.format_version) is not int or self.format_version != CHECKPOINT_FORMAT_VERSION:
            raise CheckpointEnvelopeError("format_version is unsupported")
        _require_text(self.scope_id, "scope_id", _SCOPE_RE, 128)
        _require_int(self.generation, "generation", minimum=1, maximum=_MAX_SEQUENCE)
        if self.previous_checkpoint_sha256 is not None:
            _require_digest(self.previous_checkpoint_sha256, "previous_checkpoint_sha256")
        if not isinstance(self.registry, StreamPosition) or not isinstance(self.lifecycle, StreamPosition):
            raise CheckpointEnvelopeError("registry and lifecycle must be StreamPosition values")
        _require_int(
            self.supervisor_fencing_epoch, "supervisor_fencing_epoch",
            minimum=0, maximum=_MAX_SEQUENCE,
        )
        _require_text(self.key_id, "key_id", _KEY_ID_RE, 128)
        if type(self.algorithm) is not str or self.algorithm not in SUPPORTED_ALGORITHMS:
            raise CheckpointEnvelopeError("algorithm is not supported")
        _require_int(self.issued_at, "issued_at", minimum=0, maximum=_MAX_SEQUENCE)

    @staticmethod
    def _u64(value: int) -> bytes:
        return struct.pack(">Q", value)

    @staticmethod
    def _lp(value: str) -> bytes:
        raw = value.encode("utf-8")
        return struct.pack(">I", len(raw)) + raw

    def canonical_bytes(self) -> bytes:
        """Fixed-order length-prefixed binary encoding of the complete envelope.

        This is the separately versioned canonical encoding permitted by the
        specification (format v1). It is deterministic for a given envelope and
        domain-separated from any other signed payload.
        """
        previous = (
            b"\x01" + self._lp(self.previous_checkpoint_sha256)
            if self.previous_checkpoint_sha256 is not None
            else b"\x00"
        )
        return b"".join((
            CHECKPOINT_DOMAIN_SEPARATOR,
            self._u64(self.format_version),
            self._lp(self.scope_id),
            self._u64(self.generation),
            previous,
            self._lp(self.registry.database_id),
            self._u64(self.registry.schema_version),
            self._u64(self.registry.sequence),
            self._lp(self.registry.head_sha256),
            self._lp(self.lifecycle.database_id),
            self._u64(self.lifecycle.schema_version),
            self._u64(self.lifecycle.sequence),
            self._lp(self.lifecycle.head_sha256),
            self._u64(self.supervisor_fencing_epoch),
            self._lp(self.key_id),
            self._lp(self.algorithm),
            self._u64(self.issued_at),
        ))

    def to_dict(self) -> dict[str, object]:
        return {
            "format_version": self.format_version,
            "scope_id": self.scope_id,
            "generation": self.generation,
            "previous_checkpoint_sha256": self.previous_checkpoint_sha256,
            "registry_database_id": self.registry.database_id,
            "registry_schema_version": self.registry.schema_version,
            "registry_sequence": self.registry.sequence,
            "registry_head_sha256": self.registry.head_sha256,
            "lifecycle_database_id": self.lifecycle.database_id,
            "lifecycle_schema_version": self.lifecycle.schema_version,
            "lifecycle_sequence": self.lifecycle.sequence,
            "lifecycle_head_sha256": self.lifecycle.head_sha256,
            "supervisor_fencing_epoch": self.supervisor_fencing_epoch,
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "issued_at": self.issued_at,
        }

    @classmethod
    def from_dict(cls, payload: object) -> "CompositeCheckpoint":
        if type(payload) is not dict:
            raise CheckpointEnvelopeError("checkpoint payload must be an object")
        if set(payload) != _ENVELOPE_KEYS:
            raise CheckpointEnvelopeError("checkpoint payload has missing or unknown fields")
        try:
            registry = StreamPosition(
                database_id=payload["registry_database_id"],
                schema_version=payload["registry_schema_version"],
                sequence=payload["registry_sequence"],
                head_sha256=payload["registry_head_sha256"],
            )
            lifecycle = StreamPosition(
                database_id=payload["lifecycle_database_id"],
                schema_version=payload["lifecycle_schema_version"],
                sequence=payload["lifecycle_sequence"],
                head_sha256=payload["lifecycle_head_sha256"],
            )
            return cls(
                format_version=payload["format_version"],
                scope_id=payload["scope_id"],
                generation=payload["generation"],
                previous_checkpoint_sha256=payload["previous_checkpoint_sha256"],
                registry=registry,
                lifecycle=lifecycle,
                supervisor_fencing_epoch=payload["supervisor_fencing_epoch"],
                key_id=payload["key_id"],
                algorithm=payload["algorithm"],
                issued_at=payload["issued_at"],
            )
        except CheckpointEnvelopeError:
            raise
        except (KeyError, TypeError) as exc:
            raise CheckpointEnvelopeError("checkpoint payload fields are invalid") from exc


@dataclass(frozen=True)
class SignedCheckpoint:
    """Envelope plus the signer's opaque signature over its canonical bytes."""

    checkpoint: CompositeCheckpoint
    signature: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.checkpoint, CompositeCheckpoint):
            raise CheckpointEnvelopeError("checkpoint must be a CompositeCheckpoint")
        if not isinstance(self.signature, bytes) or not 1 <= len(self.signature) <= _MAX_SIGNATURE_BYTES:
            raise CheckpointEnvelopeError("signature must be 1 to 512 bytes")


@dataclass(frozen=True)
class StoredCheckpoint:
    """A checkpoint as retained by the external monotonic store."""

    signed: SignedCheckpoint
    scope_id: str
    generation: int
    fencing_epoch: int
    append_timestamp: int

    def __post_init__(self) -> None:
        if not isinstance(self.signed, SignedCheckpoint):
            raise CheckpointEnvelopeError("signed must be a SignedCheckpoint")
        _require_text(self.scope_id, "scope_id", _SCOPE_RE, 128)
        _require_int(self.generation, "generation", minimum=1, maximum=_MAX_SEQUENCE)
        _require_int(self.fencing_epoch, "fencing_epoch", minimum=0, maximum=_MAX_SEQUENCE)
        _require_int(self.append_timestamp, "append_timestamp", minimum=0, maximum=_MAX_SEQUENCE)
        checkpoint = self.signed.checkpoint
        if self.scope_id != checkpoint.scope_id or self.generation != checkpoint.generation:
            raise CheckpointEnvelopeError("stored scope/generation does not match the envelope")
        if self.fencing_epoch != checkpoint.supervisor_fencing_epoch:
            raise CheckpointEnvelopeError("stored fencing epoch does not match the envelope")


@dataclass(frozen=True)
class CheckpointVerificationResult:
    """Verification outcome including unanchored local tail lengths."""

    registry_unanchored: int
    lifecycle_unanchored: int

    def __post_init__(self) -> None:
        _require_int(self.registry_unanchored, "registry_unanchored", minimum=0, maximum=_MAX_SEQUENCE)
        _require_int(self.lifecycle_unanchored, "lifecycle_unanchored", minimum=0, maximum=_MAX_SEQUENCE)


class CheckpointSigner(Protocol):
    """Host-supplied signer; the private key never enters this repository."""

    @property
    def key_id(self) -> str: ...

    @property
    def algorithm(self) -> str: ...

    def sign(self, key_id: str, message: bytes) -> bytes: ...


class CheckpointVerifier(Protocol):
    """Host-supplied verifier; Ed25519 verifiers need only pinned public keys."""

    @property
    def key_id(self) -> str: ...

    @property
    def algorithm(self) -> str: ...

    def verify(self, key_id: str, message: bytes, signature: bytes) -> bool: ...


class CheckpointStore(Protocol):
    """Independently administered monotonic checkpoint store."""

    def read_latest(self, scope_id: str) -> StoredCheckpoint | None: ...

    def read_checkpoint(self, scope_id: str, generation: int) -> StoredCheckpoint | None: ...

    def append_if_generation(
        self,
        scope_id: str,
        expected_generation: int,
        expected_fencing_epoch: int,
        signed: SignedCheckpoint,
    ) -> StoredCheckpoint: ...


class HmacCheckpointSigner:
    """HMAC-SHA-256 signer for host-local non-exportable key services.

    The key must be supplied by the host with at least 32 bytes of entropy and
    is never persisted by this object. Verification also requires the key, so
    this profile is for trusted local verification only, not offline verifiers.
    """

    def __init__(self, key: bytes, key_id: str) -> None:
        if not isinstance(key, bytes) or len(key) < 32:
            raise CheckpointEnvelopeError("HMAC key must be at least 32 bytes")
        object.__setattr__(self, "_key", key)
        object.__setattr__(self, "_key_id", _require_text(key_id, "key_id", _KEY_ID_RE, 128))

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def algorithm(self) -> str:
        return ALGORITHM_HMAC_SHA256

    def sign(self, key_id: str, message: bytes) -> bytes:
        if key_id != self._key_id:
            raise CheckpointError("signer refuses an unauthorized key_id")
        if not isinstance(message, bytes) or not message:
            raise CheckpointError("signer requires non-empty message bytes")
        return hmac.new(self._key, message, hashlib.sha256).digest()


class HmacCheckpointVerifier:
    """Verifier pair for :class:`HmacCheckpointSigner` (trusted local only)."""

    def __init__(self, key: bytes, key_id: str) -> None:
        if not isinstance(key, bytes) or len(key) < 32:
            raise CheckpointEnvelopeError("HMAC key must be at least 32 bytes")
        object.__setattr__(self, "_key", key)
        object.__setattr__(self, "_key_id", _require_text(key_id, "key_id", _KEY_ID_RE, 128))

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def algorithm(self) -> str:
        return ALGORITHM_HMAC_SHA256

    def verify(self, key_id: str, message: bytes, signature: bytes) -> bool:
        if key_id != self._key_id:
            return False
        if not isinstance(message, bytes) or not isinstance(signature, bytes):
            return False
        expected = hmac.new(self._key, message, hashlib.sha256).digest()
        return hmac.compare_digest(expected, signature)


def previous_checkpoint_digest(previous: StoredCheckpoint) -> str:
    """SHA-256 over the previous canonical envelope bytes plus its signature."""
    if not isinstance(previous, StoredCheckpoint):
        raise CheckpointEnvelopeError("previous must be a StoredCheckpoint")
    digest = hashlib.sha256()
    digest.update(previous.signed.checkpoint.canonical_bytes())
    digest.update(previous.signed.signature)
    return digest.hexdigest()


def sign_checkpoint(signer: CheckpointSigner, checkpoint: CompositeCheckpoint) -> SignedCheckpoint:
    """Sign the exact canonical envelope bytes after key/algorithm binding checks."""
    if not isinstance(checkpoint, CompositeCheckpoint):
        raise CheckpointEnvelopeError("checkpoint must be a CompositeCheckpoint")
    if checkpoint.key_id != signer.key_id:
        raise CheckpointError("envelope key_id does not match the signer key_id")
    if checkpoint.algorithm != signer.algorithm:
        raise CheckpointError("envelope algorithm does not match the signer algorithm")
    signature = signer.sign(checkpoint.key_id, checkpoint.canonical_bytes())
    if not isinstance(signature, bytes) or not 1 <= len(signature) <= _MAX_SIGNATURE_BYTES:
        raise CheckpointError("signer returned an invalid signature length")
    return SignedCheckpoint(checkpoint=checkpoint, signature=signature)


def _verify_signature(
    verifier: CheckpointVerifier, signed: SignedCheckpoint, *, expected_scope: str,
) -> None:
    checkpoint = signed.checkpoint
    if checkpoint.scope_id != expected_scope:
        raise CheckpointVerificationError("checkpoint scope does not match the configured scope")
    if checkpoint.algorithm != verifier.algorithm:
        raise CheckpointVerificationError("checkpoint algorithm does not match the verifier algorithm")
    if not verifier.verify(checkpoint.key_id, checkpoint.canonical_bytes(), signed.signature):
        raise CheckpointVerificationError("checkpoint signature is invalid")


def _verify_stream_binding(
    label: str,
    checkpoint_position: StreamPosition,
    local: LocalChainState,
    *,
    unanchored: list[int],
) -> None:
    if local.sequence < checkpoint_position.sequence:
        raise CheckpointVerificationError(
            f"{label} chain is rolled back or truncated behind the checkpoint anchor"
        )
    if local.sequence == checkpoint_position.sequence:
        if local.head_sha256 != checkpoint_position.head_sha256:
            raise CheckpointVerificationError(f"{label} head at the checkpoint anchor differs")
        unanchored.append(0)
        return
    # Local chain advanced past the anchor: the anchored prefix must still
    # contain exactly the checkpointed head, or the tail cannot be trusted.
    if checkpoint_position.sequence == 0:
        anchor_head = _GENESIS_HEAD
    else:
        anchor_head = local.head_at_anchor
    if anchor_head is None:
        raise CheckpointVerificationError(
            f"{label} head at the checkpoint anchor is unavailable for tail validation"
        )
    if anchor_head != checkpoint_position.head_sha256:
        raise CheckpointVerificationError(f"{label} head at the checkpoint anchor differs")
    unanchored.append(local.sequence - checkpoint_position.sequence)


def verify_composite_checkpoint(
    signed: SignedCheckpoint,
    *,
    verifier: CheckpointVerifier,
    expected_scope: str,
    registry: LocalChainState,
    lifecycle: LocalChainState,
    expected_fencing_epoch: int | None = None,
) -> CheckpointVerificationResult:
    """Verify signature and both local-chain bindings for one checkpoint.

    Failures raise :class:`CheckpointVerificationError`; callers must fail
    closed and must not publish or trust an unverified checkpoint.
    """
    if not isinstance(signed, SignedCheckpoint):
        raise CheckpointEnvelopeError("signed must be a SignedCheckpoint")
    if not isinstance(registry, LocalChainState) or not isinstance(lifecycle, LocalChainState):
        raise CheckpointEnvelopeError("registry and lifecycle must be LocalChainState values")
    if type(expected_scope) is not str or not _SCOPE_RE.fullmatch(expected_scope):
        raise CheckpointEnvelopeError("expected_scope is not a valid scope identifier")
    if expected_fencing_epoch is not None:
        _require_int(expected_fencing_epoch, "expected_fencing_epoch", minimum=0, maximum=_MAX_SEQUENCE)
    _verify_signature(verifier, signed, expected_scope=expected_scope)
    checkpoint = signed.checkpoint
    if (
        expected_fencing_epoch is not None
        and checkpoint.supervisor_fencing_epoch != expected_fencing_epoch
    ):
        raise CheckpointVerificationError("checkpoint fencing epoch does not match the host lease")
    unanchored: list[int] = []
    _verify_stream_binding("registry", checkpoint.registry, registry, unanchored=unanchored)
    _verify_stream_binding("lifecycle", checkpoint.lifecycle, lifecycle, unanchored=unanchored)
    return CheckpointVerificationResult(
        registry_unanchored=unanchored[0],
        lifecycle_unanchored=unanchored[1],
    )


def verify_checkpoint_history(
    history: Sequence[StoredCheckpoint],
    *,
    verifier: CheckpointVerifier,
    expected_scope: str,
) -> None:
    """Verify generation continuity, previous-digest links, and every signature."""
    if not isinstance(history, Sequence) or len(history) == 0:
        raise CheckpointVerificationError("checkpoint history is empty")
    previous: StoredCheckpoint | None = None
    for index, stored in enumerate(history):
        if not isinstance(stored, StoredCheckpoint):
            raise CheckpointEnvelopeError("history entries must be StoredCheckpoint values")
        if stored.scope_id != expected_scope:
            raise CheckpointVerificationError("history scope does not match the configured scope")
        expected_generation = 1 if previous is None else previous.generation + 1
        if stored.generation != expected_generation:
            raise CheckpointVerificationError("checkpoint history has a generation gap or replay")
        if previous is None:
            if stored.signed.checkpoint.previous_checkpoint_sha256 is not None:
                raise CheckpointVerificationError("genesis checkpoint must not link a predecessor")
        else:
            expected_link = previous_checkpoint_digest(previous)
            if stored.signed.checkpoint.previous_checkpoint_sha256 != expected_link:
                raise CheckpointVerificationError("checkpoint history link does not match its predecessor")
        _verify_signature(verifier, stored.signed, expected_scope=expected_scope)
        previous = stored


def verify_latest_checkpoint(
    store: CheckpointStore,
    *,
    verifier: CheckpointVerifier,
    expected_scope: str,
    registry: LocalChainState,
    lifecycle: LocalChainState,
    expected_fencing_epoch: int | None = None,
    presented: SignedCheckpoint | None = None,
) -> tuple[StoredCheckpoint, CheckpointVerificationResult]:
    """Read the external latest checkpoint, verify full history, then bind locally.

    The external store — never the database — is the freshness authority: an
    older correctly signed checkpoint presented as ``presented`` is rejected
    when it does not match the store's latest generation and envelope.
    """
    latest = store.read_latest(expected_scope)
    if latest is None:
        raise CheckpointVerificationError("external checkpoint store has no checkpoint for this scope")
    history: list[StoredCheckpoint] = []
    for generation in range(1, latest.generation + 1):
        stored = store.read_checkpoint(expected_scope, generation)
        if stored is None:
            raise CheckpointVerificationError("external checkpoint history has a generation gap")
        history.append(stored)
    if history[-1].signed.checkpoint != latest.signed.checkpoint:
        raise CheckpointVerificationError("external latest checkpoint is inconsistent with its history")
    verify_checkpoint_history(history, verifier=verifier, expected_scope=expected_scope)
    if presented is not None:
        if not isinstance(presented, SignedCheckpoint):
            raise CheckpointEnvelopeError("presented must be a SignedCheckpoint")
        if (
            presented.checkpoint.generation != latest.generation
            or presented.checkpoint != latest.signed.checkpoint
        ):
            raise CheckpointVerificationError("presented checkpoint is not the external latest generation")
    result = verify_composite_checkpoint(
        latest.signed,
        verifier=verifier,
        expected_scope=expected_scope,
        registry=registry,
        lifecycle=lifecycle,
        expected_fencing_epoch=expected_fencing_epoch,
    )
    return latest, result


class InMemoryCheckpointStore:
    """Process-local reference implementation of the store contract.

    It enforces generation compare-and-swap, fencing-epoch monotonicity, and
    immutable retention exactly as the specification requires, but it lives in
    the application process and therefore is NOT an independent trust boundary.
    Hosts must supply an externally administered store for checkpointed mode.
    """

    def __init__(self, *, clock: object | None = None) -> None:
        self._clock = clock if callable(clock) else time.time
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, int], StoredCheckpoint] = {}
        self._latest: dict[str, int] = {}

    def read_latest(self, scope_id: str) -> StoredCheckpoint | None:
        _require_text(scope_id, "scope_id", _SCOPE_RE, 128)
        with self._lock:
            generation = self._latest.get(scope_id)
            if generation is None:
                return None
            return self._rows[(scope_id, generation)]

    def read_checkpoint(self, scope_id: str, generation: int) -> StoredCheckpoint | None:
        _require_text(scope_id, "scope_id", _SCOPE_RE, 128)
        _require_int(generation, "generation", minimum=1, maximum=_MAX_SEQUENCE)
        with self._lock:
            return self._rows.get((scope_id, generation))

    def append_if_generation(
        self,
        scope_id: str,
        expected_generation: int,
        expected_fencing_epoch: int,
        signed: SignedCheckpoint,
    ) -> StoredCheckpoint:
        _require_text(scope_id, "scope_id", _SCOPE_RE, 128)
        _require_int(expected_generation, "expected_generation", minimum=0, maximum=_MAX_SEQUENCE)
        _require_int(expected_fencing_epoch, "expected_fencing_epoch", minimum=0, maximum=_MAX_SEQUENCE)
        if not isinstance(signed, SignedCheckpoint):
            raise CheckpointEnvelopeError("signed must be a SignedCheckpoint")
        checkpoint = signed.checkpoint
        if checkpoint.scope_id != scope_id:
            raise CheckpointEnvelopeError("envelope scope does not match the store scope")
        if checkpoint.generation != expected_generation + 1:
            raise CheckpointConflictError("envelope generation is not the next expected generation")
        if checkpoint.supervisor_fencing_epoch != expected_fencing_epoch:
            raise CheckpointConflictError("envelope fencing epoch does not match the append request")
        with self._lock:
            latest_generation = self._latest.get(scope_id)
            current = latest_generation if latest_generation is not None else 0
            if current != expected_generation:
                raise CheckpointConflictError("checkpoint generation compare-and-swap failed")
            if current > 0:
                previous = self._rows[(scope_id, current)]
                if checkpoint.supervisor_fencing_epoch < previous.fencing_epoch:
                    raise CheckpointConflictError("fencing epoch is older than the latest checkpoint")
                expected_link = previous_checkpoint_digest(previous)
                if checkpoint.previous_checkpoint_sha256 != expected_link:
                    raise CheckpointConflictError("previous-checkpoint digest does not match the store")
            elif checkpoint.previous_checkpoint_sha256 is not None:
                raise CheckpointConflictError("genesis checkpoint must not link a predecessor")
            stored = StoredCheckpoint(
                signed=signed,
                scope_id=scope_id,
                generation=checkpoint.generation,
                fencing_epoch=checkpoint.supervisor_fencing_epoch,
                append_timestamp=int(self._clock()),
            )
            self._rows[(scope_id, checkpoint.generation)] = stored
            self._latest[scope_id] = checkpoint.generation
            return stored
