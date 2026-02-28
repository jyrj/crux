"""Accellera CDC/RDC Standard 1.0 constraint parser.

Parses the vendor-neutral TCL format defined by the Accellera CDC/RDC
standard (released March 2026). Uses tkinter.Tcl() to evaluate the TCL
commands. The standard defines 4 commands under the accellera_cdc namespace:

  accellera_cdc::set_module -name <module>
  accellera_cdc::set_param -name <name> -type <type> -value <val>
  accellera_cdc::set_port -name <port> -type <type> [attributes...]
  accellera_cdc::set_clock_group -clocks {clk1 clk2}
"""

from __future__ import annotations

import tkinter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CDCPortInfo:
    """CDC attributes for a port from the Accellera standard."""
    name: str
    port_type: str                      # data, clock, async_reset, cdc_control, rdc_control
    direction: str = ""                 # input, output, inout
    associated_from_clocks: list[str] = field(default_factory=list)
    associated_to_clocks: list[str] = field(default_factory=list)
    hamming1: bool = False              # True = gray-coded (Hamming distance 1)
    polarity: str = ""                  # high, low (for resets)
    logic: str = ""                     # combo, inverter, glitch_free_combo, internal_sync
    cdc_static: list[str] = field(default_factory=list)
    qualifier: str = ""                 # associated qualifier signal
    ignore: str = ""                    # blocked, hanging


@dataclass
class AccelleraCDC:
    """Parsed Accellera CDC/RDC Standard 1.0 constraints."""
    module_name: str = ""
    ports: dict[str, CDCPortInfo] = field(default_factory=dict)
    clock_groups: list[list[str]] = field(default_factory=list)  # groups of synchronous clocks
    params: dict[str, str] = field(default_factory=dict)

    def get_port_type(self, port_name: str) -> str | None:
        """Get the CDC type of a port (data, clock, async_reset, etc.)."""
        info = self.ports.get(port_name)
        return info.port_type if info else None

    def is_hamming1(self, port_name: str) -> bool:
        """Check if a port is declared as Hamming-1 (gray-coded)."""
        info = self.ports.get(port_name)
        return info.hamming1 if info else False

    def get_clock_ports(self) -> list[str]:
        """Get all ports declared as clocks."""
        return [name for name, info in self.ports.items() if info.port_type == "clock"]

    def get_reset_ports(self) -> list[str]:
        """Get all ports declared as async resets."""
        return [name for name, info in self.ports.items() if info.port_type == "async_reset"]

    def are_clocks_synchronous(self, clk_a: str, clk_b: str) -> bool:
        """Check if two clocks are in the same synchronous group."""
        for group in self.clock_groups:
            if clk_a in group and clk_b in group:
                return True
        return False


def parse_accellera(cdc_path: str | Path) -> AccelleraCDC:
    """Parse an Accellera CDC/RDC Standard 1.0 constraint file."""
    result = AccelleraCDC()
    tcl = tkinter.Tcl()

    def _set_module(*args):
        args = list(args)
        i = 0
        while i < len(args):
            if args[i] == "-name" and i + 1 < len(args):
                result.module_name = args[i + 1]
                i += 2
            else:
                i += 1
        return ""

    def _set_param(*args):
        args = list(args)
        name = value = ""
        i = 0
        while i < len(args):
            if args[i] == "-name" and i + 1 < len(args):
                name = args[i + 1]
                i += 2
            elif args[i] == "-value" and i + 1 < len(args):
                value = args[i + 1]
                i += 2
            else:
                i += 1
        if name:
            result.params[name] = value
        return ""

    def _set_port(*args):
        args = list(args)
        port = CDCPortInfo(name="", port_type="data")
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "-name" and i + 1 < len(args):
                port.name = args[i + 1]
                i += 2
            elif arg == "-type" and i + 1 < len(args):
                port.port_type = args[i + 1]
                i += 2
            elif arg == "-direction" and i + 1 < len(args):
                port.direction = args[i + 1]
                i += 2
            elif arg == "-associated_from_clocks" and i + 1 < len(args):
                port.associated_from_clocks = args[i + 1].split()
                i += 2
            elif arg == "-associated_to_clocks" and i + 1 < len(args):
                port.associated_to_clocks = args[i + 1].split()
                i += 2
            elif arg == "-hamming1" and i + 1 < len(args):
                port.hamming1 = args[i + 1].lower() in ("true", "1", "yes")
                i += 2
            elif arg == "-polarity" and i + 1 < len(args):
                port.polarity = args[i + 1]
                i += 2
            elif arg == "-logic" and i + 1 < len(args):
                port.logic = args[i + 1]
                i += 2
            elif arg == "-cdc_static" and i + 1 < len(args):
                port.cdc_static = args[i + 1].split()
                i += 2
            elif arg == "-ignore" and i + 1 < len(args):
                port.ignore = args[i + 1]
                i += 2
            else:
                i += 1
        if port.name:
            result.ports[port.name] = port
        return ""

    def _set_clock_group(*args):
        args = list(args)
        i = 0
        while i < len(args):
            if args[i] == "-clocks" and i + 1 < len(args):
                clocks = args[i + 1].split()
                result.clock_groups.append(clocks)
                i += 2
            else:
                i += 1
        return ""

    # Register commands under the accellera_cdc namespace
    # TCL namespace commands are invoked as "accellera_cdc::set_module"
    # We create the namespace and register procs
    tcl.createcommand("accellera_cdc::set_module", _set_module)
    tcl.createcommand("accellera_cdc::set_param", _set_param)
    tcl.createcommand("accellera_cdc::set_port", _set_port)
    tcl.createcommand("accellera_cdc::set_clock_group", _set_clock_group)

    # Also handle the un-namespaced version (some files may omit prefix)
    tcl.createcommand("set_module", _set_module)
    tcl.createcommand("set_param", _set_param)
    tcl.createcommand("set_port", _set_port)
    tcl.createcommand("set_clock_group", _set_clock_group)

    content = Path(cdc_path).read_text()
    try:
        tcl.eval(content)
    except tkinter.TclError as e:
        import sys
        print(f"Warning: Accellera CDC parse issue (non-fatal): {e}", file=sys.stderr)

    return result
