"""Main CDC analysis: find all clock domain crossings and classify them."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .netlist import Netlist
from .clock_domains import ClockDomain, find_clock_domains
from .trace import trace_d_input, TraceResult
from .synchronizers import find_synchronizers, Synchronizer


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ViolationType(Enum):
    MISSING_SYNC = "MISSING_SYNC"
    COMBO_BEFORE_SYNC = "COMBO_BEFORE_SYNC"
    MULTI_DOMAIN_FANIN = "MULTI_DOMAIN_FANIN"


@dataclass
class Crossing:
    """A signal crossing between two clock domains."""
    source_ff_name: str
    dest_ff_name: str
    source_domain: str      # Human-readable clock name
    dest_domain: str
    source_clock_net: int
    dest_clock_net: int
    signal_name: str        # Net name of the crossing signal
    path_has_combo: bool
    is_synchronized: bool
    synchronizer: Synchronizer | None = None


@dataclass
class Violation:
    """A CDC violation found during analysis."""
    rule: ViolationType
    severity: Severity
    crossing: Crossing
    message: str

    def format(self) -> str:
        prefix = {
            Severity.ERROR: "ERROR",
            Severity.WARNING: "WARN ",
            Severity.INFO: "INFO ",
        }[self.severity]
        return f"[{prefix}] [{self.rule.value}] {self.message}"


@dataclass
class CDCReport:
    """Complete CDC analysis results."""
    module_name: str
    domains: dict[int, ClockDomain]
    crossings: list[Crossing]
    violations: list[Violation]

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.WARNING)


def analyze_cdc(netlist: Netlist) -> CDCReport:
    """Run full CDC analysis on a parsed netlist.

    1. Identify clock domains
    2. Detect synchronizer patterns
    3. Trace each FF's D-input to find cross-domain sources
    4. Classify each crossing as safe or violation
    """
    domains = find_clock_domains(netlist)
    synchronizers = find_synchronizers(netlist)

    # Build set of FF names that are part of synchronizers (stage1 or stage2)
    sync_ff_names: set[str] = set()
    for sync in synchronizers.values():
        sync_ff_names.add(sync.stage1.name)
        sync_ff_names.add(sync.stage2.name)

    crossings: list[Crossing] = []
    violations: list[Violation] = []

    for ff_name, ff in netlist.flip_flops.items():
        trace = trace_d_input(netlist, ff)

        # Find source domains that differ from this FF's domain
        cross_domains = trace.source_domains - {ff.clock_net}
        if not cross_domains:
            continue  # No crossing, all sources are same domain or input-only

        # Determine the signal name (the net connecting source to dest)
        signal_name = _get_crossing_signal_name(netlist, ff)

        # For each source domain, create a crossing record
        for src_domain_net in cross_domains:
            src_domain_name = domains[src_domain_net].clock_name if src_domain_net in domains else f"net_{src_domain_net}"
            dst_domain_name = domains[ff.clock_net].clock_name if ff.clock_net in domains else f"net_{ff.clock_net}"

            # Find source FF(s) from this domain
            src_ffs = [f for f in trace.source_ffs if f.clock_net == src_domain_net]
            src_ff_name = src_ffs[0].name if src_ffs else "?"

            # Check if this crossing is synchronized
            is_synced = False
            sync_info = None

            # Check if this FF is stage1 of a synchronizer
            if ff_name in synchronizers:
                is_synced = True
                sync_info = synchronizers[ff_name]

            # Check if this FF is stage2 of a synchronizer
            # (stage2's D comes from stage1 in same domain, so it won't appear
            #  as a cross-domain crossing. But stage1 will.)

            crossing = Crossing(
                source_ff_name=src_ff_name,
                dest_ff_name=ff_name,
                source_domain=src_domain_name,
                dest_domain=dst_domain_name,
                source_clock_net=src_domain_net,
                dest_clock_net=ff.clock_net,
                signal_name=signal_name,
                path_has_combo=trace.has_combo_logic,
                is_synchronized=is_synced,
                synchronizer=sync_info,
            )
            crossings.append(crossing)

            # Classify
            if is_synced:
                # Recognized synchronizer - no violation
                pass
            elif trace.has_combo_logic:
                violations.append(Violation(
                    rule=ViolationType.COMBO_BEFORE_SYNC,
                    severity=Severity.ERROR,
                    crossing=crossing,
                    message=(
                        f"Combinational logic on CDC path: "
                        f"'{signal_name}' ({src_domain_name} -> {dst_domain_name}), "
                        f"source: {src_ff_name}, dest: {ff_name}"
                    ),
                ))
            elif len(cross_domains) > 1:
                violations.append(Violation(
                    rule=ViolationType.MULTI_DOMAIN_FANIN,
                    severity=Severity.WARNING,
                    crossing=crossing,
                    message=(
                        f"Multi-domain fan-in: "
                        f"'{signal_name}' dest FF {ff_name} ({dst_domain_name}) "
                        f"driven by signals from {len(cross_domains) + 1} domains"
                    ),
                ))
            else:
                violations.append(Violation(
                    rule=ViolationType.MISSING_SYNC,
                    severity=Severity.ERROR,
                    crossing=crossing,
                    message=(
                        f"Missing synchronizer: "
                        f"'{signal_name}' ({src_domain_name} -> {dst_domain_name}), "
                        f"source: {src_ff_name}, dest: {ff_name}"
                    ),
                ))

    return CDCReport(
        module_name=netlist.module_name,
        domains=domains,
        crossings=crossings,
        violations=violations,
    )


def _get_crossing_signal_name(netlist: Netlist, dest_ff) -> str:
    """Get the human-readable name of the signal at a FF's D input."""
    if dest_ff.d_bits:
        first_d = dest_ff.d_bits[0]
        return netlist.get_net_name(first_d)
    return "?"
