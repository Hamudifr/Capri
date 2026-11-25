# Strategy promotion assessment v1

## Status

Implemented as a pure offline eligibility evaluator plus a host-controlled persistence/binding layer. The pure evaluator does not collect or authenticate evidence or issue grants. `SQLiteStrategyStore` can independently recompute and persist eligible multi-cohort assessments after a trusted evidence verifier authenticates every cohort, and a host-issued HMAC grant can bind that exact assessment. Neither component selects a strategy, routes live tasks, changes permissions, or performs a canary. A positive result means only that supplied records satisfy this assessment contract.

## API

Import `PromotionCohort` and `assess_strategy_canary` from `capri_core`.

Each cohort contains an immutable tuple of `StrategyObservation` records for exactly one baseline and one candidate. The host must first load and verify the source journal, authenticate its provenance, and classify the task family. Do not construct these records directly from model assertions or aggregate Observatory summaries. The registry's candidate-admission path now fails closed unless a trusted host `evidence_verifier` independently authenticates the manifest and exact cohort fingerprint.

## Fixed policy gates

The policy thresholds are constants, not caller-configurable:

- At least two and at most four independent cohorts per assessment, bounding bootstrap work.
- At least 100 matched task pairs in each cohort.
- At most 20,000 observation records per cohort; oversized inputs fail before preprocessing.
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


## Persisted assessment and activation binding (X8.5)

The host may persist an eligible assessment through `SQLiteStrategyStore.register_promotion_assessment_for_principal(...)`. The store does not accept a caller-supplied assessment result: it recomputes the multi-cohort assessment under the exported `STRATEGY_PROMOTION_POLICY_VERSION`, independently evaluates each cohort, and calls the configured host evidence verifier for every cohort. Each verifier context includes the cohort ID and host-classified task family in addition to the baseline/candidate versions, cohort fingerprint/schema, manifest locator, and matched-pair count. Every callback must return exact `True`.

The candidate's already-registered, evidence-verified evaluation cohort must be present in the promotion cohort set, and its manifest locator must match the candidate registration. The remaining cohorts must have distinct task/evidence fingerprints and independently verified manifests. The store persists no raw observations: it records the canonical assessment summary, per-cohort SHA-256 fingerprints, and exact manifest locators in an append-only `strategy_promotion_assessments` table. The record fingerprint covers all three components.

A host can then include that fingerprint as `promotion_assessment_sha256` in `StrategyApprovalRequest`. `HostStrategyApprovalAuthority` includes it in the HMAC-signed `StrategyActivationGrant`. During activation or promotion-bound rollback, the registry verifies that the record exists, remains eligible under the current policy version, matches the exact registered baseline/candidate versions, and contains the target cohort fingerprint. The activation event hash chain includes the assessment fingerprint; active and historical event records expose it. If the promotion policy version is retired, an active strategy using the old assessment is not served until it is reassessed or rolled back.

A grant without a promotion-assessment fingerprint remains a host-approved manual activation path for an individually evidence-verified candidate. It is not evidence of multi-cohort canary eligibility. The registry still does not route traffic or execute strategy code. A future host router must explicitly require the promotion binding before any canary routing and must implement the separate 5% cap, monitoring, and rollback gates.
