#!/bin/bash
# LLM smoketest: validates the actual ML framework stack (CUDA <-> driver <->
# PyTorch <-> model loading) works end-to-end - see gpu_health.sh and
# nccl_bench.sh for raw GPU health / interconnect throughput, which this
# deliberately does not re-test. Loads a real, minimal Qwen3-0.6B checkpoint
# baked into the image (see Dockerfile - same model family as ../training/)
# and runs a short generate() (inference path) plus one forward+backward
# pass (training path) on GPU via llm_smoketest.py.
#
# Env vars: see llm_smoketest.py.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/common.sh"

NAME="llm_smoketest"

if ! command -v python3 >/dev/null 2>&1; then
    write_result "$NAME" "fail" "python3 not found in container" '{}'
    exit 1
fi

python3 "$DIR/llm_smoketest.py"
STATUS=$?

# llm_smoketest.py always writes its own result file, unless it crashed
# before it got the chance to (e.g. a hard interpreter error) - synthesize a
# fail result in that case so summary.json still reflects this check ran.
if [[ ! -f "$RESULTS_DIR/${NAME}.json" ]]; then
    write_result "$NAME" "fail" "llm_smoketest.py exited unexpectedly (code $STATUS) without writing a result" '{}'
fi

exit "$STATUS"
