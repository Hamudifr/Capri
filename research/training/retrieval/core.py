"""Information retrieval study modules.

Implements core IR concepts: TF-IDF, cosine similarity,
inverted index, BM25, and document ranking.
Pure stdlib, no dependencies.

Topics covered:
- Term frequency (TF) and document frequency (DF)
- TF-IDF weighting
- Cosine similarity for document vectors
- Inverted index (the engine behind every search engine)
- BM25 ranking function (the modern standard)
- Document preprocessing: tokenization, stop words
- Precision, recall, F1 score for ranking evaluation
"""

from __future__ import annotations

import math
from collections import defaultdict


# ===========================================================================
# Text preprocessing
# ===========================================================================

DEFAULT_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "this", "that", "these", "those", "i", "you", "he", "she", "it",
    "we", "they", "me", "him", "her", "us", "them",
})


def tokenize(text: str, lowercase: bool = True) -> list[str]:
    """Simple tokenizer: split on whitespace and strip punctuation."""
    if lowercase:
        text = text.lower()
    # Split on non-alphanumeric
    tokens = []
    current = []
    for ch in text:
        if ch.isalnum():
            current.append(ch)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def remove_stop_words(tokens: list[str],
                      stop_words: frozenset[str] = DEFAULT_STOP_WORDS) -> list[str]:
    """Remove stop words from a token list."""
    return [t for t in tokens if t not in stop_words]


# ===========================================================================
# TF-IDF
# ===========================================================================

def term_frequency(tokens: list[str]) -> dict[str, float]:
    """Term frequency: count of each term normalized by total terms."""
    counts: dict[str, int] = defaultdict(int)
    for t in tokens:
        counts[t] += 1
    total = len(tokens)
    if total == 0:
        return {}
    return {t: c / total for t, c in counts.items()}


def document_frequency(documents: list[list[str]]) -> dict[str, int]:
    """Document frequency: number of documents containing each term."""
    df: dict[str, int] = defaultdict(int)
    for doc in documents:
        unique_terms = set(doc)
        for term in unique_terms:
            df[term] += 1
    return dict(df)


def inverse_document_frequency(df: dict[str, int],
                               num_docs: int) -> dict[str, float]:
    """IDF: log(N / (1 + DF)). The +1 avoids division by zero."""
    if num_docs == 0:
        return {}
    return {t: math.log(num_docs / (1 + d)) for t, d in df.items()}


def tfidf_weights(documents: list[list[str]],
                  use_stop_words: bool = True) -> list[dict[str, float]]:
    """Compute TF-IDF vectors for a corpus.

    Returns a list of dicts mapping term → TF-IDF weight.
    """
    processed = []
    for doc in documents:
        tokens = tokenize(" ".join(doc))
        if use_stop_words:
            tokens = remove_stop_words(tokens)
        processed.append(tokens)

    df = document_frequency(processed)
    idf = inverse_document_frequency(df, len(processed))

    result = []
    for tokens in processed:
        tf = term_frequency(tokens)
        tfidf = {t: w * idf.get(t, 0.0) for t, w in tf.items()}
        result.append(tfidf)
    return result


# ===========================================================================
# Similarity
# ===========================================================================

def cosine_similarity(vec_a: dict[str, float],
                      vec_b: dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors (dicts)."""
    # Dot product
    common = set(vec_a) & set(vec_b)
    dot = sum(vec_a[t] * vec_b[t] for t in common)

    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def dot_product_sparse(vec_a: dict[str, float],
                       vec_b: dict[str, float]) -> float:
    """Dot product of two sparse vectors."""
    common = set(vec_a) & set(vec_b)
    return sum(vec_a[t] * vec_b[t] for t in common)


def vector_norm(vec: dict[str, float]) -> float:
    """Euclidean norm of a sparse vector."""
    return math.sqrt(sum(v * v for v in vec.values()))


# Alias to avoid name collision with math.foundations.vector_norm
retrieval_vector_norm = vector_norm


# ===========================================================================
# Inverted index
# ===========================================================================

class InvertedIndex:
    """Inverted index: maps terms to the documents containing them.

    The core data structure behind every search engine.
    """

    def __init__(self):
        self.index: dict[str, set[int]] = defaultdict(set)
        self.documents: list[str] = []

    def add_document(self, doc_id: int, text: str) -> None:
        """Add a document to the index."""
        self.documents.append(text)
        tokens = tokenize(text)
        if True:
            tokens = remove_stop_words(tokens)
        for term in set(tokens):
            self.index[term].add(doc_id)

    def search(self, query: str) -> set[int]:
        """AND search: return doc IDs containing all query terms."""
        tokens = remove_stop_words(tokenize(query))
        if not tokens:
            return set()
        result = None
        for term in tokens:
            if term in self.index:
                if result is None:
                    result = self.index[term].copy()
                else:
                    result &= self.index[term]
            else:
                return set()
        return result or set()

    def search_or(self, query: str) -> set[int]:
        """OR search: return doc IDs containing any query term."""
        tokens = remove_stop_words(tokenize(query))
        result = set()
        for term in tokens:
            if term in self.index:
                result |= self.index[term]
        return result

    def posting_length(self, term: str) -> int:
        """Number of documents containing the term."""
        return len(self.index.get(term, set()))

    def vocabulary_size(self) -> int:
        """Number of unique terms in the index."""
        return len(self.index)


# ===========================================================================
# BM25
# ===========================================================================

class BM25Ranker:
    """BM25 ranking function — the modern standard for keyword search.

    BM25 = sum over query terms of:
        IDF(t) * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * |D|/avgdl))

    where:
        tf = term frequency in document
        |D| = document length
        avgdl = average document length in corpus
        k1, b = tuning parameters
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents: list[list[str]] = []
        self.doc_freqs: list[dict[str, float]] = []
        self.df: dict[str, int] = {}
        self.avgdl: float = 0.0

    def fit(self, documents: list,
            use_stop_words: bool = True) -> "BM25Ranker":
        """Fit BM25 on a corpus. Each element of documents can be a
        string or a list of tokens.
        """
        processed = []
        for doc in documents:
            if isinstance(doc, str):
                tokens = tokenize(doc)
            else:
                tokens = tokenize(" ".join(doc))
            if use_stop_words:
                tokens = remove_stop_words(tokens)
            processed.append(tokens)

        self.documents = processed
        self.doc_freqs = [term_frequency(doc) for doc in processed]

        # Document frequency
        self.df = document_frequency(processed)

        # Average document length
        total_len = sum(len(doc) for doc in processed)
        self.avgdl = total_len / len(processed) if processed else 0.0

        return self

    def _idf(self, term: str) -> float:
        """BM25 IDF: log((N - DF + 0.5) / (DF + 0.5) + 1)."""
        n = len(self.documents)
        df = self.df.get(term, 0)
        return math.log((n - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, doc_idx: int, query_tokens: list[str]) -> float:
        """Compute BM25 score for a document against a query."""
        doc_len = len(self.documents[doc_idx])
        tf_vec = self.doc_freqs[doc_idx]
        score = 0.0

        for term in query_tokens:
            if term not in tf_vec:
                continue
            tf = tf_vec[term]
            idf = self._idf(term)
            denom = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
            score += idf * (tf * (self.k1 + 1)) / denom

        return score

    def rank(self, query: str) -> list[tuple[int, float]]:
        """Rank all documents by BM25 score against a query.

        Returns a list of (doc_idx, score) sorted by score descending.
        """
        tokens = remove_stop_words(tokenize(query))
        scores = [(i, self.score(i, tokens)) for i in range(len(self.documents))]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores


# ===========================================================================
# Evaluation metrics
# ===========================================================================

def precision_score(retrieved: set[int], relevant: set[int]) -> float:
    """Precision: of the retrieved docs, how many are relevant."""
    if not retrieved:
        return 0.0
    return len(retrieved & relevant) / len(retrieved)


def recall_score(retrieved: set[int], relevant: set[int]) -> float:
    """Recall: of the relevant docs, how many were retrieved."""
    if not relevant:
        return 0.0
    return len(retrieved & relevant) / len(relevant)


def f1_score(retrieved: set[int], relevant: set[int]) -> float:
    """F1: harmonic mean of precision and recall."""
    p = precision_score(retrieved, relevant)
    r = recall_score(retrieved, relevant)
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def mean_average_precision(ranked_results: list[set[int]],
                           relevant: set[int]) -> float:
    """Mean Average Precision for a single query.

    ranked_results: list of retrieved doc sets at increasing cutoffs.
    """
    if not relevant:
        return 0.0
    ap_sum = 0.0
    num_relevant = 0
    for i, retrieved in enumerate(ranked_results):
        if retrieved & relevant:
            num_relevant += 1
            ap_sum += num_relevant / (i + 1)
    if num_relevant == 0:
        return 0.0
    return ap_sum / len(relevant)


def __all__() -> list[str]:
    return [
        "tokenize", "remove_stop_words", "DEFAULT_STOP_WORDS",
        "term_frequency", "document_frequency", "inverse_document_frequency",
    "tfidf_weights", "cosine_similarity", "dot_product_sparse",
    "vector_norm", "retrieval_vector_norm", "InvertedIndex", "BM25Ranker",
        "precision_score", "recall_score", "f1_score",
        "mean_average_precision",
    ]
