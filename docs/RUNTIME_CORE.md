# Runtime core prototype

This is a deliberately narrow, dependency-free prototype for append-only execution memory and non-protected evaluation metadata. It is not the complete Capri agent runtime and must not be treated as a recovered product specification.

## Components

- `EvaluationRecord`: immutable typed record with stable run/scenario identifiers, controlled status/evaluator/evidence-stage enums, timestamp, evidence reference, and optional retest parent.
- `validate_record`: fail-closed validation. A Pass/Fail needs an evidence reference and captured evidence stage. Self-scoring cannot claim independent review. Independent evaluation must be explicitly represented as Independently Reviewed. Timestamps must include a timezone.
- `HashChainLedger`: append-only JSONL storage. Each entry hashes the canonical record plus the previous hash. It rejects duplicate run IDs, unknown retest parents, malformed entries, broken links, and tampering.

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

Do not put protected evaluation instructions, rubrics, expected answers, scoring keys, secrets, or personal data in the ledger. Store only authorized references to evidence. The hash chain is tamper-evident, not an access-control system or a digital signature; an attacker able to rewrite the entire file can recompute it. Back up the ledger and restrict filesystem access in any deployment.

## Validation

Run `python -m unittest discover -s tests -v`. The tests cover valid metadata, missing evidence, evaluator-stage mismatch, timezone enforcement, retest lineage, duplicate identifiers, unknown parents, and tamper detection.

## Known limitations

- No multi-process file lock or distributed concurrency control; use a single writer.
- No encryption, authentication, authorization, evidence fetching, or retention policy.
- No runtime orchestration, model/tool adapter, session store, or deployment packaging.
- No independent review is performed by this library.
- The dimension vocabulary is intentionally limited to the six currently documented non-protected dimensions and must be versioned before changing.
