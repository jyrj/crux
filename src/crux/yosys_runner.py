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


def _find_slang_plugin() -> str | None:
    """Find the yosys-slang plugin shared library."""
    candidates = [
        # Built from our submodule
        Path(__file__).parent.parent.parent / "extern" / "yosys-slang" / "build" / "slang.so",
        # System-wide install
        Path("/usr/lib/yosys/plugins/slang.so"),
        Path("/usr/local/lib/yosys/plugins/slang.so"),
        Path("/usr/share/yosys/plugins/slang.so"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def generate_script(
    verilog_files: list[str],
    top_module: str,
    json_output: str,
    use_slang: bool = False,
    slang_plugin_path: str | None = None,
    include_dirs: list[str] | None = None,
    defines: list[str] | None = None,
) -> str:
    """Generate a Yosys script for CDC netlist preparation.

    Supports two frontend modes:
    - Verilog mode (default): uses Yosys's built-in read_verilog
    - SystemVerilog mode (--sv): uses yosys-slang plugin for full SV support
    """
    lines = []

    if use_slang:
        if slang_plugin_path:
            abs_plugin = str(Path(slang_plugin_path).resolve())
            lines.append(f"plugin -i {abs_plugin}")
        else:
            lines.append("plugin -i slang")

        # Build read_slang command with all files (absolute paths, no quotes)
        # slang uses its own argument parser, not Yosys TCL-style quoting
        slang_args = []
        for f in verilog_files:
            slang_args.append(str(Path(f).resolve()))

        if include_dirs:
            for d in include_dirs:
                slang_args.append(f"-I {str(Path(d).resolve())}")

        if defines:
            for d in defines:
                slang_args.append(f"-D{d}")

        slang_args.append(f"--top {top_module}")
        lines.append(f"read_slang {' '.join(slang_args)}")
    else:
        # Standard Verilog mode - use absolute paths since Yosys -s resolves
        # relative to the script file, not the caller's CWD
        extra_flags = []
        if defines:
            extra_flags.extend(f"-D{d}" for d in defines)
        if include_dirs:
            for d in include_dirs:
                abs_d = str(Path(d).resolve())
                extra_flags.append(f"-I {abs_d}")

        extra = (" " + " ".join(extra_flags)) if extra_flags else ""
        for f in verilog_files:
            abs_f = str(Path(f).resolve())
            escaped = abs_f.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'read_verilog -sv{extra} "{escaped}"')

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
    use_slang: bool = False,
    include_dirs: list[str] | None = None,
    defines: list[str] | None = None,
) -> Path:
    """Run Yosys on the given Verilog/SV files and return path to JSON netlist.

    Args:
        verilog_files: Paths to Verilog/SystemVerilog source files.
        top_module: Name of the top-level module.
        work_dir: Directory for intermediate files. Uses temp dir if None.
        quiet: Suppress Yosys output.
        use_slang: Use yosys-slang plugin for SystemVerilog.
        include_dirs: Include directories for `include resolution.
        defines: Preprocessor defines (e.g. ["SYNTHESIS", "WIDTH=8"]).

    Returns:
        Path to the generated JSON netlist file.
    """
    check_yosys()

    # Find slang plugin if needed
    slang_plugin_path = None
    if use_slang:
        slang_plugin_path = _find_slang_plugin()
        if slang_plugin_path is None:
            raise YosysError(
                "yosys-slang plugin not found. Build it with:\n"
                "  cd extern/yosys-slang && make\n"
                "Or install system-wide."
            )

    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="crux_")
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)

    json_output = str(work_path / "netlist.json")
    script = generate_script(
        verilog_files, top_module, json_output,
        use_slang=use_slang,
        slang_plugin_path=slang_plugin_path,
        include_dirs=include_dirs,
        defines=defines,
    )

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
            timeout=300,
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
