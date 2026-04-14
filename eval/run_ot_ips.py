#!/usr/bin/env python3
"""Run crux on real OpenTitan IPs at full scale.

Auto-resolves dependencies, synthesizes with yosys-slang, runs crux analysis.
"""

import json
import subprocess
import time
import re
import sys
from pathlib import Path

OT_ROOT = Path("extern/opentitan/hw")
PLUGIN = Path("extern/yosys-slang/build/slang.so")
PRIM_RTL = OT_ROOT / "ip/prim/rtl"
RESULTS_DIR = Path("eval/results")

# IPs to analyze
IPS = [
    ("rv_timer", "rv_timer"),
    ("uart", "uart_core"),
    ("spi_host", "spi_host"),
    ("i2c", "i2c_core"),
    ("hmac", "hmac"),
]


def build_maps():
    """Build package and module name -> file maps."""
    pkg_map = {}
    mod_map = {}
    for sv in OT_ROOT.rglob("*.sv"):
        try:
            text = sv.read_text(errors="ignore")
        except Exception:
            continue
        for m in re.finditer(r'^\s*package\s+(\w+)\s*;', text, re.MULTILINE):
            pkg_map[m.group(1)] = str(sv)
        for m in re.finditer(r'^\s*module\s+(\w+)', text, re.MULTILINE):
            mod_map[m.group(1)] = str(sv)
    return {**pkg_map, **mod_map}


def try_compile(files, top):
    """Try yosys-slang compilation, return (success, missing_names)."""
    cmd = f"plugin -i {PLUGIN}; read_slang {' '.join(files)} -I {PRIM_RTL} --top {top} -DSYNTHESIS"
    result = subprocess.run(
        ["yosys", "-p", cmd],
        capture_output=True, text=True, timeout=120
    )
    if "Build succeeded" in result.stdout:
        return True, []
    missing = set()
    for line in (result.stdout + result.stderr).split("\n"):
        m = re.search(r"unknown (?:class or )?(?:package|module) '(\w+)'", line)
        if m:
            missing.add(m.group(1))
    return False, list(missing)


def resolve_and_compile(ip_name, top_module):
    """Resolve deps and compile."""
    all_maps = build_maps()
    ip_dir = OT_ROOT / "ip" / ip_name / "rtl"
    files = [str(f) for f in sorted(ip_dir.glob("*.sv"))]

    for _ in range(25):
        ok, missing = try_compile(files, top_module)
        if ok:
            return files
        added = False
        for name in missing:
            if name in all_maps and all_maps[name] not in files:
                files.insert(0, all_maps[name])
                added = True
        if not added:
            print(f"  STUCK: cannot resolve {missing[:5]}")
            return None
    return None


def run_crux_on_json(json_path):
    """Parse JSON and run crux analysis."""
    from crux.netlist import Netlist
    from crux.cdc_check import analyze_cdc

    t0 = time.perf_counter()
    netlist = Netlist.from_json(json_path)
    report = analyze_cdc(netlist)
    elapsed = time.perf_counter() - t0

    return {
        "ff_count": len(netlist.flip_flops),
        "cell_count": len(netlist.cells),
        "domain_count": len(report.domains),
        "domains": {d.clock_name: len(d.flip_flops) for d in report.domains.values()},
        "total_crossings": len(report.crossings),
        "synchronized": sum(1 for c in report.crossings if c.is_synchronized),
        "errors": report.error_count,
        "warnings": report.warning_count,
        "info": report.info_count,
        "analysis_ms": round(elapsed * 1000, 1),
        "violations": [
            {"rule": v.rule.value, "severity": v.severity.value,
             "signal": v.signal_name, "message": v.message}
            for v in report.violations if v.severity.value in ("error", "warning")
        ],
    }


def main():
    RESULTS_DIR.mkdir(exist_ok=True)
    results = {}

    for ip_name, top_module in IPS:
        print(f"\n{'='*60}")
        print(f"  {ip_name} (top: {top_module})")
        print(f"{'='*60}")

        # Resolve deps
        print("  Resolving dependencies...")
        files = resolve_and_compile(ip_name, top_module)
        if not files:
            print(f"  FAILED to compile {ip_name}")
            results[ip_name] = {"error": "compilation failed"}
            continue

        print(f"  Compiled: {len(files)} source files")

        # Synthesize
        json_out = f"/tmp/ot_{ip_name}.json"
        cmd = (
            f"plugin -i {PLUGIN}; "
            f"read_slang {' '.join(files)} -I {PRIM_RTL} --top {top_module} -DSYNTHESIS; "
            f"hierarchy -check; proc; opt -fast -purge; flatten; opt -fast -purge; "
            f"write_json {json_out}"
        )

        t0 = time.perf_counter()
        r = subprocess.run(["yosys", "-q", "-p", cmd], capture_output=True, text=True, timeout=300)
        synth_time = time.perf_counter() - t0

        if r.returncode != 0:
            print(f"  Synthesis FAILED: {r.stderr[:200]}")
            results[ip_name] = {"error": "synthesis failed"}
            continue

        print(f"  Synthesized in {synth_time:.1f}s")

        # Run crux
        crux_result = run_crux_on_json(json_out)
        crux_result["synth_time_s"] = round(synth_time, 2)
        crux_result["source_files"] = len(files)
        results[ip_name] = crux_result

        print(f"  FFs: {crux_result['ff_count']}, Cells: {crux_result['cell_count']}")
        print(f"  Domains: {crux_result['domains']}")
        print(f"  Crossings: {crux_result['total_crossings']}, Synced: {crux_result['synchronized']}")
        print(f"  Errors: {crux_result['errors']}, Warnings: {crux_result['warnings']}")
        print(f"  Analysis: {crux_result['analysis_ms']}ms")

    # Save results
    out = RESULTS_DIR / "ot_ip_results.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\n{'='*60}")
    print(f"Results saved to {out}")

    # Summary table
    print(f"\n{'IP':<15s} {'FFs':>6s} {'Cells':>6s} {'Dom':>4s} {'Cross':>6s} {'Sync':>5s} {'Err':>4s} {'Warn':>5s} {'ms':>8s}")
    print("-" * 65)
    for ip_name, r in results.items():
        if "error" in r:
            print(f"{ip_name:<15s} {'FAILED':>6s}")
            continue
        print(f"{ip_name:<15s} {r['ff_count']:>6d} {r['cell_count']:>6d} {r['domain_count']:>4d} "
              f"{r['total_crossings']:>6d} {r['synchronized']:>5d} {r['errors']:>4d} {r['warnings']:>5d} "
              f"{r['analysis_ms']:>8.1f}")


if __name__ == "__main__":
    main()
