# Evaluation data contract

This contract applies to non-X5 evaluation metadata only. Do not export or store protected X5 instructions, rubrics, expected answers, hidden criteria, or scoring keys.

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

The current Notion source schema may use different property names and optional fields. Map to this contract explicitly; do not mutate source records merely to fit this document.
