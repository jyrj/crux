"""Detect 2FF synchronizer patterns in the netlist.

A valid 2FF synchronizer pattern:
  [Domain A] FF_src.Q --> FF_sync1.D (no combo logic between)
                          FF_sync1.Q --> FF_sync2.D (fan-out of 1 from sync1.Q)
                                         FF_sync2.Q --> [rest of Domain B]

Requirements:
  1. FF_sync1 and FF_sync2 share the same clock domain
  2. FF_sync1.Q connects ONLY to FF_sync2.D (fan-out of exactly 1 to a DFF D-port)
  3. FF_sync1.D is driven (directly, no combo) by a signal from a different clock domain
"""

from __future__ import annotations

from dataclasses import dataclass

from .netlist import Netlist, FlipFlop, is_dff_type


@dataclass
class Synchronizer:
    """A recognized 2FF synchronizer."""
    stage1: FlipFlop       # First sync FF (captures metastable)
    stage2: FlipFlop       # Second sync FF (resolves metastability)
    src_domain: int        # Source clock net ID
    dst_domain: int        # Destination clock net ID

    @property
    def stage1_name(self) -> str:
        return self.stage1.name

    @property
    def stage2_name(self) -> str:
        return self.stage2.name


def find_synchronizers(netlist: Netlist) -> dict[str, Synchronizer]:
    """Find all 2FF synchronizer patterns.

    Returns dict mapping stage1 cell name -> Synchronizer.
    """
    synchronizers: dict[str, Synchronizer] = {}

    for cell_name, ff in netlist.flip_flops.items():
        sync = _check_sync_stage1(netlist, ff)
        if sync is not None:
            synchronizers[cell_name] = sync

    return synchronizers


def _check_sync_stage1(netlist: Netlist, candidate: FlipFlop) -> Synchronizer | None:
    """Check if a FF is stage 1 of a 2FF synchronizer.

    Stage 1 requirements:
    - Each Q bit feeds exactly one DFF D-input (and nothing else)
    - That DFF is in the same clock domain
    - The candidate's D input comes from a different clock domain (no combo logic)
    """
    if not candidate.q_bits:
        return None

    # Check that ALL Q bits feed exactly one DFF D-input each, all to the same FF
    stage2_candidates: set[str] = set()

    for q_bit in candidate.q_bits:
        readers = netlist.fanout_index.get(q_bit, [])

        # Must have readers, and ALL readers must be DFF D-ports
        dff_d_readers = []
        non_dff_readers = []

        for reader_cell, reader_port in readers:
            reader_data = netlist.cells.get(reader_cell, {})
            if is_dff_type(reader_data.get("type", "")) and reader_port in ("D",):
                dff_d_readers.append(reader_cell)
            else:
                non_dff_readers.append(reader_cell)

        # Strict: Q bit must fan out to exactly 1 DFF D-port, nothing else
        if len(dff_d_readers) != 1 or non_dff_readers:
            return None

        stage2_candidates.add(dff_d_readers[0])

    # All Q bits should feed the same stage2 FF (for multi-bit syncs)
    if len(stage2_candidates) != 1:
        return None

    stage2_name = stage2_candidates.pop()
    if stage2_name not in netlist.flip_flops:
        return None

    stage2 = netlist.flip_flops[stage2_name]

    # Stage2 must be in the same clock domain as stage1
    if stage2.clock_net != candidate.clock_net:
        return None

    # Now check: stage1's D input must come from a different clock domain
    # Trace backward from stage1's D input to find source domain
    src_domain = _find_direct_source_domain(netlist, candidate)
    if src_domain is None:
        return None

    # Source domain must differ from stage1's clock domain
    if src_domain == candidate.clock_net:
        return None

    return Synchronizer(
        stage1=candidate,
        stage2=stage2,
        src_domain=src_domain,
        dst_domain=candidate.clock_net,
    )


def _find_direct_source_domain(netlist: Netlist, ff: FlipFlop) -> int | None:
    """Find the clock domain of the FF(s) DIRECTLY driving this FF's D input.

    For a valid 2FF synchronizer, the D input must come directly from a FF
    Q output with NO combinational logic in between. If any combo logic is
    found, returns None (the crossing is not a valid 2FF sync).

    Returns the source clock net ID, or None if not directly driven by a
    single-domain FF output.
    """
    source_domains: set[int] = set()

    for d_bit in ff.d_bits:
        if not isinstance(d_bit, int):
            return None
        if d_bit not in netlist.driver_index:
            return None  # Module input or undriven - not a direct FF connection

        cell_name, port_name = netlist.driver_index[d_bit]
        cell_data = netlist.cells[cell_name]

        # Must be directly driven by a DFF Q output - no combo logic allowed
        if not is_dff_type(cell_data["type"]):
            return None  # Combo logic before sync - invalid 2FF pattern

        if cell_name in netlist.flip_flops:
            source_domains.add(netlist.flip_flops[cell_name].clock_net)
        else:
            return None

    if len(source_domains) == 1:
        return source_domains.pop()
    return None
