#!/bin/bash
# Storage throughput check using fio, run against every mounted path that
# exists from STORAGE_PATHS (e.g. the network disk and the shared filesystem
# from the PoC capacity).
#
# Env vars:
#   STORAGE_PATHS         - comma-separated mount paths to test.
#                          default: "/mnt/network-disk,/mnt/shared-fs"
#   FIO_SIZE              - test file size per path (default: 1G).
#   FIO_RUNTIME           - seconds per fio job (default: 20).
#   FIO_MIN_THROUGHPUT_MBPS - optional minimum acceptable read+write throughput (MB/s).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/common.sh"

NAME="storage_bench"
STORAGE_PATHS="${STORAGE_PATHS:-/mnt/network-disk,/mnt/shared-fs}"
FIO_SIZE="${FIO_SIZE:-1G}"
FIO_RUNTIME="${FIO_RUNTIME:-20}"

if ! command -v fio >/dev/null 2>&1; then
    write_result "$NAME" "fail" "fio not found in container" '{}'
    exit 1
fi

IFS=',' read -ra PATHS <<< "$STORAGE_PATHS"
RESULTS_JSON="[]"
FAIL_REASONS=()
TESTED_ANY=0

for path in "${PATHS[@]}"; do
    path="$(echo "$path" | xargs)"
    if [[ ! -d "$path" || ! -w "$path" ]]; then
        log "Skipping $path: not mounted or not writable"
        continue
    fi
    TESTED_ANY=1
    testfile="$path/.cluster-validator-fio-test"
    log "Running fio against $path (size=$FIO_SIZE, runtime=${FIO_RUNTIME}s)"

    FIO_OUT=$(fio --name=cluster-validator \
        --filename="$testfile" \
        --directory="$path" \
        --size="$FIO_SIZE" \
        --time_based --runtime="$FIO_RUNTIME" \
        --rw=readwrite --rwmixread=50 \
        --bs=1M --direct=1 --ioengine=libaio --iodepth=16 \
        --output-format=json 2>&1)
    rm -f "$testfile" 2>/dev/null

    if ! echo "$FIO_OUT" | jq -e . >/dev/null 2>&1; then
        FAIL_REASONS+=("fio on $path did not produce valid JSON output")
        continue
    fi

    READ_BW_MBPS=$(echo "$FIO_OUT" | jq '(.jobs[0].read.bw // 0) / 1024')
    WRITE_BW_MBPS=$(echo "$FIO_OUT" | jq '(.jobs[0].write.bw // 0) / 1024')
    READ_IOPS=$(echo "$FIO_OUT" | jq '.jobs[0].read.iops // 0')
    WRITE_IOPS=$(echo "$FIO_OUT" | jq '.jobs[0].write.iops // 0')
    TOTAL_BW_MBPS=$(echo "$READ_BW_MBPS + $WRITE_BW_MBPS" | bc -l)

    if [[ -n "${FIO_MIN_THROUGHPUT_MBPS:-}" ]] && (( $(echo "$TOTAL_BW_MBPS < $FIO_MIN_THROUGHPUT_MBPS" | bc -l) )); then
        FAIL_REASONS+=("$path: throughput ${TOTAL_BW_MBPS} MB/s below threshold ${FIO_MIN_THROUGHPUT_MBPS} MB/s")
    fi

    RESULTS_JSON=$(echo "$RESULTS_JSON" | jq \
        --arg path "$path" \
        --argjson read_bw_mbps "$READ_BW_MBPS" \
        --argjson write_bw_mbps "$WRITE_BW_MBPS" \
        --argjson read_iops "$READ_IOPS" \
        --argjson write_iops "$WRITE_IOPS" \
        '. + [{path: $path, read_bw_mbps: $read_bw_mbps, write_bw_mbps: $write_bw_mbps, read_iops: $read_iops, write_iops: $write_iops}]')
done

if [[ "$TESTED_ANY" -eq 0 ]]; then
    write_result "$NAME" "fail" "no writable paths found among: $STORAGE_PATHS" '{}'
    exit 1
fi

METRICS=$(jq -n --argjson paths "$RESULTS_JSON" '{paths: $paths}')

if [[ ${#FAIL_REASONS[@]} -eq 0 ]]; then
    write_result "$NAME" "pass" "storage benchmark completed for: $(echo "$RESULTS_JSON" | jq -r '[.[].path] | join(", ")')" "$METRICS"
    exit 0
else
    write_result "$NAME" "fail" "$(IFS='; '; echo "${FAIL_REASONS[*]}")" "$METRICS"
    exit 1
fi
