# Capri

Capri is a research and execution-assistance project. This repository contains a non-X5 recovery foundation, a narrow execution-ledger prototype, and a minimal provider-neutral session runtime foundation; it does not contain an authorized X5 test specification or an X5 execution result.

## Operating principles

- Evidence before claims: distinguish observed facts, hypotheses, plans, and verified outcomes.
- Preserve history: append run records; do not rewrite past results to make a dashboard look healthier.
- Capri performs and documents its own engineering/security reviews; external independent review is not a prerequisite for ordinary internal implementation or merging. Never mislabel self-review as independent assurance.
- Fail closed: unknown, missing, ambiguous, or contaminated inputs do not become passes.
- Protect blind evaluations: protected instructions, rubrics, expected answers, scoring keys, and evidence are out of scope for ordinary repository work and CI.
- Add or improve Capri skills when a concrete capability gap justifies them; the owner has explicitly authorized this, and each skill must have a clear purpose and validation path.

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

`main` now contains the integrated non-X5 recovery foundation: a hardened append-only ledger (bounded JSONL parsing, private file permissions, symlink/path checks, crash-durability handling, hard-link/inode uncertainty latching), read-only Capri Doctor diagnostics, dependency-aware operational health, and a provider-neutral in-memory session runtime. The runtime enforces input/output/history limits both at the Runtime boundary and at direct SessionStore commits. Post-merge CI run [42281548990](https://github.com/Hamudifr/Capri/actions/runs/42281548990) passed 114 tests on each actual Python 3.11, 3.12, and 3.13 interpreter; Doctor 6/6 and operational health 7/7. The ledger remains plaintext and single-writer; the runtime still has no concrete provider, permissioned tool execution, durable memory, host authentication/tenant isolation, or deployment packaging. These are explicit next capabilities, not implied features. No X5 work is included.

## Run checks locally

Run the read-only repository diagnostic before making changes:

```bash
python -m capri_core doctor
```

It checks required project files, Python version, pinned external CI actions, minimal workflow permissions, and recovery-branch CI triggers under the actual top-level `push` and `pull_request` events. Duplicate top-level `on:` blocks or duplicate direct event mappings fail closed, as do unsupported trigger forms. The check is deliberately narrow, not a general YAML parser. Its report also includes a dependency-aware operational health graph; use `--json` to consume it programmatically. It reads only those known project files and does not inspect transcripts, credentials, or arbitrary repository contents. Use `--root PATH` to check another working tree. Add `--json` for a versioned machine-readable report (`schema_version: 1`) with per-check status and aggregate counts.


```bash
python -m compileall -q capri_core capri_runtime tests
python -m unittest discover -s tests -v
python -m capri_core verify path/to/runs.jsonl
```

Python 3.11+ is supported; CI compiles and tests on Python 3.11, 3.12, and 3.13. The verification command is read-only and requires an existing ledger file.

## Change policy

Use feature branches for isolation, perform Capri's own design/security/code review, run and inspect CI, then merge completed compatible work into `main`. Do not leave validated work stranded in Draft PRs indefinitely. Never place protected evaluation material, credentials, personal secrets, or private user data in this repository, test fixtures, logs, or CI artifacts.
