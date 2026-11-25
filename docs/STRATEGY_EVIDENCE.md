# Host strategy evidence attestation

## Status

Adds a host-only attestation primitive for immutable strategy evidence manifests. It is not a data collector, task-family classifier, strategy evaluator, activation grant, or live canary.

## Composition

Construct `HostStrategyEvidenceAuthority` only in trusted host startup code. Supply:

- A host-held `ApprovalMacProvider`.
- An authenticator that derives the collector's principal from a trusted credential.
- An attestor that loads the original evidence manifest, validates its provenance and exact cohort binding, stores it immutably, and returns the SHA-256 digest of the canonical manifest bytes.
- A verifier that reopens the manifest by digest and rechecks the principal, strategy versions, cohort fingerprint/schema, matched-pair count, and host-derived task-family classifications.

Call `issue(credential, StrategyEvidenceContext)` only from the trusted host collector. Pass the resulting token as `evidence_manifest_ref` when registering the candidate, and inject `authority.verify` as `SQLiteStrategyStore.evidence_verifier`. Never expose the authority, MAC provider, credentials, or source-manifest callback as model-visible tools.

## Attestation

The versioned HMAC payload binds key ID, manifest digest, nonce, principal, strategy class, baseline/candidate IDs and versions, cohort SHA-256/schema, and matched-pair count. The token carries the key ID, manifest digest, nonce, and MAC. Verification checks the MAC and then reopens the immutable manifest by digest. Retained keys support verification across rotation.

## Trust boundary and limitations

- The HMAC proves that the trusted host attested to a manifest digest and exact context. It does not make an untrusted collector trustworthy.
- The host attestor must independently authenticate source events, verify that each evidence reference resolves to genuine host records, recompute the exact cohort fingerprint, and derive task-family labels from trusted metadata. Never accept model-supplied outcome claims or a caller-provided digest as source proof.
- The verifier must check the immutable manifest still exists and matches the exact context. If it cannot, it must return literal `False`.
- This attestation does not independently rerun the staged promotion assessment, issue activation grants, route traffic, monitor canaries, or roll back strategies.
- No live strategy activation or routing is performed. No signing key is provisioned by this module.

## Tests

Tests cover principal authentication, exact context binding, manifest revalidation, key rotation, malformed attestor results, and candidate admission through `SQLiteStrategyStore`.

## Immutable manifest storage and backup integrity

The SQLite manifest store binds every duplicated row field to the canonical manifest bytes and SHA-256 digest. Verification rejects cross-principal or cross-context metadata rebinding even if a host source callback is permissive. It also checks canonical observation ordering and enforces the manifest size limit on reads.

When the manifest table exists, SQLiteTaskStore integrity and backup validation checks its required schema, primary/unique constraints, append-only update/delete triggers, canonical manifest digest, row-to-manifest metadata bindings, observation schema/order, recomputed cohort fingerprint and UTC creation timestamp. This is structural integrity validation; the host evidence verifier must still reauthenticate source events and rederive task-family classifications before accepting a manifest.
