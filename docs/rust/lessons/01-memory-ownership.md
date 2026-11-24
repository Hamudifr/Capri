# Lesson 01 — Memory, ownership and contiguous data

## Goal

Understand why Rust can express high-performance data structures without giving up memory safety, and apply the idea to the CCEL grid engine.

## The core idea

A Rust Vec<T> owns a growable contiguous allocation of T values. A Vec<Vec<T>> owns an outer vector whose elements are themselves separate Vec allocations. Each row's elements are contiguous within that row, but the complete matrix is not one contiguous block.

For a fixed-width grid, a flat row-major buffer stores every cell in one Vec<u8>. A coordinate maps to one offset:

    offset = row * width + column

A borrowed slice &[u8] gives read-only access without copying or transferring ownership. The owner keeps the allocation alive for the duration of the borrow. Mutable slices provide exclusive access, which is central to Rust's aliasing guarantees.

## Why this can be faster

- One main allocation instead of one allocation per row.
- Less pointer indirection.
- Better spatial locality when scanning cells.
- More predictable sequential memory access for the CPU cache.
- Easier to pass contiguous buffers to SIMD, FFI, GPU or other compute interfaces later.

These are reasons to benchmark the design, not a guarantee that every flat representation wins. Access pattern, dimensions, transform direction, allocation count and compiler optimizations matter.

## Ownership applied to CCEL

- Grid owns Vec<u8>.
- Grid exposes cells() as &[u8] and rows() as an iterator of borrowed row slices.
- An operation reads the input through shared borrows.
- An operation allocates a new output Vec<u8> and returns a new Grid.
- No unsafe code is needed for this design.

## Example

    let cells = vec![1_u8, 2, 3, 4, 5, 6];
    let width = 3;
    let row = 1;
    let column = 2;
    let value = cells[row * width + column];
    assert_eq!(value, 6);

    let second_row: &[u8] = &cells[width..2 * width];
    assert_eq!(second_row, &[4, 5, 6]);

The slice borrows the original vector. It does not copy the row.

## Evidence from the Capri implementation

The CCEL engine moved from Vec<Vec<u8>> to Vec<u8> with explicit width and height. On one same-runner synthetic 20x20 rotation-synthesis benchmark, release throughput changed from approximately 183,717 to 966,381 operations per second, a measured 5.26x improvement. This is one microbenchmark only, not a universal speed claim.

## Exercises

1. Explain the difference between Vec<T>, &[T] and &mut [T].
2. Calculate the offset for row 4, column 7, width 12.
3. Write a function that returns the borrowed third row of a flat grid, with bounds checking.
4. Explain why a Vec<Vec<u8>> has different allocation and locality properties from Vec<u8>.
5. Implement horizontal flip with safe slices and compare it to a coordinate-indexed implementation.
6. Explain why returning a slice into a locally created Vec would be invalid, and how ownership/lifetimes prevent the dangling reference.

## Review questions

- Who owns the grid allocation?
- Does taking a slice copy data?
- What invariant guarantees that row * width + column is in bounds?
- Why does Rust permit many shared borrows but restrict simultaneous mutable access?
- What would need to change for a parallel transformation to write safely into disjoint output regions?

## Status

Tested by the Rust 1.100.0 CI suite. Not yet marked retained: answer the review questions from memory and repeat the exercises after a delay.
