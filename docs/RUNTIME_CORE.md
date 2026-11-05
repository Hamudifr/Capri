# Runtime core prototype

This is a deliberately narrow, dependency-free prototype for append-only execution memory and non-protected evaluation metadata. It is not the complete Capri agent runtime and must not be treated as a recovered product specification.

## Components

- `EvaluationRecord`: immutable typed record with stable run/scenario identifiers, controlled status/evaluator/evidence-stage enums, timestamp, evidence reference, and optional retest parent.
- `validate_record`: fail-closed runtime validation, including defensive type checks. Pass/Fail requires a non-empty evidence reference and a stage beyond Not Run/Attempted. Self-scoring cannot claim independent review. Independent evaluation must be represented as Independently Reviewed. Timestamps must be valid ISO 8601 values with an explicit timezone.
- `HashChainLedger`: append-only JSONL storage. Each entry hashes the canonical record plus the previous hash. Both reads and writes validate record structure, evidence-stage consistency, unique run IDs, and retest-parent ordering. It rejects malformed entry shapes, malformed hashes, broken links, invalid records, and tampering.

## Minimal use

```python
from capri_core import (
    EvaluationRecord, EvidenceStage, EvaluatorType,
    HashChainLedger, Status,
)

ledger = HashChainLedger("data/non-x5-runs.jsonl")
record = EvaluationRecord(
    run_id="run-001",
    scenario_id="scenario-alpha",
    dimension="Agency",
    status=Status.PASS,
    evaluator_type=EvaluatorType.SELF,
    evidence_stage=EvidenceStage.SELF_SCORED,
    evidence_ref="evidence://your-authorized-reference",
    run_at="2026-11-05T08:00:00Z",
)
ledger.append(record)
print(ledger.verify())
```

## Integrity and operational limits

The hash chain is tamper-evident, not an access-control system, digital signature, or proof of who authored a record. An attacker able to rewrite the entire file can recompute the chain. Back up the ledger and restrict filesystem access in any deployment.

The implementation uses a process-local thread lock. **Use one writer process per ledger file.** It does not provide cross-process locking, distributed concurrency control, encryption, authentication, authorization, evidence fetching, or retention management. Do not use this prototype as a multi-user production store.

Do not put protected evaluation instructions, rubrics, expected answers, scoring keys, secrets, or personal data in the ledger. Store only authorized references to evidence.

## Validation

Run `python -m unittest discover -s tests -v`. Tests cover valid metadata, missing evidence, evaluator-stage mismatch, invalid field types, timezone enforcement, retest lineage, duplicate identifiers, unknown parents, malformed ledger entries, rehashed invalid records, and tamper detection.

## Remaining runtime gaps

- No runtime orchestration, model/tool adapter, session store, or deployment packaging.
- No independent review is performed by this library.
- The dimension vocabulary is intentionally limited to the six currently documented non-protected dimensions and must be versioned before changing.
- The full runtime behavior must come from an authorized, non-protected specification; this prototype does not invent it.
