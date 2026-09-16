#!/bin/bash
# NCCL / GPU-interconnect bandwidth check using the nccl-tests binaries
# already bundled in the base image (see Dockerfile).
#
# This checks single-node interconnect (NVLink/PCIe between local GPUs).
# For multi-node InfiniBand validation, launch this binary directly via an
# MPIJob instead of through this container's entrypoint - see
# k8s/job-nccl-multinode.yaml and the README for the pattern (matches
# https://docs.nebius.com/kubernetes/gpu/nccl-test).
#
# Env vars:
#   NCCL_BENCH_ARGS      - override args passed to all_reduce_perf.
#                          default: "-b 512M -e 8G -f 2 -g <local GPU count>"
#   NCCL_MIN_BUSBW_GBPS  - minimum acceptable average bus bandwidth (default: 100).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/common.sh"

NAME="nccl_bench"
NCCL_MIN_BUSBW_GBPS="${NCCL_MIN_BUSBW_GBPS:-100}"

BIN="$(command -v all_reduce_perf 2>/dev/null || find / -maxdepth 6 -type f -name all_reduce_perf 2>/dev/null | head -n1)"
if [[ -z "$BIN" ]]; then
    write_result "$NAME" "fail" "all_reduce_perf binary not found in image" '{}'
    exit 1
fi

GPU_COUNT="$(nvidia-smi -L 2>/dev/null | grep -c . || echo 1)"
ARGS="${NCCL_BENCH_ARGS:--b 512M -e 8G -f 2 -g $GPU_COUNT}"

log "Running: $BIN $ARGS"
if ! OUTPUT=$("$BIN" $ARGS 2>&1); then
    write_result "$NAME" "fail" "all_reduce_perf exited with an error" "$(jq -n --arg log "$OUTPUT" '{log: $log}')"
    exit 1
fi

OOB="$(echo "$OUTPUT" | grep -oP 'Out of bounds values\s*:\s*\K[0-9]+' | tail -n1)"
AVG_BUSBW="$(echo "$OUTPUT" | grep -oP 'Avg bus bandwidth\s*:\s*\K[0-9.]+' | tail -n1)"

FAIL_REASONS=()
[[ -z "$AVG_BUSBW" ]] && FAIL_REASONS+=("could not parse average bus bandwidth from output")
[[ -n "$OOB" && "$OOB" -ne 0 ]] && FAIL_REASONS+=("$OOB out-of-bounds values detected (data corruption)")
if [[ -n "$AVG_BUSBW" ]] && (( $(echo "$AVG_BUSBW < $NCCL_MIN_BUSBW_GBPS" | bc -l) )); then
    FAIL_REASONS+=("avg bus bandwidth ${AVG_BUSBW} GB/s below threshold ${NCCL_MIN_BUSBW_GBPS} GB/s")
fi

METRICS=$(jq -n \
    --argjson gpu_count "$GPU_COUNT" \
    --arg avg_busbw_gbps "${AVG_BUSBW:-null}" \
    --arg out_of_bounds "${OOB:-null}" \
    '{gpu_count: $gpu_count, avg_busbw_gbps: ($avg_busbw_gbps | tonumber? // null), out_of_bounds: ($out_of_bounds | tonumber? // null)}')

if [[ ${#FAIL_REASONS[@]} -eq 0 ]]; then
    write_result "$NAME" "pass" "avg bus bandwidth ${AVG_BUSBW} GB/s across ${GPU_COUNT} GPU(s)" "$METRICS"
    exit 0
else
    write_result "$NAME" "fail" "$(IFS='; '; echo "${FAIL_REASONS[*]}")" "$METRICS"
    exit 1
fi
