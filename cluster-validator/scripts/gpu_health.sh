#!/bin/bash
# GPU health check: verifies GPUs are visible, driver responds, temperatures
# are sane, and there are no uncorrectable ECC errors.
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
while IFS=',' read -r idx name driver temp ecc_uncorr ecc_corr; do
    temp="$(echo "$temp" | xargs)"
    ecc_uncorr="$(echo "$ecc_uncorr" | xargs)"
    [[ "$temp" =~ ^[0-9]+$ ]] || temp=0
    [[ "$ecc_uncorr" =~ ^[0-9]+$ ]] || ecc_uncorr=0
    (( temp > MAX_TEMP_SEEN )) && MAX_TEMP_SEEN=$temp
    (( TOTAL_UNCORRECTED += ecc_uncorr ))
    if (( temp > MAX_GPU_TEMP_C )); then
        FAIL_REASONS+=("GPU $idx ($name) temperature ${temp}C exceeds ${MAX_GPU_TEMP_C}C")
    fi
    if (( ecc_uncorr > 0 )); then
        FAIL_REASONS+=("GPU $idx ($name) has $ecc_uncorr uncorrectable ECC errors")
    fi
done <<< "$SMI_CSV"

METRICS=$(jq -n \
    --argjson gpu_count "$GPU_COUNT" \
    --argjson max_temp_c "$MAX_TEMP_SEEN" \
    --argjson uncorrectable_ecc_errors "$TOTAL_UNCORRECTED" \
    '{gpu_count: $gpu_count, max_temp_c: $max_temp_c, uncorrectable_ecc_errors: $uncorrectable_ecc_errors}')

if [[ ${#FAIL_REASONS[@]} -eq 0 ]]; then
    write_result "$NAME" "pass" "$GPU_COUNT GPU(s) healthy, max temp ${MAX_TEMP_SEEN}C" "$METRICS"
    exit 0
else
    write_result "$NAME" "fail" "$(IFS='; '; echo "${FAIL_REASONS[*]}")" "$METRICS"
    exit 1
fi
