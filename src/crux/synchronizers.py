"""Detect synchronizer patterns in the netlist.

Recognized patterns:
  1. N-FF chain synchronizer (2FF, 3FF, etc.)
     [Domain A] FF_src.Q --> sync_1.D --> sync_1.Q --> sync_2.D --> ... --> sync_N.Q
     Requirements: all sync stages share same clock, stage1 D from different domain,
     each stage fans out only to next stage (except last stage).

  2. Known module instances (pre-flatten detection via cell/net naming)
     prim_flop_2sync, prim_pulse_sync, prim_fifo_async, etc.
     After flattening, these become FF chains with names containing the module name.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .netlist import Netlist, FlipFlop, is_dff_type


# Known synchronizer module names (detected via hierarchical names after flatten)
KNOWN_SYNC_MODULES = frozenset({
    "prim_flop_2sync",
    "prim_pulse_sync",
    "prim_fifo_async",
    "prim_fifo_async_simple",
    "prim_sync_reqack",
    "prim_sync_reqack_data",
    "prim_sync_slow_fast",
    "prim_multibit_sync",
    "prim_mubi4_sync",
    "prim_mubi8_sync",
    "prim_mubi12_sync",
    "prim_mubi16_sync",
    "prim_mubi20_sync",
    "prim_mubi24_sync",
    "prim_mubi28_sync",
    "prim_mubi32_sync",
    "prim_lc_sync",
    "prim_reg_cdc",
    "prim_reg_cdc_arb",
    # PULP platform
    "cdc_2phase",
    "cdc_fifo_gray",
    "cdc_fifo_2phase",
    "cdc_2phase_clearable",
    "cdc_fifo_gray_clearable",
})


@dataclass
class Synchronizer:
    """A recognized synchronizer structure."""
    stages: list[FlipFlop]      # Ordered list of sync FFs (stage1, stage2, ...)
    src_domain: int             # Source clock net ID
    dst_domain: int             # Destination clock net ID
    sync_type: str              # "nff_chain", "known_module"
    module_name: str | None = None  # For known_module type

    @property
    def stage1(self) -> FlipFlop:
        return self.stages[0]

    @property
    def stage1_name(self) -> str:
        return self.stages[0].name

    @property
    def depth(self) -> int:
        return len(self.stages)


def find_synchronizers(netlist: Netlist) -> dict[str, Synchronizer]:
    """Find all synchronizer patterns.

    Returns dict mapping stage1 cell name -> Synchronizer.
    """
    synchronizers: dict[str, Synchronizer] = {}

    # Method 1: Structural N-FF chain detection
    _find_nff_chains(netlist, synchronizers)

    # Method 2: Known module name detection (from flattened hierarchy names)
    _find_known_modules(netlist, synchronizers)

    return synchronizers


def _find_nff_chains(netlist: Netlist, out: dict[str, Synchronizer]) -> None:
    """Find N-FF synchronizer chains (2FF, 3FF, etc.)."""
    # Build Q-bit to FF mapping for quick lookup
    q_to_ff: dict[int, FlipFlop] = {}
    for ff in netlist.flip_flops.values():
        for q_bit in ff.q_bits:
            q_to_ff[q_bit] = ff

    for ff_name, ff in netlist.flip_flops.items():
        if ff_name in out:
            continue  # Already identified as part of a sync

        # Try to build a chain starting from this FF
        chain = _build_ff_chain(netlist, ff, q_to_ff)
        if len(chain) < 2:
            continue

        # Check: first stage's D input comes from different domain
        src_domain = _find_direct_source_domain(netlist, chain[0])
        if src_domain is None or src_domain == chain[0].clock_net:
            continue

        sync = Synchronizer(
            stages=chain,
            src_domain=src_domain,
            dst_domain=chain[0].clock_net,
            sync_type="nff_chain",
        )
        out[ff_name] = sync


def _build_ff_chain(netlist: Netlist, start_ff: FlipFlop,
                    q_to_ff: dict[int, FlipFlop]) -> list[FlipFlop]:
    """Build a chain of FFs where each Q feeds the next D, all on the same clock.

    The chain's intermediate stages must have fan-out of exactly 1 to a DFF D-port.
    The last stage can fan out to anything.
    """
    chain = [start_ff]
    current = start_ff

    while True:
        next_ff = _get_sole_dff_reader(netlist, current)
        if next_ff is None:
            break
        if next_ff.clock_net != start_ff.clock_net:
            break
        if next_ff.name == current.name:
            break  # Self-loop
        chain.append(next_ff)
        current = next_ff

        if len(chain) > 8:  # Sanity limit
            break

    return chain


def _get_sole_dff_reader(netlist: Netlist, ff: FlipFlop) -> FlipFlop | None:
    """Check if this FF's Q output feeds exactly one DFF D-input and nothing else.

    Returns the downstream FF if the pattern matches, None otherwise.
    """
    if not ff.q_bits:
        return None

    # All Q bits must feed the same single DFF
    target_cells: set[str] = set()

    for q_bit in ff.q_bits:
        readers = netlist.fanout_index.get(q_bit, [])

        dff_d_readers = []
        other_readers = []
        for reader_cell, reader_port in readers:
            reader_data = netlist.cells.get(reader_cell, {})
            if is_dff_type(reader_data.get("type", "")) and reader_port == "D":
                dff_d_readers.append(reader_cell)
            else:
                other_readers.append(reader_cell)

        # Strict fan-out: only to a single DFF D-port, nothing else
        if len(dff_d_readers) != 1 or other_readers:
            return None

        target_cells.add(dff_d_readers[0])

    if len(target_cells) != 1:
        return None

    target_name = target_cells.pop()
    return netlist.flip_flops.get(target_name)


def _find_known_modules(netlist: Netlist, out: dict[str, Synchronizer]) -> None:
    """Detect synchronizers using known module names as HINTS, then structurally verify.

    Name matching narrows the search. Structural checks validate:
    - Related FFs must share the same clock domain
    - Must have a cross-domain source
    - Must form a chain (Q->D connectivity between stages)
    Name alone is NOT sufficient — prevents false "safe" classification.
    """
    for ff_name, ff in netlist.flip_flops.items():
        if ff_name in out:
            continue

        name_lower = ff_name.lower()
        src_lower = ff.src.lower()

        for module_name in KNOWN_SYNC_MODULES:
            if module_name in name_lower or module_name in src_lower:
                prefix = _extract_instance_prefix(ff_name, module_name)
                if prefix:
                    related_ffs = _find_ffs_with_prefix(netlist, prefix)
                    if len(related_ffs) >= 2:
                        related_ffs.sort(key=lambda f: f.name)
                        # Structural check: all FFs must share same clock
                        clocks = {f.clock_net for f in related_ffs}
                        if len(clocks) != 1:
                            break  # Mixed clocks — not a simple sync chain
                        # Structural check: must have cross-domain source
                        src_domain = _find_deep_source_domain(netlist, related_ffs[0])
                        if src_domain is None or src_domain == related_ffs[0].clock_net:
                            break  # No cross-domain input
                        # Structural check: stages must be connected (Q->D chain)
                        if not _verify_chain_connectivity(netlist, related_ffs):
                            break  # FFs not actually chained
                        sync = Synchronizer(
                            stages=related_ffs,
                            src_domain=src_domain,
                            dst_domain=related_ffs[0].clock_net,
                            sync_type="known_module",
                            module_name=module_name,
                        )
                        for rff in related_ffs:
                            out[rff.name] = sync
                break


def _extract_instance_prefix(cell_name: str, module_name: str) -> str | None:
    """Extract the hierarchical instance prefix for a known module.

    Example: '$flatten\\u_prim_flop_2sync.u_sync_1.$procdff$42'
    -> '$flatten\\u_prim_flop_2sync.'
    """
    idx = cell_name.lower().find(module_name)
    if idx < 0:
        return None
    # Find the end of the module name and first '.'
    end = idx + len(module_name)
    dot_idx = cell_name.find(".", end)
    if dot_idx >= 0:
        return cell_name[:dot_idx + 1]
    return cell_name[:end]


def _verify_chain_connectivity(netlist: Netlist, ffs: list[FlipFlop]) -> bool:
    """Verify that FFs form a connected chain (Q of one feeds D of next)."""
    if len(ffs) < 2:
        return False
    q_bits_to_ff: dict[int, str] = {}
    for ff in ffs:
        for q_bit in ff.q_bits:
            q_bits_to_ff[q_bit] = ff.name
    # Check: for each FF except the last, at least one Q bit feeds the next FF's D
    for i in range(len(ffs) - 1):
        connected = False
        for q_bit in ffs[i].q_bits:
            for d_bit in ffs[i + 1].d_bits:
                if q_bit == d_bit:
                    connected = True
                    break
            if connected:
                break
        if not connected:
            return False
    return True


def _find_ffs_with_prefix(netlist: Netlist, prefix: str) -> list[FlipFlop]:
    """Find all FFs whose name starts with the given prefix."""
    prefix_lower = prefix.lower()
    return [
        ff for ff in netlist.flip_flops.values()
        if ff.name.lower().startswith(prefix_lower)
    ]


def _find_direct_source_domain(netlist: Netlist, ff: FlipFlop) -> int | None:
    """Find the clock domain of the FF(s) DIRECTLY driving this FF's D input.

    For a valid N-FF synchronizer, the D input of stage 1 must come directly
    from a FF Q output with NO combinational logic in between.
    """
    source_domains: set[int] = set()

    for d_bit in ff.d_bits:
        if not isinstance(d_bit, int):
            return None
        if d_bit not in netlist.driver_index:
            return None

        cell_name, port_name = netlist.driver_index[d_bit]
        cell_data = netlist.cells[cell_name]

        if not is_dff_type(cell_data["type"]):
            return None  # Combo logic before sync - not a valid pattern

        if cell_name in netlist.flip_flops:
            source_domains.add(netlist.flip_flops[cell_name].clock_net)
        else:
            return None

    if len(source_domains) == 1:
        return source_domains.pop()
    return None


def _find_deep_source_domain(netlist: Netlist, ff: FlipFlop) -> int | None:
    """Find source domain by tracing through combo logic (for known module detection).

    Unlike _find_direct_source_domain, this allows combo logic because known
    modules (like pulse_sync) intentionally have logic before the sync stage.
    """
    source_domains: set[int] = set()

    for d_bit in ff.d_bits:
        _trace_to_domain(netlist, d_bit, set(), source_domains)

    if len(source_domains) == 1:
        return source_domains.pop()
    # If multiple domains, return any that differs from this FF's clock
    for dom in source_domains:
        if dom != ff.clock_net:
            return dom
    return None


def _trace_to_domain(netlist: Netlist, bit_id: int, visited: set[int],
                     domains: set[int]) -> None:
    """Recursively trace a bit to find source FF clock domains."""
    if not isinstance(bit_id, int) or bit_id in visited:
        return
    visited.add(bit_id)

    if bit_id not in netlist.driver_index:
        return

    cell_name, port_name = netlist.driver_index[bit_id]
    cell_data = netlist.cells[cell_name]

    if is_dff_type(cell_data["type"]):
        if cell_name in netlist.flip_flops:
            domains.add(netlist.flip_flops[cell_name].clock_net)
        return

    # Combinational: trace inputs
    pd = cell_data.get("port_directions", {})
    conn = cell_data.get("connections", {})
    for p_name, direction in pd.items():
        if direction == "input":
            for input_bit in conn.get(p_name, []):
                _trace_to_domain(netlist, input_bit, visited, domains)
