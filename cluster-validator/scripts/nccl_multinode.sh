#!/bin/bash
# Cross-node NCCL all_reduce over InfiniBand: one all_reduce_perf process per
# GPU across all nodes, launched by mpirun over SSH from pod 0. Run by
# k8s/job-validate-multinode.yaml (an Indexed Job, one pod per node), not by
# run.sh. Every pod starts sshd; pod 0 waits for the others, runs the test,
# then tells them to exit.
#
# Env vars:
#   JOB_COMPLETION_INDEX           - set by Kubernetes; 0 is the launcher.
#   NNODES                         - number of pods/nodes (default: 2).
#   GPUS_PER_NODE                  - processes per node (default: 8).
#   PEER_HOST_PATTERN              - DNS name of pod i, with {i} replaced by the index.
#   NCCL_MULTINODE_ARGS            - all_reduce_perf args (default: "-b 512M -e 8G -f 2 -g 1").
#   NCCL_MULTINODE_MIN_BUSBW_GBPS  - minimum average bus bandwidth (default: 300).
#   SSH_KEY_DIR                    - mounted Secret with id_ed25519 / id_ed25519.pub.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/common.sh"

NAME="nccl_multinode"
INDEX="${JOB_COMPLETION_INDEX:-0}"
NNODES="${NNODES:-2}"
GPUS_PER_NODE="${GPUS_PER_NODE:-8}"
ARGS="${NCCL_MULTINODE_ARGS:--b 512M -e 8G -f 2 -g 1}"
MIN_BUSBW="${NCCL_MULTINODE_MIN_BUSBW_GBPS:-300}"
SSH_KEY_DIR="${SSH_KEY_DIR:-/etc/ssh-key}"
DONE_FILE=/tmp/nccl_multinode.done

# NCCL registers GPU memory with the IB NICs; the default 8 MB memlock limit
# is far too small. Needs a privileged container. sshd (and so every
# mpirun-launched process) inherits this.
ulimit -l unlimited

mkdir -p /root/.ssh /run/sshd
cp "$SSH_KEY_DIR/id_ed25519" /root/.ssh/id_ed25519
cp "$SSH_KEY_DIR/id_ed25519.pub" /root/.ssh/authorized_keys
chmod 600 /root/.ssh/id_ed25519 /root/.ssh/authorized_keys
printf 'Host *\n  Port 2222\n  StrictHostKeyChecking no\n  UserKnownHostsFile /dev/null\n  LogLevel ERROR\n' > /root/.ssh/config
# mpirun starts orted (under /opt/hpcx) over non-interactive SSH, which
# doesn't get the image's PATH/LD_LIBRARY_PATH otherwise.
printf 'PATH=%s\nLD_LIBRARY_PATH=%s\n' "$PATH" "${LD_LIBRARY_PATH:-}" > /root/.ssh/environment
ssh-keygen -A >/dev/null
/usr/sbin/sshd -p 2222 -o PermitUserEnvironment=yes

if [[ "$INDEX" != 0 ]]; then
    log "[$NAME] worker $INDEX: sshd up, waiting for the launcher"
    for _ in $(seq 1 720); do
        [[ -e "$DONE_FILE" ]] && exit 0
        sleep 5
    done
    log "[$NAME] worker $INDEX: launcher never finished"
    exit 1
fi

HOSTS=()
for i in $(seq 0 $((NNODES - 1))); do
    HOSTS+=("${PEER_HOST_PATTERN//\{i\}/$i}")
done
for host in "${HOSTS[@]:1}"; do
    log "Waiting for sshd on $host"
    for _ in $(seq 1 120); do
        ssh -o ConnectTimeout=5 "$host" true 2>/dev/null && break
        sleep 5
    done
done

HOSTLIST=$(printf '%s:'"$GPUS_PER_NODE"',' "${HOSTS[@]}")
NP=$((NNODES * GPUS_PER_NODE))
BIN="$(command -v all_reduce_perf 2>/dev/null)"
# MPI only bootstraps the processes (over TCP on eth0); NCCL moves the data over IB.
# Keep the full pod DNS names: the short ones don't resolve across pods.
CMD=(mpirun --allow-run-as-root -np "$NP" -H "${HOSTLIST%,}" --bind-to none
     -mca orte_keep_fqdn_hostnames 1 -mca pml ob1 -mca btl tcp,self -mca btl_tcp_if_include eth0 -mca coll ^hcoll
     -x PATH -x LD_LIBRARY_PATH -x NCCL_IB_HCA=mlx5 -x NCCL_SOCKET_IFNAME=eth0
     -x NCCL_DEBUG=WARN "$BIN" $ARGS)

log "Running: ${CMD[*]}"
OUTPUT=$("${CMD[@]}" 2>&1)
RC=$?
echo "$OUTPUT"
for host in "${HOSTS[@]:1}"; do
    ssh "$host" touch "$DONE_FILE" || true
done

OOB="$(echo "$OUTPUT" | grep -oP 'Out of bounds values\s*:\s*\K[0-9]+' | tail -n1)"
AVG_BUSBW="$(echo "$OUTPUT" | grep -oP 'Avg bus bandwidth\s*:\s*\K[0-9.]+' | tail -n1)"

FAIL_REASONS=()
[[ "$RC" -ne 0 ]] && FAIL_REASONS+=("mpirun exited with code $RC")
[[ -z "$AVG_BUSBW" ]] && FAIL_REASONS+=("could not parse average bus bandwidth from output")
[[ -n "$OOB" && "$OOB" -ne 0 ]] && FAIL_REASONS+=("$OOB out-of-bounds values detected (data corruption)")
if [[ -n "$AVG_BUSBW" ]] && (( $(echo "$AVG_BUSBW < $MIN_BUSBW" | bc -l) )); then
    FAIL_REASONS+=("avg bus bandwidth ${AVG_BUSBW} GB/s below threshold ${MIN_BUSBW} GB/s")
fi

METRICS=$(jq -n \
    --argjson nnodes "$NNODES" \
    --argjson gpu_count "$NP" \
    --arg avg_busbw_gbps "${AVG_BUSBW:-null}" \
    --arg out_of_bounds "${OOB:-null}" \
    '{nnodes: $nnodes, gpu_count: $gpu_count, avg_busbw_gbps: ($avg_busbw_gbps | tonumber? // null), out_of_bounds: ($out_of_bounds | tonumber? // null)}')

if [[ ${#FAIL_REASONS[@]} -eq 0 ]]; then
    write_result "$NAME" "pass" "avg bus bandwidth ${AVG_BUSBW} GB/s across ${NP} GPU(s) on ${NNODES} nodes" "$METRICS"
    log "RESULT: ALL CHECKS PASSED"
    exit 0
else
    write_result "$NAME" "fail" "$(IFS='; '; echo "${FAIL_REASONS[*]}")" "$METRICS"
    log "RESULT: ONE OR MORE CHECKS FAILED"
    exit 1
fi
