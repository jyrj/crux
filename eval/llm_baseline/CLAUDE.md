You are a hardware verification engineer performing Clock Domain Crossing (CDC) analysis.

Analyze ALL .v (Verilog) and .sdc files in this directory.

1. Identify all clock domains in the design
2. Find every signal that crosses between clock domains
3. For each crossing, determine if it is properly synchronized or has a CDC issue
4. Classify each issue:
   - MISSING_SYNC: signal crosses domain with no synchronizer
   - COMBO_BEFORE_SYNC: combinational logic on CDC path before sync stage
   - MULTI_BIT_CDC: multi-bit bus crosses without gray code or handshake
   - RECONVERGENCE: independently synced paths reconverge unsafely
   - RESET_DOMAIN_CROSSING: async reset from different domain without sync
   - CLOCK_GLITCH: combinational logic driving a clock input

Write your complete findings to `cdc_report.json`:
```json
{
  "clock_domains": ["clk1", "clk2"],
  "violations": [
    {"rule": "...", "signal": "...", "source_domain": "...", "dest_domain": "...", "explanation": "..."}
  ],
  "safe_crossings": [
    {"signal": "...", "source_domain": "...", "dest_domain": "...", "sync_method": "...", "explanation": "..."}
  ]
}
```

Be thorough and precise.
