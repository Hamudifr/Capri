import hashlib
import json
import io
import tempfile
from contextlib import redirect_stderr, redirect_stdout
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from capri_core.__main__ import main as cli_main

from capri_core import (
    EvaluationRecord, EvidenceStage, EvaluatorType, HashChainLedger,
    LedgerIntegrityError, RecordValidationError, Status, validate_record,
)


def passing(run_id="r1", parent=None):
    return EvaluationRecord(
        run_id=run_id, scenario_id="scenario-a", dimension="Agency",
        status=Status.PASS, evaluator_type=EvaluatorType.SELF,
        evidence_stage=EvidenceStage.SELF_SCORED,
        evidence_ref="evidence://non-x5/example", run_at="2026-11-05T08:00:00Z",
        parent_run_id=parent,
    )
