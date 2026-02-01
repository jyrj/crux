"""Backward cone tracing: for each FF D-input, find all source clock domains."""

from __future__ import annotations

from dataclasses import dataclass

from .netlist import Netlist, FlipFlop, is_dff_type


@dataclass
class TraceResult:
    """Result of tracing a destination FF's D-input backward."""
    dest_ff: FlipFlop
    source_ffs: list[FlipFlop]      # Source FFs from other domains
    source_domains: set[int]        # Clock net IDs of source FFs
    has_combo_logic: bool           # Combinational logic in the path?
    is_from_input: bool             # Path originates from module input?


def trace_d_input(netlist: Netlist, dest_ff: FlipFlop) -> TraceResult:
    """Trace backward from a FF's D input to find all source FFs and domains.

    Walks backward through combinational logic, stopping at FF Q outputs
    (recording the source domain) or module inputs.
    """
    source_ffs_out: list[FlipFlop] = []
    source_domains_out: set[int] = set()
    has_combo_out = False
    is_from_input_out = False
    visited: set[int] = set()

    for d_bit in dest_ff.d_bits:
        combo, from_input = _trace_bit_full(
            netlist, d_bit, visited, source_ffs_out, source_domains_out, depth=0
        )
        has_combo_out = has_combo_out or combo
        is_from_input_out = is_from_input_out or from_input

    return TraceResult(
        dest_ff=dest_ff,
        source_ffs=source_ffs_out,
        source_domains=source_domains_out,
        has_combo_logic=has_combo_out,
        is_from_input=is_from_input_out,
    )


def _trace_bit_full(
    netlist: Netlist,
    bit_id: int,
    visited: set[int],
    source_ffs: list[FlipFlop],
    source_domains: set[int],
    depth: int,
) -> tuple[bool, bool]:
    """Trace a single net bit backward. Returns (has_combo, is_from_input).

    Stops at:
    - FF Q outputs: records the source FF and its clock domain
    - Module inputs: records as input-domain crossing
    - Already-visited bits: breaks cycles
    - Constant values (strings like "0", "1"): ignored
    """
    if not isinstance(bit_id, int):
        return False, False

    if bit_id in visited:
        return False, False
    visited.add(bit_id)

    # Check if this bit is a module input port
    if bit_id in netlist.port_bits:
        # Check if it's also driven by a cell (port loopback)
        if bit_id not in netlist.driver_index:
            return False, True  # Pure module input

    # Check if this bit is driven by a cell
    if bit_id not in netlist.driver_index:
        return False, False  # Undriven net

    cell_name, port_name = netlist.driver_index[bit_id]
    cell_data = netlist.cells[cell_name]

    # If the driver is a FF, we've found a source domain
    if is_dff_type(cell_data["type"]):
        if cell_name in netlist.flip_flops:
            ff = netlist.flip_flops[cell_name]
            source_ffs.append(ff)
            source_domains.add(ff.clock_net)
        return False, False

    # Driver is combinational logic - trace through all its inputs
    has_combo = True
    is_from_input = False

    pd = cell_data.get("port_directions", {})
    conn = cell_data.get("connections", {})

    for p_name, direction in pd.items():
        if direction == "input":
            for input_bit in conn.get(p_name, []):
                combo, from_inp = _trace_bit_full(
                    netlist, input_bit, visited, source_ffs, source_domains,
                    depth=depth + 1,
                )
                is_from_input = is_from_input or from_inp

    return has_combo, is_from_input
