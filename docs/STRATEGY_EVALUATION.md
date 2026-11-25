# X8.4 strategy evaluation: offline comparison v1

## Status

Implemented as an offline, deterministic comparison primitive. It is not connected to the task engine and does not change the active strategy. No model weights, permissions, tool capabilities, or safety policies are modified.

## Why this slice exists

The X8 roadmap requires Capri to choose future methods using observed success, cost, latency, and risk, while keeping adaptation bounded, explainable, reversible, and auditable. A live adaptive selector would be premature without trustworthy matched outcome data and an explicit host integration boundary.

This first vertical slice establishes the evaluation contract before any strategy can be activated.

## API

Import `StrategyObservation`, `evaluate_strategies`, and `verify_strategy_evaluation` from `capri_core.strategy`.

Each observation contains:
- task ID and scenario label;
- strategy ID;
- outcome: `verified_success`, `verified_failure`, or `unverified`;
- a non-empty evidence reference;
- safety-violation flag;
- tool-call count, context-token count, estimated-cost units, and latency in milliseconds.

The evaluator compares exactly two named strategies: a fixed baseline and one candidate. It requires the exact same task-ID cohort for both strategies and rejects a task whose scenario labels differ. Duplicate task/strategy observations and malformed records fail closed.

## Decision contract

Default minimum: 20 matched task pairs. This is a conservative operational sample floor, not a statistical-power guarantee.

A candidate is eligible for manual review only when all conditions hold:
1. The cohorts match exactly and the minimum matched-pair count is met.
2. Candidate verified-success rate is no lower than baseline. Unverified outcomes count as not successful.
3. Candidate safety-violation count is no higher than baseline.
4. On every matched task, candidate safety must not regress, a baseline verified success must not become a candidate failure/unverified outcome, and none of the four resource metrics may worsen. This paired non-regression rule prevents aggregate averages from hiding a harmful regression on an individual task.
5. At least one of verified-success outcome, safety outcome, or a resource metric strictly improves on at least one matched task.

Any per-task safety, success, or resource regression blocks eligibility, even if aggregate averages look better. Equal outcomes with no strict improvement do not justify changing strategy. The result includes the configured `min_pairs` floor, matched/unmatched counts, both metric summaries, improved dimensions, and stable block reasons. It also includes a SHA-256 fingerprint of the complete validated input cohort.

Estimated-cost units are abstract owner-defined integers, not currency, and the evaluator does not spend money or call a provider. Latency is supplied by the caller; this module does not measure it.

## Cohort fingerprint

Each evaluation returns `cohort_sha256`, a lowercase SHA-256 digest over a canonical JSON manifest containing schema version `capri.strategy-cohort.v1`, the baseline and candidate IDs, and every validated observation (including unmatched observations). Records are sorted by strategy ID and task ID, and JSON keys/separators are canonicalized, so input iteration order does not change the digest.

The fingerprint lets a caller bind a saved evaluation result to the exact input values later presented for verification. A changed evidence reference or metric changes the digest. The digest is not a signature, does not prove that evidence references are genuine or immutable, and does not replace preservation/readback of the referenced evidence. The module still does not persist the manifest or observations.

## Rechecking a saved result

`verify_strategy_evaluation(evaluation, observations, expected_min_pairs=None)` reruns the deterministic evaluator over the supplied observations and compares the complete derived result, including the cohort fingerprint, metrics, block reasons, eligibility flag, and stored sample floor. This detects a changed observation or an altered saved result. Supply `expected_min_pairs` from the caller's independent policy when the sample floor itself must be fixed; otherwise the verifier uses the floor stored in the evaluation.

This is a consistency check, not an authenticity mechanism. It does not sign the record, identify its author, establish evidence-source integrity, or prevent an attacker from changing both inputs and result. Preserve evidence separately and use a trusted signature or protected audit store if authenticity is required.

## Interpretation and limits

- This is descriptive evidence from a matched cohort, not a causal proof, confidence interval, statistical significance test, or independent review.
- A 20-pair floor is not enough to establish broad generalization. Evaluate representative scenario classes and repeat the comparison before any production change.
- Evidence references are locators. The caller must preserve and verify the referenced records.
- The module does not persist observations, create a strategy registry, select an active strategy, execute tools, or implement rollback. The result is only eligibility for a human-controlled next stage.
- The module does not infer a utility weighting between quality and resource use. It uses explicit non-inferiority gates and Pareto-style dominance to avoid hidden trade-offs.
- Do not use self-reported model confidence as an outcome. Record independently verifiable task results and the evidence supporting them.
- Do not include prompts, conversation bodies, secrets, or personal data in strategy observations or evidence references.

## Future integration gates

Before wiring this into a runtime selector:
1. Define a host-owned, principal-scoped strategy registry and append-only decision history.
2. Define stable strategy versions and task-class eligibility. Never mix incomparable versions.
3. Collect consent-appropriate, privacy-screened, evidence-backed outcomes.
4. Add a shadow evaluator that records what it would choose without changing execution.
5. Evaluate across multiple representative cohorts and include uncertainty estimates and safety-specific scenarios.
6. Require explicit owner/host approval for activation; preserve the previous strategy and a tested rollback path.
7. Keep authorization, tool allowlists, approvals, spend limits, and safety policy outside the adaptation mechanism and immutable to it.

## Tests

`tests/test_strategy.py` covers matched cohorts, evidence requirements, sample floor, success/safety/resource regressions, malformed inputs, deterministic results, and the absence of an activation side effect. The normal repository quality workflow runs the full unittest suite across Python 3.11–3.15.
