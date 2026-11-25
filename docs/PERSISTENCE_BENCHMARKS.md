# SQLite persistence profiling

Run from the repository root:

```bash
python benchmarks/persistence/run.py --warmup 10 --samples 50 --workers 4 --queue-size 100 --output persistence-profile.json
```

The harness is offline and standard-library-only. It creates private temporary databases, uses the production `SQLiteGoalStore`, `SQLiteTaskStore`, `SQLiteBudgetStore`, and `SQLiteSessionStore` APIs, and makes no provider or network calls.


## Baseline vs optimized comparison — 2026-11-25

The first same-runner comparison was completed by [workflow run 45640130539](https://github.com/Hamudifr/Capri/actions/runs/45640130539), introduced and merged through [PR #178](https://github.com/Hamudifr/Capri/pull/178).

- Baseline: `5de569a3ed061f3eda7509420ef74a8aabb3ce89` (parent of the SQLite optimization PR).
- Candidate: `0a105651dbd959a7f3daeef8bda71e3d8f4fe441` (optimized main plus the comparison tooling).
- Environment: standard `ubuntu-latest`, Linux x86_64, Python 3.13.18, SQLite 3.46.1, four logical CPUs.
- Configuration: three runs per revision, 20 warmups and 100 measured samples per workload, four claim workers, 100 queued tasks.
- Order: baseline/candidate, candidate/baseline, baseline/candidate. Both revisions ran sequentially in the same job with the same candidate-owned harness.
- The six raw reports and comparison JSON are preserved in [artifact 15033637978](https://github.com/Hamudifr/Capri/actions/runs/45640130539/artifacts/15033637978).

Values below are the median of the three per-run statistics. Negative latency change means the candidate was faster.

| Workload | Baseline median µs | Candidate median µs | Median change | p95 change | p99 change |
|---|---:|---:|---:|---:|---:|
| Goal create including readback | 1279.965 | 1128.245 | -11.85% | -18.75% | -33.23% |
| Principal goal read | 370.245 | 218.265 | -41.05% | -38.84% | -37.86% |
| Principal goal evidence | 343.142 | 190.681 | -44.43% | -40.93% | -39.31% |
| Principal goal events | 342.826 | 195.947 | -42.84% | -41.82% | -39.01% |
| Principal goal domain events | 414.834 | 260.529 | -37.20% | -35.81% | -33.71% |
| Principal budget usage | 261.472 | 144.618 | -44.69% | -43.58% | -40.54% |
| Multi-dimension budget reserve | 707.195 | 702.998 | -0.59% | -23.87% | -33.45% |
| Principal session commit | 872.889 | 728.813 | -16.51% | -22.96% | -25.92% |
| Task create | 788.715 | 838.203 | +6.27% | +5.89% | +24.51% |
| Unscoped task read | 142.448 | 143.842 | +0.98% | +2.01% | +0.95% |
| Principal task read | 276.611 | 156.201 | -43.53% | -42.15% | -43.22% |
| Principal task events | 432.900 | 159.689 | -63.11% | -56.92% | -56.36% |
| Principal task domain events | 315.736 | 193.841 | -38.61% | -34.23% | -35.77% |
| Plan JSON encode | 2.529 | 2.574 | +1.78% | +1.70% | -0.35% |
| Plan JSON decode | 1.224 | 1.258 | +2.78% | +8.23% | +40.84% |
| SQLite insert statement | 1.630 | 1.528 | -6.26% | -4.88% | -40.11% |
| SQLite commit after insert | 160.421 | 121.571 | -24.22% | -24.76% | -10.79% |

Concurrent task-claim throughput increased from 922.16 to 1180.68 claims/second (+28.03%). All six concurrency runs passed the exact-once invariant: 100 claimed, 100 unique, zero duplicates.

### Interpretation and limits

- Thirteen of seventeen workloads had a lower candidate median. The strongest gains are in principal-scoped goal/task reads and budget usage, matching the connection/query reductions made in the optimization.
- Task creation was slower in this sample (+6.27% median, +24.51% p99). Unscoped task reads and JSON encode/decode also showed small absolute regressions; JSON costs are in the low-microsecond range. Do not hide these regressions or generalize the result to every API.
- Multi-dimension budget reservation median was effectively flat (-0.59%), although its measured p95 and p99 were lower.
- Three rounds are directional evidence, not a formal statistical significance test. This is one hosted runner and one Python/SQLite environment, not a cross-machine result.
- API timings include validation, security checks, connection setup, SQLite work and materialization. The isolated insert/commit probes are not direct timings of production transactions.
- The comparison is not a universal application speedup claim. Re-run after material persistence changes and investigate regressions only when repeatable evidence shows material user impact.


## Measurements

- Goal create API (includes the store's readback), principal-scoped goal reads, evidence reads, event reads, and domain-event projection.
- Principal-scoped budget usage reads (policy and counters from one consistent SQLite snapshot), plus multi-dimension reservation writes.
- Principal-scoped session transcript commits, including owner authorization and the versioned durable write.
- Task create, unscoped task reads, and principal-scoped task/event reads (including owner authorization and event projection).
- Plan JSON encode/decode cost, measured separately from database calls.
- A controlled SQLite insert probe with statement execution and COMMIT wall time reported separately. It uses WAL and `synchronous=FULL`; it does not weaken durability.
- Concurrent task claims from multiple `SQLiteTaskStore` instances sharing one database. Every queued task must be claimed exactly once; duplicate or missing claims fail the run.

Each latency workload reports sample count, min, median, p95, p99, max and individual samples. For API/codec workloads, throughput uses the measured wall-clock duration of the complete sample batch, while aggregate operation time is reported separately. The isolated SQL-statement and COMMIT phase samples intentionally omit throughput because their timings are interleaved in one transaction loop and do not have independent wall-clock batch durations. The concurrency workload reports elapsed wall time, throughput, worker count, and uniqueness checks.

## Interpretation

The production API measurements include validation, path-security checks, connection setup/PRAGMAs, SQLite work and Python record materialization. Budget reservation measurements include durable writes and transaction commit. They are end-to-end API costs, not pure SQL timings. The insert/commit probe is a controlled engine-level decomposition, not instrumentation of Capri's production transaction boundaries. The concurrent probe uses threads in one process with separate store instances; it does not establish cross-process or multi-host behavior.

Run on the same hardware class, filesystem, Python and SQLite versions, with repeated samples before comparing changes. Do not change WAL, synchronous mode, busy timeout, transaction boundaries, ownership checks, append-only event semantics, or backup guarantees solely to improve a benchmark. Any proposed storage optimization must preserve crash durability, principal isolation, idempotency, lease correctness, uncertain-side-effect quarantine and backup/restore behavior.

This harness establishes better diagnostic coverage. It does not itself optimize production code and does not justify a Rust/C port. Use the measurements to identify a bottleneck, then make one small change and compare the same workloads.
