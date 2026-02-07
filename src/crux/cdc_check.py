"""Main CDC analysis: find all clock domain crossings and classify them."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .netlist import Netlist
from .clock_domains import ClockDomain, find_clock_domains
from .trace import trace_d_input, TraceResult
from .synchronizers import find_synchronizers, Synchronizer
from .sdc_parser import SDCConstraints


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ViolationType(Enum):
    MISSING_SYNC = "MISSING_SYNC"
    COMBO_BEFORE_SYNC = "COMBO_BEFORE_SYNC"
    MULTI_DOMAIN_FANIN = "MULTI_DOMAIN_FANIN"
    MULTI_BIT_CDC = "MULTI_BIT_CDC"


@dataclass
class Crossing:
    """A signal crossing between two clock domains."""
    source_ff_name: str
    dest_ff_name: str
    source_domain: str      # Human-readable clock name
    dest_domain: str
    source_clock_net: int
    dest_clock_net: int
    signal_name: str
    path_has_combo: bool
    is_synchronized: bool
    bit_width: int = 1      # Number of bits in the crossing signal
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
    sdc_loaded: bool = False

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.WARNING)


def analyze_cdc(
    netlist: Netlist,
    sdc: SDCConstraints | None = None,
) -> CDCReport:
    """Run full CDC analysis on a parsed netlist.

    1. Identify clock domains
    2. Map SDC clock names to netlist clock nets (if SDC provided)
    3. Detect synchronizer patterns
    4. Trace each FF's D-input to find cross-domain sources
    5. Classify each crossing as safe or violation
    """
    domains = find_clock_domains(netlist)
    synchronizers = find_synchronizers(netlist)

    # Map SDC clock names to domain clock names for relationship checking
    clock_name_map: dict[str, str] = {}
    if sdc:
        for domain in domains.values():
            # Try to match domain clock name to SDC clock name or port
            sdc_name = sdc.get_clock_for_port(domain.clock_name)
            if sdc_name:
                clock_name_map[domain.clock_name] = sdc_name
            elif domain.clock_name in sdc.clocks:
                clock_name_map[domain.clock_name] = domain.clock_name

    # Build set of all FF names that are part of synchronizers
    sync_ff_names: set[str] = set()
    for sync in synchronizers.values():
        for stage in sync.stages:
            sync_ff_names.add(stage.name)

    # Group FFs by destination to detect multi-bit crossings
    # Key: (dest_ff_name) -> trace result
    crossings: list[Crossing] = []
    violations: list[Violation] = []

    # Track which (src_domain, dst_domain, signal_base) we've seen for multi-bit grouping
    crossing_groups: dict[tuple[int, int, str], list[str]] = {}

    for ff_name, ff in netlist.flip_flops.items():
        trace = trace_d_input(netlist, ff)

        # Find source domains that differ from this FF's domain
        cross_domains = trace.source_domains - {ff.clock_net}
        if not cross_domains:
            continue

        signal_name = _get_crossing_signal_name(netlist, ff)

        for src_domain_net in cross_domains:
            src_domain_name = (
                domains[src_domain_net].clock_name
                if src_domain_net in domains
                else f"net_{src_domain_net}"
            )
            dst_domain_name = (
                domains[ff.clock_net].clock_name
                if ff.clock_net in domains
                else f"net_{ff.clock_net}"
            )

            # SDC check: skip crossings between related clocks
            if sdc and _are_domains_related(
                src_domain_name, dst_domain_name, sdc, clock_name_map
            ):
                continue

            # Find source FF(s) from this domain
            src_ffs = [f for f in trace.source_ffs if f.clock_net == src_domain_net]
            src_ff_name = src_ffs[0].name if src_ffs else "?"

            # Check synchronization status
            is_synced = ff_name in synchronizers
            sync_info = synchronizers.get(ff_name)

            # Determine bit width
            bit_width = len(ff.d_bits)

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
                bit_width=bit_width,
                synchronizer=sync_info,
            )
            crossings.append(crossing)

            # Track for multi-bit grouping
            base_name = _strip_bit_suffix(signal_name)
            group_key = (src_domain_net, ff.clock_net, base_name)
            crossing_groups.setdefault(group_key, []).append(ff_name)

            # Classify violation
            if is_synced:
                pass  # Recognized synchronizer
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
            elif bit_width > 1:
                # Multi-bit crossing without sync - distinct from single-bit
                violations.append(Violation(
                    rule=ViolationType.MULTI_BIT_CDC,
                    severity=Severity.ERROR,
                    crossing=crossing,
                    message=(
                        f"Multi-bit CDC without encoding: "
                        f"'{signal_name}' ({src_domain_name} -> {dst_domain_name}), "
                        f"{bit_width} bits crossing without gray code or handshake, "
                        f"source: {src_ff_name}, dest: {ff_name}"
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

    # Post-pass: detect multi-bit CDC (bus crossing without gray code / handshake)
    for (src_net, dst_net, base_name), ff_names in crossing_groups.items():
        if len(ff_names) > 1:
            # Check if ALL bits are unsynchronized
            unsync_count = sum(
                1 for fn in ff_names if fn not in sync_ff_names
            )
            if unsync_count > 1:
                src_name = (
                    domains[src_net].clock_name if src_net in domains
                    else f"net_{src_net}"
                )
                dst_name = (
                    domains[dst_net].clock_name if dst_net in domains
                    else f"net_{dst_net}"
                )
                # Find the first crossing for this group to attach the violation
                group_crossing = next(
                    (c for c in crossings
                     if c.source_clock_net == src_net
                     and c.dest_clock_net == dst_net
                     and _strip_bit_suffix(c.signal_name) == base_name),
                    None,
                )
                if group_crossing:
                    violations.append(Violation(
                        rule=ViolationType.MULTI_BIT_CDC,
                        severity=Severity.ERROR,
                        crossing=group_crossing,
                        message=(
                            f"Multi-bit CDC without encoding: "
                            f"'{base_name}' ({src_name} -> {dst_name}), "
                            f"{len(ff_names)} bits crossing without gray code or handshake"
                        ),
                    ))

    return CDCReport(
        module_name=netlist.module_name,
        domains=domains,
        crossings=crossings,
        violations=violations,
        sdc_loaded=sdc is not None,
    )


def _are_domains_related(
    src_name: str, dst_name: str,
    sdc: SDCConstraints, clock_name_map: dict[str, str],
) -> bool:
    """Check if two domain clock names are related per SDC constraints."""
    sdc_src = clock_name_map.get(src_name, src_name)
    sdc_dst = clock_name_map.get(dst_name, dst_name)
    return sdc.are_clocks_related(sdc_src, sdc_dst)


def _get_crossing_signal_name(netlist: Netlist, dest_ff) -> str:
    """Get the human-readable name of the signal at a FF's D input."""
    if dest_ff.d_bits:
        return netlist.get_net_name(dest_ff.d_bits[0])
    return "?"


def _strip_bit_suffix(name: str) -> str:
    """Strip bit index suffix to get bus base name.

    'data_a[0]' -> 'data_a'
    'data_a' -> 'data_a'
    """
    if name.endswith("]"):
        bracket = name.rfind("[")
        if bracket > 0:
            return name[:bracket]
    return name
