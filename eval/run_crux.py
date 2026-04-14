#!/usr/bin/env python3
"""Run crux on all benchmark designs, collect JSON results + timing."""

import json
import subprocess
import time
from pathlib import Path

EVAL_DIR = Path(__file__).parent
RESULTS_DIR = EVAL_DIR / "results"


def run_crux(verilog: Path, top: str, sdc: Path | None = None) -> dict:
    """Invoke crux, return parsed JSON report + runtime."""
    json_out = Path(f"/tmp/crux_eval_{top}.json")

    cmd = ["python", "-m", "crux", "--top", top, "--json-report", str(json_out), "-q"]
    if sdc:
        cmd += ["--sdc", str(sdc)]
    cmd.append(str(verilog))

    start = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    elapsed = time.perf_counter() - start

    report = {}
    if json_out.exists():
        report = json.loads(json_out.read_text())

    return {
        "top": top,
        "runtime_s": round(elapsed, 3),
        "exit_code": result.returncode,
        "report": report,
    }


def main():
    RESULTS_DIR.mkdir(exist_ok=True)
    results = {}

    # SoC-A: small benchmark
    small_dir = EVAL_DIR / "benchmarks" / "small"
    r = run_crux(
        small_dir / "crux_bench_small.v",
        "crux_bench_small",
        small_dir / "crux_bench_small.sdc",
    )
    results["small_golden"] = r
    print(f"SoC-A: {r['report'].get('summary', {}).get('errors', '?')} errors, "
          f"{r['runtime_s']}s")

    # SoC-A mutants
    mutant_dir = EVAL_DIR / "mutants" / "small"
    if mutant_dir.exists():
        for m in sorted(mutant_dir.iterdir()):
            if not m.is_dir():
                continue
            v_file = m / "crux_bench_small.v"
            if not v_file.exists():
                continue
            r = run_crux(v_file, "crux_bench_small", small_dir / "crux_bench_small.sdc")
            results[f"small_{m.name}"] = r
            print(f"  Mutant {m.name}: {r['report'].get('summary', {}).get('errors', '?')} errors")

    # SoC-B: large benchmark
    large_dir = EVAL_DIR / "benchmarks" / "large"
    if (large_dir / "ot_aon_wrapper.v").exists():
        r = run_crux(
            large_dir / "ot_aon_wrapper.v",
            "ot_aon_wrapper",
            large_dir / "ot_aon.sdc" if (large_dir / "ot_aon.sdc").exists() else None,
        )
        results["large_golden"] = r
        print(f"SoC-B: {r['report'].get('summary', {}).get('errors', '?')} errors, "
              f"{r['runtime_s']}s")

    out = RESULTS_DIR / "crux_results.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nResults written to {out}")


if __name__ == "__main__":
    main()
