"""Tests for the information retrieval training module."""

import unittest
import math

from research.training.retrieval.core import (
    tokenize, remove_stop_words, DEFAULT_STOP_WORDS,
    term_frequency, document_frequency, inverse_document_frequency,
    tfidf_weights, cosine_similarity, dot_product_sparse, vector_norm,
    InvertedIndex, BM25Ranker,
    precision_score, recall_score, f1_score, mean_average_precision,
)


class TestTokenization(unittest.TestCase):

    def test_tokenize_basic(self):
        tokens = tokenize("Hello world")
        self.assertEqual(tokens, ["hello", "world"])

    def test_tokenize_punctuation(self):
        tokens = tokenize("Hello, world! How are you?")
        self.assertEqual(tokens, ["hello", "world", "how", "are", "you"])

    def test_tokenize_uppercase(self):
        tokens = tokenize("Hello World", lowercase=False)
        self.assertEqual(tokens, ["Hello", "World"])

    def test_remove_stop_words(self):
        tokens = tokenize("the cat and the dog")
        filtered = remove_stop_words(tokens)
        self.assertEqual(filtered, ["cat", "dog"])

    def test_stop_words_present(self):
        self.assertIn("the", DEFAULT_STOP_WORDS)
        self.assertIn("and", DEFAULT_STOP_WORDS)


class TestTFIDF(unittest.TestCase):

    def test_term_frequency(self):
        tf = term_frequency(["a", "b", "a", "a"])
        self.assertAlmostEqual(tf["a"], 0.75, places=8)
        self.assertAlmostEqual(tf["b"], 0.25, places=8)

    def test_document_frequency(self):
        docs = [["a", "b"], ["b", "c"], ["a", "c"]]
        df = document_frequency(docs)
        self.assertEqual(df["a"], 2)
        self.assertEqual(df["b"], 2)
        self.assertEqual(df["c"], 2)

    def test_inverse_document_frequency(self):
        df = {"a": 2, "b": 1}
        idf = inverse_document_frequency(df, 3)
        # idf = log(3 / (1+2)) = log(1) = 0 for "a"
        self.assertAlmostEqual(idf["a"], 0.0, places=8)
        # idf = log(3 / (1+1)) = log(1.5) for "b"
        self.assertAlmostEqual(idf["b"], math.log(1.5), places=8)

    def test_tfidf_weights_shape(self):
        docs = [["the", "cat", "sat"], ["the", "dog", "ran"]]
        weights = tfidf_weights(docs, use_stop_words=False)
        self.assertEqual(len(weights), 2)
        # "the" appears in both docs so its IDF is lower
        self.assertIn("cat", weights[0])
        self.assertIn("dog", weights[1])


class TestSimilarity(unittest.TestCase):

    def test_cosine_identical(self):
        v = {"a": 1.0, "b": 2.0}
        self.assertAlmostEqual(cosine_similarity(v, v), 1.0, places=8)

    def test_cosine_orthogonal(self):
        v1 = {"a": 1.0, "b": 0.0}
        v2 = {"a": 0.0, "b": 1.0}
        self.assertAlmostEqual(cosine_similarity(v1, v2), 0.0, places=8)

    def test_cosine_zero_vector(self):
        v = {"a": 0.0}
        self.assertEqual(cosine_similarity(v, v), 0.0)

    def test_dot_product(self):
        v1 = {"a": 1.0, "b": 2.0}
        v2 = {"a": 3.0, "b": 4.0}
        self.assertAlmostEqual(dot_product_sparse(v1, v2), 11.0, places=8)

    def test_vector_norm(self):
        v = {"a": 3.0, "b": 4.0}
        self.assertAlmostEqual(vector_norm(v), 5.0, places=8)


class TestInvertedIndex(unittest.TestCase):

    def setUp(self):
        self.index = InvertedIndex()
        self.index.add_document(0, "the cat sat on the mat")
        self.index.add_document(1, "the dog ran in the park")
        self.index.add_document(2, "cats and dogs are pets")

    def test_search_and(self):
        result = self.index.search("cat dog")
        # No document contains both "cat" and "dog"
        self.assertEqual(result, set())

    def test_search_single(self):
        result = self.index.search("cat")
        # Only doc 0 contains the exact token "cat" (doc 2 has "cats")
        self.assertEqual(result, {0})

    def test_search_or(self):
        result = self.index.search_or("cat dog")
        # "cat" in doc 0, "dog" in doc 1
        self.assertIn(0, result)
        self.assertIn(1, result)
        # "cats" and "dogs" are different tokens, so doc 2 is not matched
        self.assertNotIn(2, result)

    def test_posting_length(self):
        self.assertEqual(self.index.posting_length("cat"), 1)
        self.assertEqual(self.index.posting_length("dog"), 1)
        self.assertEqual(self.index.posting_length("nonexistent"), 0)

    def test_vocabulary_size(self):
        # Unique non-stop-word terms
        self.assertGreater(self.index.vocabulary_size(), 0)


class TestBM25(unittest.TestCase):

    def setUp(self):
        self.docs = [
            "the cat sat on the mat",
            "the dog ran in the park",
            "cats and dogs are common pets",
        ]
        self.ranker = BM25Ranker().fit(self.docs)

    def test_rank_returns_sorted(self):
        results = self.ranker.rank("cat")
        self.assertEqual(len(results), 3)
        # Scores should be sorted descending
        scores = [s for _, s in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_rank_relevant_first(self):
        results = self.ranker.rank("cat")
        # Documents containing "cat" should rank higher than those without
        doc_ids = [d for d, s in results]
        # Doc 0 contains "cat", should be at the top
        self.assertIn(0, doc_ids)
        # Doc 0 should have a higher score than doc 1 (which doesn't contain "cat")
        scores_by_doc = {d: s for d, s in results}
        self.assertGreater(scores_by_doc[0], scores_by_doc[1])

    def test_bm25_score_positive(self):
        tokens = tokenize("cat")
        score = self.ranker.score(0, tokens)
        self.assertGreater(score, 0.0)


class TestEvaluation(unittest.TestCase):

    def test_precision(self):
        self.assertAlmostEqual(precision_score({0, 1, 2}, {0, 1}), 2/3, places=8)

    def test_precision_empty(self):
        self.assertEqual(precision_score(set(), {0}), 0.0)

    def test_recall(self):
        self.assertAlmostEqual(recall_score({0, 1}, {0, 1, 2}), 2/3, places=8)

    def test_recall_empty(self):
        self.assertEqual(recall_score({0}, set()), 0.0)

    def test_f1(self):
        # Perfect match
        self.assertAlmostEqual(f1_score({0, 1}, {0, 1}), 1.0, places=8)

    def test_f1_no_overlap(self):
        self.assertEqual(f1_score({0}, {1}), 0.0)

    def test_map(self):
        # All relevant docs retrieved and ranked first
        ranked = [{0}, {0, 1}, {0, 1, 2}]
        self.assertAlmostEqual(mean_average_precision(ranked, {0, 1, 2}), 1.0, places=8)


if __name__ == "__main__":
    unittest.main()
