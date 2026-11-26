"""Fail-closed validation for project evaluation metadata."""
from datetime import datetime
from .models import EvaluationRecord, EvidenceStage, EvaluatorType, Status


class RecordValidationError(ValueError):
    pass


ALLOWED_DIMENSIONS = {
    "Agency", "Reasoning", "Memory", "Adaptability", "Reliability", "Cross-skill"
}


def contains_surrogate(value: str) -> bool:
    """Reject lone UTF-16 surrogate code points that cannot be UTF-8 encoded."""
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def validate_record(record: EvaluationRecord) -> None:
    """Reject malformed records without relying on callers to honor type hints."""
    if not isinstance(record, EvaluationRecord):
        raise RecordValidationError("record must be an EvaluationRecord")

    errors: list[str] = []
    string_fields = ("run_id", "scenario_id", "dimension", "run_at")
    for field in string_fields:
        value = getattr(record, field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} must be a non-empty string")
        elif contains_surrogate(value):
            errors.append(f"{field} must contain valid Unicode scalar values")

    if isinstance(record.dimension, str) and record.dimension not in ALLOWED_DIMENSIONS:
        errors.append("dimension is not in the controlled vocabulary")

    if not isinstance(record.status, Status):
        errors.append("status must be a supported Status")
    if not isinstance(record.evaluator_type, EvaluatorType):
        errors.append("evaluator_type must be a supported EvaluatorType")
    if not isinstance(record.evidence_stage, EvidenceStage):
        errors.append("evidence_stage must be a supported EvidenceStage")

    if isinstance(record.run_at, str) and record.run_at.strip():
        try:
            parsed = datetime.fromisoformat(record.run_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                errors.append("run_at must include a timezone")
        except ValueError:
            errors.append("run_at must be a valid ISO 8601 timestamp")

    optional_strings = ("evidence_ref", "parent_run_id", "rubric_version")
    for field in optional_strings:
        value = getattr(record, field)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{field} must be a non-empty string when supplied")
            elif contains_surrogate(value):
                errors.append(f"{field} must contain valid Unicode scalar values")

    # Enum-specific rules are evaluated only after enum types are confirmed.
    if isinstance(record.status, Status) and isinstance(record.evidence_stage, EvidenceStage):
        if record.status in (Status.PASS, Status.FAIL):
            if not isinstance(record.evidence_ref, str) or not record.evidence_ref.strip():
                errors.append("Pass/Fail requires evidence_ref")
            if record.evidence_stage not in (
                EvidenceStage.SELF_SCORED,
                EvidenceStage.INDEPENDENTLY_REVIEWED,
            ):
                errors.append("Pass/Fail requires a completed scoring stage")
        if record.status is Status.NOT_RUN:
            if record.evidence_stage is not EvidenceStage.NOT_RUN:
                errors.append("Not Run status requires Not Run evidence stage")
            if record.evidence_ref is not None:
                errors.append("Not Run record cannot claim an evidence reference")

    if isinstance(record.evidence_stage, EvidenceStage) and isinstance(record.evaluator_type, EvaluatorType):
        if record.evidence_stage is EvidenceStage.INDEPENDENTLY_REVIEWED:
            if record.evaluator_type is not EvaluatorType.INDEPENDENT:
                errors.append("Independently Reviewed requires Independent evaluator")
        if record.evaluator_type is EvaluatorType.INDEPENDENT:
            if record.evidence_stage is not EvidenceStage.INDEPENDENTLY_REVIEWED:
                errors.append("Independent evaluator must use Independently Reviewed stage")
        if record.evidence_stage is EvidenceStage.SELF_SCORED:
            if record.evaluator_type is not EvaluatorType.SELF:
                errors.append("Self-Scored requires Self evaluator")

    if isinstance(record.run_id, str) and isinstance(record.parent_run_id, str):
        if record.parent_run_id == record.run_id:
            errors.append("a run cannot be its own parent")

    if errors:
        raise RecordValidationError("; ".join(errors))
