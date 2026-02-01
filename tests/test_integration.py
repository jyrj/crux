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

    def test_detects_missing_sync(self):
        report = _run_analysis("multi_bit_cdc.v", "multi_bit_cdc")
        assert report.error_count >= 1
        rules = {v.rule for v in report.violations}
        assert ViolationType.MISSING_SYNC in rules


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
