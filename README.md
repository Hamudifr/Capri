# Capri

Capri is a research and execution-assistance project. This repository currently contains the non-X5 recovery foundation; it does not contain an authorized X5 test specification or an X5 execution result.

## Operating principles

- Evidence before claims: distinguish observed facts, hypotheses, plans, and verified outcomes.
- Preserve history: append run records; do not rewrite past results to make a dashboard look healthier.
- Separate evaluation from implementation: a self-assessment is not an independent review.
- Fail closed: unknown, missing, ambiguous, or contaminated inputs do not become passes.
- Protect blind evaluations: X5 instructions, rubrics, expected answers, scoring keys, and protected evidence are out of scope for this repository's ordinary CI.
- Keep canonical Capri skills unchanged unless explicitly authorized.

## Repository map

- `docs/OPERATING_MODEL.md` — scope, evidence rules, release gates, and safety boundaries.
- `docs/RECOVERY_PLAN.md` — ordered recovery work and exit criteria.
- `docs/EVALUATION_DATA_CONTRACT.md` — non-sensitive evaluation record contract.
- `tests/` — local structural checks for the public/non-X5 project shell.
- `.github/workflows/quality.yml` — non-X5 documentation and test checks.

## Current status

The project shell was previously observed to have only a minimal README and no CI workflow. This recovery branch adds a reviewable foundation. It does not assert that Capri's runtime, skills, evaluator, or X5 have been implemented or validated.

## Run checks locally

```bash
python -m unittest discover -s tests -v
```

Python 3.11+ is recommended. CI runs the same checks.

## Change policy

Work on feature branches and review changes before merging to `main`. Never place protected X5 material in this repository, test fixtures, logs, issue bodies, or CI artifacts.
