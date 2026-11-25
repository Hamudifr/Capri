# Four-language benchmark

Compares C, C++, Rust and CPython on the same deterministic, single-threaded Conway's Game of Life workload.

- Grid: 256 x 256
- Generations: 80 (5,242,880 cell updates)
- Toroidal boundaries and B3/S23 rules
- Identical deterministic initial state, two-buffer update model and final FNV-1a checksum
- C17 and C++23, both compiled with -O3 -march=native
- Latest stable Rust, edition 2024, opt-level 3, native CPU target
- CPython 3.15, matching the supported Capri runtime
- One warm-up and five measured samples; median kernel time reported
- Initialization, process startup, compilation and checksum calculation excluded from the timed region
- Single-threaded, no third-party libraries; mismatched checksums fail the run

Run on Linux with cc, c++, rustc and Python 3.15.x:

    python benchmarks/four-language/run.py

This is one CPU-bound stencil benchmark, not a universal language ranking. Compiler versions, CPU, flags and workload shape affect results. It does not measure startup time, memory footprint, parallel scaling, I/O or application throughput.

## Verified results (2026-11-24)

Three independent GitHub-hosted runner batches all produced checksum 61ba73df36b48d49 and ranked Rust first on this exact implementation/workload.

Median kernel times (ms), one warm-up and five measured samples per batch:

| Language | Run 2 | Run 3 | Run 4 | Median of batch medians |
|---|---:|---:|---:|---:|
| Rust | 9.169 | 10.165 | 8.918 | 9.169 |
| C | 9.707 | 11.110 | 9.685 | 9.707 |
| C++ | 10.000 | 11.124 | 9.419 | 10.000 |
| Python | 2,043.594 | 2,470.183 | 1,979.225 | 2,043.594 |

Across these three batches, Rust was about 5.5% faster than C and 8.3% faster than C++; the Python loop took about 223x the Rust time. These are three batch medians, not a large statistical sample.

Toolchains and runner:
- GCC C compiler 15.2.0, C17, -O3 -march=native
- GCC C++ compiler 15.2.0, C++23, -O3 -march=native
- rustc 1.100.0, edition 2024, opt-level 3, native CPU target
- CPython 3.15.2
- Intel Xeon Platinum 8573C, 4 vCPUs exposed to GitHub-hosted Ubuntu job

An initial Rust flat-index implementation measured 12.566 ms in an earlier separate run. Switching to borrowed row slices improved later Rust results to 9 ms range. This is an optimization observation, not a controlled paired A/B.

See RESULTS-2026-11-24.md for full method, limitations, run IDs and interpretation. The benchmark is one single-threaded CPU-bound task, not a universal language ranking.
