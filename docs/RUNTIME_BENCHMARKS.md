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

The report records Python implementation/version, SQLite version, OS/platform, machine architecture, CPU model when detectable, logical CPU count, the source branch head SHA, pull-request base SHA, workflow merge SHA, branch name and workflow run ID. The workflow summary shows compact latency/throughput metrics; raw sample latencies remain in the job log. It also reports process peak RSS where the operating system exposes it. Peak RSS is process-wide for the entire benchmark, not attributed to an individual workload.

For meaningful comparisons, run on the same hardware class, runner image, Python and SQLite versions, with the same warm-up and sample counts. Repeat runs and compare distributions; do not treat a single shared-runner result as a universal performance ranking. Background load, virtualization and CPU scheduling can affect results.

## First measured baseline (provisional)

- Measured: 2026-11-25 UTC
- Source commit: `6918360c6018e5c5bb11073a062a9c8e02bcd8b7`
- Workflow merge SHA: `3961a44724bd387535312a33def3f1f91a9b9fb1`
- Base commit: `cdfdf7698c854672654d65f9361f86a01f1d252b`
- GitHub Actions run: [45560504118](https://github.com/Hamudifr/Capri/actions/runs/45560504118)
- Runner: Ubuntu Linux 7.0.0-1020-azure, AMD EPYC 7763, 4 logical CPUs
- Runtime: CPython 3.13.18, SQLite 3.46.1
- Sampling: 50 warm-up operations and 250 measured samples per workload
- Process peak RSS: 34,484,224 bytes
- External provider/network calls: 0

| Workload | Median µs | p95 µs | p99 µs | Operations/s |
|---|---:|---:|---:|---:|
| Goal create and read | 3,604.917 | 4,120.798 | 4,731.377 | 272.19 |
| Task create and read | 2,696.935 | 3,370.591 | 4,717.230 | 355.91 |
| Task claim | 1,717.520 | 1,996.460 | 2,972.690 | 572.23 |
| Tool validation and dispatch | 55.453 | 73.928 | 98.835 | 16,845.43 |
| Orchestration with fake adapter | 14.217 | 14.658 | 23.524 | 68,886.60 |

This is one shared-runner baseline, not a stable cross-machine benchmark and not evidence that any component should be ported. The raw 250-sample distributions are retained in the linked workflow log. Repeat measurements on the same runner class before drawing optimization conclusions. No Rust/C migration is justified by this run alone.

## Migration gate

A Rust or C vertical slice is justified only when:
1. repeated measurements identify a material hotspot in a real Capri workload;
2. profiling identifies the specific operation responsible, rather than relying on intuition or language reputation;
3. the component has a stable language-neutral contract and a bounded FFI boundary;
4. the replacement passes differential and adversarial tests, compatibility checks and rollback/recovery verification; and
5. end-to-end performance improves enough to justify the extra build, maintenance and operational complexity.

Keep the Python implementation until the replacement passes those gates. This baseline measures Python runtime paths only; it does not claim C/Rust superiority or compare unlike implementations. Exact provider token/cost measurement and synchronous handler preemption remain outside this benchmark.
