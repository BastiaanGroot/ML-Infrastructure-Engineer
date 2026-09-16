#!/bin/bash
# Entrypoint: runs the enabled checks and prints/writes an aggregate summary.
#
# Env vars (all default to true/enabled):
#   RUN_GPU_HEALTH, RUN_NCCL, RUN_LLM_SMOKETEST, RUN_STORAGE  - set to "false" to skip a check.
#   RESULTS_DIR                                               - where per-check JSON is written (default: /results).
#   UPLOAD_LOGS_BUCKET                                        - if set, uploads summary.json to this Object Storage bucket.
#
# Exit code: 0 if all enabled checks passed, 1 otherwise.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/common.sh"

log "=== Nebius cluster-validator ==="
log "Node: $(hostname)"
log "Results dir: $RESULTS_DIR"

OVERALL_STATUS=0

run_check() {
    local script="$1" enabled="$2"
    if [[ "$enabled" == "false" ]]; then
        log "Skipping $script (disabled)"
        return
    fi
    "$DIR/$script" || OVERALL_STATUS=1
}

run_check "gpu_health.sh"     "${RUN_GPU_HEALTH:-true}"
run_check "nccl_bench.sh"     "${RUN_NCCL:-true}"
run_check "llm_smoketest.sh"  "${RUN_LLM_SMOKETEST:-true}"
run_check "storage_bench.sh"  "${RUN_STORAGE:-true}"

log "=== Summary ==="
SUMMARY="[]"
for f in "$RESULTS_DIR"/*.json; do
    [[ -e "$f" ]] || continue
    SUMMARY=$(echo "$SUMMARY" | jq --slurpfile r "$f" '. + $r')
done
echo "$SUMMARY" | jq -c '.[] | "\(.name): \(.status | ascii_upcase) — \(.message)"' | sed 's/^"//;s/"$//'
echo "$SUMMARY" > "$RESULTS_DIR/summary.json"
log "Full summary written to $RESULTS_DIR/summary.json"

if [[ -n "${UPLOAD_LOGS_BUCKET:-}" ]]; then
    "$DIR/upload_logs.sh" || log "WARNING: log upload to object storage failed (non-fatal)"
fi

if [[ "$OVERALL_STATUS" -eq 0 ]]; then
    log "RESULT: ALL CHECKS PASSED"
else
    log "RESULT: ONE OR MORE CHECKS FAILED"
fi

exit "$OVERALL_STATUS"
