"""Reset Domain Crossing (RDC) and clock glitch detection.

RDC: An asynchronous reset that crosses clock domains can cause metastability
if not properly synchronized. The standard fix is "async assert, sync de-assert"
using a 2FF reset synchronizer (see OpenTitan's prim_rst_sync).

Clock glitch: Combinational logic driving a clock input can produce runt pulses
that corrupt the entire clock tree.
"""

from __future__ import annotations

from dataclasses import dataclass

from .netlist import Netlist, FlipFlop, has_async_reset, is_dff_type


@dataclass
class ResetCrossing:
    """A reset signal that crosses clock domains."""
    ff_name: str                    # FF with the async reset
    ff_domain: str                  # clock domain of the FF
    reset_net: int                  # the reset net bit ID
    reset_source: str               # human-readable reset source name
    reset_source_domain: str | None # clock domain driving the reset (if from FF)
    is_from_port: bool              # True if reset comes from module input
    is_synchronized: bool           # True if sync chain on reset path
    sync_depth: int                 # number of FF stages in reset sync chain


@dataclass
class ClockGlitch:
    """A FF whose clock input is driven by combinational logic."""
    ff_name: str
    clock_net: int
    clock_name: str
    driver_cell: str                # the combo cell driving the clock
    driver_type: str                # cell type of the driver


def find_rdc_violations(
    netlist: Netlist,
    domain_names: dict[int, str],
) -> list[ResetCrossing]:
    """Find reset signals that cross clock domains without synchronization.

    For each FF with an async reset:
    1. Trace reset_net backward to find the source (FF or port)
    2. If source FF is in a different clock domain → potential RDC
    3. Check if there's a sync chain in the reset path
    4. Skip FFs that are part of a reset synchronizer chain
    """
    # First, identify FFs that are part of reset sync chains.
    # Pattern: FF whose Q output drives another FF's ARST in the same domain,
    # and whose own ARST comes from a different domain.
    # These are intentional "async assert, sync de-assert" stages.
    reset_sync_ffs = _find_reset_sync_stages(netlist)

    violations: list[ResetCrossing] = []

    for ff_name, ff in netlist.flip_flops.items():
        if not has_async_reset(ff):
            continue

        # Skip reset synchronizer stages - they intentionally have cross-domain resets
        if ff_name in reset_sync_ffs:
            continue

        ff_domain = domain_names.get(ff.clock_net, f"net_{ff.clock_net}")

        # Trace reset backward
        source_info = _trace_reset_source(netlist, ff.reset_net)

        if source_info is None:
            continue

        src_ff, is_port, depth = source_info

        if is_port:
            reset_name = netlist.get_net_name(ff.reset_net)
            violations.append(ResetCrossing(
                ff_name=ff_name,
                ff_domain=ff_domain,
                reset_net=ff.reset_net,
                reset_source=reset_name,
                reset_source_domain=None,
                is_from_port=True,
                is_synchronized=False,
                sync_depth=0,
            ))
            continue

        if src_ff is None:
            continue

        src_domain = domain_names.get(src_ff.clock_net, f"net_{src_ff.clock_net}")

        if src_ff.clock_net == ff.clock_net:
            continue

        # Check if the reset goes through a sync chain before reaching this FF
        sync_depth = _count_reset_sync_depth(netlist, ff)
        is_synced = sync_depth >= 2

        violations.append(ResetCrossing(
            ff_name=ff_name,
            ff_domain=ff_domain,
            reset_net=ff.reset_net,
            reset_source=src_ff.name,
            reset_source_domain=src_domain,
            is_from_port=False,
            is_synchronized=is_synced,
            sync_depth=sync_depth,
        ))

    return violations


def _find_reset_sync_stages(netlist: Netlist) -> set[str]:
    """Identify FFs that are part of reset synchronizer chains.

    A reset sync stage is a FF that:
    1. Has an async reset from a different clock domain
    2. Its Q output feeds another FF's ARST (or its own chain continues to one that does)

    This is the "async assert, sync de-assert" pattern (prim_rst_sync).
    These FFs intentionally have unsynchronized resets and should not be
    flagged as RDC violations.
    """
    # Build map: which FF Q-bits drive which FF ARST ports?
    q_drives_reset: dict[int, list[str]] = {}  # q_bit -> [ff_names whose ARST it drives]
    for ff_name, ff in netlist.flip_flops.items():
        if ff.reset_net is not None and isinstance(ff.reset_net, int):
            q_drives_reset.setdefault(ff.reset_net, []).append(ff_name)

    reset_sync_ffs: set[str] = set()

    for ff_name, ff in netlist.flip_flops.items():
        if not has_async_reset(ff):
            continue

        # Check if any of this FF's Q-bits drive another FF's reset
        for q_bit in ff.q_bits:
            if q_bit in q_drives_reset:
                driven_ffs = q_drives_reset[q_bit]
                for driven_name in driven_ffs:
                    driven_ff = netlist.flip_flops.get(driven_name)
                    if driven_ff and driven_ff.clock_net == ff.clock_net:
                        # This FF's Q drives a same-domain FF's reset
                        # → it's a reset sync stage
                        reset_sync_ffs.add(ff_name)

    # Also add the first stage: FFs in the same domain whose Q feeds
    # another FF that we already identified as a reset sync stage
    # (handles multi-stage chains)
    changed = True
    while changed:
        changed = False
        for ff_name, ff in netlist.flip_flops.items():
            if ff_name in reset_sync_ffs:
                continue
            if not has_async_reset(ff):
                continue
            for q_bit in ff.q_bits:
                readers = netlist.fanout_index.get(q_bit, [])
                for reader_cell, reader_port in readers:
                    if reader_port == "D" and reader_cell in reset_sync_ffs:
                        # Q feeds a D input of a known reset sync stage
                        if reader_cell in netlist.flip_flops:
                            if netlist.flip_flops[reader_cell].clock_net == ff.clock_net:
                                reset_sync_ffs.add(ff_name)
                                changed = True

    return reset_sync_ffs


def _trace_reset_source(
    netlist: Netlist,
    reset_bit: int,
) -> tuple[FlipFlop | None, bool, int] | None:
    """Trace a reset bit backward to find the ultimate source.

    Returns (source_ff, is_from_port, combo_depth) or None if constant/undriven.
    Traces through combinational logic to find the source FF or port.
    """
    visited: set[int] = set()
    bit = reset_bit
    combo_depth = 0

    while isinstance(bit, int) and bit not in visited:
        visited.add(bit)

        # Check if this is a module input port
        if bit in netlist.port_bits and bit not in netlist.driver_index:
            return None, True, combo_depth

        if bit not in netlist.driver_index:
            return None  # Undriven

        cell_name, port_name = netlist.driver_index[bit]
        cell_data = netlist.cells.get(cell_name, {})

        if is_dff_type(cell_data.get("type", "")):
            ff = netlist.flip_flops.get(cell_name)
            return ff, False, combo_depth

        # Combinational: trace through first input
        combo_depth += 1
        pd = cell_data.get("port_directions", {})
        conn = cell_data.get("connections", {})
        found_input = False
        for p_name, direction in pd.items():
            if direction == "input":
                bits = conn.get(p_name, [])
                for b in bits:
                    if isinstance(b, int) and b not in visited:
                        bit = b
                        found_input = True
                        break
                if found_input:
                    break

        if not found_input:
            return None

    return None


def _count_reset_sync_depth(netlist: Netlist, target_ff: FlipFlop) -> int:
    """Count how many FF stages in the reset path are in the target's clock domain.

    For a properly synchronized reset (async assert, sync de-assert), the reset
    signal passes through 2+ FFs all clocked by the target domain before driving
    the target FF's async reset. This is the prim_rst_sync pattern.
    """
    if target_ff.reset_net is None:
        return 0

    depth = 0
    bit = target_ff.reset_net
    visited: set[int] = set()

    while isinstance(bit, int) and bit not in visited:
        visited.add(bit)

        if bit not in netlist.driver_index:
            break

        cell_name, port_name = netlist.driver_index[bit]
        cell_data = netlist.cells.get(cell_name, {})

        if is_dff_type(cell_data.get("type", "")):
            ff = netlist.flip_flops.get(cell_name)
            if ff is None:
                break
            # Only count stages in the TARGET domain (sync de-assert pattern)
            if ff.clock_net == target_ff.clock_net:
                depth += 1
                # Continue tracing from this FF's D input
                if ff.d_bits:
                    bit = ff.d_bits[0]
                else:
                    break
            else:
                break  # Hit a FF in a different domain - stop counting
        else:
            # Combinational logic: trace through
            pd = cell_data.get("port_directions", {})
            conn = cell_data.get("connections", {})
            found = False
            for p_name, direction in pd.items():
                if direction == "input":
                    for b in conn.get(p_name, []):
                        if isinstance(b, int) and b not in visited:
                            bit = b
                            found = True
                            break
                    if found:
                        break
            if not found:
                break

    return depth


def find_clock_glitches(netlist: Netlist) -> list[ClockGlitch]:
    """Find FFs whose clock input is driven by combinational logic.

    A clock driven by combo logic (MUX, AND, OR, etc.) can produce glitches
    (runt pulses) that corrupt the clock tree. Safe patterns use dedicated
    clock mux cells or clock gating cells.
    """
    glitches: list[ClockGlitch] = []

    # Collect all unique clock nets
    checked_clocks: set[int] = set()

    for ff_name, ff in netlist.flip_flops.items():
        if ff.clock_net in checked_clocks:
            continue
        checked_clocks.add(ff.clock_net)

        # Check if clock net is a module input port (safe)
        if ff.clock_net in netlist.port_bits:
            continue

        # Check what drives the clock net
        if ff.clock_net not in netlist.driver_index:
            continue  # Undriven or external

        cell_name, port_name = netlist.driver_index[ff.clock_net]
        cell_data = netlist.cells.get(cell_name, {})
        cell_type = cell_data.get("type", "")

        # Skip if driven by a FF (unusual but not a glitch)
        if is_dff_type(cell_type):
            continue

        # Combinational logic driving clock - potential glitch
        clock_name = netlist.get_net_name(ff.clock_net)

        # Find all FFs affected by this glitchy clock
        for ff2_name, ff2 in netlist.flip_flops.items():
            if ff2.clock_net == ff.clock_net:
                glitches.append(ClockGlitch(
                    ff_name=ff2_name,
                    clock_net=ff.clock_net,
                    clock_name=clock_name,
                    driver_cell=cell_name,
                    driver_type=cell_type,
                ))
                break  # Report once per clock net, not per FF

    return glitches
