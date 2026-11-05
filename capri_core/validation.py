"""Fail-closed validation for non-protected evaluation metadata."""
from datetime import datetime
from .models import EvaluationRecord, EvidenceStage, EvaluatorType, Status


class RecordValidationError(ValueError):
    pass


ALLOWED_DIMENSIONS = {
    "Agency", "Reasoning", "Memory", "Adaptability", "Reliability", "Cross-skill"
}


def validate_record(record: EvaluationRecord) -> None:
    errors: list[str] = []
    for field in ("run_id", "scenario_id", "dimension", "run_at"):
        if not getattr(record, field).strip():
            errors.append(f"{field} must be non-empty")
    if record.dimension not in ALLOWED_DIMENSIONS:
        errors.append("dimension is not in the controlled vocabulary")
    try:
        parsed = datetime.fromisoformat(record.run_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            errors.append("run_at must include a timezone")
    except ValueError:
        errors.append("run_at must be a valid ISO 8601 timestamp")

    if record.status in (Status.PASS, Status.FAIL):
        if not record.evidence_ref or not record.evidence_ref.strip():
            errors.append("Pass/Fail requires evidence_ref")
        if record.evidence_stage in (EvidenceStage.NOT_RUN, EvidenceStage.ATTEMPTED):
            errors.append("Pass/Fail requires captured evidence")
    if record.evidence_stage is EvidenceStage.INDEPENDENTLY_REVIEWED:
        if record.evaluator_type is not EvaluatorType.INDEPENDENT:
            errors.append("Independently Reviewed requires Independent evaluator")
    if record.evaluator_type is EvaluatorType.INDEPENDENT:
        if record.evidence_stage is not EvidenceStage.INDEPENDENTLY_REVIEWED:
            errors.append("Independent evaluator must use Independently Reviewed stage")
    if record.evidence_stage is EvidenceStage.SELF_SCORED:
        if record.evaluator_type is not EvaluatorType.SELF:
            errors.append("Self-Scored requires Self evaluator")
    if record.status is Status.NOT_RUN:
        if record.evidence_stage is not EvidenceStage.NOT_RUN:
            errors.append("Not Run status requires Not Run evidence stage")
        if record.evidence_ref:
            errors.append("Not Run record cannot claim an evidence reference")
    if record.parent_run_id is not None and not record.parent_run_id.strip():
        errors.append("parent_run_id must be non-empty when supplied")
    if record.parent_run_id == record.run_id:
        errors.append("a run cannot be its own parent")
    if errors:
        raise RecordValidationError("; ".join(errors))
