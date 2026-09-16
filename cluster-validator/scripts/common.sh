#!/bin/bash
# Shared helpers for cluster-validator check scripts.

RESULTS_DIR="${RESULTS_DIR:-/results}"
mkdir -p "$RESULTS_DIR"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

# write_result <check_name> <status: pass|fail> <message> <metrics_json>
# metrics_json must be a valid JSON object string, e.g. '{"avg_busbw_gbps":312.4}'
write_result() {
    local name="$1" check_status="$2" message="$3" metrics="${4:-\{\}}"
    local file="$RESULTS_DIR/${name}.json"
    jq -n \
        --arg name "$name" \
        --arg status "$check_status" \
        --arg message "$message" \
        --argjson metrics "$metrics" \
        '{name: $name, status: $status, message: $message, metrics: $metrics}' \
        > "$file"
    log "[$name] $check_status: $message"
}
