import unittest

from benchmarks.runtime.run import run_benchmarks


class RuntimeBenchmarkTests(unittest.TestCase):
    def test_small_offline_run_reports_all_workloads_and_valid_statistics(self):
        report = run_benchmarks(warmup=1, samples=5)
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["configuration"]["external_provider_calls"], 0)
        self.assertEqual(report["configuration"]["external_network_calls"], 0)
        self.assertEqual(
            [item["name"] for item in report["results"]],
            [
                "goal_create_and_read",
                "task_create_and_read",
                "task_claim_throughput",
                "tool_validation_and_dispatch",
                "orchestration_with_fake_adapter",
            ],
        )
        for result in report["results"]:
            self.assertEqual(result["warmup_operations"], 1)
            self.assertEqual(result["sample_count"], 5)
            self.assertEqual(len(result["latency_samples_us"]), 5)
            latency = result["latency_us"]
            self.assertLessEqual(latency["min"], latency["median"])
            self.assertLessEqual(latency["median"], latency["p95"])
            self.assertLessEqual(latency["p95"], latency["p99"])
            self.assertLessEqual(latency["p99"], latency["max"])
            self.assertGreater(result["throughput_operations_per_second"], 0)

    def test_invalid_sample_count_is_rejected(self):
        with self.assertRaises(ValueError):
            run_benchmarks(warmup=1, samples=4)


if __name__ == "__main__":
    unittest.main()
