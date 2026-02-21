"""Reconvergence detection: forward BFS from sync outputs to find where
independently synchronized paths meet. Independently synced signals may
arrive 0-2 cycles apart, so reconvergence can produce states that never
existed in the source domain. MUX-based reconvergence is usually safe.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .netlist import Netlist, FlipFlop, is_dff_type, MUX_TYPES
from .synchronizers import Synchronizer


@dataclass
class ReconvergencePoint:
    """A point where independently synchronized paths reconverge."""
    cell_name: str
    sync_names: list[str]       # stage1 names of converging synchronizers
    src_domain: str             # human-readable source domain
    dst_domain: str             # human-readable dest domain
    through_mux: bool           # path passes through $mux/$pmux (usually intentional)
    ff_depth: int               # FF levels past synchronizer output
    signal_name: str            # human-readable name of the reconvergence net


def find_reconvergences(
    netlist: Netlist,
    synchronizers: dict[str, Synchronizer],
    domain_names: dict[int, str],
    max_depth: int = 2,
) -> list[ReconvergencePoint]:
    """Find all reconvergence points in the design.

    Args:
        netlist: Parsed netlist.
        synchronizers: Dict of stage1_name -> Synchronizer.
        domain_names: Map of clock_net -> human-readable name.
        max_depth: Max FF levels to trace past synchronizer outputs.

    Returns:
        List of reconvergence points found.
    """
    results: list[ReconvergencePoint] = []

    # Group synchronizers by (src_domain, dst_domain) pair
    domain_pairs: dict[tuple[int, int], list[Synchronizer]] = defaultdict(list)
    seen_syncs: set[str] = set()

    for sync_name, sync in synchronizers.items():
        # Avoid counting the same sync multiple times (all stages map to same sync)
        sync_id = sync.stages[0].name
        if sync_id in seen_syncs:
            continue
        seen_syncs.add(sync_id)
        domain_pairs[(sync.src_domain, sync.dst_domain)].append(sync)

    # Only pairs with 2+ syncs can have reconvergence
    for (src_dom, dst_dom), syncs in domain_pairs.items():
        if len(syncs) < 2:
            continue

        src_name = domain_names.get(src_dom, f"net_{src_dom}")
        dst_name = domain_names.get(dst_dom, f"net_{dst_dom}")

        # Forward trace from all syncs in this pair
        recon_points = _trace_domain_pair(
            netlist, syncs, max_depth, src_name, dst_name
        )
        results.extend(recon_points)

    return results


def _trace_domain_pair(
    netlist: Netlist,
    syncs: list[Synchronizer],
    max_depth: int,
    src_name: str,
    dst_name: str,
) -> list[ReconvergencePoint]:
    """Forward-trace from all syncs in a domain pair and detect reconvergence."""
    results: list[ReconvergencePoint] = []

    # Tag: for each net bit, which sync(s) can reach it, and was a mux involved?
    # bit_id -> (set of sync_ids that reach it, through_mux)
    reach: dict[int, tuple[set[str], bool]] = {}

    # BFS state: (bit_id, sync_id, ff_depth, through_mux)
    queue: list[tuple[int, str, int, bool]] = []

    # Seed: output Q-bits of each sync's last stage
    for sync in syncs:
        sync_id = sync.stages[0].name
        last_stage = sync.stages[-1]
        for q_bit in last_stage.q_bits:
            queue.append((q_bit, sync_id, 0, False))

    visited_edges: set[tuple[int, str]] = set()  # (bit_id, sync_id) to avoid re-tracing

    while queue:
        bit_id, sync_id, ff_depth, through_mux = queue.pop(0)

        if not isinstance(bit_id, int):
            continue
        if (bit_id, sync_id) in visited_edges:
            continue
        visited_edges.add((bit_id, sync_id))

        # Update reach map
        if bit_id in reach:
            existing_syncs, existing_mux = reach[bit_id]
            existing_syncs.add(sync_id)
            reach[bit_id] = (existing_syncs, existing_mux or through_mux)
        else:
            reach[bit_id] = ({sync_id}, through_mux)

        # Check for reconvergence: 2+ syncs reaching same bit
        current_syncs, current_mux = reach[bit_id]
        if len(current_syncs) >= 2:
            # Find the cell that reads this bit
            readers = netlist.fanout_index.get(bit_id, [])
            for reader_cell, reader_port in readers:
                # Record reconvergence at the reader cell
                signal = netlist.get_net_name(bit_id)
                results.append(ReconvergencePoint(
                    cell_name=reader_cell,
                    sync_names=sorted(current_syncs),
                    src_domain=src_name,
                    dst_domain=dst_name,
                    through_mux=current_mux,
                    ff_depth=ff_depth,
                    signal_name=signal,
                ))
            # Don't trace further from a reconvergence point (avoid duplicates)
            continue

        # Trace forward through fanout
        readers = netlist.fanout_index.get(bit_id, [])
        for reader_cell, reader_port in readers:
            cell_data = netlist.cells.get(reader_cell, {})
            cell_type = cell_data.get("type", "")

            if is_dff_type(cell_type):
                # Hit a FF: increment depth, continue from its Q if within limit
                new_depth = ff_depth + 1
                if new_depth <= max_depth and reader_cell in netlist.flip_flops:
                    ff = netlist.flip_flops[reader_cell]
                    for q_bit in ff.q_bits:
                        queue.append((q_bit, sync_id, new_depth, through_mux))
            else:
                # Combinational cell: trace through to outputs
                is_mux = cell_type in MUX_TYPES
                new_mux = through_mux or is_mux

                pd = cell_data.get("port_directions", {})
                conn = cell_data.get("connections", {})
                for port_name, direction in pd.items():
                    if direction == "output":
                        for out_bit in conn.get(port_name, []):
                            if isinstance(out_bit, int):
                                queue.append((out_bit, sync_id, ff_depth, new_mux))

    return _deduplicate(results)


def _deduplicate(points: list[ReconvergencePoint]) -> list[ReconvergencePoint]:
    """Remove duplicate reconvergence reports for the same cell."""
    seen: set[str] = set()
    unique: list[ReconvergencePoint] = []
    for p in points:
        key = f"{p.cell_name}:{','.join(p.sync_names)}"
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique
