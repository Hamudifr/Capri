"""Validate and summarize repeated same-runner SQLite persistence comparisons."""
from __future__ import annotations
import argparse, json, statistics
from pathlib import Path
from typing import Any

def _change(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before == 0:
        return None
    return round((after / before - 1.0) * 100.0, 2)

def _median(values: list[float]) -> float:
    return round(statistics.median(values), 3)

def compare_reports(baseline_reports: list[dict[str, Any]], candidate_reports: list[dict[str, Any]], *, baseline_sha: str, candidate_sha: str) -> dict[str, Any]:
    if not baseline_reports or len(baseline_reports) != len(candidate_reports):
        raise ValueError("baseline and candidate must have the same non-zero round count")
    all_reports = baseline_reports + candidate_reports
    for report in all_reports:
        if report.get("schema_version") != 1 or report.get("benchmark") != "capri_sqlite_persistence_profile":
            raise ValueError("unsupported benchmark report schema")
        config = report.get("configuration", {})
        if config.get("external_network_calls") != 0 or config.get("external_provider_calls") != 0:
            raise ValueError("benchmark must not make external calls")
        concurrency = report.get("concurrency", {})
        if (concurrency.get("correctness") != "passed" or concurrency.get("duplicate_claims") != 0
                or concurrency.get("claimed_count") != concurrency.get("queue_size")):
            raise ValueError("concurrent task-claim correctness invariant failed")
    if any(x.get("commit_sha") != baseline_sha for x in baseline_reports):
        raise ValueError("baseline report commit SHA does not match requested baseline")
    if any(x.get("commit_sha") != candidate_sha for x in candidate_reports):
        raise ValueError("candidate report commit SHA does not match requested candidate")
    first = baseline_reports[0]
    environment, configuration = first.get("environment"), first.get("configuration")
    names = [x["name"] for x in first.get("results", [])]
    if not names or len(names) != len(set(names)):
        raise ValueError("benchmark workload names are empty or duplicated")
    for report in all_reports:
        if report.get("environment") != environment:
            raise ValueError("runner/runtime environment differs between samples")
        if report.get("configuration") != configuration:
            raise ValueError("benchmark configuration differs between samples")
        if [x["name"] for x in report.get("results", [])] != names:
            raise ValueError("benchmark workload set or order differs between samples")
        for item in report["results"]:
            count, samples = item.get("sample_count"), item.get("latency_samples_us", [])
            if type(count) is not int or count < 5 or len(samples) != count:
                raise ValueError(f"invalid raw latency samples for {item['name']}")
            if not all(k in item.get("latency_us", {}) for k in ("median", "p95", "p99")):
                raise ValueError(f"missing latency statistics for {item['name']}")
    workloads = []
    for name in names:
        before = [next(x for x in r["results"] if x["name"] == name) for r in baseline_reports]
        after = [next(x for x in r["results"] if x["name"] == name) for r in candidate_reports]
        row: dict[str, Any] = {"name": name}
        for metric in ("median", "p95", "p99"):
            b = _median([float(x["latency_us"][metric]) for x in before])
            c = _median([float(x["latency_us"][metric]) for x in after])
            row[f"baseline_{metric}_us"], row[f"candidate_{metric}_us"] = b, c
            row[f"{metric}_change_percent"] = _change(b, c)
        b_rates = [x.get("throughput_per_second") for x in before]
        c_rates = [x.get("throughput_per_second") for x in after]
        if all(x is not None for x in b_rates + c_rates):
            b, c = _median([float(x) for x in b_rates]), _median([float(x) for x in c_rates])
            row["baseline_throughput_per_second"], row["candidate_throughput_per_second"] = b, c
            row["throughput_change_percent"] = _change(b, c)
        workloads.append(row)
    b_claims = _median([float(x["concurrency"]["throughput_claims_per_second"]) for x in baseline_reports])
    c_claims = _median([float(x["concurrency"]["throughput_claims_per_second"]) for x in candidate_reports])
    return {
        "schema_version": 1, "benchmark": "capri_sqlite_persistence_comparison",
        "baseline_sha": baseline_sha, "candidate_sha": candidate_sha,
        "rounds_per_revision": len(baseline_reports),
        "run_order": ["baseline", "candidate", "candidate", "baseline", "baseline", "candidate"] if len(baseline_reports) == 3 else "alternating paired runs",
        "environment": environment, "configuration": configuration, "workloads": workloads,
        "concurrency": {"baseline_claims_per_second": b_claims, "candidate_claims_per_second": c_claims,
                        "throughput_change_percent": _change(b_claims, c_claims), "correctness": "passed for every run"},
        "interpretation": [
            "Displayed values are medians of per-run statistics across repeated runs.",
            "Negative latency change means faster candidate latency; positive throughput change means faster candidate throughput.",
            "Same-runner directional comparison, not a cross-machine performance claim.",
            "Three rounds are directional evidence, not a formal statistical significance test.",
            "No noisy percentage threshold is used as a CI pass/fail gate.",
        ],
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.rounds < 1:
        parser.error("--rounds must be at least 1")
    baseline, candidate = [], []
    for i in range(1, args.rounds + 1):
        baseline.append(json.loads((args.input_dir / f"baseline-{i}.json").read_text(encoding="utf-8")))
        candidate.append(json.loads((args.input_dir / f"candidate-{i}.json").read_text(encoding="utf-8")))
    result = compare_reports(baseline, candidate, baseline_sha=args.baseline_sha, candidate_sha=args.candidate_sha)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote comparison to {args.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
