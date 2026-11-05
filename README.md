# Capri

Capri is a research and execution-assistance project. This repository contains a non-X5 recovery foundation, a narrow execution-ledger prototype, and a minimal provider-neutral session runtime foundation; it does not contain an authorized X5 test specification or an X5 execution result.

## Operating principles

- Evidence before claims: distinguish observed facts, hypotheses, plans, and verified outcomes.
- Preserve history: append run records; do not rewrite past results to make a dashboard look healthier.
- Separate evaluation from implementation: a self-assessment is not an independent review.
- Fail closed: unknown, missing, ambiguous, or contaminated inputs do not become passes.
- Protect blind evaluations: protected instructions, rubrics, expected answers, scoring keys, and evidence are out of scope for ordinary repository work and CI.
- Keep canonical Capri skills unchanged unless explicitly authorized.

## Repository map

- `docs/OPERATING_MODEL.md` — scope, evidence rules, release gates, and safety boundaries.
- `docs/RECOVERY_PLAN.md` — ordered recovery work and exit criteria.
- `docs/EVALUATION_DATA_CONTRACT.md` — non-sensitive evaluation record contract.
- `docs/RUNTIME_CORE.md` — narrow runtime-core prototype, API, limitations, and tests.
- `docs/NON_X5_RUNTIME_SPEC_TEMPLATE.md` — product-owner specification template; blank decisions remain blockers.
- `docs/NON_X5_RUNTIME_DESIGN.md` — conservative proposed defaults and implemented runtime slice.
- `docs/SECURITY_REVIEW.md` — non-X5 trust boundaries, verified controls, unresolved risks, and required abuse-case tests.
- `docs/LEDGER_THREAT_MODEL.md` — ledger-specific security assumptions, bounded parsing, and crash behavior.
- `docs/LEDGER_OPERATIONS.md` — backup verification, integrity-incident response, and controlled recovery runbook.
- `docs/LEDGER_SCALING_DECISION.md` — proposed transactional storage migration, explicitly not implemented.
- `capri_core/` — immutable evaluation records, fail-closed validation, and hash-chained append-only ledger.
- `capri_runtime/` — in-memory session lifecycle and injected model-adapter boundary; no tools or durable memory.
- `tests/` — deterministic structural, ledger, and runtime tests.
- `.github/workflows/quality.yml` — non-X5 documentation and test checks.

## Current status

The repository has a reviewable foundation, a tested execution-ledger prototype, and a minimal provider-neutral runtime slice. Ledger access rejects observed symlinks and non-regular paths, uses no-follow directory traversal where supported, and syncs the parent directory on first file creation; platform fallback and uncertain-write limitations are documented in the threat model. Ledger entries are limited to 1 MiB by default (configurable per `HashChainLedger` instance); each JSONL record must end with a newline, and incomplete tails fail closed. Verification and append remain linear scans with an in-memory run-ID set, and the ledger supports only one writer process. The runtime currently supports in-memory sessions and an injected text adapter only. It does not include a concrete model provider, tool execution, durable memory, authentication, cross-process storage, or deployment packaging. These are explicit gaps, not implied capabilities. No X5 work is included.

## Run checks locally

```bash
python -m compileall -q capri_core capri_runtime tests
python -m unittest discover -s tests -v
python -m capri_core verify path/to/runs.jsonl
```

Python 3.11+ is supported; CI compiles and tests on Python 3.11, 3.12, and 3.13. The verification command is read-only and requires an existing ledger file.

## Change policy

Work on feature branches and review changes before merging to `main`. Never place protected evaluation material, credentials, personal secrets, or private user data in this repository, test fixtures, logs, or CI artifacts.
