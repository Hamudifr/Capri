# Labelled knowledge-graph retrieval benchmark

Run from the repository root:

```sh
python -m benchmarks.knowledge_graph.run
python -m unittest tests.test_knowledge_graph_benchmark -v
```

The benchmark is deterministic, offline, synthetic, and dependency-free. It does not call Notion, an LLM, an embedding service, or any network endpoint.

## What it measures

Each labelled query is evaluated twice:

1. **Seed ranking:** `retrieve_knowledge(..., max_hops=0)` measures lexical seed selection without graph expansion.
2. **Full context:** `retrieve_knowledge(..., max_hops=2)` measures the ordered neuron context after bounded breadth-first traversal.

Both report macro-averaged MRR@5, nDCG@5, and Recall@5 over relevant neuron IDs. The evaluator also reports labelled synapse edge recall, required contradiction-edge preservation, context truncation rate, per-query selected IDs, and a SHA-256 digest of serialized context. Repeated retrieval of each query must produce byte-identical serialized output.

- **MRR@5:** reciprocal rank of the first relevant neuron, zero when none appears in the first five.
- **nDCG@5:** binary-relevance discounted gain normalized by the ideal ordering of the labelled relevant set.
- **Recall@5:** fraction of labelled relevant neuron IDs present in the first five.
- **Edge recall:** fraction of a query's explicitly labelled relevant synapses selected into the graph context. The aggregate is macro-averaged only over queries with edge labels; unlabelled queries are not counted as perfect scores. The report includes the applicable query count.
- **Contradiction preservation:** fraction of queries with explicitly required active contradiction edges that retain all those edges, including the superseded claim endpoint. The aggregate excludes queries without contradiction labels and reports its applicable query count. Per-query values are null when not applicable.

## Dataset scope

The initial fixture contains 13 neurons, 9 synapses, and 6 queries. It deliberately covers principal/idempotency collisions, authenticated worker dispatch, consent revocation, pathless staging recovery, sequential Notion snapshot consistency, and semantic-retrieval vocabulary. It includes hard negatives and a superseded claim reachable only through an active contradiction edge.

All records are synthetic, use reserved example.org source URLs, and contain no user or production data. The fixture is a mechanism/regression baseline, not a representative sample of real Capri owner queries. Six queries are insufficient to establish general retrieval quality or compare architecture choices statistically.

## Decision policy

No MRR/nDCG/Recall release threshold is set from this small fixture. The benchmark CLI exits unsuccessfully unless output is deterministic, macro edge recall over labelled queries is 1.0, and all explicitly labelled contradiction edges are preserved. The dataset must contain at least one labelled edge query and one labelled contradiction query, preventing vacuous success. These checks are regression guards, not a production release gate. Treat the ranking metrics as descriptive until a larger, independently reviewed, representative and non-sensitive query set exists.

Do not infer that embeddings are required or unnecessary from this fixture. Add a broader graph corpus and compare lexical, hybrid, and embedding approaches under the same labels before making that decision.
