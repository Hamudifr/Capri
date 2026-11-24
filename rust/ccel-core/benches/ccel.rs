use ccel_core::{synthesize, Example, Grid};
use std::hint::black_box;
use std::time::Instant;

fn main() {
    let source = Grid::new((0..20).map(|r| (0..20).map(|c| ((r + c) % 10) as u8).collect()).collect()).unwrap();
    let target = source.clone();
    let examples = [Example::new(source, target)];
    let rounds = 10_000;
    let start = Instant::now();
    for _ in 0..rounds { black_box(synthesize(black_box(&examples), 3, 4096).unwrap()); }
    let elapsed = start.elapsed();
    println!("CCEL synthesis: {rounds} rounds in {elapsed:?} ({:.2} ops/s)", rounds as f64 / elapsed.as_secs_f64());
}
