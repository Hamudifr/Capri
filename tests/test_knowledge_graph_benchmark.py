"""Regression tests for the offline labelled graph retrieval benchmark."""
import unittest

from benchmarks.knowledge_graph.run import evaluate


class KnowledgeGraphBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = evaluate()

    def test_fixture_has_expected_scope(self):
        self.assertEqual(self.result["neuron_count"], 13)
        self.assertEqual(self.result["synapse_count"], 9)
        self.assertEqual(self.result["query_count"], 6)
        self.assertFalse(self.result["release_gate"])

    def test_retrieval_is_deterministic_and_preserves_labelled_contradictions(self):
        self.assertTrue(self.result["deterministic"])
        self.assertEqual(self.result["contradiction_preservation_rate"], 1.0)
        consent = next(
            item for item in self.result["queries"]
            if item["id"] == "consent-revocation"
        )
        self.assertTrue(consent["required_contradictions_preserved"])
        self.assertIn(
            "00000000-0000-4000-8000-000000000013",
            consent["context_order"],
        )

    def test_labelled_edges_are_retrieved(self):
        self.assertEqual(self.result["edge_recall"], 1.0)

    def test_report_contains_separate_seed_and_context_metrics(self):
        self.assertIn("seed_ranking_at_5", self.result)
        self.assertIn("full_context_ranking_at_5", self.result)
        self.assertIn("truncation_rate", self.result)
        for query in self.result["queries"]:
            self.assertIn("seed_metrics", query)
            self.assertIn("context_metrics", query)
            self.assertIn("deterministic_sha256", query)


if __name__ == "__main__":
    unittest.main()
