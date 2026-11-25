"""Offline labelled benchmark for knowledge-graph ranking and traversal.

Run from the repository root:
    python -m benchmarks.knowledge_graph.run

Synthetic and non-sensitive. No network, LLM, embedding service, credentials,
or third-party dependency is required. Metrics are descriptive; this first
fixture intentionally establishes a baseline rather than a release threshold.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from capri_runtime.knowledge_graph import (
    GraphNeuron,
    GraphSynapse,
    InMemoryKnowledgeGraphProvider,
    retrieve_knowledge,
    serialize_untrusted_knowledge_context,
)

_DATASET_PATH = Path(__file__).with_name("dataset.json")
_K = 5


def _metrics(ranked: list[str], relevant: set[str], *, k: int = _K) -> dict[str, float]:
    top = ranked[:k]
    reciprocal_rank = 0.0
    dcg = 0.0
    for index, identifier in enumerate(top, start=1):
        if identifier in relevant:
            if reciprocal_rank == 0.0:
                reciprocal_rank = 1.0 / index
            dcg += 1.0 / math.log2(index + 1)
    ideal_hits = min(len(relevant), k)
    ideal_dcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return {
        "mrr_at_5": reciprocal_rank,
        "ndcg_at_5": dcg / ideal_dcg if ideal_dcg else 0.0,
        "recall_at_5": len(set(top) & relevant) / len(relevant) if relevant else 1.0,
    }


def _mean(rows: list[dict[str, float]], key: str) -> float:
    return round(sum(row[key] for row in rows) / len(rows), 6) if rows else 0.0


def _regression_gates_pass(
    *, deterministic: bool, edge_recall: float | None,
    contradiction_preservation_rate: float | None,
) -> bool:
    return deterministic and edge_recall == 1.0 and contradiction_preservation_rate == 1.0


def _load_graph(dataset: dict[str, Any]) -> InMemoryKnowledgeGraphProvider:
    neurons = tuple(GraphNeuron(
        neuron_id=item["id"],
        title=item["title"],
        notes=item["notes"],
        kind=item["kind"],
        layer=item["layer"],
        evidence_state=item["evidence_state"],
        confidence=item["confidence"],
        source=item["source"],
        tags=tuple(item["tags"]),
        created_at="2026-11-24T00:00:00+00:00",
        updated_at="2026-11-25T00:00:00+00:00",
    ) for item in dataset["neurons"])
    synapses = tuple(GraphSynapse(
        synapse_id=item["id"],
        title=item["title"],
        from_neuron_id=item["from"],
        to_neuron_id=item["to"],
        relationship=item["relationship"],
        rationale=item["rationale"],
        evidence="https://example.org/capri/graph-edge",
        strength=item["strength"],
        status=item["status"],
    ) for item in dataset["synapses"])
    return InMemoryKnowledgeGraphProvider(neurons, synapses)


def evaluate() -> dict[str, Any]:
    raw = _DATASET_PATH.read_bytes()
    dataset = json.loads(raw)
    if dataset.get("format") != "capri.labelled-knowledge-graph-benchmark.v1":
        raise ValueError("unsupported graph benchmark dataset format")
    if not dataset.get("queries") or not dataset.get("neurons"):
        raise ValueError("graph benchmark dataset must contain neurons and queries")
    if not any(case.get("relevant_edges") for case in dataset["queries"]):
        raise ValueError("graph benchmark dataset must label at least one relevant edge")
    if not any(case.get("required_contradiction_edges") for case in dataset["queries"]):
        raise ValueError("graph benchmark dataset must label at least one required contradiction edge")

    provider = _load_graph(dataset)
    seed_rows: list[dict[str, float]] = []
    context_rows: list[dict[str, float]] = []
    edge_recalls: list[float] = []
    contradiction_checks: list[bool] = []
    query_results: list[dict[str, Any]] = []
    truncated_count = 0
    deterministic = True

    for case in dataset["queries"]:
        query = case["query"]
        relevant_neurons = set(case["relevant_neurons"])
        relevant_edges = set(case.get("relevant_edges", ()))
        seed_context = retrieve_knowledge(
            query, provider, max_hops=0, max_neurons=5, max_synapses=0,
        )
        context = retrieve_knowledge(
            query, provider, max_hops=2, max_neurons=20, max_synapses=40,
        )
        repeated = retrieve_knowledge(
            query, provider, max_hops=2, max_neurons=20, max_synapses=40,
        )
        first_serialized = serialize_untrusted_knowledge_context(context)
        second_serialized = serialize_untrusted_knowledge_context(repeated)
        deterministic = deterministic and first_serialized == second_serialized

        seed_ids = [item.neuron_id for item in seed_context.neurons]
        context_ids = [item.neuron_id for item in context.neurons]
        edge_ids = {item.synapse_id for item in context.synapses}
        seed_metrics = _metrics(seed_ids, relevant_neurons)
        context_metrics = _metrics(context_ids, relevant_neurons)
        edge_recall = (
            len(edge_ids & relevant_edges) / len(relevant_edges)
            if relevant_edges else 1.0
        )
        required_contradictions = set(case.get("required_contradiction_edges", ()))
        preserved = required_contradictions.issubset(edge_ids)
        truncated_count += int(context.truncated)
        seed_rows.append(seed_metrics)
        context_rows.append(context_metrics)
        if relevant_edges:
            edge_recalls.append(edge_recall)
        if required_contradictions:
            contradiction_checks.append(preserved)
        query_results.append({
            "id": case["id"],
            "query": query,
            "seed_metrics": seed_metrics,
            "context_metrics": context_metrics,
            "edge_recall": round(edge_recall, 6) if relevant_edges else None,
            "required_contradictions_preserved": preserved if required_contradictions else None,
            "seed_order": seed_ids,
            "context_order": context_ids,
            "selected_edges": sorted(edge_ids),
            "truncated": context.truncated,
            "deterministic_sha256": hashlib.sha256(
                first_serialized.encode("utf-8")
            ).hexdigest(),
        })

    count = len(query_results)
    seed_aggregate = {
        key: _mean(seed_rows, key)
        for key in ("mrr_at_5", "ndcg_at_5", "recall_at_5")
    }
    context_aggregate = {
        key: _mean(context_rows, key)
        for key in ("mrr_at_5", "ndcg_at_5", "recall_at_5")
    }
    edge_recall_rate = (
        round(sum(edge_recalls) / len(edge_recalls), 6) if edge_recalls else None
    )
    contradiction_rate = (
        round(sum(contradiction_checks) / len(contradiction_checks), 6)
        if contradiction_checks else None
    )
    passed = _regression_gates_pass(
        deterministic=deterministic,
        edge_recall=edge_recall_rate,
        contradiction_preservation_rate=contradiction_rate,
    )
    return {
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "dataset_format": dataset["format"],
        "description": dataset["description"],
        "neuron_count": len(dataset["neurons"]),
        "synapse_count": len(dataset["synapses"]),
        "query_count": count,
        "seed_ranking_at_5": seed_aggregate,
        "full_context_ranking_at_5": context_aggregate,
        "edge_recall": edge_recall_rate,
        "edge_query_count": len(edge_recalls),
        "contradiction_preservation_rate": contradiction_rate,
        "contradiction_query_count": len(contradiction_checks),
        "truncation_rate": round(truncated_count / count, 6) if count else 0.0,
        "deterministic": deterministic,
        "passed": passed,
        "release_gate": False,
        "queries": query_results,
    }


def main() -> int:
    result = evaluate()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
