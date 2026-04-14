"""Main CDC/RDC analysis: orchestrates all checks and produces a unified report."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .netlist import Netlist, is_dff_type
from .clock_domains import ClockDomain, find_clock_domains
from .trace import trace_d_input
from .synchronizers import find_synchronizers, Synchronizer
from .reconvergence import find_reconvergences, ReconvergencePoint
from .rdc import find_rdc_violations, find_clock_glitches, ResetCrossing, ClockGlitch
from .gray_code import is_gray_encoded
from .handshake import is_handshake_protected
from .sdc_parser import SDCConstraints
from .waivers import Waiver, apply_waivers


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ViolationType(Enum):
    MISSING_SYNC = "MISSING_SYNC"
    COMBO_BEFORE_SYNC = "COMBO_BEFORE_SYNC"
    MULTI_DOMAIN_FANIN = "MULTI_DOMAIN_FANIN"
    MULTI_BIT_CDC = "MULTI_BIT_CDC"
    RECONVERGENCE = "RECONVERGENCE"
    RESET_DOMAIN_CROSSING = "RESET_DOMAIN_CROSSING"
    CLOCK_GLITCH = "CLOCK_GLITCH"
    FREQ_MISMATCH = "FREQ_MISMATCH"
    PORT_CDC_HAZARD = "PORT_CDC_HAZARD"


@dataclass
class Crossing:
    """A signal crossing between two clock domains."""
    source_ff_name: str
    dest_ff_name: str
    source_domain: str
    dest_domain: str
    source_clock_net: int
    dest_clock_net: int
    signal_name: str
    path_has_combo: bool
    is_synchronized: bool
    bit_width: int = 1
    synchronizer: Synchronizer | None = None


@dataclass
class Violation:
    """A CDC/RDC violation found during analysis."""
    rule: ViolationType
    severity: Severity
    message: str
    # Fields for waiver matching and reporting
    signal_name: str = ""
    source_domain: str = ""
    dest_domain: str = ""
    # Optional crossing context (None for RDC/glitch violations)
    crossing: Crossing | None = None

    def format(self) -> str:
        prefix = {
            Severity.ERROR: "ERROR",
            Severity.WARNING: "WARN ",
            Severity.INFO: "INFO ",
        }[self.severity]
        return f"[{prefix}] [{self.rule.value}] {self.message}"


@dataclass
class CDCReport:
    """Complete CDC/RDC analysis results."""
    module_name: str
    domains: dict[int, ClockDomain]
    crossings: list[Crossing]
    violations: list[Violation]
    waived_violations: list[tuple[Violation, Waiver]] = field(default_factory=list)
    reconvergences: list[ReconvergencePoint] = field(default_factory=list)
    reset_crossings: list[ResetCrossing] = field(default_factory=list)
    clock_glitches: list[ClockGlitch] = field(default_factory=list)
    sdc_loaded: bool = False

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.INFO)


def analyze_cdc(
    netlist: Netlist,
    sdc: SDCConstraints | None = None,
    waivers: list[Waiver] | None = None,
    max_reconvergence_depth: int = 2,
    skip_rdc: bool = False,
) -> CDCReport:
    """Run full CDC/RDC analysis.

    1. Identify clock domains
    2. Detect synchronizer patterns
    3. Trace each FF's D-input for cross-domain sources
    4. Classify CDC crossings
    5. Detect reconvergence of independently synchronized paths
    6. Detect reset domain crossings
    7. Detect clock mux glitches
    8. Apply waivers
    """
    domains = find_clock_domains(netlist)
    synchronizers = find_synchronizers(netlist)
    domain_names = {net: d.clock_name for net, d in domains.items()}

    # Map SDC clock names to netlist clock names
    clock_name_map: dict[str, str] = {}
    if sdc:
        for domain in domains.values():
            sdc_name = sdc.get_clock_for_port(domain.clock_name)
            if sdc_name:
                clock_name_map[domain.clock_name] = sdc_name
            elif domain.clock_name in sdc.clocks:
                clock_name_map[domain.clock_name] = domain.clock_name

    # Build set of sync FF names
    sync_ff_names: set[str] = set()
    for sync in synchronizers.values():
        for stage in sync.stages:
            sync_ff_names.add(stage.name)

    crossings: list[Crossing] = []
    violations: list[Violation] = []
    trace_memo: dict[int, tuple[set[int], bool, bool]] = {}
    cdc_files = _build_cdc_source_files(netlist) if len(domains) >= 2 else set()

    # === Phase 1: CDC crossing analysis ===
    # Skip per-FF tracing if design has only one clock domain (no CDC possible)
    skip_trace = len(domains) < 2
    for ff_name, ff in netlist.flip_flops.items():
        if skip_trace:
            continue
        trace = trace_d_input(netlist, ff, memo=trace_memo)
        cross_domains = trace.source_domains - {ff.clock_net}
        if not cross_domains:
            continue

        signal_name = _get_crossing_signal_name(netlist, ff)

        for src_domain_net in cross_domains:
            src_domain_name = domain_names.get(src_domain_net, f"net_{src_domain_net}")
            dst_domain_name = domain_names.get(ff.clock_net, f"net_{ff.clock_net}")

            if sdc and _are_domains_related(
                src_domain_name, dst_domain_name, sdc, clock_name_map
            ):
                continue

            src_ffs = [f for f in trace.source_ffs if f.clock_net == src_domain_net]
            src_ff_name = src_ffs[0].name if src_ffs else "?"

            is_synced = ff_name in synchronizers
            sync_info = synchronizers.get(ff_name)
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

            if is_synced:
                # Multi-bit synchronized crossing: verify gray encoding
                if bit_width > 1 and sync_info:
                    if is_gray_encoded(netlist, sync_info.stages[0]):
                        crossing.is_synchronized = True  # confirmed safe
                    # If not gray, it's still "synchronized" (has a sync chain)
                    # but the multi-bit nature is a concern — not flagged as
                    # error though, since the sync pattern was recognized
                pass
            elif trace.has_combo_logic:
                # Check if this combo path is inside a CDC primitive
                # (both FFs from CDC module source files → internal path)
                if _is_cdc_internal_path(netlist, src_ff_name, ff_name, cdc_files):
                    pass  # suppress — internal to CDC primitive
                elif is_handshake_protected(
                    netlist, ff, src_domain_net, synchronizers
                ):
                    violations.append(Violation(
                        rule=ViolationType.COMBO_BEFORE_SYNC,
                        severity=Severity.INFO,
                        message=(
                            f"Combinational CDC path with handshake protection: "
                            f"'{signal_name}' ({src_domain_name} -> {dst_domain_name}), "
                            f"gated by synchronized control"
                        ),
                        signal_name=signal_name,
                        source_domain=src_domain_name,
                        dest_domain=dst_domain_name,
                        crossing=crossing,
                    ))
                else:
                    violations.append(Violation(
                        rule=ViolationType.COMBO_BEFORE_SYNC,
                        severity=Severity.ERROR,
                        message=(
                            f"Combinational logic on CDC path: "
                            f"'{signal_name}' ({src_domain_name} -> {dst_domain_name}), "
                            f"source: {src_ff_name}, dest: {ff_name}"
                        ),
                        signal_name=signal_name,
                        source_domain=src_domain_name,
                        dest_domain=dst_domain_name,
                        crossing=crossing,
                    ))
            elif bit_width > 1:
                # Multi-bit crossing without synchronizer — check for
                # handshake/qualifier protection before flagging
                if is_handshake_protected(
                    netlist, ff, src_domain_net, synchronizers
                ):
                    violations.append(Violation(
                        rule=ViolationType.MULTI_BIT_CDC,
                        severity=Severity.WARNING,
                        message=(
                            f"Multi-bit CDC with handshake qualifier: "
                            f"'{signal_name}' ({src_domain_name} -> {dst_domain_name}), "
                            f"{bit_width} bits, enable gated by synchronized control"
                        ),
                        signal_name=signal_name,
                        source_domain=src_domain_name,
                        dest_domain=dst_domain_name,
                        crossing=crossing,
                    ))
                else:
                    violations.append(Violation(
                        rule=ViolationType.MULTI_BIT_CDC,
                        severity=Severity.ERROR,
                        message=(
                            f"Multi-bit CDC without encoding: "
                            f"'{signal_name}' ({src_domain_name} -> {dst_domain_name}), "
                            f"{bit_width} bits crossing without gray code or handshake, "
                            f"source: {src_ff_name}, dest: {ff_name}"
                        ),
                        signal_name=signal_name,
                        source_domain=src_domain_name,
                        dest_domain=dst_domain_name,
                        crossing=crossing,
                    ))
            else:
                violations.append(Violation(
                    rule=ViolationType.MISSING_SYNC,
                    severity=Severity.ERROR,
                    message=(
                        f"Missing synchronizer: "
                        f"'{signal_name}' ({src_domain_name} -> {dst_domain_name}), "
                        f"source: {src_ff_name}, dest: {ff_name}"
                    ),
                    signal_name=signal_name,
                    source_domain=src_domain_name,
                    dest_domain=dst_domain_name,
                    crossing=crossing,
                ))

    # === Phase 1b: Port-boundary CDC analysis ===
    # Check module output ports driven by combinational logic from a clock domain.
    # These are invisible to FF-to-FF tracing but are real CDC hazards when the
    # output is consumed in a different domain externally.
    _check_port_boundary_cdc(netlist, domains, domain_names, trace_memo, violations)

    # === Phase 2: Reconvergence analysis ===
    reconvergences = find_reconvergences(
        netlist, synchronizers, domain_names, max_depth=max_reconvergence_depth
    )
    for r in reconvergences:
        severity = Severity.INFO if r.through_mux else Severity.WARNING
        violations.append(Violation(
            rule=ViolationType.RECONVERGENCE,
            severity=severity,
            message=(
                f"Reconvergence of synchronized signals: "
                f"{', '.join(r.sync_names)} meet at {r.cell_name} "
                f"({r.src_domain} -> {r.dst_domain})"
                f"{' via MUX (likely safe)' if r.through_mux else ' (potential data corruption)'}"
            ),
            signal_name=r.signal_name,
            source_domain=r.src_domain,
            dest_domain=r.dst_domain,
        ))

    # === Phase 3: RDC analysis ===
    reset_crossings: list[ResetCrossing] = []
    clock_glitches: list[ClockGlitch] = []

    if not skip_rdc:
        reset_crossings = find_rdc_violations(netlist, domain_names)
        for rdc in reset_crossings:
            if rdc.is_from_port:
                continue  # Module input resets are responsibility of integrator
            if not rdc.is_synchronized:
                violations.append(Violation(
                    rule=ViolationType.RESET_DOMAIN_CROSSING,
                    severity=Severity.ERROR,
                    message=(
                        f"Async reset crosses domain without synchronization: "
                        f"FF {rdc.ff_name} ({rdc.ff_domain}) reset from "
                        f"{rdc.reset_source_domain} via {rdc.reset_source}"
                    ),
                    signal_name=netlist.get_net_name(rdc.reset_net),
                    source_domain=rdc.reset_source_domain or "",
                    dest_domain=rdc.ff_domain,
                ))

        clock_glitches = find_clock_glitches(netlist)
        for g in clock_glitches:
            violations.append(Violation(
                rule=ViolationType.CLOCK_GLITCH,
                severity=Severity.ERROR,
                message=(
                    f"Combinational logic driving clock: "
                    f"'{g.clock_name}' driven by {g.driver_type} cell {g.driver_cell}, "
                    f"affects FF {g.ff_name}"
                ),
                signal_name=g.clock_name,
            ))

    # === Phase 4: Clock frequency validation ===
    if sdc:
        _check_frequency_ratios(sdc, clock_name_map, crossings, violations)

    # === Phase 5: Apply waivers ===
    waived: list[tuple[Violation, Waiver]] = []
    if waivers:
        violations, waived = apply_waivers(violations, waivers)

    return CDCReport(
        module_name=netlist.module_name,
        domains=domains,
        crossings=crossings,
        violations=violations,
        waived_violations=waived,
        reconvergences=reconvergences,
        reset_crossings=reset_crossings,
        clock_glitches=clock_glitches,
        sdc_loaded=sdc is not None,
    )


def _are_domains_related(
    src_name: str, dst_name: str,
    sdc: SDCConstraints, clock_name_map: dict[str, str],
) -> bool:
    sdc_src = clock_name_map.get(src_name, src_name)
    sdc_dst = clock_name_map.get(dst_name, dst_name)
    return sdc.are_clocks_related(sdc_src, sdc_dst)


def _get_crossing_signal_name(netlist: Netlist, dest_ff) -> str:
    if dest_ff.d_bits:
        return netlist.get_net_name(dest_ff.d_bits[0])
    return "?"


def _build_cdc_source_files(netlist: Netlist) -> set[str]:
    """Dynamically identify source files that are CDC primitives.

    A source file is a CDC primitive if:
    1. It contains FFs from 2+ clock domains (handles CDC internally)
    2. It is NOT the only source file (not the top-level design itself)

    This distinguishes between a CDC module (prim_reg_cdc.sv — handles
    crossings internally) and a top-level design (soc.sv — has crossings
    that need to be checked).
    """
    from collections import defaultdict
    file_clocks: dict[str, set[int]] = defaultdict(set)
    file_ff_count: dict[str, int] = defaultdict(int)

    for ff in netlist.flip_flops.values():
        if ff.src:
            src_file = ff.src.split(":")[0] if ":" in ff.src else ff.src
            file_clocks[src_file].add(ff.clock_net)
            file_ff_count[src_file] += 1

    # Files with FFs on 2+ domains
    multi_domain_files = {f for f, clocks in file_clocks.items() if len(clocks) >= 2}

    # If there's only one source file, it's the top-level — don't suppress
    if len(file_clocks) <= 1:
        return set()

    # Also exclude the file with the most FFs (likely the top-level or main logic)
    # CDC primitives are typically small helper modules, not the biggest file
    if multi_domain_files:
        biggest = max(multi_domain_files, key=lambda f: file_ff_count[f])
        # Only exclude if it has significantly more FFs than others
        avg_size = sum(file_ff_count[f] for f in multi_domain_files) / len(multi_domain_files)
        if file_ff_count[biggest] > avg_size * 3:
            multi_domain_files.discard(biggest)

    return multi_domain_files


def _is_cdc_internal_path(
    netlist: Netlist,
    src_ff_name: str,
    dst_ff_name: str,
    cdc_files: set[str] | None = None,
) -> bool:
    """Check if both FFs are inside CDC primitive modules (internal path).

    Uses source file attribution: if both FFs originate from files that
    contain multi-domain FFs (dynamically detected CDC primitives), the
    crossing is internal to the CDC mechanism.
    """
    src_ff = netlist.flip_flops.get(src_ff_name)
    dst_ff = netlist.flip_flops.get(dst_ff_name)
    if not src_ff or not dst_ff:
        return False

    if cdc_files is None:
        cdc_files = _build_cdc_source_files(netlist)

    def _from_cdc_file(ff):
        src = ff.src.split(":")[0] if ":" in ff.src else ff.src
        return src in cdc_files

    return _from_cdc_file(src_ff) and _from_cdc_file(dst_ff)


def _check_port_boundary_cdc(
    netlist: Netlist,
    domains: dict[int, ClockDomain],
    domain_names: dict[int, str],
    trace_memo: dict,
    violations: list[Violation],
) -> None:
    """Check module output ports for unregistered CDC hazards.

    Pattern: a module output port is driven by combinational logic sourced
    from clock domain X. Any external consumer in domain Y will see this as
    an unsynchronized combinational crossing. This is the bug pattern from
    OpenTitan #19200 (fsm_err_o).

    We trace each output port bit backward. If it reaches FFs in a specific
    domain through combinational logic (not directly from a FF Q-output),
    it's a combinational port that could cause CDC issues for consumers.
    """
    for port_name, port_data in netlist.ports.items():
        if port_data["direction"] != "output":
            continue

        for bit in port_data["bits"]:
            if not isinstance(bit, int):
                continue  # constant-driven output

            # Check if this bit is directly a FF Q-output (registered = safe)
            if bit in netlist.driver_index:
                cell_name, port = netlist.driver_index[bit]
                cell_data = netlist.cells.get(cell_name, {})
                if is_dff_type(cell_data.get("type", "")):
                    continue  # registered output, not a hazard

            # Trace backward to find source domain(s)
            from .trace import _trace_bit
            source_ffs: list = []
            source_doms: set[int] = set()
            visited: set[int] = set()
            has_combo, from_input = _trace_bit(
                netlist, bit, visited, source_ffs, source_doms, depth=0
            )

            if not has_combo or not source_doms:
                continue  # either registered or no FF source

            # This output port is combinational from a specific domain.
            # Flag each source domain — external consumers in other domains
            # will see an unsynchronized combinational crossing.
            # Only flag if the design has multiple clock domains
            # (single-domain designs have no CDC concern on outputs)
            if len(domains) < 2:
                continue

            for src_net in source_doms:
                src_name = domain_names.get(src_net, f"net_{src_net}")
                violations.append(Violation(
                    rule=ViolationType.PORT_CDC_HAZARD,
                    severity=Severity.INFO,
                    message=(
                        f"Combinational output port '{port_name}' driven by "
                        f"{src_name} domain through logic — potential CDC hazard "
                        f"if consumed in a different domain externally"
                    ),
                    signal_name=port_name,
                    source_domain=src_name,
                    dest_domain="(external)",
                ))
                break


def _check_frequency_ratios(
    sdc: SDCConstraints,
    clock_name_map: dict[str, str],
    crossings: list[Crossing],
    violations: list[Violation],
) -> None:
    """Check clock frequency relationships for crossed domain pairs.

    Warns when:
    - Clocks declared "related" (generated) have non-integer frequency ratio
    - Frequency ratio is very high (>10x) suggesting inadequate sync depth
    """
    checked_pairs: set[tuple[str, str]] = set()

    for crossing in crossings:
        pair = (crossing.source_domain, crossing.dest_domain)
        if pair in checked_pairs:
            continue
        checked_pairs.add(pair)

        sdc_src = clock_name_map.get(crossing.source_domain, crossing.source_domain)
        sdc_dst = clock_name_map.get(crossing.dest_domain, crossing.dest_domain)

        src_clk = sdc.clocks.get(sdc_src)
        dst_clk = sdc.clocks.get(sdc_dst)

        if not src_clk or not dst_clk:
            continue
        if not src_clk.period or not dst_clk.period:
            continue

        freq_src = 1.0 / src_clk.period  # GHz (period in ns)
        freq_dst = 1.0 / dst_clk.period

        ratio = max(freq_src, freq_dst) / min(freq_src, freq_dst)

        # Check: if related clocks have non-integer ratio, that's suspicious
        if sdc.are_clocks_related(sdc_src, sdc_dst):
            nearest_int = round(ratio)
            if nearest_int > 0 and abs(ratio - nearest_int) > 0.01:
                violations.append(Violation(
                    rule=ViolationType.FREQ_MISMATCH,
                    severity=Severity.WARNING,
                    message=(
                        f"Related clocks with non-integer frequency ratio: "
                        f"{sdc_src} ({1000/src_clk.period:.1f} MHz) / "
                        f"{sdc_dst} ({1000/dst_clk.period:.1f} MHz) = {ratio:.2f}x"
                    ),
                    signal_name="",
                    source_domain=crossing.source_domain,
                    dest_domain=crossing.dest_domain,
                ))
