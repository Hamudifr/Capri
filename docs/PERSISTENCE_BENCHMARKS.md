# SQLite persistence profiling

Run from the repository root:

```bash
python benchmarks/persistence/run.py --warmup 10 --samples 50 --workers 4 --queue-size 100 --output persistence-profile.json
```

The harness is offline and standard-library-only. It creates private temporary databases, uses the production `SQLiteGoalStore` and `SQLiteTaskStore` APIs, and makes no provider or network calls.

## Measurements

- Goal create API (includes the store's readback), principal-scoped goal reads, evidence reads, event reads, and domain-event projection.
- Principal-scoped budget usage reads (policy and counters from one consistent SQLite snapshot), plus multi-dimension reservation writes.
- Task create, unscoped task reads, and principal-scoped task/event reads (including owner authorization and event projection).
- Plan JSON encode/decode cost, measured separately from database calls.
- A controlled SQLite insert probe with statement execution and COMMIT wall time reported separately. It uses WAL and `synchronous=FULL`; it does not weaken durability.
- Concurrent task claims from multiple `SQLiteTaskStore` instances sharing one database. Every queued task must be claimed exactly once; duplicate or missing claims fail the run.

Each latency workload reports sample count, min, median, p95, p99, max and individual samples. For API/codec workloads, throughput uses the measured wall-clock duration of the complete sample batch, while aggregate operation time is reported separately. The isolated SQL-statement and COMMIT phase samples intentionally omit throughput because their timings are interleaved in one transaction loop and do not have independent wall-clock batch durations. The concurrency workload reports elapsed wall time, throughput, worker count, and uniqueness checks.

## Interpretation

The production API measurements include validation, path-security checks, connection setup/PRAGMAs, SQLite work and Python record materialization. They are end-to-end API costs, not pure SQL timings. The insert/commit probe is a controlled engine-level decomposition, not instrumentation of Capri's production transaction boundaries. The concurrent probe uses threads in one process with separate store instances; it does not establish cross-process or multi-host behavior.

Run on the same hardware class, filesystem, Python and SQLite versions, with repeated samples before comparing changes. Do not change WAL, synchronous mode, busy timeout, transaction boundaries, ownership checks, append-only event semantics, or backup guarantees solely to improve a benchmark. Any proposed storage optimization must preserve crash durability, principal isolation, idempotency, lease correctness, uncertain-side-effect quarantine and backup/restore behavior.

This harness establishes better diagnostic coverage. It does not itself optimize production code and does not justify a Rust/C port. Use the measurements to identify a bottleneck, then make one small change and compare the same workloads.
