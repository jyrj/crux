#!/usr/bin/env python3
"""Analyze crux vs LLM baseline results and generate comparison table."""

import json
import yaml
from pathlib import Path
from dataclasses import dataclass

EVAL_DIR = Path(__file__).parent


@dataclass
class Metrics:
    tp: int; fp: int; fn: int; runtime_ms: int

    @property
    def precision(self): return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 1.0
    @property
    def recall(self): return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 1.0
    @property
    def f1(self):
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def load_ground_truth(bench: str) -> list[dict]:
    gt = yaml.safe_load((EVAL_DIR / "benchmarks" / bench / "ground_truth.yaml").read_text())
    return [c for c in gt["crossings"] if c.get("bug")]


def match_violations(found: list[dict], expected: list[dict]) -> tuple[int, int, int]:
    """Returns (TP, FP, FN). Matches on (rule, src, dst)."""
    matched = set()
    tp = 0
    for f in found:
        f_key = (f.get("rule"), f.get("source_domain"), f.get("dest_domain"))
        for i, e in enumerate(expected):
            if i in matched:
                continue
            e_key = (e.get("rule"), e.get("src"), e.get("dst"))
            if f_key == e_key:
                tp += 1; matched.add(i); break
    return tp, len(found) - tp, len(expected) - len(matched)


def analyze_crux(bench: str) -> Metrics:
    results = json.loads((EVAL_DIR / "results" / "crux_results.json").read_text())
    r = results[f"{bench}_golden"]
    found = [v for v in r["report"].get("violations", []) if v.get("severity") == "error"]
    expected = load_ground_truth(bench)
    tp, fp, fn = match_violations(found, expected)
    return Metrics(tp, fp, fn, int(r["runtime_s"] * 1000))


def analyze_llm_runs(bench: str) -> list[Metrics]:
    """Analyze all LLM runs for a benchmark."""
    results_dir = EVAL_DIR / "llm_baseline" / "results"
    runs = []
    for i in range(1, 10):
        f = results_dir / f"{bench}_run{i}.json"
        meta = results_dir / f"{bench}_run{i}_meta.json"
        if not f.exists():
            break
        data = json.loads(f.read_text())
        found = data.get("violations", [])
        expected = load_ground_truth(bench)
        tp, fp, fn = match_violations(found, expected)
        rt = json.loads(meta.read_text()).get("runtime_ms", 0) if meta.exists() else 0
        runs.append(Metrics(tp, fp, fn, rt))
    return runs


def per_rule_analysis(bench: str):
    """Check which specific rules each tool finds/misses per run."""
    expected = load_ground_truth(bench)
    rules = [e["rule"] for e in expected]

    # Crux
    results = json.loads((EVAL_DIR / "results" / "crux_results.json").read_text())
    crux_found = [v["rule"] for v in results[f"{bench}_golden"]["report"].get("violations", [])
                  if v.get("severity") == "error"]

    print("\nPer-rule detection:")
    print(f"{'Rule':<25s} {'Ground Truth':<12s} {'crux':<8s}", end="")

    # LLM runs
    results_dir = EVAL_DIR / "llm_baseline" / "results"
    llm_runs_rules = []
    for i in range(1, 10):
        f = results_dir / f"{bench}_run{i}.json"
        if not f.exists():
            break
        data = json.loads(f.read_text())
        found_rules = [v["rule"] for v in data.get("violations", [])]
        llm_runs_rules.append(found_rules)
        print(f" {'LLM-' + str(i):<8s}", end="")
    print()
    print("-" * (25 + 12 + 8 + 8 * len(llm_runs_rules)))

    for e in expected:
        rule = e["rule"]
        src, dst = e["src"], e["dst"]
        crux_hit = any(r == rule for r in crux_found)
        print(f"{rule:<25s} {src}->{dst:<8s} {'YES' if crux_hit else 'MISS':<8s}", end="")
        for lr in llm_runs_rules:
            hit = any(r == rule for r in lr)
            print(f" {'YES' if hit else 'MISS':<8s}", end="")
        print()


def main():
    bench = "small"
    expected = load_ground_truth(bench)

    print("=" * 70)
    print("  CRUX vs LLM (Claude Opus 4.6): CDC Bug Detection Comparison")
    print("=" * 70)
    print(f"\nBenchmark: {bench}")
    print(f"Design: crux_bench_small (4 clock domains, 34 FFs)")
    print(f"Ground truth: {len(expected)} bugs")
    print()

    # Crux results
    crux = analyze_crux(bench)
    print(f"{'Tool':<20s} {'TP':>4s} {'FP':>4s} {'FN':>4s} {'P':>6s} {'R':>6s} {'F1':>6s} {'Time':>10s}")
    print("-" * 60)
    print(f"{'crux':<20s} {crux.tp:>4d} {crux.fp:>4d} {crux.fn:>4d} "
          f"{crux.precision:>6.2f} {crux.recall:>6.2f} {crux.f1:>6.2f} "
          f"{crux.runtime_ms:>7d} ms")

    # LLM results
    llm_runs = analyze_llm_runs(bench)
    for i, m in enumerate(llm_runs, 1):
        print(f"{'LLM run ' + str(i):<20s} {m.tp:>4d} {m.fp:>4d} {m.fn:>4d} "
              f"{m.precision:>6.2f} {m.recall:>6.2f} {m.f1:>6.2f} "
              f"{m.runtime_ms:>7d} ms")

    if llm_runs:
        avg_tp = sum(m.tp for m in llm_runs) / len(llm_runs)
        avg_fp = sum(m.fp for m in llm_runs) / len(llm_runs)
        avg_fn = sum(m.fn for m in llm_runs) / len(llm_runs)
        avg_rt = sum(m.runtime_ms for m in llm_runs) / len(llm_runs)
        avg_p = sum(m.precision for m in llm_runs) / len(llm_runs)
        avg_r = sum(m.recall for m in llm_runs) / len(llm_runs)
        avg_f1 = sum(m.f1 for m in llm_runs) / len(llm_runs)
        print(f"{'LLM average':<20s} {avg_tp:>4.1f} {avg_fp:>4.1f} {avg_fn:>4.1f} "
              f"{avg_p:>6.2f} {avg_r:>6.2f} {avg_f1:>6.2f} "
              f"{avg_rt:>7.0f} ms")

    # Speedup
    if llm_runs:
        avg_llm_ms = sum(m.runtime_ms for m in llm_runs) / len(llm_runs)
        if crux.runtime_ms > 0:
            speedup = avg_llm_ms / crux.runtime_ms
            print(f"\ncrux speedup over LLM: {speedup:.0f}x")

    per_rule_analysis(bench)

    # Key takeaway
    print("\n" + "=" * 70)
    if llm_runs:
        all_perfect = all(m.tp == len(expected) and m.fp == 0 for m in llm_runs)
        if all_perfect:
            print("NOTE: LLM found all bugs on this small design (~280 LOC).")
            print("This is expected — the design fits in the LLM context window.")
            print("The real test is on larger designs (SoC-B, 1000+ LOC) where")
            print("LLMs cannot see the full design at once.")
        else:
            llm_misses = [m for m in llm_runs if m.fn > 0]
            llm_fps = [m for m in llm_runs if m.fp > 0]
            if llm_misses:
                print(f"LLM missed bugs in {len(llm_misses)}/{len(llm_runs)} runs.")
            if llm_fps:
                print(f"LLM had false positives in {len(llm_fps)}/{len(llm_runs)} runs.")
    print("=" * 70)


if __name__ == "__main__":
    main()
