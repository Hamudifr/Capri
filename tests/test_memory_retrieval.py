import unittest

from benchmarks.memory_retrieval.run import evaluate


class MemoryRetrievalEvaluationTests(unittest.TestCase):
    def test_labelled_retrieval_benchmark_meets_regression_thresholds(self):
        result = evaluate()
        self.assertTrue(result["passed"], msg=result)
        self.assertEqual(result["document_count"], 69)
        self.assertEqual(result["query_count"], 12)
        self.assertGreaterEqual(result["ranked"]["ndcg_at_5"], 0.95)
        self.assertGreaterEqual(result["ranked"]["mrr_at_5"], 0.95)
        self.assertEqual(result["ranked"]["recall_at_5"], 1.0)
        self.assertGreaterEqual(result["gain_over_previous"]["ndcg_at_5"], 0.25)
        # Family gates: the lexical families must stay perfect and the
        # zero-overlap paraphrase family (semantic rewording) must be solved,
        # not just the aggregate diluted by easier queries.
        self.assertGreaterEqual(result["families"]["lexical"]["ndcg_at_5"], 0.95)
        self.assertGreaterEqual(result["families"]["semantic"]["ndcg_at_5"], 0.95)
        self.assertEqual(result["families"]["semantic"]["recall_at_5"], 1.0)
