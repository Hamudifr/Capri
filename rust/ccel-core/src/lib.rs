//! CCEL deterministic bounded program-learning core.
//! This is a research component, not a general world model or an AGI claim.

use std::collections::BTreeMap;
use std::fmt;

pub const MAX_SIDE: usize = 30;
pub const MAX_CELLS: usize = 900;
pub const MAX_PROGRAM_DEPTH: usize = 5;
pub const MAX_EXAMPLES: usize = 100;
pub const MAX_CANDIDATES: usize = 10_000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CcelError {
    EmptyGrid, EmptyRow, NonRectangular, SideTooLarge, TooManyCells,
    CellOutOfRange(u8), ProgramTooDeep, InvalidDepth, InvalidCandidateBudget,
    NoExamples, TooManyExamples, NoPrograms, NoProbes, NoConsistentModel,
    SearchLimitExceeded,
}

impl fmt::Display for CcelError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyGrid => write!(f, "grid must contain at least one row"),
            Self::EmptyRow => write!(f, "grid rows must not be empty"),
            Self::NonRectangular => write!(f, "grid must be rectangular"),
            Self::SideTooLarge => write!(f, "grid side exceeds {MAX_SIDE}"),
            Self::TooManyCells => write!(f, "grid exceeds {MAX_CELLS} cells"),
            Self::CellOutOfRange(v) => write!(f, "cell value {v} is outside 0..=9"),
            Self::ProgramTooDeep => write!(f, "program exceeds depth {MAX_PROGRAM_DEPTH}"),
            Self::InvalidDepth => write!(f, "max_depth must be in 0..={MAX_PROGRAM_DEPTH}"),
            Self::InvalidCandidateBudget => write!(f, "candidate budget must be in 1..={MAX_CANDIDATES}"),
            Self::NoExamples => write!(f, "provide at least one example"),
            Self::TooManyExamples => write!(f, "example count exceeds {MAX_EXAMPLES}"),
            Self::NoPrograms => write!(f, "provide at least one program"),
            Self::NoProbes => write!(f, "provide at least one candidate probe"),
            Self::NoConsistentModel => write!(f, "no program in the bounded DSL explains all examples"),
            Self::SearchLimitExceeded => write!(f, "consistent models exceed the candidate budget"),
        }
    }
}
impl std::error::Error for CcelError {}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Grid { rows: Vec<Vec<u8>>, width: usize }

impl Grid {
    pub fn new(rows: Vec<Vec<u8>>) -> Result<Self, CcelError> {
        if rows.is_empty() { return Err(CcelError::EmptyGrid); }
        if rows.len() > MAX_SIDE { return Err(CcelError::SideTooLarge); }
        let width = rows[0].len();
        if width == 0 || rows.iter().any(Vec::is_empty) { return Err(CcelError::EmptyRow); }
        if width > MAX_SIDE { return Err(CcelError::SideTooLarge); }
        if rows.iter().any(|row| row.len() != width) { return Err(CcelError::NonRectangular); }
        if rows.len().saturating_mul(width) > MAX_CELLS { return Err(CcelError::TooManyCells); }
        if let Some(value) = rows.iter().flatten().find(|&&value| value > 9) {
            return Err(CcelError::CellOutOfRange(*value));
        }
        Ok(Self { rows, width })
    }
    pub fn rows(&self) -> &[Vec<u8>] { &self.rows }
    pub fn height(&self) -> usize { self.rows.len() }
    pub fn width(&self) -> usize { self.width }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Operation { RotateClockwise, RotateCounterClockwise, FlipHorizontal, FlipVertical, Transpose }

pub const OPERATIONS: [Operation; 5] = [
    Operation::RotateClockwise, Operation::RotateCounterClockwise,
    Operation::FlipHorizontal, Operation::FlipVertical, Operation::Transpose,
];

impl Operation {
    pub fn apply(self, grid: &Grid) -> Grid {
        let h = grid.height();
        let w = grid.width();
        let (out_h, out_w) = match self {
            Self::RotateClockwise | Self::RotateCounterClockwise | Self::Transpose => (w, h),
            Self::FlipHorizontal | Self::FlipVertical => (h, w),
        };
        let mut out = vec![vec![0; out_w]; out_h];
        match self {
            Self::RotateClockwise => for r in 0..h { for c in 0..w { out[c][h - 1 - r] = grid.rows[r][c]; } },
            Self::RotateCounterClockwise => for r in 0..h { for c in 0..w { out[w - 1 - c][r] = grid.rows[r][c]; } },
            Self::FlipHorizontal => for r in 0..h { for c in 0..w { out[r][w - 1 - c] = grid.rows[r][c]; } },
            Self::FlipVertical => for r in 0..h { out[h - 1 - r].clone_from(&grid.rows[r]); },
            Self::Transpose => for r in 0..h { for c in 0..w { out[c][r] = grid.rows[r][c]; } },
        }
        Grid { rows: out, width: out_w }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Example { pub source: Grid, pub target: Grid }
impl Example { pub fn new(source: Grid, target: Grid) -> Self { Self { source, target } } }

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct Program { pub operations: Vec<Operation> }
impl Program {
    pub fn new(operations: Vec<Operation>) -> Result<Self, CcelError> {
        if operations.len() > MAX_PROGRAM_DEPTH { return Err(CcelError::ProgramTooDeep); }
        Ok(Self { operations })
    }
    pub fn complexity(&self) -> usize { self.operations.len() }
    pub fn apply(&self, input: &Grid) -> Grid {
        self.operations.iter().fold(input.clone(), |grid, op| op.apply(&grid))
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SynthesisResult { pub programs: Vec<Program>, pub depth: usize, pub examples_seen: usize }

#[derive(Debug, Clone, PartialEq)]
pub struct ProbeChoice {
    pub grid: Grid,
    pub entropy_bits: f64,
    pub distinct_outcomes: usize,
    pub predictions: Vec<(Grid, usize)>,
}

pub fn synthesize(examples: &[Example], max_depth: usize, max_candidates: usize) -> Result<SynthesisResult, CcelError> {
    if max_depth > MAX_PROGRAM_DEPTH { return Err(CcelError::InvalidDepth); }
    if !(1..=MAX_CANDIDATES).contains(&max_candidates) { return Err(CcelError::InvalidCandidateBudget); }
    if examples.is_empty() { return Err(CcelError::NoExamples); }
    if examples.len() > MAX_EXAMPLES { return Err(CcelError::TooManyExamples); }
    for depth in 0..=max_depth {
        let mut matches = Vec::new();
        enumerate_programs(depth, &mut Vec::with_capacity(depth), &mut |program| {
            if examples.iter().all(|e| program.apply(&e.source) == e.target) {
                matches.push(program.clone());
                if matches.len() > max_candidates { return Err(CcelError::SearchLimitExceeded); }
            }
            Ok(())
        })?;
        if !matches.is_empty() {
            matches.sort();
            return Ok(SynthesisResult { programs: matches, depth, examples_seen: examples.len() });
        }
    }
    Err(CcelError::NoConsistentModel)
}

fn enumerate_programs<F>(target_depth: usize, sequence: &mut Vec<Operation>, visit: &mut F) -> Result<(), CcelError>
where F: FnMut(&Program) -> Result<(), CcelError> {
    if sequence.len() == target_depth { return visit(&Program { operations: sequence.clone() }); }
    for operation in OPERATIONS {
        sequence.push(operation);
        enumerate_programs(target_depth, sequence, visit)?;
        sequence.pop();
    }
    Ok(())
}

pub fn predict(programs: &[Program], input: &Grid) -> Result<Vec<Grid>, CcelError> {
    if programs.is_empty() { return Err(CcelError::NoPrograms); }
    let mut outputs: Vec<Grid> = programs.iter().map(|p| p.apply(input)).collect();
    outputs.sort();
    outputs.dedup();
    Ok(outputs)
}

pub fn select_probe(programs: &[Program], probes: &[Grid]) -> Result<ProbeChoice, CcelError> {
    if programs.is_empty() { return Err(CcelError::NoPrograms); }
    if probes.is_empty() { return Err(CcelError::NoProbes); }
    let mut best: Option<ProbeChoice> = None;
    for grid in probes {
        let mut counts: BTreeMap<Grid, usize> = BTreeMap::new();
        for program in programs { *counts.entry(program.apply(grid)).or_insert(0) += 1; }
        let total = programs.len() as f64;
        let entropy_bits = counts.values().map(|&count| {
            let p = count as f64 / total;
            -p * p.log2()
        }).sum();
        let predictions: Vec<(Grid, usize)> = counts.into_iter().collect();
        let choice = ProbeChoice { grid: grid.clone(), entropy_bits, distinct_outcomes: predictions.len(), predictions };
        let better = match &best {
            None => true,
            Some(current) => choice.entropy_bits > current.entropy_bits
                || (choice.entropy_bits == current.entropy_bits && choice.distinct_outcomes > current.distinct_outcomes)
                || (choice.entropy_bits == current.entropy_bits && choice.distinct_outcomes == current.distinct_outcomes && choice.grid < current.grid),
        };
        if better { best = Some(choice); }
    }
    best.ok_or(CcelError::NoProbes)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn g(rows: &[&[u8]]) -> Grid { Grid::new(rows.iter().map(|r| r.to_vec()).collect()).unwrap() }

    #[test] fn validates_bad_grids() {
        assert_eq!(Grid::new(vec![]), Err(CcelError::EmptyGrid));
        assert_eq!(Grid::new(vec![vec![]]), Err(CcelError::EmptyRow));
        assert_eq!(Grid::new(vec![vec![1,2], vec![3]]), Err(CcelError::NonRectangular));
        assert_eq!(Grid::new(vec![vec![10]]), Err(CcelError::CellOutOfRange(10)));
        assert_eq!(Grid::new(vec![vec![1; MAX_SIDE + 1]]), Err(CcelError::SideTooLarge));
    }
    #[test] fn clockwise_rotation() {
        assert_eq!(Operation::RotateClockwise.apply(&g(&[&[1,2,3], &[4,5,6]])), g(&[&[4,1], &[5,2], &[6,3]]));
    }
    #[test] fn counter_clockwise_rotation() {
        assert_eq!(Operation::RotateCounterClockwise.apply(&g(&[&[1,2,3], &[4,5,6]])), g(&[&[3,6], &[2,5], &[1,4]]));
    }
    #[test] fn both_flips() {
        let x = g(&[&[1,2], &[3,4]]);
        assert_eq!(Operation::FlipHorizontal.apply(&x), g(&[&[2,1], &[4,3]]));
        assert_eq!(Operation::FlipVertical.apply(&x), g(&[&[3,4], &[1,2]]));
    }
    #[test] fn transpose() {
        assert_eq!(Operation::Transpose.apply(&g(&[&[1,2,3], &[4,5,6]])), g(&[&[1,4], &[2,5], &[3,6]]));
    }
    #[test] fn identity_is_minimum_depth() {
        let x = g(&[&[1,2]]);
        let result = synthesize(&[Example::new(x.clone(), x)], 3, 4096).unwrap();
        assert_eq!(result.depth, 0);
        assert_eq!(result.programs, vec![Program::new(vec![]).unwrap()]);
    }
    #[test] fn synthesizes_from_multiple_examples() {
        let examples = [
            Example::new(g(&[&[1,2,3], &[4,5,6]]), g(&[&[4,1], &[5,2], &[6,3]])),
            Example::new(g(&[&[7,8], &[9,1], &[2,3]]), g(&[&[2,9,7], &[3,1,8]])),
        ];
        let result = synthesize(&examples, 1, 4096).unwrap();
        assert_eq!(result.depth, 1);
        assert!(result.programs.contains(&Program::new(vec![Operation::RotateClockwise]).unwrap()));
    }
    #[test] fn preserves_ambiguity() {
        let result = synthesize(&[Example::new(g(&[&[1,2]]), g(&[&[1], &[2]]))], 1, 4096).unwrap();
        assert!(result.programs.contains(&Program::new(vec![Operation::Transpose]).unwrap()));
        assert!(result.programs.contains(&Program::new(vec![Operation::RotateClockwise]).unwrap()));
    }
    #[test] fn no_model_is_explicit() {
        assert_eq!(synthesize(&[Example::new(g(&[&[1,2,3]]), g(&[&[9,9]]))], 1, 4096), Err(CcelError::NoConsistentModel));
    }
    #[test] fn limits_are_enforced() {
        let x = g(&[&[1]]);
        let ex = [Example::new(x.clone(), x.clone())];
        assert_eq!(synthesize(&ex, 0, 0), Err(CcelError::InvalidCandidateBudget));
        assert_eq!(synthesize(&ex, 6, 1), Err(CcelError::InvalidDepth));
        assert_eq!(Program::new(vec![Operation::Transpose; 6]), Err(CcelError::ProgramTooDeep));
    }
    #[test] fn probe_maximizes_disagreement() {
        let ps = [Program::new(vec![Operation::RotateClockwise]).unwrap(), Program::new(vec![Operation::FlipHorizontal]).unwrap()];
        let probes = [g(&[&[1,1], &[1,1]]), g(&[&[1,2,3], &[4,5,6]])];
        let choice = select_probe(&ps, &probes).unwrap();
        assert_eq!(choice.grid, probes[1]);
        assert_eq!(choice.distinct_outcomes, 2);
        assert!(choice.entropy_bits > 0.0);
    }
    #[test] fn predictions_are_unique() {
        let ps = [Program::new(vec![Operation::RotateClockwise]).unwrap(), Program::new(vec![Operation::FlipHorizontal]).unwrap()];
        assert_eq!(predict(&ps, &g(&[&[1,2,3], &[4,5,6]])).unwrap().len(), 2);
    }
    #[test] fn empty_inputs_fail_closed() {
        assert_eq!(synthesize(&[], 1, 10), Err(CcelError::NoExamples));
        let x = g(&[&[1]]);
        assert_eq!(predict(&[], &x), Err(CcelError::NoPrograms));
        assert_eq!(select_probe(&[], std::slice::from_ref(&x)), Err(CcelError::NoPrograms));
        assert_eq!(select_probe(&[Program::new(vec![]).unwrap()], &[]), Err(CcelError::NoProbes));
    }
}
