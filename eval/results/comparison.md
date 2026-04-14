# Crux vs LLM (Claude Opus 4.6): CDC Bug Detection — Clean Baseline

No hint leakage. All file comments stripped. Neutral filenames. LLM ran in
fully isolated workspace with zero access to crux code or ground truth.

## SoC-A: crux_bench_small (4 clock domains, 34 FFs, 4 bugs)

| Tool | TP | FP | FN | Precision | Recall | Runtime |
|------|----|----|-----|-----------|--------|---------|
| crux | 4 | 0 | 0 | 1.00 | 1.00 | 71 ms |
| LLM | 4 | 3 | 0 | 0.57 | 1.00 | ~90 s |

**LLM false positives** (3):
- `uart_rx_data` per_clk→sys_clk — module input, not a registered CDC crossing
- `uart_rx_valid` per_clk→sys_clk — module input, not a registered CDC crossing
- `gpio_in` per_clk→sys_clk — module input, not a registered CDC crossing

The LLM incorrectly flagged module input ports as domain crossings. These
ports don't belong to any clock domain — they are external inputs. The
clock domain is determined by which FF samples them, not the port name.
crux correctly handles this because it traces from FF Q-outputs, not ports.

## Design B1: Real OpenTitan lc_ctrl_kmac_if (lowRISC/opentitan#19200)

| Tool | True bug found | Additional findings | FP |
|------|---------------|--------------------|----|
| crux | hash_done COMBO_BEFORE_SYNC | — | 0 |
| LLM | hash_done COMBO_BEFORE_SYNC | fsm_err_o MISSING_SYNC, token_hash_req unused sync, rst_n shared reset | 1-2 |

Both found the core bug (hash_done). The LLM additionally found:
- `fsm_err_o` unsynchronized crossing — **real bug** (the one documented in PR#19202)
- `token_hash_req` unused synchronizer — **real observation** (req_sync2 is never read)
- `rst_n` shared across domains — **debatable FP** (common practice, depends on reset architecture)

crux missed `fsm_err_o` because it's an `assign` from combinational logic to a module output — crux only traces crossings between FFs within the flattened module, not at port boundaries.

## Design B3: Real OpenTitan prim_count (lowRISC/opentitan#24125)

| Tool | True bug found | Additional findings | FP |
|------|---------------|--------------------|----|
| crux | cnt_err COMBO_BEFORE_SYNC | — | 0 |
| LLM | cnt_err COMBO_BEFORE_SYNC | rst_n shared reset | 0-1 |

Both found the bug. LLM additionally noted shared reset (same as B1).

## Summary

| Metric | crux | LLM (Opus 4.6) |
|--------|------|-----------------|
| True bugs found (SoC-A, 4 bugs) | 4/4 | 4/4 |
| False positives (SoC-A) | 0 | 3 |
| Precision (SoC-A) | 1.00 | 0.57 |
| Recall (SoC-A) | 1.00 | 1.00 |
| Real OT bugs found (B1+B3) | 2/2 | 2/2 |
| Additional real issues found | 0 | 2 (fsm_err_o, unused sync) |
| Runtime | ~70ms | ~90s |
| Deterministic | Yes | No |

## Key Observations

1. **LLM has perfect recall but lower precision.** It found all real bugs but
   also flagged 3 false positives on module input ports. This is because LLMs
   reason about signal names and comments, not about the actual FF-level
   netlist graph. Module inputs don't have a clock domain until sampled by a FF.

2. **crux has perfect precision but misses port-level crossings.** It correctly
   identifies all FF-to-FF CDC violations but doesn't flag `fsm_err_o` (an assign
   from combinational logic to a module output port consumed in another domain).

3. **LLM finds real issues crux misses** (fsm_err_o, unused synchronizer). These
   are RTL-level semantic observations that require understanding design intent,
   not just structural graph traversal.

4. **crux is 1000x faster and deterministic.** For CI/CD integration and
   large designs, this matters more than the LLM's ability to find edge cases.

5. **The tools are complementary.** crux for fast, precise, scalable structural
   analysis. LLM for review of crux findings, explanation, and catching
   semantic issues crux cannot see.
