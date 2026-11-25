# Evaluation data contract

This contract applies to all Capri evaluation metadata and artifacts. Scenario definitions, rubrics, expected answers, hidden criteria, and scoring keys are ordinary project materials and may be inspected, stored, revised, and used for internal evaluation. Do not include credentials, personal secrets, private user data, customer-confidential information, or unlicensed third-party material.

## Required fields

| Field | Meaning | Rule |
|---|---|---|
| run_id | Immutable identifier for one execution | Unique; never reuse |
| scenario_id | Stable scenario identifier | Used for coverage denominator |
| dimension | Agency, Reasoning, Memory, Adaptability, Reliability, or Cross-skill | Use controlled vocabulary |
| status | Not Run, Pass, Fail, or Retest Needed | No implicit status |
| evaluator_type | Self or Independent | Independent requires a genuinely separate reviewer |
| evidence_stage | Not Run, Attempted, Evidence Captured, Self-Scored, Independently Reviewed | Must reflect actual evidence |
| evidence_ref | Link or immutable reference to evidence | Non-empty for evidence-backed outcomes |
| run_at | Timestamp with timezone | ISO 8601 |
| parent_run_id | Prior run for a retest/correction | Required for retest lineage |
| rubric_version | Version identifier where applicable and authorized | Never expose protected rubric content |

## Counting rules

- **Run count** = number of records.
- **Scenario coverage** = count of distinct scenario_id values, not record count.
- **Retest count** = records with parent_run_id.
- **Pass count** = records whose latest applicable outcome is Pass; report whether this is record-level or latest-per-scenario.
- **Independent review count** = records with evaluator_type Independent and evidence_stage Independently Reviewed.
- **Evidence completeness** = records with a valid evidence_ref and a stage consistent with the claimed outcome.

## Validation rules

- Pass without evidence_ref is invalid.
- Independently Reviewed with evaluator_type Self is invalid.
- Retest without parent_run_id is invalid.
- Self-Scored does not equal Independently Reviewed.
- Not Run cannot carry a Pass/Fail outcome.
- Aggregates must disclose filters, timestamp, and denominator.
- Conflicting or duplicate run identifiers fail validation.

### Implementation note

The contract requires `parent_run_id` for a retest/correction execution. The current validator checks that a supplied parent is non-empty and that the ledger parent exists earlier, but it does not require a parent based solely on `status = Retest Needed`. This is intentionally left as an explicit contract gap until the product owner confirms whether that status describes (a) an outcome that requests a future retest, or (b) a retest execution that must itself link to a prior run. Do not infer one meaning from the label alone.

The current Notion source schema may use different property names and optional fields. Map to this contract explicitly; do not mutate source records merely to fit this document.
