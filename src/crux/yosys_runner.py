"""Generate and execute Yosys synthesis scripts for CDC analysis."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


class YosysError(Exception):
    """Raised when Yosys execution fails."""
    pass


def check_yosys() -> str:
    """Check that Yosys is installed and return its version string."""
    yosys_path = shutil.which("yosys")
    if yosys_path is None:
        raise YosysError(
            "Yosys not found in PATH. Install with: dnf install yosys (Fedora) "
            "or apt install yosys (Debian/Ubuntu)"
        )
    result = subprocess.run(
        ["yosys", "--version"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


def generate_script(
    verilog_files: list[str],
    top_module: str,
    json_output: str,
) -> str:
    """Generate a Yosys TCL script for CDC netlist preparation.

    The script:
    1. Reads all Verilog files
    2. Sets the top module and checks hierarchy
    3. Converts behavioral processes to explicit FFs (proc)
    4. Flattens the design (CDC paths span module boundaries)
    5. Optimizes to clean up unused logic
    6. Exports to JSON with explicit $dff cells
    """
    lines = []

    # Read input files
    for f in verilog_files:
        # Escape any special characters in path
        escaped = f.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'read_verilog "{escaped}"')

    # Elaborate
    lines.append(f"hierarchy -check -top {top_module}")

    # Convert processes to netlist (makes FFs explicit)
    lines.append("proc")

    # First optimization pass
    lines.append("opt -fast -purge")

    # Flatten hierarchy - essential for cross-module CDC tracing
    lines.append("flatten")

    # Clean up after flattening
    lines.append("opt -fast -purge")

    # Export to JSON
    escaped_out = json_output.replace("\\", "\\\\").replace('"', '\\"')
    lines.append(f'write_json "{escaped_out}"')

    return "\n".join(lines)


def run_yosys(
    verilog_files: list[str],
    top_module: str,
    work_dir: str | None = None,
    quiet: bool = True,
) -> Path:
    """Run Yosys on the given Verilog files and return path to JSON netlist.

    Args:
        verilog_files: Paths to Verilog/SystemVerilog source files.
        top_module: Name of the top-level module.
        work_dir: Directory for intermediate files. Uses temp dir if None.
        quiet: Suppress Yosys output.

    Returns:
        Path to the generated JSON netlist file.
    """
    check_yosys()

    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="crux_")
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)

    json_output = str(work_path / "netlist.json")
    script = generate_script(verilog_files, top_module, json_output)

    script_path = work_path / "cdc_prep.ys"
    script_path.write_text(script)

    # Run Yosys
    cmd = ["yosys", "-s", str(script_path)]
    if quiet:
        cmd.insert(1, "-q")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )
    except subprocess.TimeoutExpired:
        raise YosysError("Yosys timed out after 300 seconds")

    if result.returncode != 0:
        raise YosysError(
            f"Yosys failed (exit code {result.returncode}):\n"
            f"{result.stderr}"
        )

    json_path = Path(json_output)
    if not json_path.exists():
        raise YosysError(
            f"Yosys completed but JSON output not found at {json_output}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    return json_path
