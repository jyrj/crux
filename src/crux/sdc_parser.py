"""SDC (Synopsys Design Constraints) parser using Python's built-in TCL interpreter.

This is NOT a regex hack - we use a real TCL interpreter to evaluate SDC files,
which are valid TCL scripts. We register custom command handlers for the SDC
commands we care about (create_clock, create_generated_clock, set_clock_groups,
set_false_path) and let TCL handle all the parsing, variable expansion, and
control flow.

This is the same approach commercial tools use - SDC is TCL by design.
"""

from __future__ import annotations

import tkinter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ClockDefinition:
    """A clock defined via create_clock or create_generated_clock."""
    name: str
    period: float | None = None          # ns
    waveform: tuple[float, float] | None = None  # (rise, fall) in ns
    port: str | None = None              # Port name the clock is attached to
    source: str | None = None            # For generated clocks: source clock/pin
    divide_by: int | None = None         # For generated clocks
    multiply_by: int | None = None       # For generated clocks
    is_generated: bool = False


@dataclass
class ClockGroup:
    """A group of clocks declared as asynchronous/exclusive."""
    groups: list[list[str]]              # List of groups, each group is list of clock names
    relationship: str = "asynchronous"   # "asynchronous", "exclusive", "physically_exclusive"


@dataclass
class FalsePath:
    """A false path declaration."""
    from_clock: str | None = None
    to_clock: str | None = None
    from_pin: str | None = None
    to_pin: str | None = None


@dataclass
class SDCConstraints:
    """All constraints parsed from an SDC file."""
    clocks: dict[str, ClockDefinition] = field(default_factory=dict)
    clock_groups: list[ClockGroup] = field(default_factory=list)
    false_paths: list[FalsePath] = field(default_factory=list)

    def are_clocks_async(self, clk_a: str, clk_b: str) -> bool:
        """Check if two clocks are declared as asynchronous."""
        for cg in self.clock_groups:
            if cg.relationship in ("asynchronous", "exclusive", "physically_exclusive"):
                # Find which groups each clock belongs to
                group_a = None
                group_b = None
                for i, group in enumerate(cg.groups):
                    if clk_a in group:
                        group_a = i
                    if clk_b in group:
                        group_b = i
                # Async if they're in different groups within the same set_clock_groups
                if group_a is not None and group_b is not None and group_a != group_b:
                    return True
        return False

    def are_clocks_related(self, clk_a: str, clk_b: str) -> bool:
        """Check if two clocks are related (derived from same source)."""
        if clk_a == clk_b:
            return True

        # Build port-to-clock mapping for resolving sources
        port_to_clock: dict[str, str] = {}
        for clk in self.clocks.values():
            if clk.port:
                port_to_clock[_strip_tcl_getter(clk.port)] = clk.name

        # Check if one is generated from the other
        for clk in self.clocks.values():
            if clk.is_generated and clk.source:
                src = _strip_tcl_getter(clk.source)
                # Source might be a port name or a clock name - resolve both
                src_clock = port_to_clock.get(src, src)
                if (clk.name == clk_a and src_clock == clk_b) or \
                   (clk.name == clk_b and src_clock == clk_a):
                    return True

        # If explicitly declared async, they're not related
        if self.are_clocks_async(clk_a, clk_b):
            return False

        # By default, clocks without explicit relationship are potentially related
        # (conservative - don't flag crossings between potentially synchronous clocks)
        return False

    def get_clock_for_port(self, port_name: str) -> str | None:
        """Find which clock is defined on a given port."""
        for clk in self.clocks.values():
            if clk.port and _strip_tcl_getter(clk.port) == port_name:
                return clk.name
        return None


def parse_sdc(sdc_path: str | Path) -> SDCConstraints:
    """Parse an SDC file using a real TCL interpreter.

    The SDC file is evaluated as a TCL script. We register handlers for:
    - create_clock
    - create_generated_clock
    - set_clock_groups
    - set_false_path
    - get_ports, get_pins, get_clocks (return their argument for downstream use)
    """
    constraints = SDCConstraints()

    # Create a TCL interpreter
    tcl = tkinter.Tcl()

    # Register SDC command handlers
    def _create_clock(*args):
        args = list(args)
        clk = ClockDefinition(name="", is_generated=False)

        i = 0
        positional_target = None
        while i < len(args):
            arg = args[i]
            if arg == "-name" and i + 1 < len(args):
                clk.name = args[i + 1]
                i += 2
            elif arg == "-period" and i + 1 < len(args):
                clk.period = float(args[i + 1])
                i += 2
            elif arg == "-waveform" and i + 1 < len(args):
                wf = args[i + 1].split()
                if len(wf) >= 2:
                    clk.waveform = (float(wf[0]), float(wf[1]))
                i += 2
            elif not arg.startswith("-"):
                positional_target = arg
                i += 1
            else:
                i += 1  # Skip unknown flags

        if positional_target:
            clk.port = positional_target

        # If no -name given, use port name
        if not clk.name and clk.port:
            clk.name = _strip_tcl_getter(clk.port)

        if clk.name:
            constraints.clocks[clk.name] = clk
        return clk.name or ""

    def _create_generated_clock(*args):
        args = list(args)
        clk = ClockDefinition(name="", is_generated=True)

        i = 0
        positional_target = None
        while i < len(args):
            arg = args[i]
            if arg == "-name" and i + 1 < len(args):
                clk.name = args[i + 1]
                i += 2
            elif arg == "-source" and i + 1 < len(args):
                clk.source = args[i + 1]
                i += 2
            elif arg == "-divide_by" and i + 1 < len(args):
                clk.divide_by = int(args[i + 1])
                i += 2
            elif arg == "-multiply_by" and i + 1 < len(args):
                clk.multiply_by = int(args[i + 1])
                i += 2
            elif not arg.startswith("-"):
                positional_target = arg
                i += 1
            else:
                i += 1

        if positional_target:
            clk.port = positional_target

        if not clk.name and clk.port:
            clk.name = _strip_tcl_getter(clk.port)

        if clk.name:
            constraints.clocks[clk.name] = clk
        return clk.name or ""

    def _set_clock_groups(*args):
        args = list(args)
        relationship = "asynchronous"
        groups: list[list[str]] = []

        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "-asynchronous":
                relationship = "asynchronous"
                i += 1
            elif arg == "-exclusive":
                relationship = "exclusive"
                i += 1
            elif arg == "-physically_exclusive":
                relationship = "physically_exclusive"
                i += 1
            elif arg == "-group" and i + 1 < len(args):
                # Group can be a single clock name or a TCL list
                group_str = args[i + 1]
                group_clocks = group_str.split()
                groups.append(group_clocks)
                i += 2
            elif arg == "-name":
                i += 2  # Skip name argument
            else:
                i += 1

        if groups:
            constraints.clock_groups.append(ClockGroup(
                groups=groups,
                relationship=relationship,
            ))
        return ""

    def _set_false_path(*args):
        args = list(args)
        fp = FalsePath()

        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "-from" and i + 1 < len(args):
                val = args[i + 1]
                fp.from_clock = _strip_tcl_getter(val)
                i += 2
            elif arg == "-to" and i + 1 < len(args):
                val = args[i + 1]
                fp.to_clock = _strip_tcl_getter(val)
                i += 2
            else:
                i += 1

        constraints.false_paths.append(fp)
        return ""

    def _get_ports(*args):
        return " ".join(args)

    def _get_pins(*args):
        return " ".join(args)

    def _get_clocks(*args):
        return " ".join(args)

    def _get_nets(*args):
        return " ".join(args)

    # Register all commands in TCL
    tcl.createcommand("create_clock", _create_clock)
    tcl.createcommand("create_generated_clock", _create_generated_clock)
    tcl.createcommand("set_clock_groups", _set_clock_groups)
    tcl.createcommand("set_false_path", _set_false_path)
    tcl.createcommand("get_ports", _get_ports)
    tcl.createcommand("get_pins", _get_pins)
    tcl.createcommand("get_clocks", _get_clocks)
    tcl.createcommand("get_nets", _get_nets)

    # Common SDC commands we don't need but should not error on
    for passthrough in [
        "set_input_delay", "set_output_delay", "set_max_delay",
        "set_min_delay", "set_multicycle_path", "set_input_transition",
        "set_load", "set_driving_cell", "set_dont_touch",
        "set_max_fanout", "set_max_transition", "set_ideal_network",
        "set_propagated_clock", "set_clock_uncertainty",
        "set_clock_latency", "set_clock_transition",
        "current_design", "all_clocks", "all_inputs", "all_outputs",
    ]:
        tcl.createcommand(passthrough, lambda *a, **kw: "")

    # Evaluate the SDC file
    sdc_content = Path(sdc_path).read_text()
    try:
        tcl.eval(sdc_content)
    except tkinter.TclError as e:
        # Don't fail hard on unknown commands - SDC files often have
        # tool-specific extensions
        import sys
        print(f"Warning: SDC parse issue (non-fatal): {e}", file=sys.stderr)

    return constraints


def _strip_tcl_getter(s: str) -> str:
    """Strip get_ports/get_pins/get_clocks wrappers from a value.

    e.g., '[get_ports clk_i]' -> 'clk_i'
    """
    s = s.strip()
    # Remove surrounding brackets if present
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()
    # Remove get_* prefix
    for prefix in ("get_ports ", "get_pins ", "get_clocks ", "get_nets "):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
    # Remove braces
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1].strip()
    return s
