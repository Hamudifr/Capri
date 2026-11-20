import json
import tempfile
import unittest
from pathlib import Path

from capri_core.learning import LearningDataError, LearningExample, LearningStore


def example(**overrides):
    values = dict(
        example_id="ex-001", task_id="task-001", capability="tool_execution",
        prompt="Use the read-only status tool.", completion="Returned the verified status.",
        outcome="verified_success", evidence_ref="test://evidence/001",
        quality_score=0.98, consent=True, privacy_reviewed=True,
    )
    values.update(overrides)
    return LearningExample(**values)


class LearningStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = LearningStore(self.root / "learning.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_rejects_missing_consent(self):
        with self.assertRaises(LearningDataError):
            self.store.record(example(consent=False))

    def test_rejects_missing_privacy_review(self):
        with self.assertRaises(LearningDataError):
            self.store.record(example(privacy_reviewed=False))

    def test_rejects_sensitive_content(self):
        with self.assertRaises(LearningDataError):
            self.store.record(example(sensitive=True))

    def test_rejects_invalid_quality(self):
        with self.assertRaises(LearningDataError):
            self.store.record(example(quality_score=1.1))

    def test_rejects_duplicate_identifier(self):
        self.store.record(example())
        with self.assertRaises(Exception):
            self.store.record(example())

    def test_only_verified_success_is_exported(self):
        self.store.record(example())
        self.store.record(example(
            example_id="ex-002", task_id="task-002",
            outcome="verified_failure", prompt="bad", completion="bad",
        ))
        self.store.record(example(
            example_id="ex-003", task_id="task-003",
            outcome="unverified", prompt="unknown", completion="unknown",
        ))
        output = self.root / "dataset.jsonl"
        counts = self.store.export_jsonl(output)
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual(sum(counts[s] for s in ("train", "validation", "test")), 1)
        self.assertEqual([row["example_id"] for row in rows], ["ex-001"])

    def test_quality_threshold_excludes_low_quality(self):
        self.store.record(example(quality_score=0.89))
        counts = self.store.export_jsonl(self.root / "out.jsonl")
        self.assertEqual(sum(counts[s] for s in ("train", "validation", "test")), 0)

    def test_duplicate_content_is_exported_once(self):
        self.store.record(example())
        self.store.record(example(
            example_id="ex-002", task_id="task-002",
            evidence_ref="test://evidence/002",
        ))
        counts = self.store.export_jsonl(self.root / "out.jsonl")
        self.assertEqual(counts["excluded_duplicate"], 1)
        self.assertEqual(sum(counts[s] for s in ("train", "validation", "test")), 1)

    def test_splits_are_deterministic_and_disjoint_by_example_id(self):
        self.store.record(example())
        first = self.root / "first.jsonl"
        second = self.root / "second.jsonl"
        self.store.export_jsonl(first)
        self.store.export_jsonl(second)
        self.assertEqual(first.read_text(), second.read_text())
        rows = [json.loads(line) for line in first.read_text().splitlines()]
        self.assertIn(rows[0]["split"], {"train", "validation", "test"})

    def test_capability_allowlist(self):
        self.store.record(example(capability="research"))
        counts = self.store.export_jsonl(
            self.root / "out.jsonl", allowed_capabilities={"tool_execution"}
        )
        self.assertEqual(sum(counts[s] for s in ("train", "validation", "test")), 0)


if __name__ == "__main__":
    unittest.main()
