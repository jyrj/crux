# Crux vs LLM (Claude Opus 4.6): Complete Experimental Results

All LLM runs: fully isolated agent, zero hint leakage, neutral filenames.

## Table 1: Synthetic Benchmark (crux_bench_small)

4 clock domains, 34 FFs, 4 planted bugs, ~280 LOC.

| Tool | TP | FP | FN | Precision | Recall | F1 | Time |
|------|----|----|-----|-----------|--------|----|------|
| crux | 4 | 0 | 0 | 1.00 | 1.00 | 1.00 | 71 ms |
| LLM | 4 | 3 | 0 | 0.57 | 1.00 | 0.73 | ~96 s |

LLM FPs: flagged module input ports as domain crossings.

## Table 2: Real OpenTitan CDC Bugs

From lowRISC/opentitan git history, PRs #19202, #24622, #24125.

| Bug | Reference | Category | crux | LLM |
|-----|-----------|----------|------|-----|
| A | PR #19202 | COMBO_BEFORE_SYNC | FOUND | FOUND |
| B | PR #24622 | Timing glitch | MISSED | FOUND |
| C | PR #24125 | COMBO_BEFORE_SYNC | FOUND | FOUND |

Bug B: Yosys optimizes the comparator to constant. Structural tools cannot
detect timing-dependent glitches. LLM reasoned about register update timing.

## Table 3: aon_timer (Real OpenTitan IP, 196 FFs)

| Metric | crux | LLM |
|--------|------|-----|
| Crossings found | 80 | 14 |
| Synced recognized | 25 | 13 |
| Errors (COMBO_BEFORE_SYNC) | 13 | 0 |
| Warnings (RECONVERGENCE) | 13 | 1 |
| CDC-internal suppressed | 36 | — |
| Runtime | 57 ms | ~120 s |

crux's 13 remaining errors are register write paths through prim_reg_cdc.
Structurally correct but semantically safe (handshake protocol). Would be waived.
LLM read prim_reg_cdc.sv and understood the protocol — zero FPs.

## Table 4: Single-Domain IPs (negative control)

| IP | FFs | Cells | Errors |
|----|-----|-------|--------|
| rv_timer | 40 | 467 | 0 |
| uart_core | 138 | 435 | 0 |
| i2c_core | 121 | 2358 | 0 |
| hmac | 202 | 2890 | 0 |

## Table 5: CDC Primitives (zero FP benchmark)

| Module | Crossings | Synced | Errors |
|--------|-----------|--------|--------|
| prim_pulse_sync | 1 | 1 | 0 |
| prim_fifo_async | 2 | 2 | 0 |
| prim_sync_reqack | 2 | 2 | 0 |

## Key Finding

The tools have fundamentally different failure modes:
- crux: exhaustive structural coverage, over-reports on CDC primitive internals
- LLM: precise semantic understanding, cannot guarantee exhaustive coverage
- Combined: crux for structural backbone + LLM for semantic review
