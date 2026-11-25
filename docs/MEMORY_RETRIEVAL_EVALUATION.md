# Memory retrieval evaluation

## Purpose

X8.2 introduces a reproducible regression gate for the existing non-sensitive memory retrieval path. The benchmark is deliberately offline and dependency-free. It does not call a model, embedding service, Notion API, or other network service.

Run from the repository root:

```bash
python -m benchmarks.memory_retrieval.run
```

The versioned labelled corpus is `benchmarks/memory_retrieval/dataset.json`. It contains 60 synthetic records, nine queries, and explicit relevant-record labels. Six additional query classes (lease heartbeat, approval replay, backup validation, tool routing, event provenance, and strategy evaluation) each include two title/tag-rich relevant records followed by six newer body-only hard negatives. This deliberately tests whether relevance outranks freshness without relying on private user data. The corpus remains a regression fixture, not a representative sample of owner queries.

## Metrics and regression gate

The evaluator reports per-query and macro-average:
- NDCG@5: ranking quality with logarithmic position discount;
- MRR@5: reciprocal rank of the first relevant result;
- Recall@5: fraction of labelled relevant records retrieved in the first five.

The benchmark reproduces the previous all-term substring matcher and exact-title/freshness ordering as its baseline. The candidate must meet all of these gates:

| Metric | Required |
|---|---:|
| NDCG@5 | ≥ 0.95 |
| MRR@5 | ≥ 0.95 |
| Recall@5 | 1.00 |
| NDCG@5 gain over previous baseline | ≥ 0.25 |

The dataset SHA-256 and both rankings are emitted in the JSON result to make changes auditable. The same evaluator is invoked by the normal repository test suite, so the regression gate runs on every supported Python version in CI.

## Ranking behavior

SQLite and Notion adapters share the same provider-neutral scorer:
- all query terms must still occur in the candidate record; this change does not broaden matching to OR semantics;
- title matches carry the greatest weight, followed by tags, scope, and body mentions;
- inverse document frequency reduces the influence of terms common to all candidates;
- freshness is a tie-breaker after relevance, not a substitute for relevance;
- deterministic memory ID ordering resolves any remaining tie.

The scorer is intentionally lexical and explainable. It adds no dependency, model call, embedding store, or new authority path. Scope, status, expiry, and pagination filters remain applied before results are returned.

## Interpretation and limitations

This synthetic corpus is a regression fixture, not a statistically representative sample of real owner queries. Passing it proves the implementation behaves as labelled on these hard-negative cases; it does not prove semantic understanding, production retrieval quality, or end-to-end prompt-injection resistance. The expanded corpus improves query-class and hard-negative coverage but does not change that limitation. Before considering semantic retrieval, collect a privacy-screened, owner-labelled query set with explicit relevance grades and measure it separately. Do not place secrets or sensitive personal data in the benchmark.

No Rust/C port is justified by this work. Measure realistic retrieval latency and profile a stable hotspot before considering a native slice.
