# Strategy promotion assessment v1

## Status

Implemented as a pure offline eligibility evaluator. It does not collect or authenticate evidence, issue activation grants, select a strategy, route live tasks, change permissions, or perform a canary. A positive result means only that supplied records satisfy this assessment contract.

## API

Import `PromotionCohort` and `assess_strategy_canary` from `capri_core`.

Each cohort contains an immutable tuple of `StrategyObservation` records for exactly one baseline and one candidate. The host must first load and verify the source journal, authenticate its provenance, and classify the task family. Do not construct these records directly from model assertions or aggregate Observatory summaries.

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


## Host approval binding (library API)

The host can now use `StrategyApprovalBridge` and `StrategyApprovalRequest` from `capri_runtime` to connect strategy activation grants to the existing durable HostApprovalService:

1. Construct HostApprovalService with the real host authenticator, authorization callback, private HMAC signer, and durable SQLiteApprovalChallengeStore.
2. Construct StrategyApprovalBridge with that service. It refuses configurations whose challenge lifetime plus grant lifetime exceeds 15 minutes.
3. Construct SQLiteStrategyStore with `approval_verifier=bridge.verify`.
4. Host code creates a request for the exact principal, strategy class/ID/version, current evaluation fingerprint, config fingerprint, expected activation generation and action. Preserve the request object and operation ID for retries.
5. Present a redacted human-readable summary through the authenticated approval UX. Call `bridge.approve(credential, request)` only after the configured approver authentication and authorization policy succeeds.
6. Pass the resulting signed StrategyActivationGrant to the strategy store. The store still enforces exact principal, strategy, version, config/evaluation fingerprints, generation, expiry and one-use approval ID.

New HMAC approval grants bind the authenticated approver identity as well as the operation ID and exact digest. The challenge record is immutable after its one terminal decision and cannot be deleted. Keep the signer and bridge in trusted host code; do not expose them to the model. The same trusted UTC clock must be used by HostApprovalService and its HMAC signer.

**Important limitation:** this bridge binds the existing single-cohort StrategyEvaluation fingerprint stored on a candidate. It does not yet persist or bind the multi-cohort StrategyPromotionAssessment, authenticate the evidence manifest, or prove task-family classification. It therefore strengthens explicitly approved manual activation only. It is not sufficient to enable automatic canary routing or staged promotion. Those remain disabled until assessment persistence, evidence provenance and passive shadow-mode gates are implemented and verified.
