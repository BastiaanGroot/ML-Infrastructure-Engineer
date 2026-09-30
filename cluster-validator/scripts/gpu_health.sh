#!/bin/bash
# GPU health check: verifies GPUs are visible, driver responds, temperatures
# are sane, and there are no uncorrectable ECC errors or pending/failed row
# remaps. (Temperatures here are at idle; gpu_compute.py checks them under load.)
#
# Env vars:
#   EXPECTED_GPU_COUNT   - if set, fail when detected GPU count differs.
#   MAX_GPU_TEMP_C       - max acceptable GPU temperature (default: 85).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/common.sh"

MAX_GPU_TEMP_C="${MAX_GPU_TEMP_C:-85}"
NAME="gpu_health"

if ! command -v nvidia-smi >/dev/null 2>&1; then
    write_result "$NAME" "fail" "nvidia-smi not found in container" '{}'
    exit 1
fi

if ! SMI_CSV=$(nvidia-smi --query-gpu=index,name,driver_version,temperature.gpu,ecc.errors.uncorrected.volatile.total,ecc.errors.corrected.volatile.total --format=csv,noheader,nounits 2>&1); then
    write_result "$NAME" "fail" "nvidia-smi query failed: $SMI_CSV" '{}'
    exit 1
fi

GPU_COUNT=$(echo "$SMI_CSV" | grep -c . || true)
FAIL_REASONS=()

if [[ -n "${EXPECTED_GPU_COUNT:-}" && "$GPU_COUNT" -ne "$EXPECTED_GPU_COUNT" ]]; then
    FAIL_REASONS+=("expected $EXPECTED_GPU_COUNT GPUs, found $GPU_COUNT")
fi

MAX_TEMP_SEEN=0
TOTAL_UNCORRECTED=0
TOTAL_CORRECTED=0
while IFS=',' read -r idx name driver temp ecc_uncorr ecc_corr; do
    temp="$(echo "$temp" | xargs)"
    ecc_uncorr="$(echo "$ecc_uncorr" | xargs)"
    ecc_corr="$(echo "$ecc_corr" | xargs)"
    [[ "$temp" =~ ^[0-9]+$ ]] || temp=0
    [[ "$ecc_uncorr" =~ ^[0-9]+$ ]] || ecc_uncorr=0
    [[ "$ecc_corr" =~ ^[0-9]+$ ]] || ecc_corr=0
    (( temp > MAX_TEMP_SEEN )) && MAX_TEMP_SEEN=$temp
    (( TOTAL_UNCORRECTED += ecc_uncorr ))
    (( TOTAL_CORRECTED += ecc_corr ))
    if (( temp > MAX_GPU_TEMP_C )); then
        FAIL_REASONS+=("GPU $idx ($name) temperature ${temp}C exceeds ${MAX_GPU_TEMP_C}C")
    fi
    if (( ecc_uncorr > 0 )); then
        FAIL_REASONS+=("GPU $idx ($name) has $ecc_uncorr uncorrectable ECC errors")
    fi
done <<< "$SMI_CSV"

# Row remapping (Ampere+): a pending remap needs a GPU reset before it takes
# effect, and a failed remap means the GPU ran out of spare rows - both mean
# the GPU shouldn't take a job.
REMAP_CSV=$(nvidia-smi --query-remapped-rows=gpu_bus_id,remapped_rows.pending,remapped_rows.failure --format=csv,noheader 2>/dev/null || true)
REMAP_ISSUES=0
while IFS=',' read -r bus pending failure; do
    [[ -z "$bus" ]] && continue
    pending="$(echo "$pending" | xargs)"
    failure="$(echo "$failure" | xargs)"
    if [[ "$pending" == "Yes" || "$pending" == "1" ]]; then
        FAIL_REASONS+=("GPU $bus has a pending row remap (needs a GPU reset)")
        (( REMAP_ISSUES += 1 ))
    fi
    if [[ "$failure" == "Yes" || "$failure" == "1" ]]; then
        FAIL_REASONS+=("GPU $bus has a failed row remap")
        (( REMAP_ISSUES += 1 ))
    fi
done <<< "$REMAP_CSV"

# Corrected ECC errors don't fail the check (the hardware already recovered
# from them), but they're a genuine early-warning signal for degrading memory
# worth surfacing in the metrics/logs rather than silently discarding.
METRICS=$(jq -n \
    --argjson gpu_count "$GPU_COUNT" \
    --argjson max_temp_c "$MAX_TEMP_SEEN" \
    --argjson uncorrectable_ecc_errors "$TOTAL_UNCORRECTED" \
    --argjson corrected_ecc_errors "$TOTAL_CORRECTED" \
    --argjson row_remap_issues "$REMAP_ISSUES" \
    '{gpu_count: $gpu_count, max_temp_c: $max_temp_c, uncorrectable_ecc_errors: $uncorrectable_ecc_errors, corrected_ecc_errors: $corrected_ecc_errors, row_remap_issues: $row_remap_issues}')

if [[ ${#FAIL_REASONS[@]} -eq 0 ]]; then
    write_result "$NAME" "pass" "$GPU_COUNT GPU(s) healthy, max temp ${MAX_TEMP_SEEN}C" "$METRICS"
    exit 0
else
    write_result "$NAME" "fail" "$(IFS='; '; echo "${FAIL_REASONS[*]}")" "$METRICS"
    exit 1
fi
