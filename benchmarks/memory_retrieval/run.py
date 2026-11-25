"""Labelled, offline memory-retrieval evaluation and regression gate.

Run from the repository root:
    python -m benchmarks.memory_retrieval.run

The corpus is synthetic and non-sensitive. No network, model, embedding service,
provider credential, or third-party dependency is used.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from capri_runtime.memory import SQLiteMemoryStore

_DATASET_PATH = Path(__file__).with_name("dataset.json")


def _metrics(results: list[str], relevant: set[str], *, k: int) -> dict[str, float]:
    ranked = results[:k]
    reciprocal_rank = 0.0
    dcg = 0.0
    for index, item in enumerate(ranked, start=1):
        if item in relevant and reciprocal_rank == 0.0:
            reciprocal_rank = 1.0 / index
        if item in relevant:
            dcg += 1.0 / math.log2(index + 1)
    ideal_hits = min(len(relevant), k)
    ideal_dcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return {
        "ndcg_at_5": dcg / ideal_dcg if ideal_dcg else 0.0,
        "mrr_at_5": reciprocal_rank,
        "recall_at_5": len(set(ranked) & relevant) / len(relevant) if relevant else 1.0,
    }


def evaluate() -> dict[str, Any]:
    dataset_bytes = _DATASET_PATH.read_bytes()
    dataset = json.loads(dataset_bytes)
    directory = tempfile.TemporaryDirectory(prefix="capri-memory-eval-")
    try:
        if os.name == "posix":
            os.chmod(directory.name, 0o700)
        store = SQLiteMemoryStore(str(Path(directory.name) / "memory.sqlite3"))
        identifiers: dict[str, str] = {}
        records = []
        # Dataset order is intentional: hard negatives are newer, exposing the
        # previous freshness-only tie-breaker rather than rewarding recency.
        for document in dataset["documents"]:
            record = store.create(
                title=document["title"],
                content=document["content"],
                record_type="project_fact",
                scope=document["scope"],
                source="benchmark://capri/memory-retrieval",
                confidence="verified",
                retention="keep",
                tags=tuple(document["tags"]),
            )
            identifiers[document["id"]] = record.memory_id
            records.append((document, record))

        per_query: list[dict[str, Any]] = []
        for query_case in dataset["queries"]:
            query = query_case["query"]
            relevant = set(query_case["relevant"])
            current = [
                next(key for key, value in identifiers.items() if value == record.memory_id)
                for record in store.search(query, limit=100)
            ]
            # Reproduce the previous all-term substring matcher and its
            # exact-title/freshness ordering for a fair before/after comparison.
            terms = tuple(dict.fromkeys(part.casefold() for part in query.split() if part))
            previous_candidates = []
            for document, record in records:
                haystack = (
                    document["title"] + "\n" + document["content"] + "\n"
                    + document["scope"] + "\n" + " ".join(document["tags"])
                ).casefold()
                if sum(term in haystack for term in terms) == len(terms):
                    exact = int(document["title"].casefold() == query.casefold())
                    updated = datetime.fromisoformat(record.updated_at).timestamp()
                    previous_candidates.append((exact, updated, record.memory_id, document["id"]))
            previous_candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
            previous = [item[3] for item in previous_candidates]
            per_query.append({
                "query": query,
                "relevant_count": len(relevant),
                "previous": _metrics(previous, relevant, k=5),
                "ranked": _metrics(current, relevant, k=5),
                "previous_order": previous[:5],
                "ranked_order": current[:5],
            })

        metric_names = ("ndcg_at_5", "mrr_at_5", "recall_at_5")
        aggregate = {
            name: round(sum(item["ranked"][name] for item in per_query) / len(per_query), 6)
            for name in metric_names
        }
        previous_aggregate = {
            name: round(sum(item["previous"][name] for item in per_query) / len(per_query), 6)
            for name in metric_names
        }
        thresholds = dataset["regression_thresholds"]
        gains = {
            name: round(aggregate[name] - previous_aggregate[name], 6)
            for name in metric_names
        }
        passed = (
            aggregate["ndcg_at_5"] >= thresholds["ndcg_at_5"]
            and aggregate["mrr_at_5"] >= thresholds["mrr_at_5"]
            and aggregate["recall_at_5"] >= thresholds["recall_at_5"]
            and gains["ndcg_at_5"] >= thresholds["minimum_ndcg_gain_over_previous"]
        )
        return {
            "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
            "document_count": len(records),
            "query_count": len(per_query),
            "previous_baseline": previous_aggregate,
            "ranked": aggregate,
            "gain_over_previous": gains,
            "thresholds": thresholds,
            "passed": passed,
            "queries": per_query,
        }
    finally:
        directory.cleanup()


def main() -> int:
    result = evaluate()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
