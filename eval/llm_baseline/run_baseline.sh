#!/bin/bash
# Run fully isolated Claude Code agent on CDC benchmark designs.
# Each run gets a fresh temp directory with ONLY the design files + CLAUDE.md.
# No crux code, no project context, no conversation history.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EVAL_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$SCRIPT_DIR/results"
mkdir -p "$RESULTS_DIR"

run_isolated_agent() {
    local bench_name="$1"
    local bench_dir="$2"
    local run_id="$3"

    echo "=== Running LLM baseline: $bench_name (run $run_id) ==="

    # Create isolated workspace
    local workspace=$(mktemp -d /tmp/crux_llm_eval_XXXXXX)

    # Copy ONLY design files (no crux code, no project files)
    cp "$bench_dir"/*.v "$workspace/" 2>/dev/null || true
    cp "$bench_dir"/*.sdc "$workspace/" 2>/dev/null || true
    cp "$SCRIPT_DIR/CLAUDE.md" "$workspace/"

    echo "Workspace: $workspace"
    echo "Files:"
    ls -la "$workspace"

    # Run Claude Code agent in isolated workspace
    # --no-profile: don't load user profile
    # --max-turns 20: limit interaction
    # -p: non-interactive with prompt
    local start_time=$(date +%s%N)

    cd "$workspace"
    claude -p "Read all .v and .sdc files in this directory. Perform CDC analysis as described in CLAUDE.md. Write results to cdc_report.json." \
        --allowedTools "Read,Write,Glob,Grep,Bash" \
        --max-turns 30 \
        2>&1 | tee "$RESULTS_DIR/${bench_name}_run${run_id}_log.txt"

    local end_time=$(date +%s%N)
    local elapsed_ms=$(( (end_time - start_time) / 1000000 ))

    # Collect results
    if [ -f "$workspace/cdc_report.json" ]; then
        cp "$workspace/cdc_report.json" "$RESULTS_DIR/${bench_name}_run${run_id}.json"
        echo "Results saved to ${bench_name}_run${run_id}.json"
    else
        echo '{"error": "no cdc_report.json produced", "violations": [], "safe_crossings": []}' \
            > "$RESULTS_DIR/${bench_name}_run${run_id}.json"
        echo "WARNING: Agent did not produce cdc_report.json"
    fi

    echo "Runtime: ${elapsed_ms}ms"
    echo "{\"runtime_ms\": $elapsed_ms}" > "$RESULTS_DIR/${bench_name}_run${run_id}_meta.json"

    # Cleanup
    rm -rf "$workspace"
    echo ""
}

# Run on SoC-A (small benchmark)
SMALL_DIR="$EVAL_DIR/benchmarks/small"
if [ -f "$SMALL_DIR/crux_bench_small.v" ]; then
    for run in 1 2 3; do
        run_isolated_agent "small" "$SMALL_DIR" "$run"
    done
fi

# Run on SoC-B (large benchmark)
LARGE_DIR="$EVAL_DIR/benchmarks/large"
if [ -f "$LARGE_DIR/ot_aon_wrapper.v" ]; then
    for run in 1 2 3; do
        run_isolated_agent "large" "$LARGE_DIR" "$run"
    done
fi

echo "=== All baseline runs complete ==="
echo "Results in: $RESULTS_DIR/"
ls -la "$RESULTS_DIR/"
