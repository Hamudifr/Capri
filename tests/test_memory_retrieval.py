import unittest

from benchmarks.memory_retrieval.run import evaluate


class MemoryRetrievalEvaluationTests(unittest.TestCase):
    def test_labelled_retrieval_benchmark_meets_regression_thresholds(self):
        result = evaluate()
        self.assertTrue(result["passed"], msg=result)
        self.assertEqual(result["document_count"], 12)
        self.assertEqual(result["query_count"], 3)
        self.assertGreaterEqual(result["ranked"]["ndcg_at_5"], 0.95)
        self.assertGreaterEqual(result["ranked"]["mrr_at_5"], 0.95)
        self.assertEqual(result["ranked"]["recall_at_5"], 1.0)
        self.assertGreaterEqual(result["gain_over_previous"]["ndcg_at_5"], 0.25)
