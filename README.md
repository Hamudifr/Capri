# Capri

Capri is a research and execution-assistance project. This repository contains a non-X5 recovery foundation and a narrow execution-ledger prototype; it does not contain an authorized X5 test specification or an X5 execution result.

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
- `docs/LEDGER_THREAT_MODEL.md` — explicit trust assumptions, controls, limitations, and operator guidance.
- `capri_core/` — immutable evaluation records, fail-closed validation, and hash-chained append-only ledger.
- `tests/` — deterministic structural and runtime-core tests.
- `.github/workflows/quality.yml` — non-X5 documentation and test checks.

## Current status

The repository now has a reviewable foundation and a small tested execution-ledger prototype. This is not the complete Capri runtime: no authorized runtime specification, model/tool adapter, session orchestration, or deployment design has been recovered. No X5 work is included.

## Run checks locally

```bash
python -m unittest discover -s tests -v
python -m capri_core verify path/to/runs.jsonl
```

Python 3.11+ is supported; CI compiles and tests on Python 3.11, 3.12, and 3.13. The verification command is read-only and requires an existing ledger file.

## Change policy

Work on feature branches and review changes before merging to `main`. Never place protected evaluation material, credentials, personal secrets, or private user data in this repository, test fixtures, logs, issues, or CI artifacts.
