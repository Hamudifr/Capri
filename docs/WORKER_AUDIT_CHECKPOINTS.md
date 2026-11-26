# Independently Protected Worker Audit Checkpoints

**Status:** architecture proposal; not implemented and not a production-readiness claim  
**Scope:** independent authenticity and anti-rollback checkpoints for the Nexus worker registry and host lifecycle audit stream  
**Related:** issue #246, PR #242, PR #250, `docs/WORKER_SUPERVISOR_RECOVERY.md`

## 1. Current assurance boundary

`SQLiteWorkerRegistry` stores a canonical, unkeyed SHA-256 event chain in the task database. It detects many accidental inconsistencies and partial modifications, but a writer able to rewrite the complete database can recompute the chain and update its head.

Host lifecycle audit events are stored separately in `SQLiteSecurityStore.audit_events`. Their metadata is canonicalized and individually hashed, and SQLite append-only triggers reject ordinary UPDATE/DELETE statements. The lifecycle stream does not currently have an independently authenticated global chain. A privileged database-file writer can replace, remove, reorder, or rebuild rows.

Registry state/event persistence and host lifecycle audit persistence cannot be committed in one SQLite transaction. The pending lifecycle-operation counter makes interrupted operations fail closed, but it does not authenticate history against a privileged database writer.

**Required outcome:** detect rollback, truncation, replay, rewrite, fork, and checkpoint gaps against a trust anchor that an attacker with write access to either SQLite database cannot also rewrite.

Until implemented and deployed, assurance remains trusted-host-local persistence only. Do not describe the unkeyed chain or append-only triggers as independent cryptographic tamper evidence.

## 2. Threat model

### In scope
- An attacker can read, replace, restore, truncate, reorder, or fully rewrite either SQLite database and its WAL/SHM sidecars.
- An attacker can recompute unkeyed SHA-256 digests and rebuild SQLite tables/triggers.
- An operator restores an older valid SQLite backup after the external checkpoint has advanced.
- A crash occurs between registry commit, host audit write, signing, external checkpoint publication, and local acknowledgement.
- Two host processes or supervisors attempt competing checkpoint publications.
- A signing key is rotated, unavailable, revoked, or suspected compromised.

### Out of scope
- A compromised host process authorized to invoke the signer and checkpoint store can potentially create false events and request valid signatures. Preventing this requires stronger host isolation and authorization.
- A compromised signing provider, checkpoint-store administrator, or root of trust is outside this guarantee unless the provider supplies stronger multi-party controls.
- This design does not provide confidentiality, exactly-once external task execution, worker process isolation, or transport authentication.

Every security claim must name the protected assets, attacker privileges, key provider, checkpoint store, and remaining trust assumptions.

## 3. Trust boundaries

Separate three responsibilities:

1. **Event sources:** the task-store worker-registry event chain and the security-store host lifecycle audit stream.
2. **Signing provider:** a host-supplied interface that signs and verifies canonical checkpoint payloads. Production key material is held outside the repository and both SQLite databases. The runtime receives a key identifier and signature, not an exportable secret by default.
3. **Monotonic checkpoint store:** a separate durable service or device that atomically stores the latest checkpoint and rejects stale generations, rollback, and competing updates. Its write authority must not be shared with the SQLite database-file writer.

A local JSON file next to the databases, a table inside either SQLite file, or a key committed to the repository is not an independent trust boundary.

## 4. Canonical checkpoint envelope

A versioned envelope should bind both audit streams and their database identities:

| Field | Meaning |
|---|---|
| `format_version` | Strict checkpoint schema version |
| `checkpoint_id` | Unique identifier |
| `scope_id` | Stable host/installation identity, not a path |
| `generation` | Monotonic compare-and-swap generation |
| `previous_checkpoint_digest` | Digest of prior accepted envelope |
| `registry_database_id` | Stable identity from validated registry metadata |
| `registry_sequence` | Last included registry event sequence |
| `registry_head_sha256` | Last included registry chain head |
| `lifecycle_database_id` | Stable security audit-stream identity |
| `lifecycle_sequence` | Last included lifecycle event sequence |
| `lifecycle_head_sha256` | Head of deterministic lifecycle-event chain |
| `key_id` | Non-secret signing-key identifier |
| `created_at` | Informational UTC timestamp, not ordering authority |

The signature covers the canonical serialization of every field except the signature itself. The monotonic store's generation and compare-and-swap token are authoritative; timestamps alone are not.

### Lifecycle stream requirement

Before checkpointing the lifecycle stream, introduce a deterministic sequence and rolling digest for worker lifecycle events. The fold must bind event identity, order, timestamp, principal, event type, status, error code, resource identifiers, task identifier, and canonical metadata digest. Reject duplicate event IDs, malformed metadata, invalid ordering, and unsupported schema versions.

Do not assume the existing `argument_digest` forms a chain: it currently hashes an individual metadata JSON object, not the preceding lifecycle event.

### Database identity

Each store needs a stable random identity created during safe initialization and validated on every open, backup, and restore. A path is not an identity. A copied database retains its identity so an older snapshot can be recognized against the external checkpoint. Cloning to a new installation requires explicit identity rotation/re-enrolment and a new checkpoint scope.

## 5. Narrow provider interfaces

Suggested conceptual interfaces, not current APIs:

- `CheckpointSigner.sign(key_id, canonical_payload) -> signature`
- `CheckpointVerifier.verify(key_id, canonical_payload, signature) -> bool`
- `MonotonicCheckpointStore.read(scope_id) -> checkpoint | none`
- `MonotonicCheckpointStore.compare_and_swap(scope_id, expected_generation, new_checkpoint) -> accepted | conflict`

The production signer should keep private key material in an OS-managed protected provider, hardware-backed provider, or separately administered signing service. Verification must use a trusted key registry and reject unknown, retired, or revoked key IDs according to the rotation policy.

The monotonic store must support atomic compare-and-swap, durable reads, access control independent of the SQLite writer, and auditable administrative recovery. A mutable local file or object store without conditional writes/monotonic enforcement is insufficient.

A test-only fake provider may be used for deterministic unit and fault-injection tests. It must never be selectable as a production provider by default.

## 6. Publication and crash semantics

SQLite and the external checkpoint store do not share a transaction. The protocol must expose this rather than pretending to offer distributed atomicity.

1. Acquire the host's exclusive supervisor/lifecycle fence. A SQLite write lock is not a multi-step supervisor lease.
2. Ensure no lifecycle operation is pending. Capture a consistent snapshot of both stores while the same fence prevents new writers.
3. Validate schemas, integrity, event sequences/chains, database identities, and reservation projections.
4. Construct the next canonical envelope using the latest externally accepted generation and digest.
5. Sign through the configured provider.
6. Publish with compare-and-swap against the exact prior generation. A conflict is not overwritten; re-read and reconcile.
7. Read back the published checkpoint and verify signature, generation, predecessor, scope, and both stream heads.
8. Only then mark local publication acknowledged. Local acknowledgement is diagnostic metadata, not the root of trust.

### Failure matrix

| Failure point | Required result |
|---|---|
| Before either event store commits | No new checkpoint; inspect operation state before retry |
| Registry event committed, lifecycle audit incomplete | Pending lifecycle marker blocks checkpoint; reconcile first |
| Both stores committed, signer unavailable | Block critical writes or apply an explicitly bounded unanchored-tail policy; never claim the tail authenticated |
| Signature created, external CAS fails | Do not assume publication; re-read and resolve generation conflict |
| External CAS succeeds, process crashes before local acknowledgement | Verify both streams against the external checkpoint, then repair only local acknowledgement metadata |
| Database is behind external checkpoint | Fail closed; rollback/truncation or wrong identity |
| Database is ahead of external checkpoint | Treat the tail as unanchored and untrusted; preserve it and require explicit reconciliation before signing |
| Generation forks or predecessor mismatches | Fail closed; no automatic winner selection |
| External store unavailable | Do not silently downgrade to unkeyed-only mode |
| Key rotated or revoked | Verify historical checkpoints with retained trusted verification material and enforce explicit retirement rules |

A legitimate crash can leave a database tail newer than the last external checkpoint. That tail is indistinguishable from a forged append by the database writer. The safe default is to preserve it and require operator reconciliation. Automatically signing it on restart would erase the distinction the checkpoint is meant to provide.

## 7. Cadence and availability

Per-event publication minimizes the unanchored window but couples lifecycle availability to the external provider. Batching improves throughput but leaves a suffix outside the authenticity guarantee.

Do not select a batching interval without measured event rate, latency budget, and accepted recovery-point objective. The initial production policy should prefer checkpointing every security-critical lifecycle operation. If heartbeats are batched, define maximum unanchored event count and elapsed time; keep the suffix visibly distinct from verified history.

Provider unavailability must not silently switch to a weaker trust mode. A deliberate restricted mode may allow read-only diagnostics, but must not admit new work or mutate security-critical lifecycle state unless the accepted unanchored-tail policy explicitly permits it.

## 8. Key lifecycle

- Provision keys outside source control and both SQLite databases.
- Give each key a stable non-secret key ID and record algorithm/version in the envelope.
- Define creation, activation, rotation, overlap, retirement, revocation, backup, restore, and compromise recovery.
- Retain verification capability for historical checkpoints for the full audit-retention period.
- A new key must not retroactively bless an unverified historical tail.
- Rotation must be checkpointed and bind the prior accepted generation, old key ID, new key ID, and authorization evidence.
- If a key is suspected compromised, stop publication, preserve both databases and external checkpoint history, and perform explicit trust-root recovery. Never rewrite historical signatures in place.

## 9. Required adversarial tests

1. Rewrite every registry event and recompute the unkeyed chain; external verification must fail.
2. Rewrite, delete, reorder, duplicate, or truncate lifecycle events and recompute individual metadata digests; checkpoint verification must fail.
3. Restore a backup older than the latest external checkpoint; startup must reject it.
4. Replay an old valid signed checkpoint; monotonic generation/CAS must reject it.
5. Publish competing checkpoints from different supervisors; only one CAS may succeed.
6. Crash at every publication boundary; restart must distinguish accepted checkpoint, unanchored tail, and incomplete lifecycle operation.
7. Change either database identity, sequence, or head digest; verification must fail.
8. Rotate and revoke keys; unknown/retired key IDs must follow the documented policy.
9. Make signer or checkpoint store unavailable; configured fail-closed policy must be enforced.
10. Corrupt serialization, signature, predecessor digest, scope ID, and generation; verification must fail.
11. Verify backup/restore preserves database identity and chain heads, while intentional clone/re-enrolment creates a new scope.
12. Verify private key material never appears in repository files, SQLite rows, logs, test snapshots, or exception messages.

## 10. Incremental implementation plan

1. **Decision gate:** select signature algorithm/provider, monotonic-store contract, lifecycle chain schema, database identity semantics, and unanchored-tail policy. Record threat model and limitations.
2. **Pure core:** implement canonical envelope encoding, digest calculation, signature verification contract, generation/predecessor validation, and deterministic lifecycle fold. No external provider or production wiring yet.
3. **Persistence:** add strict schema-versioned lifecycle sequence/chain and stable database IDs. Extend backup validation and restore tests. Existing databases must fail closed or use explicit backup-first migration; no silent repair.
4. **Provider adapters:** implement a test fake and one host-supplied production adapter. Keep keys outside SQLite and source control. Add monotonic CAS storage with access control.
5. **Host integration:** fence writers, publish after lifecycle operations, verify on startup, and fail closed on rollback, unanchored tails, provider outages, or ambiguous state.
6. **Adversarial release gate:** pass every test above, supervisor tests in `WORKER_SUPERVISOR_RECOVERY.md`, exact-head quality CI, backup/restore validation, and a documented recovery drill.

## 11. Open decisions

- Which host-managed signer provider exists on the deployment target?
- Which independently administered monotonic checkpoint store is available without a paid dependency?
- Is per-critical-operation checkpointing required, or is a measured bounded unanchored tail acceptable for heartbeat-only events?
- What is the operational policy for a valid database tail newer than the latest external checkpoint after a crash?
- How will installation cloning and disaster recovery re-enrol a new database identity without accepting rollback?

Until these decisions are made and adversarial gates pass, this is a design proposal only. Issue #246 remains open; no production dispatch or cutover is authorized.
