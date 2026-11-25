# Strategy promotion assessment v1

## Status

Implemented as a pure offline eligibility evaluator. It does not collect or authenticate evidence, issue activation grants, select a strategy, route live tasks, change permissions, or perform a canary. A positive result means only that supplied records satisfy this assessment contract.

## API

Import `PromotionCohort` and `assess_strategy_canary` from `capri_core`.

Each cohort contains an immutable tuple of `StrategyObservation` records for exactly one baseline and one candidate. The host must first load and verify the source journal, authenticate its provenance, and classify the task family. Do not construct these records directly from model assertions or aggregate Observatory summaries.

## Fixed policy gates

The policy thresholds are constants, not caller-configurable:

- At least two independent cohorts.
- At least 100 matched task pairs in each cohort.
- At least five scenarios in each cohort, with at least 20 matched pairs per scenario.
- Disjoint task IDs and evidence references across cohorts.
- Explicit, identical baseline and candidate versions across cohorts; `unversioned` records are not eligible.
- Strategy class must be one of `formatting`, `planning`, `reasoning`, `retrieval`, or `tool_routing`.
- Host-classified task family must be one of `coding`, `formatting`, `general_qa`, `research`, `retrieval`, `summarization`, or `writing`. High-stakes task families are deliberately absent.
- Existing evaluator hard gates apply to every task: no safety regression, no loss of a baseline verified success, and no worsening of tool calls, context tokens, estimated cost units, or latency on any matched task.
- A stratified paired-bootstrap 95% percentile interval for the declared primary metric must have a strictly positive lower bound in every cohort. Supported primary metrics are verified success rate, safety violations, tool calls, context tokens, estimated cost units, and latency.

Bootstrap uses 5,000 deterministic resamples within each scenario. The cohort ordering is canonicalized by cohort ID so reordering the input collection does not change the result. The seed is fixed by policy version, sorted cohort position, and primary metric, rather than chosen from evidence values.

## Interpretation

A passing assessment is eligible for the next host-controlled canary gate only. It is not an activation grant or proof that a canary was actually run. The trusted host must independently verify journal integrity and provenance, enforce the task-family classification, bind the exact strategy/config/evaluation hashes to a short-lived principal-scoped grant, route no more than 5% of eligible low-risk tasks, monitor outcomes, preserve the baseline, and automatically roll back on a hard-gate breach.

This evaluator does not implement the later full-promotion gate. Full promotion requires at least 200 actual canary tasks across two independent windows, verified by the host, with all hard gates and improvement evidence still passing.

## Statistical and security limitations

- Percentile bootstrap intervals are approximate. They are not a causal proof, a guarantee of future performance, or a substitute for representative data.
- The 5,000-resample deterministic procedure is intended for reproducibility and screening, not adversarial cryptographic randomness.
- Cohort IDs, task-family labels, evidence references, and observations are caller-supplied values. The evaluator cannot authenticate them.
- Disjoint identifiers reduce accidental overlap but do not prove independent sampling or genuine execution.
- A malicious or biased host can fabricate evidence. Production integration must use authenticated host events, immutable journal verification, privacy screening, and an independently trusted task-family classifier.
- The module is not wired into the task engine. No strategy has been activated by this code.

## Tests

`tests/test_strategy_promotion.py` covers two-cohort eligibility, deterministic order-independent results, minimum cohort/scenario coverage, confidence-interval rejection, per-task resource regression, version consistency, task-family allowlisting, and evidence separation.
