use ccel_core::{Example, Grid, synthesize};
use std::hint::black_box;
use std::time::{Duration, Instant};

fn rotate_clockwise(rows: &[Vec<u8>]) -> Vec<Vec<u8>> {
    let height = rows.len();
    let width = rows[0].len();
    let mut output = vec![vec![0; height]; width];
    for (row_index, row) in rows.iter().enumerate() {
        for (column_index, &value) in row.iter().enumerate() {
            output[column_index][height - 1 - row_index] = value;
        }
    }
    output
}

fn median(mut values: Vec<Duration>) -> Duration {
    values.sort();
    values[values.len() / 2]
}

fn main() {
    let rows: Vec<Vec<u8>> = (0..20)
        .map(|r| {
            (0..20)
                .map(|c| ((r * 7 + c * 3 + r * c) % 10) as u8)
                .collect()
        })
        .collect();
    let source = Grid::new(rows.clone()).unwrap();
    let target = Grid::new(rotate_clockwise(&rows)).unwrap();
    let examples = [Example::new(source, target)];

    for _ in 0..100 {
        black_box(synthesize(black_box(&examples), 1, 4096).unwrap());
    }

    let rounds = 10_000;
    let mut samples = Vec::with_capacity(5);
    for _ in 0..5 {
        let start = Instant::now();
        for _ in 0..rounds {
            black_box(synthesize(black_box(&examples), 1, 4096).unwrap());
        }
        samples.push(start.elapsed());
    }
    let elapsed = median(samples);
    println!(
        "Rust CCEL synthesis: median of 5 x {rounds} rounds = {elapsed:?} ({:.2} ops/s)",
        rounds as f64 / elapsed.as_secs_f64()
    );
}
