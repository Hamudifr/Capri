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
- Each bundle is registered in the same local SQLite store before publication.
  SQLite foreign-key enforcement binds each registry dependency to an existing
  export and consent record. The registry tracks `publishing`, `active`, `invalidated`, or `failed` state;
  publication uses a same-directory no-overwrite hard link. A crash or uncertain
  publication remains non-active and therefore fails closed. If the file is
  published but final registry activation cannot be confirmed, the API raises
  `LearningExportOutcomeUncertainError` with `export_id` and `path`; callers
  can use `get_export_status()` and `verify_export()` to reconcile without
  blindly repeating the export.
- Revoking any contributing consent transactionally marks every registered
  dependent bundle invalidated. `verify_export()` checks registry state,
  bundle hash, manifest identity, and dataset hash, then re-reads registry status
  after file verification so a revocation committed during inspection is observed.
  That final status read is the verification linearization point. Downstream consumers must
  call this verifier against the authoritative store before use; a copied ZIP
  alone cannot carry or enforce revocation, and an unavailable registry means
  the bundle must not be treated as verified.
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
automatic event capture, consent UI, PII scanner, dataset signing/version
manager, trainer, adapter registry, or model-serving integration. The consent
and privacy-review booleans remain per-example attestations; the new consent
ledger adds provenance and revocation but does not itself authenticate the
person granting consent or recall previously exported files. These capabilities
must be implemented as separate, reviewed steps. The Android phone environment
is not assumed to be capable of training a 20B-class model.
