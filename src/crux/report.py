"""Generate CDC/RDC analysis reports in text and JSON formats."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from io import StringIO

from . import __version__
from .cdc_check import CDCReport, Crossing, Violation, Severity


def format_text_report(report: CDCReport, file=None) -> str:
    """Generate a human-readable text report."""
    buf = StringIO()

    buf.write("=" * 60 + "\n")
    buf.write("  Crux CDC/RDC Analysis Report\n")
    buf.write("=" * 60 + "\n\n")

    buf.write(f"  Design:   {report.module_name}\n")
    buf.write(f"  Date:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    buf.write(f"  Version:  crux {__version__}\n\n")

    # Clock domains
    buf.write("Clock Domains:\n")
    buf.write("-" * 40 + "\n")
    if not report.domains:
        buf.write("  (no flip-flops found)\n")
    else:
        for domain in sorted(report.domains.values(), key=lambda d: d.clock_name):
            edge = "posedge" if domain.polarity else "negedge"
            buf.write(
                f"  {domain.clock_name:<20s} {len(domain.flip_flops):>4d} FFs  ({edge})\n"
            )
    buf.write("\n")

    # Crossing summary by domain pair
    pair_crossings: dict[tuple[str, str], list[Crossing]] = defaultdict(list)
    for c in report.crossings:
        pair_crossings[(c.source_domain, c.dest_domain)].append(c)

    buf.write("Domain Crossings:\n")
    buf.write("-" * 60 + "\n")
    if not pair_crossings:
        buf.write("  (no crossings found)\n")
    else:
        for (src, dst), clist in sorted(pair_crossings.items()):
            synced = sum(1 for c in clist if c.is_synchronized)
            violations = len(clist) - synced
            status = "OK" if violations == 0 else f"{violations} VIOLATION(S)"
            buf.write(
                f"  {src} -> {dst}: "
                f"{len(clist)} signal(s), {synced} synchronized, {status}\n"
            )
    buf.write("\n")

    # Violations (errors and warnings only in main section)
    errors_warnings = [v for v in report.violations if v.severity in (Severity.ERROR, Severity.WARNING)]
    buf.write("Violations:\n")
    buf.write("-" * 60 + "\n")
    if not errors_warnings:
        buf.write("  None.\n")
    else:
        for i, v in enumerate(errors_warnings, 1):
            buf.write(f"  {i}. {v.format()}\n")
            if v.crossing:
                c = v.crossing
                buf.write(f"     Signal: {c.signal_name}\n")
                buf.write(f"     Path:   {c.source_domain} -> {c.dest_domain}\n")
            elif v.signal_name:
                buf.write(f"     Signal: {v.signal_name}\n")
                if v.source_domain and v.dest_domain:
                    buf.write(f"     Path:   {v.source_domain} -> {v.dest_domain}\n")
            buf.write("\n")

    # Info-level findings (reconvergence through mux, etc.)
    infos = [v for v in report.violations if v.severity == Severity.INFO]
    if infos:
        buf.write("Info:\n")
        buf.write("-" * 60 + "\n")
        for v in infos:
            buf.write(f"  {v.format()}\n")
        buf.write("\n")

    # Synchronized crossings
    synced = [c for c in report.crossings if c.is_synchronized]
    if synced:
        buf.write("Synchronized Crossings:\n")
        buf.write("-" * 60 + "\n")
        for c in synced:
            sync_type = ""
            if c.synchronizer:
                sync_type = f" [{c.synchronizer.sync_type}"
                if c.synchronizer.module_name:
                    sync_type += f": {c.synchronizer.module_name}"
                sync_type += f", {c.synchronizer.depth}-stage]"
            buf.write(
                f"  {c.signal_name}: {c.source_domain} -> {c.dest_domain}{sync_type}\n"
            )
        buf.write("\n")

    # Waived violations
    if report.waived_violations:
        buf.write("Waived Violations:\n")
        buf.write("-" * 60 + "\n")
        for v, w in report.waived_violations:
            buf.write(f"  [{v.rule.value}] {v.signal_name}")
            buf.write(f" - waived: {w.reason}\n")
        buf.write("\n")

    # Summary
    buf.write("=" * 60 + "\n")
    buf.write(f"  Total crossings:  {len(report.crossings)}\n")
    buf.write(f"  Synchronized:     {sum(1 for c in report.crossings if c.is_synchronized)}\n")
    buf.write(f"  Errors:           {report.error_count}\n")
    buf.write(f"  Warnings:         {report.warning_count}\n")
    if report.info_count:
        buf.write(f"  Info:             {report.info_count}\n")
    if report.waived_violations:
        buf.write(f"  Waived:           {len(report.waived_violations)}\n")
    if report.sdc_loaded:
        buf.write(f"  SDC constraints:  loaded\n")
    buf.write("=" * 60 + "\n")

    text = buf.getvalue()
    if file is not None:
        file.write(text)
    return text


def format_json_report(report: CDCReport) -> dict:
    """Generate a machine-readable JSON report."""
    return {
        "tool": "crux",
        "version": __version__,
        "design": report.module_name,
        "clock_domains": [
            {
                "name": d.clock_name,
                "clock_net": d.clock_net,
                "polarity": "posedge" if d.polarity else "negedge",
                "ff_count": len(d.flip_flops),
            }
            for d in sorted(report.domains.values(), key=lambda d: d.clock_name)
        ],
        "crossings": [
            {
                "source_ff": c.source_ff_name,
                "dest_ff": c.dest_ff_name,
                "source_domain": c.source_domain,
                "dest_domain": c.dest_domain,
                "signal": c.signal_name,
                "has_combo_logic": c.path_has_combo,
                "is_synchronized": c.is_synchronized,
            }
            for c in report.crossings
        ],
        "violations": [
            {
                "rule": v.rule.value,
                "severity": v.severity.value,
                "message": v.message,
                "signal": v.signal_name,
                "source_domain": v.source_domain,
                "dest_domain": v.dest_domain,
            }
            for v in report.violations
        ],
        "waived": [
            {
                "rule": v.rule.value,
                "signal": v.signal_name,
                "reason": w.reason,
            }
            for v, w in report.waived_violations
        ],
        "summary": {
            "total_crossings": len(report.crossings),
            "synchronized": sum(1 for c in report.crossings if c.is_synchronized),
            "errors": report.error_count,
            "warnings": report.warning_count,
            "info": report.info_count,
            "waived": len(report.waived_violations),
        },
    }
