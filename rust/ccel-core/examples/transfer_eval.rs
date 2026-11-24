use ccel_core::{Example, Grid, MAX_CANDIDATES, Operation, predict, synthesize};
use std::time::Instant;

#[derive(Clone, Copy)]
enum ExpectedKind {
    Unique,
    Ambiguous,
    Reject,
}

struct Case {
    name: &'static str,
    family: &'static str,
    known_solution: &'static str,
    examples: Vec<Example>,
    query: Grid,
    expected: Option<Grid>,
    kind: ExpectedKind,
}

fn grid(rows: &[&str]) -> Grid {
    Grid::new(
        rows.iter()
            .map(|row| row.bytes().map(|cell| cell - b'0').collect())
            .collect(),
    )
    .expect("versioned fixture grids are valid")
}

fn example(source: &[&str], target: &[&str]) -> Example {
    Example::new(grid(source), grid(target))
}

fn dataset_v1() -> Vec<Case> {
    vec![
        Case {
            name: "rotate_cw_rectangular",
            family: "single_operation",
            known_solution: "RotateClockwise",
            examples: vec![
                example(&["5937", "3838", "1739"], &["135", "789", "333", "987"]),
                example(&["05", "95", "85", "75"], &["7890", "5555"]),
            ],
            query: grid(&["51289", "52413"]),
            expected: Some(grid(&["55", "21", "42", "18", "39"])),
            kind: ExpectedKind::Unique,
        },
        Case {
            name: "rotate_ccw_rectangular",
            family: "single_operation",
            known_solution: "RotateCounterClockwise",
            examples: vec![
                example(&["079", "192", "548", "661"], &["9281", "7946", "0156"]),
                example(&["5814", "7159"], &["49", "15", "81", "57"]),
            ],
            query: grid(&["048", "383", "951", "529", "197"]),
            expected: Some(grid(&["83197", "48529", "03951"])),
            kind: ExpectedKind::Unique,
        },
        Case {
            name: "flip_horizontal",
            family: "single_operation",
            known_solution: "FlipHorizontal",
            examples: vec![
                example(&["50550", "28451", "96352"], &["05505", "15482", "25369"]),
                example(&["0673", "8574"], &["3760", "4758"]),
            ],
            query: grid(&["524", "425", "326", "227"]),
            expected: Some(grid(&["425", "524", "623", "722"])),
            kind: ExpectedKind::Unique,
        },
        Case {
            name: "flip_vertical",
            family: "single_operation",
            known_solution: "FlipVertical",
            examples: vec![
                example(
                    &["03", "04", "05", "39", "30"],
                    &["30", "39", "05", "04", "03"],
                ),
                example(&["5937", "6161", "0628"], &["0628", "6161", "5937"]),
            ],
            query: grid(&["05005", "28451"]),
            expected: Some(grid(&["28451", "05005"])),
            kind: ExpectedKind::Unique,
        },
        Case {
            name: "transpose_rectangular",
            family: "single_operation",
            known_solution: "Transpose",
            examples: vec![
                example(
                    &["51289", "85746", "42536", "09326"],
                    &["5840", "1529", "2753", "8432", "9666"],
                ),
                example(&["07", "75", "43"], &["074", "753"]),
            ],
            query: grid(&["581", "371", "161", "951", "741"]),
            expected: Some(grid(&["53197", "87654", "11111"])),
            kind: ExpectedKind::Unique,
        },
        Case {
            name: "rotate_180_composition",
            family: "two_operation_composition",
            known_solution: "RotateClockwise > RotateClockwise (equivalent FlipHorizontal > FlipVertical)",
            examples: vec![
                example(&["0482", "9494", "8406"], &["6048", "4949", "2840"]),
                example(&["505", "517", "529", "864"], &["468", "925", "715", "505"]),
            ],
            query: grid(&["06734", "18079"]),
            expected: Some(grid(&["97081", "43760"])),
            kind: ExpectedKind::Unique,
        },
        Case {
            name: "anti_diagonal_reflection_composition",
            family: "two_operation_composition",
            known_solution: "RotateClockwise > FlipVertical",
            examples: vec![
                example(
                    &["52468", "75814", "21593"],
                    &["348", "916", "584", "152", "275"],
                ),
                example(&["0369", "3715"], &["59", "16", "73", "30"]),
            ],
            query: grid(&["593", "272", "951", "630"]),
            expected: Some(grid(&["0123", "3579", "6925"])),
            kind: ExpectedKind::Unique,
        },
        Case {
            name: "single_demo_preserves_symmetry_ambiguity",
            family: "ambiguity",
            known_solution: "FlipHorizontal; the one demonstration is also consistent with RotateClockwise, FlipVertical and RotateCounterClockwise",
            examples: vec![example(&["246", "497", "676"], &["642", "794", "676"])],
            query: grid(&["05005", "84017", "63029"]),
            expected: Some(grid(&["50050", "71048", "92036"])),
            kind: ExpectedKind::Ambiguous,
        },
        Case {
            name: "shortest_program_suppresses_deeper_ambiguity",
            family: "cross_depth_ambiguity",
            known_solution: "FlipHorizontal; identity also fits the one horizontally symmetric demonstration",
            examples: vec![example(&["121", "343", "565"], &["121", "343", "565"])],
            query: grid(&["52468", "31470", "10482"]),
            expected: Some(grid(&["86425", "07413", "28401"])),
            kind: ExpectedKind::Ambiguous,
        },
        Case {
            name: "multiple_demos_resolve_flip",
            family: "ambiguity",
            known_solution: "FlipHorizontal",
            examples: vec![
                example(&["51289", "41302", "31425"], &["98215", "20314", "52413"]),
                example(&["0791", "0814"], &["1970", "4180"]),
            ],
            query: grid(&["581", "604", "050", "173"]),
            expected: Some(grid(&["185", "406", "050", "371"])),
            kind: ExpectedKind::Unique,
        },
        Case {
            name: "unsupported_cellwise_increment",
            family: "out_of_dsl_rejection",
            known_solution: "No accepted program; targets increment each cell modulo 10, which is outside the spatial DSL",
            examples: vec![
                example(&["0482", "2727", "7395"], &["1593", "3838", "8406"]),
                example(&["505", "840", "418", "086"], &["616", "951", "529", "197"]),
            ],
            query: grid(&["06734", "74635"]),
            expected: None,
            kind: ExpectedKind::Reject,
        },
    ]
}

fn one_operation_baseline(examples: &[Example], query: &Grid) -> Option<Vec<Grid>> {
    let candidates = [
        None,
        Some(Operation::RotateClockwise),
        Some(Operation::RotateCounterClockwise),
        Some(Operation::FlipHorizontal),
        Some(Operation::FlipVertical),
        Some(Operation::Transpose),
    ];
    let mut outputs = Vec::new();
    for operation in candidates {
        let matches = examples.iter().all(|example| {
            let output = match operation {
                None => example.source.clone(),
                Some(operation) => operation.apply(&example.source),
            };
            output == example.target
        });
        if matches {
            outputs.push(match operation {
                None => query.clone(),
                Some(operation) => operation.apply(query),
            });
        }
    }
    if outputs.is_empty() {
        return None;
    }
    outputs.sort();
    outputs.dedup();
    Some(outputs)
}

fn identity_baseline(examples: &[Example], query: &Grid) -> Option<Vec<Grid>> {
    if examples
        .iter()
        .all(|example| example.source == example.target)
    {
        Some(vec![query.clone()])
    } else {
        None
    }
}

fn score(kind: ExpectedKind, expected: Option<&Grid>, outputs: Option<&[Grid]>) -> bool {
    match kind {
        ExpectedKind::Unique => match (expected, outputs) {
            (Some(expected), Some(outputs)) => outputs.len() == 1 && outputs[0] == *expected,
            _ => false,
        },
        ExpectedKind::Ambiguous => match (expected, outputs) {
            (Some(expected), Some(outputs)) => outputs.len() > 1 && outputs.contains(expected),
            _ => false,
        },
        ExpectedKind::Reject => outputs.is_none(),
    }
}

fn main() {
    // v1.1 deliberately records the cross-depth ambiguity limitation instead of hiding it.
    const DATASET: &str = "CCEL-TRANSFER-v1.1";
    const MAX_DEPTH: usize = 3;
    let cases = dataset_v1();
    let unique_total = cases
        .iter()
        .filter(|case| matches!(case.kind, ExpectedKind::Unique))
        .count();
    let ambiguous_total = cases
        .iter()
        .filter(|case| matches!(case.kind, ExpectedKind::Ambiguous))
        .count();
    let reject_total = cases
        .iter()
        .filter(|case| matches!(case.kind, ExpectedKind::Reject))
        .count();

    let mut current_total = 0;
    let mut current_unique = 0;
    let mut current_ambiguous = 0;
    let mut current_reject = 0;
    let mut all_programs_valid = true;
    let mut total_programs = 0usize;
    let mut total_depth = 0usize;
    let mut depth_cases = 0usize;
    let current_start = Instant::now();

    let mut single_total = 0;
    let mut single_unique = 0;
    let mut identity_total = 0;
    let mut identity_unique = 0;

    println!("dataset={DATASET} cases={}", cases.len());
    println!(
        "scoring: unique=exactly one expected output; ambiguous=>1 outputs including expected; reject=no consistent program"
    );
    println!(
        "case\tfamily\tknown_solution\tcurrent\tdepth\tprograms\tpredictions\tone_op\tidentity"
    );

    for case in &cases {
        let one_op = one_operation_baseline(&case.examples, &case.query);
        let identity = identity_baseline(&case.examples, &case.query);
        let examples = &case.examples;

        let identity_ok = score(case.kind, case.expected.as_ref(), identity.as_deref());
        let single_ok = score(case.kind, case.expected.as_ref(), one_op.as_deref());
        identity_total += usize::from(identity_ok);
        single_total += usize::from(single_ok);
        if matches!(case.kind, ExpectedKind::Unique) {
            identity_unique += usize::from(identity_ok);
            single_unique += usize::from(single_ok);
        }

        let result = synthesize(examples, MAX_DEPTH, MAX_CANDIDATES);
        let (outputs, depth, program_count, valid) = match result {
            Ok(result) => {
                let valid = result.programs.iter().all(|program| {
                    examples
                        .iter()
                        .all(|example| program.apply(&example.source) == example.target)
                });
                let outputs = predict(&result.programs, &case.query)
                    .expect("synthesis returned a non-empty program set");
                let program_count = result.programs.len();
                let depth = result.depth;
                (Some(outputs), Some(depth), program_count, valid)
            }
            Err(_) => (None, None, 0, true),
        };

        let passed = score(case.kind, case.expected.as_ref(), outputs.as_deref());
        current_total += usize::from(passed);
        all_programs_valid &= valid;
        total_programs += program_count;
        if let Some(depth) = depth {
            total_depth += depth;
            depth_cases += 1;
        }
        match case.kind {
            ExpectedKind::Unique => current_unique += usize::from(passed),
            ExpectedKind::Ambiguous => current_ambiguous += usize::from(passed),
            ExpectedKind::Reject => current_reject += usize::from(passed),
        }

        let current_label = if passed { "PASS" } else { "FAIL" };
        println!(
            "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
            case.name,
            case.family,
            case.known_solution,
            current_label,
            depth.map_or_else(|| "-".to_string(), |value| value.to_string()),
            program_count,
            outputs.as_ref().map_or(0, Vec::len),
            if single_ok { "PASS" } else { "FAIL" },
            if identity_ok { "PASS" } else { "FAIL" },
        );
    }

    let elapsed_ms = current_start.elapsed().as_secs_f64() * 1000.0;
    println!(
        "current: {current_total}/{} total; unique={current_unique}/{unique_total}; ambiguity={current_ambiguous}/{ambiguous_total}; rejection={current_reject}/{reject_total}; programs={total_programs}; mean_min_depth={:.2}; elapsed_ms={elapsed_ms:.3}; program_validity={}",
        cases.len(),
        if depth_cases == 0 {
            0.0
        } else {
            total_depth as f64 / depth_cases as f64
        },
        all_programs_valid,
    );
    println!(
        "single_operation_baseline: {single_total}/{} total; unique={single_unique}/{unique_total}",
        cases.len(),
    );
    println!(
        "identity_baseline: {identity_total}/{} total; unique={identity_unique}/{unique_total}",
        cases.len(),
    );
    println!(
        "pilot_limits: n={} deterministic synthetic cases; no confidence interval; one run; runtime is runner-dependent",
        cases.len(),
    );

    assert!(
        current_total >= 10,
        "current synthesizer regressed below the pre-registered v1.1 pilot floor"
    );
    assert_eq!(
        current_unique, 8,
        "supported unique-task score changed unexpectedly"
    );
    assert_eq!(
        current_reject, 1,
        "out-of-DSL rejection behavior changed unexpectedly"
    );
    assert!(
        current_ambiguous >= 1,
        "same-depth ambiguity preservation regressed"
    );
    assert_eq!(
        single_total, 9,
        "single-operation baseline changed unexpectedly"
    );
    assert_eq!(
        single_unique, 6,
        "single-operation unique baseline changed unexpectedly"
    );
    assert_eq!(identity_total, 1, "identity baseline changed unexpectedly");
    assert_eq!(
        identity_unique, 0,
        "identity unique baseline changed unexpectedly"
    );
    assert!(
        all_programs_valid,
        "synthesizer returned a program inconsistent with its demonstrations"
    );
}
