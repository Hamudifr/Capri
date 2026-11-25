import unittest

from benchmarks.persistence.run import run


class PersistenceBenchmarkTests(unittest.TestCase):
    def test_small_profile_reports_api_codec_transaction_and_concurrency_results(self):
        report = run(warmup=0, samples=5, workers=2, queue_size=5)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["configuration"]["external_network_calls"], 0)
        names = [item["name"] for item in report["results"]]
        self.assertEqual(
            names,
            [
                "goal_create_api_including_readback",
                "goal_get_for_principal",
                "goal_evidence_for_principal",
                "goal_events_for_principal",
                "goal_domain_events_for_principal",
                "budget_usage_for_principal",
                "budget_reserve_multi_dimension",
                "session_commit_for_principal",
                "task_create_api",
                "task_get_api",
                "task_get_for_principal",
                "task_events_for_principal",
                "task_domain_events_for_principal",
                "plan_json_encode",
                "plan_json_decode",
                "sqlite_insert_statement_only",
                "sqlite_commit_only_after_insert",
            ],
        )
        for result in report["results"]:
            self.assertEqual(result["sample_count"], 5)
            self.assertEqual(len(result["latency_samples_us"]), 5)
            self.assertGreaterEqual(result["aggregate_operation_seconds"], 0)
            if result["elapsed_seconds"] is not None:
                self.assertGreater(result["elapsed_seconds"], 0)
                self.assertAlmostEqual(
                    result["throughput_per_second"],
                    5 / result["elapsed_seconds"],
                    delta=0.02,
                )
            else:
                self.assertIsNone(result["throughput_per_second"])
            latency = result["latency_us"]
            self.assertLessEqual(latency["min"], latency["median"])
            self.assertLessEqual(latency["median"], latency["p95"])
            self.assertLessEqual(latency["p95"], latency["p99"])
            self.assertLessEqual(latency["p99"], latency["max"])
        concurrency = report["concurrency"]
        self.assertEqual(concurrency["correctness"], "passed")
        self.assertEqual(concurrency["claimed_count"], 5)
        self.assertEqual(concurrency["unique_claim_count"], 5)
        self.assertEqual(concurrency["duplicate_claims"], 0)

    def test_invalid_concurrency_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            run(warmup=0, samples=5, workers=1, queue_size=5)


if __name__ == "__main__":
    unittest.main()
