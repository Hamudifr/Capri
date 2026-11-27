# Nexus Independently Protected Audit Checkpoints

**Status:** architecture proposal; local lifecycle-chain phase 1 is implemented in Draft PR #269; external signing/checkpoint trust is not implemented and this is not production authorization  
**Scope:** independent authenticity and rollback detection for both durable Nexus registry events and host lifecycle audit events  
**Tracker:** [issue #246](https://github.com/Hamudifr/Capri/issues/246)  
**Related:** [worker registry design](superpowers/specs/2026-11-25-sqlite-worker-registry.md), [supervisor recovery contract](WORKER_SUPERVISOR_RECOVERY.md), [security review](SECURITY_REVIEW.md)

## 1. Decision summary

Retain the existing SQLite SHA-256 event chain as an efficient local consistency mechanism, but do not treat it as an authenticity boundary against an attacker who can rewrite the complete database.

Add a host-integrated checkpoint layer with two independent trust dependencies:

1. A **signer** whose private key is not available to the SQLite database writer or stored in the repository/database.
2. A **monotonic external checkpoint store** whose latest generation cannot be rolled back by an attacker who can modify only the local database.

Prefer an Ed25519 signing provider when the host can keep the private key in a KMS/HSM or other protected signer. Verifiers need only pinned public keys, so they do not receive signing authority. Permit HMAC-SHA-256 as an alternative where the host's protected key service supports non-exportable MAC keys and trusted verification; never copy the shared key into the SQLite database or repository.

The production target is a **composite worker-lifecycle checkpoint** that binds both the durable registry event stream and the separate host lifecycle audit stream. A registry-only checkpoint may be used for a narrowly labelled registry-integrity claim, but it does not satisfy the complete worker-lifecycle authenticity gate in issue #246. The two stores must be captured under one exclusive host-level supervisor fence.

This is an interface and trust-boundary decision, not a request to provision a cloud service, buy a KMS, or add a runtime dependency. A host may supply an existing free/local signer and an independently administered checkpoint store. If no external signer and store are configured, report the audit mode as **host-local consistency only** and keep the current production-readiness restriction.

**Decision record (2026-11-27, PR #265 merged as `93572dd`):** the two trust dependencies above are now decided and implemented — (1) the **signer** profile is Ed25519 via the host-protected `CheckpointSigner` interface, with an HMAC-SHA-256 non-exportable local-only fallback whose key never leaves the host process; key material is never provisioned by this repository and never stored in SQLite. (2) The **monotonic store** is an independently administered local checkpoint store outside the application database, with atomic compare-and-swap on generation and immutable checkpoint retention; fencing epochs are bound into the signed envelope. These choices were made and merged by Capri under the owner's sole decision-maker directive of the same day ("only Capri makes the choices") — no owner sign-off gate exists between Capri and the audit-checkpoint roadmap. Platform red lines (no spending, no paid KMS, no credential requests) still apply: both trust dependencies must remain free/local or already-provisioned host resources.

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
- `CheckpointStore.read_latest(scope_id) -> checkpoint | None`
- `CheckpointStore.read_checkpoint(scope_id, generation) -> checkpoint | None` (or an authenticated append-only history iterator)
- `CheckpointStore.append_if_generation(scope_id, expected_generation, expected_fencing_epoch, checkpoint) -> stored_checkpoint`

The external store must provide atomic compare-and-swap or equivalent conditional append, immutable retention of prior signed records, and a monotonic fencing-epoch check. Generation CAS alone is insufficient: a stale supervisor that still holds signing credentials must not be able to append a higher generation after losing its lease. The signer or checkpoint store must authenticate the current lease epoch and reject an epoch older than the latest accepted epoch. A plain mutable object key without conditional writes, retention protection or access separation is insufficient. The signer must enforce which scope, key ID, fencing epoch and operation are authorized; model output and database content cannot select arbitrary signing keys or request signatures.

No secret, private key, HMAC key, bearer token, KMS credential or raw reservation token is stored in the checkpoint or database.

## 4. Checkpoint envelope

Use a versioned, domain-separated **composite** payload. At minimum it binds:

| Field | Meaning |
|---|---|
| `format_version` | Checkpoint envelope version |
| `scope_id` | Stable logical scope, e.g. `nexus-worker-lifecycle-v1` |
| `generation` | Monotonic checkpoint-store generation |
| `previous_checkpoint_sha256` | Digest of the immediately previous signed checkpoint, or a defined genesis value |
| `registry_database_id` | Random immutable installation ID for the task/registry SQLite store |
| `registry_schema_version` | Worker-registry schema version |
| `registry_sequence` | Highest included registry-event sequence |
| `registry_head_sha256` | Hash of the registry event at that sequence |
| `lifecycle_database_id` | Random immutable installation ID for the security/audit SQLite store |
| `lifecycle_schema_version` | Security/lifecycle schema version |
| `lifecycle_sequence` | Highest included host-lifecycle audit sequence |
| `lifecycle_head_sha256` | Hash of the lifecycle event at that sequence |
| `supervisor_fencing_epoch` | Authenticated host lease epoch; required where multiple supervisors can write |
| `key_id` | External signer key identifier |
| `algorithm` | Explicit signature/MAC algorithm identifier |
| `issued_at` | Trusted signer/coordinator timestamp, informational rather than the rollback control |

The signed bytes are a canonical serialization of the complete envelope, prefixed with a fixed domain separator such as:

`capri:nexus:audit-checkpoint:v1\0`

Use [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785) or a separately versioned canonical binary encoding. Do not assume Python's `json.dumps(sort_keys=True)` is automatically RFC 8785 compliant. Reject duplicate keys, invalid Unicode, non-finite numbers, unknown fields and unsupported versions before signing or verification. Keep numeric fields within a precisely specified integer range.

The external store retains the exact signed envelope, signature, generation, fencing epoch and append timestamp as immutable history. Define `previous_checkpoint_sha256` as SHA-256 over the canonical envelope bytes concatenated with the signature bytes of the immediately previous checkpoint; the genesis value is explicitly null (or a fixed versioned genesis digest). The database may retain only a non-authoritative cache/reference to the latest checkpoint; verification must always consult the external latest checkpoint and authenticated history when validating generation continuity or key transitions.

### Cross-store host lifecycle audit coverage

The registry event chain is not the only worker audit source. Host lifecycle events are written separately to `SQLiteSecurityStore.audit_events`. Draft PR [#269](https://github.com/Hamudifr/Capri/pull/269) now adds a local deterministic sequence and rolling SHA-256 chain to this stream, binding event identity/order, timestamp, principal, event type, status, error/resource/task fields and the canonical metadata digest. It routes ordinary writes and supervisor reconciliation acknowledgements through the same atomic append helper, and validates the chain at startup, during integrity checks and during backup validation. This local unkeyed chain detects inconsistent/partial rewriting, but does not authenticate history against a privileged writer able to rewrite the complete database and recompute the chain. A checkpoint that binds only `worker_registry_events` must still be described as authenticating only that stream; it must not imply that the host lifecycle audit history is independently protected.

The production target is the composite envelope shown above, with both store identities and both stream positions. Do not mark the complete worker-lifecycle audit gate satisfied until both streams are chained and checkpointed.

The local lifecycle chain phase 1 is implemented in Draft PR #269 (exact head `db4f42d60419cc4e6fb00685f4fa373150c87118`; Repository Quality run 45888281284 passed 1,055 tests). It uses chain columns on `audit_events` plus a singleton state row, strict sequence/index/trigger validation, and atomic append/head updates. The per-row `argument_digest` remains a separate event-field digest, not the chain. Backup and integrity validation are covered; paired cross-store restore semantics remain unimplemented. This local chain is not an external authenticity anchor.

Both database identities must be stable, random installation identities. A filesystem path is not an identity. A copied database retains its identity for rollback detection; intentional installation cloning requires explicit re-enrolment and a new checkpoint scope.

### Consistent cross-store snapshot

The two SQLite stores cannot be read as one atomic transaction. Before signing a composite checkpoint:

1. Acquire the embedding host's exclusive supervisor/lifecycle fence. SQLite transaction locking alone does not prevent another host process from interleaving a multi-store operation.
2. Quiesce all registry and lifecycle writers under that fence.
3. Confirm the security store has zero pending lifecycle-operation markers and that the host's reservation/audit reconciliation is healthy.
4. Capture and validate both stream identities, sequences, and heads while no writer can mutate either store.
5. Sign and publish the composite envelope with external generation compare-and-swap.
6. Read back and verify the external checkpoint before releasing the fence.

If registry persistence commits but its corresponding host lifecycle event does not, the pending operation marker must block checkpoint publication. If the external checkpoint is published but the coordinator crashes before returning success, startup must read the external latest checkpoint and verify it against both stores; it must not re-sign, lower the generation, or silently repair event history. If either store is ahead of the checkpoint, that suffix remains unanchored and requires explicit reconciliation; do not silently sign it during restart.

The checkpoint store's compare-and-swap prevents competing checkpoint generations, but it does not replace the host-level fencing lease. Where multiple supervisors can write, a verifiable lease/fencing epoch from the embedding host is mandatory and must be included in the signed checkpoint. The current note-based `acknowledge_worker_lifecycle_reconciliation()` API is not itself a lease provider or proof of lease ownership.

## 5. Checkpoint creation and atomicity

A checkpoint cannot be made atomic with a local SQLite commit and a remote signing/store operation. The coordinator must therefore expose and test the crash windows rather than pretending there is a distributed transaction.

Recommended sequence:

1. Acquire the embedding host's exclusive supervisor/lifecycle fence and quiesce every writer to both SQLite stores.
2. Confirm the lifecycle audit store has zero pending operation markers and that worker reservation reconciliation is healthy.
3. Read and validate both local chains and their registry/audit projections under stable read snapshots while the fence prevents cross-store interleaving.
4. Capture both stream identities, schema versions, sequences and heads into one composite envelope.
5. Construct the next generation using the latest externally stored checkpoint and the authenticated fencing epoch.
6. Ask the host signer to sign the domain-separated canonical envelope.
7. Append it to the external store with `expected_generation` equal to the latest observed generation.
8. On compare-and-swap conflict, discard the candidate, reload the latest checkpoint and retry only after revalidating both local chains under the fence. Never overwrite or replace a newer checkpoint.
9. Read back the external checkpoint and verify its signature and every field before reporting success; only then release the host fence.

A crash before external append leaves no new checkpoint. A crash after append but before local acknowledgement is recoverable by reading the external latest checkpoint and matching both stream positions/heads to the two local stores. An ambiguous timeout must be reconciled by reading the store, not by blindly appending another generation. A pending host lifecycle-operation marker blocks checkpoint publication.

### Checkpoint cadence and unanchored tail

A signed composite checkpoint protects each stream only through its respective `registry_sequence` and `lifecycle_sequence`. Events after either anchor remain protected only by the local unkeyed chain until a later composite checkpoint is committed.

- **High assurance:** checkpoint every security-sensitive lifecycle transaction before acknowledging that operation to its caller.
- **Batched mode:** permit a bounded event/time lag only when the host explicitly accepts the maximum unanchored tail and the runtime exposes that lag in health state.
- If the external signer/store is unavailable, do not silently downgrade a configured checkpointed deployment to local-only mode. Fail closed for operations whose policy requires an externally anchored audit record; preserve the local event and expose a reconciliation-required state.
- No universal checkpoint interval is selected here. The host owner must choose it from the tolerated loss/tamper window and measured service availability.

## 6. Verification and rollback rules

Given both SQLite stores and the latest external checkpoint:

1. Authenticate the external store response and verify the checkpoint signature/MAC using the key identified by `key_id`.
2. Verify scope ID, format version, algorithm, supervisor fencing epoch policy, and both database identities/schema versions against the expected deployment.
3. Verify that each database chain is structurally valid and that the event at `registry_sequence` / `lifecycle_sequence` has exactly the corresponding anchored head hash.
4. Reject if either database sequence is lower than its checkpoint sequence (rollback/truncation), or if either hash at its checkpoint sequence differs.
5. Verify each local event chain from its checkpoint anchor through its current local head. Any gap, duplicate sequence, invalid previous hash or projection mismatch fails closed.
6. Verify the checkpoint generation and previous-checkpoint digest against the external store's authoritative ordered history or authenticated latest record.
7. Reject an older signed checkpoint presented as the latest. A valid signature alone does not establish freshness.
8. Reject a mixed backup/restore pair whose database IDs, lifecycle state, pending-operation markers or cross-store sequence relationship do not match one consistent fenced snapshot.

The databases must not be allowed to nominate their own trusted checkpoint or public key. The verifier obtains the latest checkpoint from the separate trust store and trust roots from host configuration.

### Backup and restore

A restore set contains both the task/registry database and the security/lifecycle database captured under the same exclusive host fence. Each carries its immutable installation ID and local chain. Restore validation compares the pair with the external latest composite checkpoint:

- Missing one store, mismatched capture identity, inconsistent lifecycle/registry operation markers or an unfenced mixed-time pair: reject.
- Either backup behind its corresponding latest checkpoint: reject as stale; do not lower the external generation.
- Both backups exactly at the checkpoint: accept only if both sequence/head pairs and database IDs match exactly.
- One or both backups ahead of the checkpoint: verify both anchored prefixes, then validate both local tails and their cross-store lifecycle markers. The tails remain unanchored until a new composite checkpoint is committed under the host fence.
- Either database ID mismatch: reject unless an explicit clone/re-enrolment procedure creates new identities for both stores and a new external trust history.
- External checkpoint store unavailable: checkpointed mode cannot claim successful authenticity verification. Preserve both backups and stop protected writes until verification is possible.

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
17. Tamper with a host lifecycle audit row and recompute its per-row `argument_digest`; composite verification still fails.
18. Insert, delete or reorder lifecycle rows; deterministic lifecycle-chain validation fails.
19. Leave a worker lifecycle operation marker pending after a registry commit; composite checkpoint publication is blocked.
20. Interleave a registry write between the two store snapshots; the exclusive host fence prevents publication of a mixed-time checkpoint.
21. Restore task/registry and security/lifecycle backups from different snapshots; restore validation rejects the pair.
22. Supply an older supervisor fencing epoch; the host/signing boundary rejects the stale supervisor.

## 10. Incremental implementation plan

1. **Lifecycle chain first (phase 1 drafted):** PR #269 adds the deterministic local sequence/hash chain, strict schema validation, append-only enforcement, integrity checks and backup validation. Remaining work is paired cross-store restore semantics and an independently protected composite checkpoint.
2. **Contracts and data model:** add typed signer, verifier and checkpoint-store protocols plus immutable composite-envelope validation. No real key provider.
3. **Verifier first:** verify the external latest composite checkpoint against both local chains; add rollback, tamper, mixed-backup and cross-store consistency tests using deterministic fakes.
4. **Checkpoint writer:** implement generation-fenced append, idempotent timeout recovery and explicit checkpoint health state.
5. **Host integration:** require explicit policy for local-only versus checkpointed mode; no implicit downgrade. Acquire an enforceable supervisor fencing lease and capture both stores under one exclusive host fence.
6. **Rotation and restore:** implement authenticated trust transitions, paired backup/restore validation and compromise recovery.
7. **Operational evidence:** document checkpoint lag, external store retention, backup drills, alerting and outage procedures. Run exact-head quality tests and a separate security review.

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
