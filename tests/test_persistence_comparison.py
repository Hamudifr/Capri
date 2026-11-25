from __future__ import annotations
import unittest
from benchmarks.persistence.compare import compare_reports

def report(commit: str, offset: float = 0.0) -> dict:
    return {
        "schema_version": 1, "benchmark": "capri_sqlite_persistence_profile", "commit_sha": commit,
        "environment": {"python": "3.13.9", "sqlite": "3.46.1", "machine": "x86_64"},
        "configuration": {"warmup": 20, "samples": 5, "workers": 2, "concurrent_queue_size": 5,
                          "external_network_calls": 0, "external_provider_calls": 0},
        "results": [{"name": "example", "sample_count": 5, "latency_samples_us": [10, 11, 12, 13, 14],
                     "latency_us": {"median": 12 + offset, "p95": 14 + offset, "p99": 14 + offset},
                     "throughput_per_second": 1000 - offset}],
        "concurrency": {"correctness": "passed", "duplicate_claims": 0, "claimed_count": 5,
                        "queue_size": 5, "throughput_claims_per_second": 200 - offset},
    }

class PersistenceComparisonTests(unittest.TestCase):
    def test_comparison_aggregates_repeated_runs(self):
        result = compare_reports([report("base"), report("base", 1), report("base", 2)],
                                 [report("candidate", -2), report("candidate", -1), report("candidate", 0)],
                                 baseline_sha="base", candidate_sha="candidate")
        self.assertEqual(result["rounds_per_revision"], 3)
        self.assertEqual(result["workloads"][0]["baseline_median_us"], 13)
        self.assertEqual(result["workloads"][0]["candidate_median_us"], 11)
        self.assertLess(result["workloads"][0]["median_change_percent"], 0)

    def test_rejects_mismatched_runtime_environment(self):
        after = report("candidate")
        after["environment"]["sqlite"] = "different"
        with self.assertRaisesRegex(ValueError, "environment differs"):
            compare_reports([report("base")], [after], baseline_sha="base", candidate_sha="candidate")

    def test_rejects_wrong_commit_identity(self):
        with self.assertRaisesRegex(ValueError, "commit SHA"):
            compare_reports([report("other")], [report("candidate")], baseline_sha="base", candidate_sha="candidate")

    def test_rejects_duplicate_concurrent_claims(self):
        bad = report("candidate")
        bad["concurrency"]["duplicate_claims"] = 1
        with self.assertRaisesRegex(ValueError, "correctness invariant"):
            compare_reports([report("base")], [bad], baseline_sha="base", candidate_sha="candidate")

    def test_rejects_configuration_mismatch(self):
        after = report("candidate")
        after["configuration"]["samples"] = 6
        with self.assertRaisesRegex(ValueError, "configuration differs"):
            compare_reports([report("base")], [after], baseline_sha="base", candidate_sha="candidate")

if __name__ == "__main__":
    unittest.main()
