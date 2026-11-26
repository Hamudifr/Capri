"""Typed, immutable records for project evaluation metadata."""
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class Status(str, Enum):
    NOT_RUN = "Not Run"
    PASS = "Pass"
    FAIL = "Fail"
    RETEST_NEEDED = "Retest Needed"


class EvaluatorType(str, Enum):
    SELF = "Self"
    INDEPENDENT = "Independent"


class EvidenceStage(str, Enum):
    NOT_RUN = "Not Run"
    ATTEMPTED = "Attempted"
    EVIDENCE_CAPTURED = "Evidence Captured"
    SELF_SCORED = "Self-Scored"
    INDEPENDENTLY_REVIEWED = "Independently Reviewed"


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    run_id: str
    scenario_id: str
    dimension: str
    status: Status
    evaluator_type: EvaluatorType
    evidence_stage: EvidenceStage
    run_at: str
    evidence_ref: str | None = None
    parent_run_id: str | None = None
    rubric_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("status", "evaluator_type", "evidence_stage"):
            value[key] = value[key].value
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvaluationRecord":
        data = dict(value)
        data["status"] = Status(data["status"])
        data["evaluator_type"] = EvaluatorType(data["evaluator_type"])
        data["evidence_stage"] = EvidenceStage(data["evidence_stage"])
        return cls(**data)
