#!/usr/bin/env python3
"""Uploads the cluster-validator summary.json to Nebius Object Storage
(S3-compatible), if UPLOAD_LOGS_BUCKET is set. Called from run.sh at the end
of a run. Deliberately non-fatal on failure - see upload_logs.sh, which logs
a warning but doesn't change the overall validation exit code.

Env vars:
  UPLOAD_LOGS_BUCKET    - target bucket name (required; if unset, run.sh never calls this).
  UPLOAD_LOGS_ENDPOINT  - S3-compatible endpoint (default: https://storage.eu-north1.nebius.cloud).
  UPLOAD_LOGS_PREFIX    - object key prefix (default: "cluster-validator").
  RESULTS_DIR           - where summary.json lives (default: /results).
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY - Nebius IAM static access key with
      write access to the bucket. See cluster-validator/README.md for how to
      create one and wire it in as a Kubernetes Secret.
"""
import datetime
import os
import socket
import sys


def main():
    bucket = os.environ.get("UPLOAD_LOGS_BUCKET")
    if not bucket:
        return 0

    try:
        import boto3
    except ImportError as e:
        print(f"[upload_logs] skipping upload: boto3 not available ({e})")
        return 1

    endpoint = os.environ.get("UPLOAD_LOGS_ENDPOINT", "https://storage.eu-north1.nebius.cloud")
    prefix = os.environ.get("UPLOAD_LOGS_PREFIX", "cluster-validator")
    results_dir = os.environ.get("RESULTS_DIR", "/results")
    summary_path = os.path.join(results_dir, "summary.json")

    if not os.path.isfile(summary_path):
        print(f"[upload_logs] skipping upload: {summary_path} not found")
        return 1

    timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    key = f"{prefix}/{socket.gethostname()}/{timestamp}/summary.json"

    try:
        client = boto3.client("s3", endpoint_url=endpoint)
        client.upload_file(summary_path, bucket, key)
    except Exception as e:
        print(f"[upload_logs] upload failed: {e}")
        return 1

    print(f"[upload_logs] uploaded {summary_path} to s3://{bucket}/{key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
