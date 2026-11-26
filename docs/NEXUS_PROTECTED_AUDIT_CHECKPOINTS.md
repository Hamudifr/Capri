# Nexus Independently Protected Audit Checkpoints

**Status:** architecture proposal; not implemented and not production authorization  
**Scope:** independent authenticity and rollback detection for the durable Nexus worker-registry audit stream  
**Tracker:** [issue #246](https://github.com/Hamudifr/Capri/issues/246)  
**Related:** [worker registry design](superpowers/specs/2026-11-25-sqlite-worker-registry.md), [supervisor recovery contract](WORKER_SUPERVISOR_RECOVERY.md), [security review](SECURITY_REVIEW.md)

## 1. Decision summary

Retain the existing SQLite SHA-256 event chain as an efficient local consistency mechanism, but do not treat it as an authenticity boundary against an attacker who can rewrite the complete database.

Add a host-integrated checkpoint layer with two independent trust dependencies:

1. A **signer** whose private key is not available to the SQLite database writer or stored in the repository/database.
2. A **monotonic external checkpoint store** whose latest generation cannot be rolled back by an attacker who can modify only the local database.

Prefer an Ed25519 signing provider when the host can keep the private key in a KMS/HSM or other protected signer. Verifiers need only pinned public keys, so they do not receive signing authority. Permit HMAC-SHA-256 as an alternative where the host's protected key service supports non-exportable MAC keys and trusted verification; never copy the shared key into the SQLite database or repository.

This is an interface and trust-boundary decision, not a request to provision a cloud service, buy a KMS, or add a runtime dependency. A host may supply an existing free/local signer and an independently administered checkpoint store. If no external signer and store are configured, report the audit mode as **host-local consistency only** and keep the current production-readiness restriction.

## 2. Threat model

### Protected assets

- The ordered Nexus worker-registry event history.
- The relationship between event sequence, event hash and the current registry projection.
- Evidence that a database has not been rolled back behind a previously acknowledged checkpoint.
- Key identity, key lifecycle metadata and checkpoint generation.

### In-scope attacker

An attacker can read, copy, replace, truncate or rewrite the local SQLite task database, including its registry rows, audit events, triggers, metadata and unkeyed hash-chain head. The attacker may recompute a self-consistent unkeyed chain after changing the file.

The attacker cannot:
- access the external signing key or invoke the signer outside its authorization policy;
- modify the separately administered monotonic checkpoint store;
- replace the verifier's pinned trust roots or trusted key registry.

### Out of scope

Compromise of the host kernel/root account together with the signer identity and external checkpoint-store credentials; compromise of the external trust service itself; denial of service; confidentiality/encryption of SQLite backups; malicious authorized operators; correctness of worker identity or task outcomes. These require separate controls.

A signature proves that the configured signer authorized a checkpoint payload. It does not prove that the payload was truthful, that the signer observed every event, or that the worker/task system behaved correctly.

## 3. Trust architecture

```text
SQLite registry + audit chain
          |
          | sequence + chain head
          v
Host checkpoint coordinator
          |                         |
          | sign canonical payload   | append with compare-and-swap
          v                         v
Protected signer                 External monotonic checkpoint store
(private key outside DB)         (append-only / generation fenced)
          |                         |
          +-----------+-------------+
                      |
                      v
              Independent verifier
       (pinned public keys + latest checkpoint)
```

The SQLite database remains the source of detailed event data. The external store is the source of the latest trusted checkpoint position. The signer authenticates checkpoint contents. Neither external component may be implemented by another table in the same SQLite file.

### Required interfaces

The runtime should depend on narrow host-supplied protocols, not a cloud-vendor SDK:

- `CheckpointSigner.sign(key_id, message) -> signature`
- `CheckpointVerifier.verify(key_id, message, signature) -> bool` (or a verifier service when using HMAC)
- `CheckpointStore.read_latest(stream_id) -> checkpoint | None`
- `CheckpointStore.append_if_generation(stream_id, expected_generation, checkpoint) -> stored_checkpoint`

The external store must provide atomic compare-and-swap or equivalent conditional append. A plain mutable object key without conditional writes, retention protection or access separation is insufficient. The signer must enforce which stream, key ID and operation are authorized; model output and database content cannot select arbitrary signing keys or request signatures.

No secret, private key, HMAC key, bearer token, KMS credential or raw reservation token is stored in the checkpoint or database.

## 4. Checkpoint envelope

Use a versioned, domain-separated payload. At minimum it binds:

| Field | Meaning |
|---|---|
| `format_version` | Checkpoint envelope version |
| `stream_id` | Stable logical audit stream identifier |
| `database_id` | Random immutable identifier created with the registry schema |
| `schema_version` | Worker-registry schema version |
| `generation` | Monotonic checkpoint-store generation |
| `event_sequence` | Highest included event sequence |
| `event_head_sha256` | Hash of the event at that sequence |
| `previous_checkpoint_sha256` | Digest of the immediately previous signed checkpoint, or a defined genesis value |
| `key_id` | External signer key identifier |
| `algorithm` | Explicit signature/MAC algorithm identifier |
| `issued_at` | Trusted signer/coordinator timestamp, informational rather than the rollback control |

The signed bytes are a canonical serialization of the complete envelope, prefixed with a fixed domain separator such as:

`capri:nexus:audit-checkpoint:v1\0`

Use [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785) or a separately versioned canonical binary encoding. Do not assume Python's `json.dumps(sort_keys=True)` is automatically RFC 8785 compliant. Reject duplicate keys, invalid Unicode, non-finite numbers, unknown fields and unsupported versions before signing or verification. Keep numeric fields within a precisely specified integer range.

The external store retains the exact signed envelope, signature, generation and append timestamp. The database may retain only a non-authoritative cache/reference to the latest checkpoint; verification must always consult the external latest checkpoint.

### Cross-store host lifecycle audit coverage

The registry event chain is not the only worker audit source. Host lifecycle events are written separately to `SQLiteSecurityStore.audit_events`. Those rows currently have canonical per-event metadata digests and append-only triggers, but they do not form an independently authenticated global chain. A checkpoint that binds only `worker_registry_events` must be described as authenticating only that stream; it must not imply that the host lifecycle audit history is also protected.

If the production security claim covers the complete worker lifecycle, extend the envelope to a composite checkpoint with both store identities and both stream positions:

- `registry_database_id`, `registry_schema_version`, `registry_sequence`, `registry_head_sha256`
- `lifecycle_database_id`, `lifecycle_schema_version`, `lifecycle_sequence`, `lifecycle_head_sha256`

The lifecycle stream needs its own deterministic sequence and rolling digest. Each chained record should bind the event ID, event order, timestamp, principal, event type, status, error code, resource type/ID, task ID, and canonical metadata digest. Do not treat the current per-row `argument_digest` as a chain. A dedicated worker-lifecycle chain table/state row or equivalent strictly validated schema may implement this; backup validation, integrity checks, and restore semantics must cover it.

Both database identities must be stable, random installation identities. A filesystem path is not an identity. A copied database retains its identity for rollback detection; intentional installation cloning requires explicit re-enrolment and a new checkpoint scope.

### Consistent cross-store snapshot

The two SQLite stores cannot be read as one atomic transaction. Before signing a composite checkpoint:

1. Acquire the embedding host's exclusive supervisor/lifecycle fence. SQLite transaction locking alone does not prevent another host process from interleaving a multi-store operation.
2. Quiesce all registry and lifecycle writers under that fence.
3. Confirm the security store has zero pending lifecycle-operation markers and that the host's reservation/audit reconciliation is healthy.
4. Capture and validate both stream identities, sequences, and heads while no writer can mutate either store.
5. Sign and publish the composite envelope with external generation compare-and-swap.
6. Read back and verify the external checkpoint before releasing the fence.

If registry persistence commits but its corresponding host lifecycle event does not, the pending operation marker must block checkpoint publication. If the external checkpoint is published but local acknowledgement fails, startup must verify the external checkpoint against both stores and repair only local diagnostic state. If either store is ahead of the checkpoint, that suffix remains unanchored and requires explicit reconciliation; do not silently sign it during restart.

The checkpoint store's compare-and-swap prevents competing checkpoint generations, but it does not replace the host-level fencing lease. A lease/fencing epoch should be supplied by the embedding host and included in the checkpoint or its authenticated metadata when the deployment supports multiple supervisors.

## 5. Checkpoint creation and atomicity

A checkpoint cannot be made atomic with a local SQLite commit and a remote signing/store operation. The coordinator must therefore expose and test the crash windows rather than pretending there is a distributed transaction.

Recommended sequence:

1. Read and validate the local audit chain and projection under a stable SQLite read snapshot.
2. Capture `(database_id, schema_version, event_sequence, event_head_sha256)`.
3. Construct the next generation using the latest externally stored checkpoint.
4. Ask the host signer to sign the domain-separated canonical envelope.
5. Append it to the external store with `expected_generation` equal to the latest observed generation.
6. On compare-and-swap conflict, discard the candidate, reload the latest checkpoint and retry only after revalidating the local chain. Never overwrite or replace a newer checkpoint.
7. Read back the external checkpoint and verify its signature and fields before reporting success.

A crash before external append leaves no new checkpoint. A crash after append but before local acknowledgement is recoverable by reading the external latest checkpoint and matching its sequence/head to the local chain. An ambiguous timeout must be reconciled by reading the store, not by blindly appending another generation.

### Checkpoint cadence and unanchored tail

A signed checkpoint protects history only through its `event_sequence`. Events after that sequence remain protected only by the existing unkeyed local chain until a later checkpoint is committed.

- **High assurance:** checkpoint every security-sensitive lifecycle transaction before acknowledging that operation to its caller.
- **Batched mode:** permit a bounded event/time lag only when the host explicitly accepts the maximum unanchored tail and the runtime exposes that lag in health state.
- If the external signer/store is unavailable, do not silently downgrade a configured checkpointed deployment to local-only mode. Fail closed for operations whose policy requires an externally anchored audit record; preserve the local event and expose a reconciliation-required state.
- No universal checkpoint interval is selected here. The host owner must choose it from the tolerated loss/tamper window and measured service availability.

## 6. Verification and rollback rules

Given a database and the latest external checkpoint:

1. Authenticate the external store response and verify the checkpoint signature/MAC using the key identified by `key_id`.
2. Verify stream ID, database ID, schema version, format version and algorithm against the expected deployment.
3. Verify that the database chain is structurally valid and that the event at `event_sequence` has exactly `event_head_sha256`.
4. Reject if the database sequence is lower than the checkpoint sequence (rollback/truncation), or if the hash at the checkpoint sequence differs.
5. Verify the local event chain from the checkpoint anchor through the current local head. Any gap, duplicate sequence, invalid previous hash or projection mismatch fails closed.
6. Verify the checkpoint generation and previous-checkpoint digest against the external store's authoritative ordered history or authenticated latest record.
7. Reject an older signed checkpoint presented as the latest. A valid signature alone does not establish freshness.

The database must not be allowed to nominate its own trusted checkpoint or public key. The verifier obtains the latest checkpoint from the separate trust store and trust roots from host configuration.

### Backup and restore

A backup carries the same immutable `database_id` and local event chain. Restore validation compares it with the external latest checkpoint:

- Backup behind the latest checkpoint: reject as stale; do not lower the external generation.
- Backup exactly at the checkpoint: accept only if the sequence and head match exactly.
- Backup ahead of the checkpoint: verify the anchored prefix, then validate the local tail. The tail remains unanchored until a new checkpoint is committed.
- Database ID mismatch: reject unless an explicit clone/re-key procedure creates a new stream identity and new external trust history.
- External checkpoint store unavailable: checkpointed mode cannot claim successful authenticity verification. Preserve the backup and stop protected writes until verification is possible.

Never reset the external checkpoint store because a restored database appears older. Recovery must preserve the highest trusted generation.

## 7. Key lifecycle

### Ed25519 preferred profile

- Private signing key generated and retained by a host-managed protected signer.
- Public verification key distributed to authorized verifiers through a separately authenticated trust configuration.
- Each checkpoint includes a stable `key_id`; the database contains no private material.
- Historical public keys remain available for verification after signing rotation.

[RFC 8032](https://www.rfc-editor.org/rfc/rfc8032) specifies EdDSA and describes Ed25519's nominal 128-bit security level. Use a vetted provider implementation; do not implement curve arithmetic in Capri.

### HMAC-SHA-256 alternative

[RFC 2104](https://www.rfc-editor.org/rfc/rfc2104) defines HMAC as keyed message authentication. Use a cryptographically random key with sufficient entropy, held in a non-exportable host-managed key service. Because verification also requires the symmetric key, do not distribute it to offline verifiers. Prefer a trusted verification service or Ed25519 where independent offline verification is required.

### Rotation, retirement and compromise

- Rotation is an externally recorded trust transition, not a mutable database setting.
- The new key becomes active only after a rotation record is authenticated by the currently trusted key (or by an out-of-band trust-root ceremony).
- Record old/new key IDs, algorithm, activation generation, retirement policy and authorized operator in the external trust store.
- Retain old public verification keys for historical checkpoints. Retired keys must not sign new checkpoints.
- HMAC keys must remain available to the trusted verifier for the required retention period, or be rewrapped/retired under an explicit policy.
- On suspected compromise: stop checkpoint acceptance under the compromised key, preserve all stores, identify the last known-good external checkpoint, rotate from an uncompromised trust root, mark the uncertain interval, and perform a documented recovery. Never silently re-sign old history as though it had always been trusted.

NIST [SP 800-57 Part 1 Rev. 5](https://csrc.nist.gov/pubs/sp/800/57/pt1/r5/final) provides key-management guidance, including protection, lifecycle and compromise recovery. This design does not claim certification or regulatory compliance.

## 8. Failure and recovery matrix

| Failure | Required behavior |
|---|---|
| Signer unavailable before signing | No checkpoint success; retain local audit state; protected operation remains pending |
| External store unavailable | No silent downgrade; checkpointed mode reports unavailable and blocks protected acknowledgement |
| Timeout after external append | Read latest and reconcile by generation/idempotency; never blindly duplicate |
| CAS conflict from another supervisor | Reload latest, revalidate chain, then retry with a new generation |
| Signature invalid or unknown key ID | Fail closed; preserve evidence; do not import the checkpoint |
| External generation regresses | Treat as trust-store rollback/compromise; stop |
| Database sequence below latest checkpoint | Reject database/backup as stale or truncated |
| Database head at anchor differs | Reject tampered or wrong database |
| Local tail after anchor is invalid | Reject; do not repair or truncate |
| Old valid checkpoint replayed | Reject because it is not the external latest generation |
| Key rotation interrupted | Resolve from external rotation state; accept neither uncommitted key state nor a fallback key |
| Signer key suspected compromised | Freeze, preserve evidence, rotate trust root, classify affected interval as suspect |
| Checkpoint provider removed from configuration | Do not silently downgrade an already checkpointed stream to local-only |

## 9. Required tests before implementation acceptance

Use deterministic fake signer and checkpoint-store adapters in offline CI. Test the production interface contract without storing real keys or invoking paid services.

1. Valid checkpoint signs and verifies the exact canonical payload.
2. Change every signed field independently; verification fails.
3. Alter a local event, recompute the unkeyed chain and metadata head; anchored verification still fails.
4. Restore a backup whose sequence is below the latest external checkpoint; verification rejects rollback.
5. Truncate events before the checkpoint sequence; verification rejects.
6. Change the event hash at the checkpoint sequence; verification rejects.
7. Append a valid local tail after the checkpoint and verify it is reported as unanchored until a new checkpoint.
8. Replay an older correctly signed checkpoint; external latest-generation check rejects it.
9. Race two writers/supervisors for one generation; exactly one compare-and-swap succeeds.
10. Crash before append, after append, and before local acknowledgement; recovery converges without duplicate or regressing generations.
11. Inject signer/store timeouts and verify idempotent reconciliation rather than blind retry.
12. Rotate keys; new checkpoints use the new key while old checkpoints remain verifiable.
13. Revoke a key and verify the policy distinguishes historical verification from new signing.
14. Simulate key compromise and verify the affected interval is marked suspect rather than silently re-signed.
15. Clone a database ID and verify stream binding prevents cross-stream checkpoint acceptance.
16. Remove the signer/store configuration from a checkpointed deployment; no silent local-only downgrade.

## 10. Incremental implementation plan

1. **Contracts and data model:** add typed signer, verifier and checkpoint-store protocols plus immutable envelope validation. No real key provider.
2. **Verifier first:** verify external latest checkpoint against a local chain; add rollback/tamper tests using deterministic fakes.
3. **Checkpoint writer:** implement generation-fenced append, idempotent timeout recovery and explicit checkpoint health state.
4. **Host integration:** require explicit policy for local-only versus checkpointed mode; no implicit downgrade. Bind signer permissions and supervisor identity at the embedding-host boundary.
5. **Rotation and restore:** implement authenticated trust transitions, backup/restore validation and compromise recovery.
6. **Operational evidence:** document checkpoint lag, external store retention, backup drills, alerting and outage procedures. Run exact-head quality tests and a separate security review.

Do not implement all phases in one patch. Each phase needs its own reviewable interface, failure tests and compatibility decision.

## 11. Release boundary

Until the external signer, monotonic checkpoint store, verifier, key lifecycle and adversarial tests are implemented and configured:

- The existing SQLite SHA-256 chain remains **host-local consistency/tamper-evidence only**.
- Do not claim independent cryptographic authenticity, rollback protection or immutable audit storage.
- Do not enable worker dispatch or production cutover.
- No KMS/HSM, cloud service, paid dependency, key provisioning or production secret is included in this proposal.
- The host owner must explicitly approve any paid service, secret provisioning, production integration or deployment.

## References

- [RFC 8032 — Edwards-Curve Digital Signature Algorithm](https://www.rfc-editor.org/rfc/rfc8032)
- [RFC 2104 — HMAC: Keyed-Hashing for Message Authentication](https://www.rfc-editor.org/rfc/rfc2104)
- [RFC 8785 — JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)
- [NIST SP 800-57 Part 1 Rev. 5 — Recommendation for Key Management](https://csrc.nist.gov/pubs/sp/800/57/pt1/r5/final)
