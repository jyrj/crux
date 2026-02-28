"""End-to-end integration tests: Verilog -> Yosys -> analysis -> report."""

import json
from pathlib import Path

import pytest

from crux.yosys_runner import run_yosys
from crux.netlist import Netlist
from crux.cdc_check import analyze_cdc, ViolationType
from crux.report import format_json_report

DESIGNS = Path(__file__).parent / "designs"


def _run_analysis(design_file: str, top_module: str):
    """Helper: run full CDC analysis pipeline on a test design."""
    verilog_path = str(DESIGNS / design_file)
    json_path = run_yosys([verilog_path], top_module)
    netlist = Netlist.from_json(json_path)
    return analyze_cdc(netlist)


class TestSimpleCDC:
    """simple_cdc.v: missing synchronizer, must flag MISSING_SYNC."""

    def test_detects_missing_sync(self):
        report = _run_analysis("simple_cdc.v", "simple_cdc")
        assert report.error_count == 1
        assert report.warning_count == 0
        assert len(report.violations) == 1
        assert report.violations[0].rule == ViolationType.MISSING_SYNC

    def test_identifies_two_domains(self):
        report = _run_analysis("simple_cdc.v", "simple_cdc")
        domain_names = {d.clock_name for d in report.domains.values()}
        assert "clk_a" in domain_names
        assert "clk_b" in domain_names

    def test_crossing_signal_name(self):
        report = _run_analysis("simple_cdc.v", "simple_cdc")
        assert len(report.crossings) == 1
        assert report.crossings[0].signal_name == "data_a"
        assert report.crossings[0].source_domain == "clk_a"
        assert report.crossings[0].dest_domain == "clk_b"


class TestSimpleSync:
    """simple_sync.v: proper 2FF synchronizer, must pass clean."""

    def test_no_violations(self):
        report = _run_analysis("simple_sync.v", "simple_sync")
        assert report.error_count == 0
        assert report.warning_count == 0
        assert len(report.violations) == 0

    def test_crossing_recognized_as_synchronized(self):
        report = _run_analysis("simple_sync.v", "simple_sync")
        assert len(report.crossings) == 1
        assert report.crossings[0].is_synchronized is True

    def test_identifies_two_domains(self):
        report = _run_analysis("simple_sync.v", "simple_sync")
        domain_names = {d.clock_name for d in report.domains.values()}
        assert "clk_a" in domain_names
        assert "clk_b" in domain_names


class TestComboBeforeSync:
    """combo_before_sync.v: combo logic before sync, must flag."""

    def test_detects_combo_before_sync(self):
        report = _run_analysis("combo_before_sync.v", "combo_before_sync")
        assert report.error_count == 1
        assert len(report.violations) == 1
        assert report.violations[0].rule == ViolationType.COMBO_BEFORE_SYNC

    def test_crossing_signal_is_data_masked(self):
        report = _run_analysis("combo_before_sync.v", "combo_before_sync")
        assert report.crossings[0].signal_name == "data_masked"


class TestMultiBitCDC:
    """multi_bit_cdc.v: multi-bit bus crossing without encoding."""

    def test_detects_multi_bit_cdc(self):
        report = _run_analysis("multi_bit_cdc.v", "multi_bit_cdc")
        assert report.error_count >= 1
        rules = {v.rule for v in report.violations}
        assert ViolationType.MULTI_BIT_CDC in rules


class TestRealisticSoC:
    """realistic_soc.v: multi-module design with mixed CDC patterns + SDC."""

    def _run_with_sdc(self):
        verilog_path = str(DESIGNS / "realistic_soc.v")
        sdc_path = DESIGNS.parent / "constraints" / "realistic_soc.sdc"
        json_path = run_yosys([verilog_path], "realistic_soc")
        netlist = Netlist.from_json(json_path)
        from crux.sdc_parser import parse_sdc
        sdc = parse_sdc(sdc_path)
        return analyze_cdc(netlist, sdc=sdc)

    def test_three_domains(self):
        report = self._run_with_sdc()
        assert len(report.domains) == 3

    def test_pulse_sync_recognized(self):
        """The prim_pulse_sync path should be recognized as synchronized."""
        report = self._run_with_sdc()
        synced = [c for c in report.crossings if c.is_synchronized]
        assert len(synced) >= 1

    def test_multi_bit_cdc_detected(self):
        """8-bit sys_status -> io_status should flag MULTI_BIT_CDC."""
        report = self._run_with_sdc()
        rules = {v.rule for v in report.violations}
        assert ViolationType.MULTI_BIT_CDC in rules

    def test_missing_sync_detected(self):
        """sys_status[0] -> aon_flag should flag MISSING_SYNC."""
        report = self._run_with_sdc()
        rules = {v.rule for v in report.violations}
        assert ViolationType.MISSING_SYNC in rules

    def test_exactly_two_violations(self):
        """Should have exactly 2 violations: multi-bit + missing sync."""
        report = self._run_with_sdc()
        assert report.error_count == 2

    def test_sdc_loaded(self):
        report = self._run_with_sdc()
        assert report.sdc_loaded is True


class TestSDCParser:
    """Test SDC constraint parsing and clock relationship logic."""

    def test_parse_earlgrey_sdc(self):
        from crux.sdc_parser import parse_sdc
        sdc_path = DESIGNS.parent / "constraints" / "earlgrey_cdc.sdc"
        sdc = parse_sdc(sdc_path)
        assert len(sdc.clocks) == 6
        assert "clk_main" in sdc.clocks
        assert sdc.clocks["clk_io_div2"].is_generated

    def test_async_detection(self):
        from crux.sdc_parser import parse_sdc
        sdc_path = DESIGNS.parent / "constraints" / "earlgrey_cdc.sdc"
        sdc = parse_sdc(sdc_path)
        assert sdc.are_clocks_async("clk_main", "clk_usb") is True
        assert sdc.are_clocks_async("clk_io", "clk_io_div2") is False

    def test_related_detection(self):
        from crux.sdc_parser import parse_sdc
        sdc_path = DESIGNS.parent / "constraints" / "earlgrey_cdc.sdc"
        sdc = parse_sdc(sdc_path)
        assert sdc.are_clocks_related("clk_io", "clk_io_div4") is True
        assert sdc.are_clocks_related("clk_main", "clk_usb") is False


class TestReconvergenceUnsafe:
    """reconvergence_unsafe.v: direct reconvergence should be WARNING."""

    def test_detects_reconvergence(self):
        report = _run_analysis("reconvergence_unsafe.v", "reconvergence_unsafe")
        rules = {v.rule for v in report.violations}
        assert ViolationType.RECONVERGENCE in rules

    def test_warning_severity(self):
        report = _run_analysis("reconvergence_unsafe.v", "reconvergence_unsafe")
        recon = [v for v in report.violations if v.rule == ViolationType.RECONVERGENCE]
        assert len(recon) >= 1
        from crux.cdc_check import Severity
        assert recon[0].severity == Severity.WARNING

    def test_both_crossings_synchronized(self):
        report = _run_analysis("reconvergence_unsafe.v", "reconvergence_unsafe")
        assert report.error_count == 0  # No errors, only warning


class TestReconvergenceMux:
    """reconvergence_mux.v: MUX-based reconvergence should be INFO."""

    def test_detects_mux_reconvergence(self):
        report = _run_analysis("reconvergence_mux.v", "reconvergence_mux")
        recon = [v for v in report.violations if v.rule == ViolationType.RECONVERGENCE]
        assert len(recon) >= 1
        from crux.cdc_check import Severity
        assert recon[0].severity == Severity.INFO

    def test_no_errors_or_warnings(self):
        report = _run_analysis("reconvergence_mux.v", "reconvergence_mux")
        assert report.error_count == 0
        assert report.warning_count == 0


class TestRDCMissingSync:
    """rdc_missing_sync.v: unsynchronized reset from different domain."""

    def test_detects_rdc_violation(self):
        report = _run_analysis("rdc_missing_sync.v", "rdc_missing_sync")
        rules = {v.rule for v in report.violations}
        assert ViolationType.RESET_DOMAIN_CROSSING in rules

    def test_error_severity(self):
        report = _run_analysis("rdc_missing_sync.v", "rdc_missing_sync")
        assert report.error_count >= 1


class TestRDCProperSync:
    """rdc_proper_sync.v: properly synchronized reset should pass clean."""

    def test_no_violations(self):
        report = _run_analysis("rdc_proper_sync.v", "rdc_proper_sync")
        assert report.error_count == 0
        assert report.warning_count == 0


class TestWaivers:
    """Test waiver system with realistic_soc design."""

    def test_waiver_suppresses_violation(self):
        from crux.sdc_parser import parse_sdc
        from crux.waivers import load_waivers
        verilog = str(DESIGNS / "realistic_soc.v")
        sdc = parse_sdc(DESIGNS.parent / "constraints" / "realistic_soc.sdc")
        waivers = load_waivers(DESIGNS.parent / "waivers" / "realistic_soc.yaml")
        json_path = run_yosys([verilog], "realistic_soc")
        netlist = Netlist.from_json(json_path)
        report = analyze_cdc(netlist, sdc=sdc, waivers=waivers)
        # MULTI_BIT_CDC should be waived
        active_rules = {v.rule for v in report.violations}
        assert ViolationType.MULTI_BIT_CDC not in active_rules
        assert len(report.waived_violations) == 1
        assert report.waived_violations[0][1].reason == "quasi-static register, read only during idle"

    def test_non_waived_still_flagged(self):
        from crux.sdc_parser import parse_sdc
        from crux.waivers import load_waivers
        verilog = str(DESIGNS / "realistic_soc.v")
        sdc = parse_sdc(DESIGNS.parent / "constraints" / "realistic_soc.sdc")
        waivers = load_waivers(DESIGNS.parent / "waivers" / "realistic_soc.yaml")
        json_path = run_yosys([verilog], "realistic_soc")
        netlist = Netlist.from_json(json_path)
        report = analyze_cdc(netlist, sdc=sdc, waivers=waivers)
        # MISSING_SYNC should still be there
        active_rules = {v.rule for v in report.violations}
        assert ViolationType.MISSING_SYNC in active_rules


class TestGrayCode:
    """gray_cdc.v: gray-encoded counter should be recognized as safe."""

    def test_no_multi_bit_error(self):
        report = _run_analysis("gray_cdc.v", "gray_cdc")
        rules = {v.rule for v in report.violations if v.severity.value == "error"}
        assert ViolationType.MULTI_BIT_CDC not in rules

    def test_crossing_synchronized(self):
        report = _run_analysis("gray_cdc.v", "gray_cdc")
        synced = [c for c in report.crossings if c.is_synchronized]
        assert len(synced) >= 1


class TestHandshake:
    """handshake_cdc.v: req/ack protected data should be WARNING not ERROR."""

    def test_handshake_downgraded(self):
        report = _run_analysis("handshake_cdc.v", "handshake_cdc")
        multi_bit = [v for v in report.violations if v.rule == ViolationType.MULTI_BIT_CDC]
        assert len(multi_bit) >= 1
        from crux.cdc_check import Severity
        assert multi_bit[0].severity == Severity.WARNING

    def test_req_ack_syncs_detected(self):
        report = _run_analysis("handshake_cdc.v", "handshake_cdc")
        synced = [c for c in report.crossings if c.is_synchronized]
        assert len(synced) >= 2  # req sync + ack sync

    def test_no_errors(self):
        report = _run_analysis("handshake_cdc.v", "handshake_cdc")
        assert report.error_count == 0


class TestClockMuxSafe:
    """clock_mux_safe.v: glitch-free clock mux should not flag CLOCK_GLITCH."""

    def test_no_clock_glitch(self):
        report = _run_analysis("clock_mux_safe.v", "clock_mux_safe")
        rules = {v.rule for v in report.violations}
        assert ViolationType.CLOCK_GLITCH not in rules


class TestAccelleraParser:
    """Accellera CDC/RDC Standard 1.0 parser."""

    def test_parse_cdcspec(self):
        from crux.accellera_parser import parse_accellera
        a = parse_accellera(DESIGNS.parent / "constraints" / "example.cdcspec")
        assert a.module_name == "gray_cdc"
        assert len(a.ports) == 4
        assert a.is_hamming1("gray_out")
        assert a.get_port_type("clk_a") == "clock"
        assert a.get_port_type("rst_n") == "async_reset"

    def test_clock_groups(self):
        from crux.accellera_parser import parse_accellera
        a = parse_accellera(DESIGNS.parent / "constraints" / "example.cdcspec")
        assert a.are_clocks_synchronous("clk_a", "clk_b")


class TestFormalGeneration:
    """Formal assertion generation for SymbiYosys."""

    def test_generates_gray_assertion(self):
        report = _run_analysis("gray_cdc.v", "gray_cdc")
        from crux.formal import generate_formal_checks
        sby, wrapper = generate_formal_checks(
            report, ["tests/designs/gray_cdc.v"], "gray_cdc"
        )
        assert "countones" in wrapper
        assert "smtbmc" in sby
        assert "multiclock on" in sby

    def test_no_formal_for_clean_design(self):
        report = _run_analysis("simple_sync.v", "simple_sync")
        from crux.formal import generate_formal_checks
        sby, wrapper = generate_formal_checks(
            report, ["tests/designs/simple_sync.v"], "simple_sync"
        )
        # Single-bit sync, no gray code — no assertions generated
        assert sby == ""


class TestJSONReport:
    """Verify JSON report structure."""

    def test_json_report_structure(self):
        report = _run_analysis("simple_cdc.v", "simple_cdc")
        data = format_json_report(report)
        assert data["tool"] == "crux"
        assert data["design"] == "simple_cdc"
        assert len(data["clock_domains"]) == 2
        assert len(data["violations"]) == 1
        assert data["summary"]["errors"] == 1
        assert data["summary"]["synchronized"] == 0

    def test_json_clean_report(self):
        report = _run_analysis("simple_sync.v", "simple_sync")
        data = format_json_report(report)
        assert data["summary"]["errors"] == 0
        assert data["summary"]["synchronized"] == 1
        assert len(data["violations"]) == 0
