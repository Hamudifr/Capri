# X8.4 strategy evaluation: offline comparison v2

## Status

Implemented as an offline, deterministic comparison primitive, with a principal-scoped registry and host Capri-decided activation/rollback API described in [STRATEGY_REGISTRY.md](STRATEGY_REGISTRY.md). The registry independently recomputes candidate evaluations from supplied observations, binds exact strategy versions and configuration hashes, and keeps an append-only activation history. The active strategy is not automatically consumed by task execution. No model weights, permissions, tool capabilities, budgets, or safety policies are modified.

## Why this slice exists

The X8 roadmap requires Capri to choose future methods using observed success, cost, latency, and risk, while keeping adaptation bounded, explainable, reversible, and auditable. A live adaptive selector would be premature without trustworthy matched outcome data and an explicit host integration boundary.

This first vertical slice establishes the evaluation contract before any strategy can be activated.

## API

Import `StrategyObservation` and `evaluate_strategies` from `capri_core`.

Each observation contains:
- task ID and scenario label;
- strategy ID;
- outcome: `verified_success`, `verified_failure`, or `unverified`;
- a non-empty evidence reference;
- an explicit strategy version (keyword-only in the public constructor, defaulting to `unversioned` for legacy positional callers);
- safety-violation flag;
- tool-call count, context-token count, estimated-cost units, and latency in milliseconds.

The evaluator compares exactly two named strategies: a fixed baseline and one candidate. It requires exactly one version per strategy across the cohort, fingerprints those versions with every observation, requires the exact same task-ID cohort for both strategies, and rejects a task whose scenario labels differ. Legacy offline comparisons may use the default `unversioned` marker; the durable registry rejects it and requires explicit, registered baseline and candidate versions. Duplicate task/strategy observations and malformed records fail closed.

## Decision contract

Default minimum: 20 matched task pairs. This is a conservative operational sample floor, not a statistical-power guarantee.

A candidate is eligible for manual review only when all conditions hold:
1. The cohorts match exactly and the minimum matched-pair count is met.
2. Candidate verified-success rate is no lower than baseline. Unverified outcomes count as not successful.
3. Candidate safety-violation count is no higher than baseline.
4. On every matched task, candidate safety must not regress, a baseline verified success must not become a candidate failure/unverified outcome, and none of the four resource metrics may worsen. This paired non-regression rule prevents aggregate averages from hiding a harmful regression on an individual task.
5. At least one of verified-success outcome, safety outcome, or a resource metric strictly improves on at least one matched task.

Any per-task safety, success, or resource regression blocks eligibility, even if aggregate averages look better. Equal outcomes with no strict improvement do not justify changing strategy. The result includes matched/unmatched counts, both metric summaries, improved dimensions, and stable block reasons. It also includes a SHA-256 fingerprint of the complete validated input cohort.

Estimated-cost units are abstract owner-defined integers, not currency, and the evaluator does not spend money or call a provider. Latency is supplied by the caller; this module does not measure it.

## Cohort fingerprint

Version 2 explicitly includes the exact strategy version in every observation. This corrects the earlier mislabeled-v1 change: v1 represented the pre-versioned observation schema, while v2 represents version-bound observations. Never relabel or recompute historical v1 digests as v2; preserve old records with their original schema identifier.

Each evaluation returns `cohort_sha256`, a lowercase SHA-256 digest over a canonical JSON manifest containing schema version `capri.strategy-cohort.v2`, the baseline and candidate IDs, and every validated observation (including unmatched observations). Records are sorted by strategy ID and task ID, and JSON keys/separators are canonicalized, so input iteration order does not change the digest.

The fingerprint lets a caller bind a saved evaluation result to the exact input values later presented for verification. A changed evidence reference or metric changes the digest. The digest is not a signature, does not prove that evidence references are genuine or immutable, and does not replace preservation/readback of the referenced evidence. The module still does not persist the manifest or observations.

## Interpretation and limits

- This is descriptive evidence from a matched cohort, not a causal proof, confidence interval, statistical significance test, or independent review.
- A 20-pair floor is not enough to establish broad generalization. Evaluate representative scenario classes and repeat the comparison before any production change.
- Evidence references are locators. The caller must preserve and verify the referenced records.
- The module does not persist observations, create a strategy registry, select an active strategy, execute tools, or implement rollback. Its v2 fingerprint is a deterministic integrity identifier, not an authenticated evidence claim. The result is only eligibility for a human-controlled next stage.
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
6. Follow the owner-delegated staged autonomy policy in Capri — Capability Growth & Benchmarking: automatic canary/promotion is permitted only after trusted evidence collection, paired uncertainty estimates, non-authority-changing strategy configs, hard gates, monitoring and tested automatic rollback are implemented end to end.
7. Keep authorization, tool allowlists, spend limits, and safety policy outside the adaptation mechanism and immutable to it.

## Tests

`tests/test_strategy.py` covers matched cohorts, evidence requirements, sample floor, success/safety/resource regressions, malformed inputs, deterministic results, and the absence of an activation side effect. The normal repository quality workflow runs the full unittest suite on Python 3.15 only.
