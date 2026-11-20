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
5. Export a versioned dataset and record its hash and split counts.
6. Train only when suitable no-cost compute and a compatible open-weight model
   are actually available.
7. Evaluate against a frozen, untouched holdout set and adjacent safety cases.
8. Retain an adapter only if the improvement is reproducible and does not
   degrade safety, privacy, or general task performance.

## Current limitations

The module is not yet wired into the task engine or runtime. There is no
automatic event capture, consent UI, PII scanner, dataset signing/version
manager, trainer, adapter registry, or model-serving integration. These must
be implemented as separate, reviewed steps. The Android phone environment is
not assumed to be capable of training a 20B-class model.
