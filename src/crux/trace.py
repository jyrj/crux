"""Backward cone tracing: for each FF D-input, find all source clock domains."""

from __future__ import annotations

from dataclasses import dataclass

from .netlist import Netlist, FlipFlop, is_dff_type

MAX_TRACE_DEPTH = 500


@dataclass
class TraceResult:
    """Result of tracing a destination FF's D-input backward."""
    dest_ff: FlipFlop
    source_ffs: list[FlipFlop]
    source_domains: set[int]
    has_combo_logic: bool
    is_from_input: bool


def trace_d_input(
    netlist: Netlist,
    dest_ff: FlipFlop,
    memo: dict[int, tuple[set[int], bool, bool]] | None = None,
) -> TraceResult:
    """Trace backward from a FF's D input to find all source FFs and domains.

    Optionally accepts a memo dict to cache per-bit results across calls.
    Cache key: bit_id -> (source_domains, has_combo, is_from_input).
    """
    source_ffs_out: list[FlipFlop] = []
    source_domains_out: set[int] = set()
    has_combo_out = False
    is_from_input_out = False
    visited: set[int] = set()

    for d_bit in dest_ff.d_bits:
        if memo is not None and d_bit in memo:
            cached_doms, cached_combo, cached_input = memo[d_bit]
            source_domains_out |= cached_doms
            has_combo_out = has_combo_out or cached_combo
            is_from_input_out = is_from_input_out or cached_input
            continue

        local_ffs: list[FlipFlop] = []
        local_doms: set[int] = set()
        combo, from_input = _trace_bit(
            netlist, d_bit, visited, local_ffs, local_doms, depth=0
        )

        source_ffs_out.extend(local_ffs)
        source_domains_out |= local_doms
        has_combo_out = has_combo_out or combo
        is_from_input_out = is_from_input_out or from_input

        if memo is not None:
            memo[d_bit] = (frozenset(local_doms), combo, from_input)

    return TraceResult(
        dest_ff=dest_ff,
        source_ffs=source_ffs_out,
        source_domains=source_domains_out,
        has_combo_logic=has_combo_out,
        is_from_input=is_from_input_out,
    )


def _trace_bit(
    netlist: Netlist,
    bit_id: int,
    visited: set[int],
    source_ffs: list[FlipFlop],
    source_domains: set[int],
    depth: int,
) -> tuple[bool, bool]:
    """Trace a single net bit backward. Returns (has_combo, is_from_input)."""
    if not isinstance(bit_id, int):
        return False, False
    if bit_id in visited:
        return False, False
    if depth > MAX_TRACE_DEPTH:
        return False, False
    visited.add(bit_id)

    if bit_id in netlist.port_bits:
        if bit_id not in netlist.driver_index:
            return False, True

    if bit_id not in netlist.driver_index:
        return False, False

    cell_name, port_name = netlist.driver_index[bit_id]
    cell_data = netlist.cells[cell_name]

    if is_dff_type(cell_data["type"]):
        if cell_name in netlist.flip_flops:
            ff = netlist.flip_flops[cell_name]
            source_ffs.append(ff)
            source_domains.add(ff.clock_net)
        return False, False

    has_combo = True
    is_from_input = False
    pd = cell_data.get("port_directions", {})
    conn = cell_data.get("connections", {})

    for p_name, direction in pd.items():
        if direction == "input":
            for input_bit in conn.get(p_name, []):
                combo, from_inp = _trace_bit(
                    netlist, input_bit, visited, source_ffs, source_domains,
                    depth=depth + 1,
                )
                is_from_input = is_from_input or from_inp

    return has_combo, is_from_input
