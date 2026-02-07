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
from .sdc_parser import parse_sdc, SDCConstraints
from .report import format_text_report, format_json_report


@click.command()
@click.argument("verilog_files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--top", required=True, help="Top-level module name")
@click.option("--sdc", "sdc_path", type=click.Path(exists=True), default=None,
              help="SDC constraints file (clock definitions, async groups)")
@click.option("--json-report", "json_path", type=click.Path(), default=None,
              help="Write JSON report to file")
@click.option("--work-dir", type=click.Path(), default=None,
              help="Working directory for intermediate files")
@click.option("--sv", "use_slang", is_flag=True,
              help="Use yosys-slang plugin for SystemVerilog support")
@click.option("-I", "--include", "include_dirs", multiple=True,
              help="Include directory for `include resolution (repeatable)")
@click.option("-D", "--define", "defines", multiple=True,
              help="Preprocessor define (repeatable, e.g. -DSYNTHESIS)")
@click.option("-q", "--quiet", is_flag=True, help="Only show violations")
@click.option("-v", "--verbose", is_flag=True, help="Show Yosys output")
@click.version_option(version=__version__)
def main(
    verilog_files: tuple[str, ...],
    top: str,
    sdc_path: str | None,
    json_path: str | None,
    work_dir: str | None,
    use_slang: bool,
    include_dirs: tuple[str, ...],
    defines: tuple[str, ...],
    quiet: bool,
    verbose: bool,
):
    """Crux: Clock Domain Crossing analysis engine.

    Analyze Verilog/SystemVerilog designs for CDC violations.

    \b
    Examples:
      crux --top my_design rtl/*.v
      crux --top uart_core --sdc constraints.sdc rtl/uart.sv
      crux --sv --top aon_timer rtl/*.sv   # SystemVerilog via yosys-slang
    """
    file_list = list(verilog_files)

    if not quiet:
        click.echo(f"crux {__version__} - CDC analysis engine")
        click.echo(f"Analyzing {len(file_list)} file(s), top module: {top}")
        if sdc_path:
            click.echo(f"SDC constraints: {sdc_path}")
        click.echo()

    # Parse SDC constraints if provided
    sdc: SDCConstraints | None = None
    if sdc_path:
        if not quiet:
            click.echo("Parsing SDC constraints...")
        sdc = parse_sdc(sdc_path)
        if not quiet:
            click.echo(
                f"  {len(sdc.clocks)} clock(s), "
                f"{len(sdc.clock_groups)} group(s), "
                f"{len(sdc.false_paths)} false path(s)"
            )

    # Run Yosys to get netlist
    if not quiet:
        click.echo("Running Yosys synthesis...")

    try:
        json_netlist = run_yosys(
            file_list, top,
            work_dir=work_dir,
            quiet=not verbose,
            use_slang=use_slang,
            include_dirs=list(include_dirs) if include_dirs else None,
            defines=list(defines) if defines else None,
        )
    except YosysError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not quiet:
        click.echo(f"Netlist exported to {json_netlist}")

    # Parse netlist
    if not quiet:
        click.echo("Parsing netlist...")

    netlist = Netlist.from_json(json_netlist)

    if not quiet:
        click.echo(
            f"Found {len(netlist.flip_flops)} flip-flops, "
            f"{len(netlist.cells)} total cells"
        )

    # Run CDC analysis
    if not quiet:
        click.echo("Running CDC analysis...")
        click.echo()

    report = analyze_cdc(netlist, sdc=sdc)

    # Output report
    text = format_text_report(report)
    click.echo(text)

    # Write JSON report if requested
    if json_path:
        json_data = format_json_report(report)
        with open(json_path, "w") as f:
            json.dump(json_data, f, indent=2)
        if not quiet:
            click.echo(f"\nJSON report written to {json_path}")

    # Exit code: non-zero if errors found
    if report.error_count > 0:
        sys.exit(1)
