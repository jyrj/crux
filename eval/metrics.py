#!/usr/bin/env python3
"""Compute precision/recall/F1 from crux and LLM results vs ground truth."""

import json
import yaml
from pathlib import Path
from dataclasses import dataclass

EVAL_DIR = Path(__file__).parent


@dataclass
class Metrics:
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def load_ground_truth(bench: str) -> list[dict]:
    """Load expected bugs from ground truth YAML."""
    gt_path = EVAL_DIR / "benchmarks" / bench / "ground_truth.yaml"
    with open(gt_path) as f:
        gt = yaml.safe_load(f)
    return [c for c in gt["crossings"] if c.get("bug")]


def match_violations(found: list[dict], expected: list[dict]) -> Metrics:
    """Match found violations to expected bugs by (rule, src, dst) tuple."""
    matched = set()
    tp = 0

    for f in found:
        f_key = (f.get("rule"), f.get("source_domain"), f.get("dest_domain"))
        for i, e in enumerate(expected):
            if i in matched:
                continue
            e_key = (e.get("rule"), e.get("src"), e.get("dst"))
            if f_key == e_key:
                tp += 1
                matched.add(i)
                break

    fp = len(found) - tp
    fn = len(expected) - len(matched)
    return Metrics(tp=tp, fp=fp, fn=fn)


def evaluate_crux(bench: str) -> Metrics:
    """Evaluate crux results against ground truth."""
    results_path = EVAL_DIR / "results" / "crux_results.json"
    with open(results_path) as f:
        results = json.load(f)

    key = f"{bench}_golden"
    if key not in results:
        print(f"No crux results for {key}")
        return Metrics(0, 0, 0)

    report = results[key]["report"]
    # Only count ERROR-severity violations (not warnings/info)
    found = [v for v in report.get("violations", []) if v.get("severity") == "error"]
    expected = load_ground_truth(bench)

    return match_violations(found, expected)


def evaluate_llm(bench: str) -> Metrics | None:
    """Evaluate LLM results against ground truth."""
    llm_path = EVAL_DIR / "results" / "llm_results.json"
    if not llm_path.exists():
        return None
    with open(llm_path) as f:
        results = json.load(f)

    key = f"{bench}_golden"
    if key not in results:
        return None

    found = results[key].get("violations", [])
    expected = load_ground_truth(bench)
    return match_violations(found, expected)


def main():
    print("=" * 60)
    print("  Crux vs LLM: CDC Bug Detection Metrics")
    print("=" * 60)

    for bench in ["small"]:
        expected = load_ground_truth(bench)
        print(f"\nBenchmark: {bench} ({len(expected)} known bugs)")
        print("-" * 50)

        crux_m = evaluate_crux(bench)
        print(f"  crux:  TP={crux_m.tp} FP={crux_m.fp} FN={crux_m.fn} "
              f"P={crux_m.precision:.2f} R={crux_m.recall:.2f} F1={crux_m.f1:.2f}")

        llm_m = evaluate_llm(bench)
        if llm_m:
            print(f"  LLM:   TP={llm_m.tp} FP={llm_m.fp} FN={llm_m.fn} "
                  f"P={llm_m.precision:.2f} R={llm_m.recall:.2f} F1={llm_m.f1:.2f}")
        else:
            print(f"  LLM:   (no results yet — run eval/run_llm_baseline.sh)")


if __name__ == "__main__":
    main()
