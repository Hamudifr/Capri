# Runtime performance baseline

X7.5 establishes a repeatable Python baseline before any performance-driven Rust or C migration.

## Run locally

From the repository root:

```bash
python benchmarks/runtime/run.py --warmup 50 --samples 250 --output runtime-benchmark-results.json
```

The harness uses only the Python standard library and Capri's existing package. It creates private temporary SQLite databases, uses a deterministic fake model adapter, and makes zero provider or external network calls.

## Workloads

| Workload | Timed operation |
|---|---|
| Goal persistence | Create a principal-owned goal and read it back |
| Task persistence | Create a principal-owned task and read it back |
| Task claim throughput | Claim one pre-created queued task |
| Tool validation and dispatch | Validate and execute one allowlisted local tool call, including the in-memory audit write |
| Orchestration overhead | Run one tool-free orchestration turn against a deterministic fake adapter |

Store initialization, temporary-directory creation, and pre-population of the task-claim queue are excluded from timed samples. Each sample times one operation. The report includes warm-up count, sample count, total measured batch time, operations/second, minimum, median, p95, p99 and maximum latency, plus the raw per-sample latencies.

## Environment and memory

The report records Python implementation/version, SQLite version, OS/platform, machine architecture, CPU model when detectable, logical CPU count, commit SHA and workflow run ID. It also reports process peak RSS where the operating system exposes it. Peak RSS is process-wide for the entire benchmark, not attributed to an individual workload.

For meaningful comparisons, run on the same hardware class, runner image, Python and SQLite versions, with the same warm-up and sample counts. Repeat runs and compare distributions; do not treat a single shared-runner result as a universal performance ranking. Background load, virtualization and CPU scheduling can affect results.

## Migration gate

A Rust or C vertical slice is justified only when:
1. repeated measurements identify a material hotspot in a real Capri workload;
2. profiling identifies the specific operation responsible, rather than relying on intuition or language reputation;
3. the component has a stable language-neutral contract and a bounded FFI boundary;
4. the replacement passes differential and adversarial tests, compatibility checks and rollback/recovery verification; and
5. end-to-end performance improves enough to justify the extra build, maintenance and operational complexity.

Keep the Python implementation until the replacement passes those gates. This baseline measures Python runtime paths only; it does not claim C/Rust superiority or compare unlike implementations. Exact provider token/cost measurement and synchronous handler preemption remain outside this benchmark.
