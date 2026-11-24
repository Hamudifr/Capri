# Four-language benchmark

Compares C, C++, Rust and CPython on the same deterministic, single-threaded Conway's Game of Life workload.

- Grid: 256 x 256
- Generations: 80 (5,242,880 cell updates)
- Toroidal boundaries and B3/S23 rules
- Identical deterministic initial state, two-buffer update model and final FNV-1a checksum
- C17 and C++23, both compiled with -O3 -march=native
- Latest stable Rust, edition 2024, opt-level 3, native CPU target
- Latest stable CPython selected by setup-python 3.x
- One warm-up and five measured samples; median kernel time reported
- Initialization, process startup, compilation and checksum calculation excluded from the timed region
- Single-threaded, no third-party libraries; mismatched checksums fail the run

Run on Linux with cc, c++, rustc and Python 3.15+:

    python benchmarks/four-language/run.py

This is one CPU-bound stencil benchmark, not a universal language ranking. Compiler versions, CPU, flags and workload shape affect results. It does not measure startup time, memory footprint, parallel scaling, I/O or application throughput.

## Verified run (2026-11-24)

Latest exact-head run: GitHub Actions run 2, on a 4-vCPU Intel Xeon Platinum 8573C runner.

Toolchains:
- GCC C compiler: Ubuntu 15.2.0-16ubuntu1 (15.2.0), C17
- GCC C++ compiler: Ubuntu 15.2.0-16ubuntu1 (15.2.0), C++23
- rustc 1.100.0, edition 2024
- CPython 3.15.2

All four outputs matched checksum 61ba73df36b48d49.

| Language | Median kernel time | Cell updates/second | Relative time vs fastest |
|---|---:|---:|---:|
| Rust | 9.169 ms | 571,777,183 | 1.00x |
| C | 9.707 ms | 540,130,403 | 1.06x |
| C++ | 10.000 ms | 524,312,223 | 1.09x |
| Python | 2,043.594 ms | 2,565,520 | 222.87x |

Raw sample times (ms):
- Rust: 9.162, 9.169, 9.138, 9.193, 9.171
- C: 9.629, 9.598, 9.798, 10.041, 9.707
- C++: 10.014, 10.397, 9.900, 10.000, 9.867
- Python: 2054.437, 2043.594, 2051.592, 2039.672, 2042.659

This one run puts Rust about 5.5% faster than C and 9.1% faster than C++ for this exact implementation and workload. The difference among native languages is small enough that compiler optimization and code shape can change the ordering. Python is about 223 times slower than the fastest native result here.

An earlier Rust implementation using direct flat indexing measured 12.566 ms on a separate run. Changing the Rust kernel to borrow row slices reduced its subsequent measured median to 9.169 ms. Treat this as an optimization observation, not a controlled paired A/B experiment.

The result is specific to one CPU-bound, single-threaded cellular-automaton workload. It is not a universal language ranking or a prediction for CCEL's full application performance.

## Independent confirmation run (2026-11-24)

A second exact-head CI run reproduced the same checksum and ordering:

| Language | Run 3 median |
|---|---:|
| Rust | 10.165 ms |
| C | 11.110 ms |
| C++ | 11.124 ms |
| Python | 2,470.183 ms |

Across the two independent runner batches, the median of each batch's median time was:

| Language | Median of two batch medians |
|---|---:|
| Rust | 9.667 ms |
| C | 10.409 ms |
| C++ | 10.562 ms |
| Python | 2,256.889 ms |

Across these two batches, Rust's measured kernel time was about 7.1% lower than C and 8.5% lower than C++; Python's was about 233x the Rust time. This is still only two CI batches on one runner class, not a broad statistical benchmark.
