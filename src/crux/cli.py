"""CLI entry point for crux CDC analysis."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import __version__
from .yosys_runner import run_yosys, YosysError
from .netlist import Netlist
from .cdc_check import analyze_cdc
from .report import format_text_report, format_json_report


@click.command()
@click.argument("verilog_files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--top", required=True, help="Top-level module name")
@click.option("--json-report", "json_path", type=click.Path(), default=None,
              help="Write JSON report to file")
@click.option("--work-dir", type=click.Path(), default=None,
              help="Working directory for intermediate files")
@click.option("-q", "--quiet", is_flag=True, help="Only show violations")
@click.option("-v", "--verbose", is_flag=True, help="Show Yosys output")
@click.version_option(version=__version__)
def main(
    verilog_files: tuple[str, ...],
    top: str,
    json_path: str | None,
    work_dir: str | None,
    quiet: bool,
    verbose: bool,
):
    """Crux: Clock Domain Crossing analysis engine.

    Analyze Verilog/SystemVerilog designs for CDC violations.

    \b
    Examples:
      crux --top my_design rtl/*.v
      crux --top uart_core --json-report report.json rtl/uart.v rtl/sync.v
    """
    file_list = list(verilog_files)

    if not quiet:
        click.echo(f"crux {__version__} - CDC analysis engine")
        click.echo(f"Analyzing {len(file_list)} file(s), top module: {top}")
        click.echo()

    # Step 1: Run Yosys to get netlist
    if not quiet:
        click.echo("Running Yosys synthesis...")

    try:
        json_netlist = run_yosys(
            file_list, top,
            work_dir=work_dir,
            quiet=not verbose,
        )
    except YosysError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not quiet:
        click.echo(f"Netlist exported to {json_netlist}")

    # Step 2: Parse netlist
    if not quiet:
        click.echo("Parsing netlist...")

    netlist = Netlist.from_json(json_netlist)

    if not quiet:
        click.echo(
            f"Found {len(netlist.flip_flops)} flip-flops, "
            f"{len(netlist.cells)} total cells"
        )

    # Step 3: Run CDC analysis
    if not quiet:
        click.echo("Running CDC analysis...")
        click.echo()

    report = analyze_cdc(netlist)

    # Step 4: Output report
    text = format_text_report(report)
    click.echo(text)

    # Step 5: Write JSON report if requested
    if json_path:
        json_data = format_json_report(report)
        with open(json_path, "w") as f:
            json.dump(json_data, f, indent=2)
        if not quiet:
            click.echo(f"\nJSON report written to {json_path}")

    # Exit code: non-zero if errors found
    if report.error_count > 0:
        sys.exit(1)
