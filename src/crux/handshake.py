"""Handshake/qualifier detection for multi-bit CDC crossings.

When a multi-bit data bus crosses clock domains without per-bit synchronizers,
it may be safe if a synchronized control signal (qualifier) gates the data
capture. Common patterns:

1. Req/Ack handshake: data held stable while req is asserted, destination
   captures only when synchronized req arrives.
2. Enable-gated: destination FF has an enable (EN) port controlled by a
   synchronized signal.
3. MUX-gated: destination FF D-input goes through a MUX whose select is
   synchronized.

Detection: For $adffe cells (FF with enable), trace the EN signal backward
to see if it depends on a synchronized control signal from the same crossing
domain pair.
"""

from __future__ import annotations

from .netlist import Netlist, FlipFlop, is_dff_type
from .synchronizers import Synchronizer


def _build_last_stage_index(
    synchronizers: dict[str, Synchronizer],
) -> dict[str, Synchronizer]:
    """Map last-stage FF name -> Synchronizer for O(1) lookup."""
    index: dict[str, Synchronizer] = {}
    for sync in synchronizers.values():
        index[sync.stages[-1].name] = sync
    return index


def is_handshake_protected(
    netlist: Netlist,
    dest_ff: FlipFlop,
    src_domain_net: int,
    synchronizers: dict[str, Synchronizer],
    max_trace_depth: int = 10,
) -> bool:
    """Check if a multi-bit crossing is protected by a handshake/qualifier.

    Returns True if the destination FF's enable signal depends on a
    synchronized control signal from the same source domain.
    """
    if dest_ff.cell_type not in ("$adffe", "$sdffe", "$sdffce"):
        return False

    cell_data = netlist.cells.get(dest_ff.name, {})
    conn = cell_data.get("connections", {})
    en_bits = conn.get("EN", [])

    if not en_bits:
        return False

    last_stage_idx = _build_last_stage_index(synchronizers)

    for en_bit in en_bits:
        if _traces_to_synchronizer(
            netlist, en_bit, dest_ff.clock_net, src_domain_net,
            synchronizers, last_stage_idx, set(), max_trace_depth
        ):
            return True

    return False


def _traces_to_synchronizer(
    netlist: Netlist,
    bit_id: int,
    dst_clock_net: int,
    src_domain_net: int,
    synchronizers: dict[str, Synchronizer],
    last_stage_idx: dict[str, Synchronizer],
    visited: set[int],
    depth: int,
) -> bool:
    """Trace a bit backward to check if it depends on a synchronizer output."""
    if not isinstance(bit_id, int) or bit_id in visited or depth <= 0:
        return False
    visited.add(bit_id)

    if bit_id not in netlist.driver_index:
        return False

    cell_name, port_name = netlist.driver_index[bit_id]
    cell_data = netlist.cells.get(cell_name, {})
    cell_type = cell_data.get("type", "")

    if is_dff_type(cell_type):
        ff = netlist.flip_flops.get(cell_name)
        if ff is None:
            return False
        # Check stage1 index
        if cell_name in synchronizers:
            sync = synchronizers[cell_name]
            if sync.src_domain == src_domain_net and sync.dst_domain == dst_clock_net:
                return True
        # Check last-stage index (O(1) instead of O(N))
        if cell_name in last_stage_idx:
            sync = last_stage_idx[cell_name]
            if sync.src_domain == src_domain_net:
                return True
        return False

    pd = cell_data.get("port_directions", {})
    conn = cell_data.get("connections", {})
    for p_name, direction in pd.items():
        if direction == "input":
            for input_bit in conn.get(p_name, []):
                if _traces_to_synchronizer(
                    netlist, input_bit, dst_clock_net, src_domain_net,
                    synchronizers, last_stage_idx, visited, depth - 1
                ):
                    return True

    return False
