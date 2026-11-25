# Capri Learning Engine v1

## Purpose

A local, auditable pipeline that turns carefully approved task outcomes into
candidate training examples. It is a data-curation and evaluation foundation,
not a self-modifying hosted model and not an automatic training service.

## Current implementation

- Standard-library-only SQLite journal; no new runtime dependency.
- Explicit consent, human privacy review, and non-sensitive classification are
  mandatory before raw prompt/completion text is stored.
- Each record carries task identity, capability, outcome, evidence reference,
  quality score, source, and schema version.
- Failed and unverified outcomes remain available for analysis but are never
  exported as positive supervised fine-tuning examples.
- Export defaults to quality >= 0.90, supports a capability allowlist, removes
  exact prompt/completion duplicates, and assigns deterministic task-level train,
  validation, and test splits so examples from one task cannot cross partitions.
- Exported examples retain evidence references and stable identifiers.

## Private storage and export

- On POSIX hosts, the store creates its database file with mode `0600` inside an
  owner-only (`0700`) directory. Existing database files must be regular files
  owned by the current user with mode `0600`; symlinks are rejected. The target
  directory must be owner-only, and path ancestors must be owned by root/current
  user and not group/other writable unless sticky-bit protection applies.
  Existing destination directories must also be owner-only.
- Non-POSIX hosts fail closed because this module cannot verify equivalent ACL
  privacy with portable standard-library checks.
- JSONL export is written to a same-directory temporary file with mode `0600`,
  flushed and file-synced, then atomically published with a hard link that
  refuses to replace an existing file or follow an existing destination symlink.
  The containing directory is synced after publication. Unsupported hard-link
  or directory-sync behavior fails visibly; if directory sync fails after the
  link, the complete file may exist but its durability is uncertain.
- Files remain plaintext. Private permissions are not encryption, secure
  deletion, backup protection, or a substitute for host-level storage controls.

## Consent provenance and revocation

- Each admitted example must reference an active `LearningConsent` record with
  the single supported scope `curated_training_examples`, a policy version,
  a bounded evidence reference, and a timezone-aware grant timestamp.
- Consent records deliberately omit subject names, email addresses, account
  identifiers, raw consent text, and other personal identifiers. The host owns
  the consent interaction and must create the record only after an explicit
  user action; this library does not present a consent UI.
- Exported JSONL includes the consent ID and policy version so downstream
  artifacts retain a traceable authorization reference.
- Revocation is transactional: the consent is marked revoked and all source
  examples bound to it are deleted from the local learning database. New
  admissions and future exports exclude revoked consent.
- Existing databases are migrated by adding a consent reference. Legacy examples
  without a verifiable consent record remain stored for review but are excluded
  from future exports; they must be explicitly re-admitted under a new consent
  record rather than inheriting the old boolean attestation.
- Revocation cannot recall files already exported outside this store.
  New ZIP bundles contain a versioned manifest, a SHA-256 hash of the JSONL
  dataset, the bundle's stable export ID, row/split counts, and the contributing
  consent IDs and policy versions.
- Both standalone `export_jsonl()` artifacts and ZIP bundles are registered in
  the same local SQLite store before publication. The registry records artifact
  kind, final path, staging path, SHA-256, manifest metadata and every contributing
  consent ID. SQLite foreign-key enforcement binds each dependency to an existing
  export and consent record. Publication uses a same-directory no-overwrite hard
  link. The registry tracks `publishing`, `active`, `invalidated`, or `failed`.
- A crash or uncertain publication remains non-active and therefore fails
  closed. `reconcile_pending_exports()` verifies the exact published artifact,
  re-fsyncs its directory, rechecks consent dependencies inside a write
  transaction, and activates only a still-publishing artifact whose bytes and
  provenance match the registry. Missing, corrupt, legacy pathless or otherwise
  unverifiable pending artifacts become failed; revoked dependencies remain
  invalidated. Stale private staging files are cleaned only when their path
  matches the recorded artifact sibling. Recovery is idempotent.
- If an artifact is published but final registry activation cannot be confirmed,
  the API raises `LearningExportOutcomeUncertainError` with `export_id` and
  `path`; callers must inspect `get_export_status()`, run
  `reconcile_pending_exports()`, and call `verify_export()` before reuse.
- Revoking any contributing consent transactionally marks every registered
  dependent JSONL or ZIP artifact invalidated. `verify_export()` checks the
  artifact hash, JSONL/ZIP structure, manifest identity, dataset hash and exact
  consent dependencies, then re-reads registry status after file verification
  so a concurrent revocation is observed. That final status read is the
  verification linearization point. Downstream consumers must call this verifier
  against the authoritative store before use; a copied file alone cannot carry
  or enforce revocation, and an unavailable registry means the artifact must
  not be treated as verified.
- This is application-level deletion, not a guarantee of forensic secure
  erasure from filesystem blocks, snapshots, backups, or external copies.

## Non-goals and safety

- This does not alter GPT-6 or any hosted model's weights.
- No model is trained, downloaded, deployed, or called by this module.
- Do not ingest full conversations by default. Never ingest credentials,
  personal secrets, health records, financial account data, or protected/private
  material. Obtain explicit consent and perform a human privacy review for each
  example before admission.
- The privacy-review flag is an operator attestation, not an automated PII
  detector. It does not guarantee text is anonymized.
- Do not export examples with merely plausible or unverified outcomes.
- Do not train on test-split examples. Keep a frozen holdout set and compare a
  candidate model against the untuned baseline on identical tasks.
- Do not auto-promote or auto-deploy an adapter. Require measured gains and no
  safety regressions; preserve rollback to the baseline.

## Data lifecycle

1. Observe a task result and preserve the original evidence separately.
2. Decide whether the result is suitable and whether the user has consented to
   training use.
3. Review and redact the prompt/completion manually; reject sensitive material.
4. Record the example with a stable ID and evidence reference.
5. Publish a versioned ZIP bundle with a content-hashed manifest and a
   local consent-dependency registry; verify registry status before downstream use.
6. Train only when suitable no-cost compute and a compatible open-weight model
   are actually available.
7. Evaluate against a frozen, untouched holdout set and adjacent safety cases.
8. Retain an adapter only if the improvement is reproducible and does not
   degrade safety, privacy, or general task performance.

## Current limitations

The module is not yet wired into the task engine or runtime. There is no
automatic event capture, consent UI, production consent-evidence verifier,
PII scanner, dataset signing/version manager, trainer, adapter registry, or
model-serving integration. `record_consent()` now fails closed unless the
trusted host application injects a `consent_verifier` at `LearningStore`
construction; false results or verifier exceptions reject the grant. The
`evidence_ref` string is only a locator, never proof by itself. The injected
verifier must authenticate a real affirmative grant from a trusted consent
capture system. The library does not identify the human or independently
prove that consent was obtained. The `privacy_reviewed` flag remains an
operator attestation, not an automated PII detector. Revocation invalidates
registered local artifacts but cannot recall copies already distributed outside
the store. These capabilities require a reviewed host integration. The Android
phone environment is not assumed to be capable of training a 20B-class model.

## Export lifecycle and consent evidence hardening — 2026-11-24

- Standalone JSONL export is no longer an untracked side path. It now creates a
  registry record before publishing, records the exact contributing consent
  dependencies and artifact hash, and returns an `export_id`. Revoking any
  contributing consent marks the JSONL export invalidated just like a ZIP bundle.
  The artifact remains on disk; consumers must call `verify_export()` against
  the authoritative local registry before use.
- Both JSONL and ZIP exports persist their final destination and staging paths.
  `reconcile_pending_exports()` handles interrupted `publishing` rows:
  verify the artifact and manifest, fsync the directory, remove a matching
  private staging sibling, and activate only after rechecking consent state in
  a SQLite write transaction. Missing or corrupt artifacts fail closed. Legacy
  pending rows without a recorded destination cannot be recovered and are marked
  failed. Revoked artifacts remain invalidated.
- Consent recording now requires a trusted verifier injected by the host
  application. The default is deny. A caller-supplied evidence reference is
  not accepted as authentication. The host verifier must validate an actual
  signed or otherwise authenticated consent grant from its trusted capture
  workflow. No production consent capture/verifier integration exists yet, so
  no real user consent can currently be recorded through the default store.
- No real user data was used. These changes do not recall copies already
  distributed outside the local store and do not authorize training or
  deployment.


## Host-side authenticated consent authority

`capri_runtime.HostLearningConsentAuthority` provides the reusable signing and
verification primitive for an embedding application. It does not create a UI
or an identity provider. The host must keep the authority and its key server-side,
authenticate the request credential, and implement the confirmation callback
so it returns the literal `True` only after an explicit affirmative action
bound to that authenticated session and the exact consent scope/policy version.
The host callback must enforce its normal CSRF/request-integrity and session
controls. Never wire this callback to a model tool, a client-supplied boolean,
or an unauthenticated endpoint.

Example host composition:

```python
from capri_core.learning import LearningStore
from capri_runtime import HostLearningConsentAuthority

consent_authority = HostLearningConsentAuthority(
    signing_key=load_host_secret("CAPRI_LEARNING_CONSENT_HMAC_KEY"),
    authenticate=authenticate_request_credential,
    confirm_explicit_consent=confirm_server_validated_user_action,
)
learning_store = LearningStore(
    "/private/capri/learning.sqlite3",
    consent_verifier=consent_authority.verify,
)

# Call only from the host's authenticated consent-confirmation route,
# after its UI has obtained an explicit affirmative user action.
consent = consent_authority.issue(
    request_credential,
    consent_id=create_server_side_consent_id(),
    scope="curated_training_examples",
    policy_version="learning-consent-v1",
)
learning_store.record_consent(consent)
```

The HMAC covers the consent ID, exact scope, policy version, grant timestamp,
and a random nonce. Evidence contains no principal ID or raw consent text;
tampering or use with another signing key fails verification. The LearningStore
primary key rejects exact-record replay. The signing key must be at least 32
random bytes, stored outside source control, and backed up/rotated under the
host's secret-management policy. Key rotation requires retaining the relevant
verification keys or an explicit migration policy for existing evidence.

**Integration boundary:** this library now supplies the host-side authority
primitive and tests, but the repository still has no production consent UI,
identity-provider implementation, HTTP route, CSRF/session middleware, or
deployed secret management. The callbacks are trusted application code, not
proof supplied by this package. Do not enable real-data learning until an actual
host application wires and independently tests those controls. The default
LearningStore remains fail-closed when no verifier is injected.

## SQLite backup, integrity and restore

`LearningStore.backup_to(destination)` creates a consistent SQLite online backup of all four
Learning Engine tables: `learning_examples`, `learning_consents`, `learning_exports`,
and `learning_export_consents`. The destination parent must already exist and be private.
The backup is created with owner-only permissions, validated before atomic no-overwrite
publication, and includes committed SQLite state without copying live WAL sidecars.

Backup validation checks SQLite integrity and foreign keys, then verifies the application
invariants for consent timestamps and scope, example admission flags and content hashes,
export manifests and hashes, and export-to-consent dependencies. An active export cannot
reference revoked consent. Legacy examples without a consent ID remain preserved but are
not eligible for export; their historical content hashes are not reinterpreted.

A database backup does **not** contain the separately published JSONL or ZIP artifact files.
To restore, open the backup file as a new store:

```python
restored = LearningStore(
    "/private/backup/learning-backup.sqlite3",
    consent_verifier=trusted_consent_authority.verify,
)
assert restored.integrity_check() == "ok"
```

Back up the artifact files separately. After restore, consumers must call
`verify_export(export_id, artifact_path)` against the restored registry before using any
artifact. Missing or mismatched files fail closed. Do not treat a SQLite backup alone as a
portable training dataset.
