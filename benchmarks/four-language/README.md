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
