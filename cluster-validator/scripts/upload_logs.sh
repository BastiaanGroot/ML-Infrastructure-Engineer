#!/bin/bash
# Uploads summary.json to Nebius Object Storage if UPLOAD_LOGS_BUCKET is set.
# Called from run.sh at the end of a run - non-fatal by design, see there.
#
# Env vars: see upload_logs.py.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/common.sh"

if ! command -v python3 >/dev/null 2>&1; then
    log "[upload_logs] python3 not found in container, skipping upload"
    exit 1
fi

python3 "$DIR/upload_logs.py"
