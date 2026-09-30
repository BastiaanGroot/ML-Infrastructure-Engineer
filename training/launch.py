#!/usr/bin/env python3
"""Launch one experiment from the matrix below on the cluster.

    ./launch.py --list
    ./launch.py q8b-baseline
    kubectl logs -f job/q8b-baseline        # node rank 0
    kubectl delete job,svc q8b-baseline     # when done

Regenerates the qwen3-training-scripts ConfigMap from scripts/, renders
k8s/worker.yaml.tmpl (one torchrun worker pod per node) and applies it. The
MLflow run name is the experiment name.
"""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

Q1P7B = "--model qwen3-1p7b --micro-batch-size 2 --global-batch-size 32"
Q8B = "--model qwen3-8b --micro-batch-size 1 --global-batch-size 64"
Q8B_BASE = f"{Q8B} --tensor-parallelism 2"
Q8B_LONG = "--model qwen3-8b --micro-batch-size 1 --global-batch-size 32 --seq-length 16384 --tensor-parallelism 2"
Q30B_A3B = "--model qwen3-30b-a3b --micro-batch-size 1 --global-batch-size 64"
Q32B = "--model qwen3-32b --micro-batch-size 1 --global-batch-size 64"
# Real FineWeb-Edu data (k8s/prepare-data.yaml): 1000 x 256 x 4096 = ~1B tokens.
E2E = (
    "--model qwen3-1p7b --micro-batch-size 2 --global-batch-size 256"
    " --train-iters 1000 --lr-warmup-iters 50 --run-kind e2e"
    " --data-path /mnt/shared-fs/data/fineweb-edu/fineweb-edu_text_document"
    " --checkpoint-dir /mnt/shared-fs/checkpoints/e2e-q1p7b --save-interval 250"
)

# name -> (options, script, args). Options: nodes (default 2), nproc (GPUs per
# node, default 8), profile (wrap node rank 0 in nsys), retries (Job
# backoffLimit, default 0).
EXPERIMENTS = {
    # NCCL all_reduce bandwidth: NVLink within a node, 16 GPUs over
    # InfiniBand, and one GPU per node (a single NIC).
    "nccl-8gpu-nvlink": ({"nodes": 1}, "nccl_bandwidth_sweep.py", ""),
    "nccl-16gpu-ib": ({}, "nccl_bandwidth_sweep.py", ""),
    "nccl-2gpu-ib": ({"nproc": 1}, "nccl_bandwidth_sweep.py", ""),
    # Qwen3-1.7B: DP vs TP vs PP at 16 GPUs.
    "q1p7b-dp16": ({}, "run_experiment.py", Q1P7B),
    "q1p7b-tp2-dp8": ({}, "run_experiment.py", f"{Q1P7B} --tensor-parallelism 2"),
    "q1p7b-pp2-dp8": ({}, "run_experiment.py", f"{Q1P7B} --pipeline-parallelism 2"),
    # Qwen3-8B single-variable suite around a TP2 x DP8 baseline.
    "q8b-baseline": ({}, "run_experiment.py", Q8B_BASE),
    # Same per-GPU work on one node (TP2 x DP4, half the global batch): the
    # scaling efficiency of adding the second node over InfiniBand.
    "q8b-baseline-1node": ({"nodes": 1}, "run_experiment.py",
                           Q8B_BASE.replace("--global-batch-size 64", "--global-batch-size 32")),
    "q8b-dp16": ({}, "run_experiment.py", Q8B),
    "q8b-dp16-recompute": ({}, "run_experiment.py", f"{Q8B} --recompute"),
    "q8b-tp4-dp4": ({}, "run_experiment.py", f"{Q8B} --tensor-parallelism 4"),
    "q8b-tp8-dp2": ({}, "run_experiment.py", f"{Q8B} --tensor-parallelism 8"),
    # TP8 on one node (NVLink) vs TP8 split 4+4 across both nodes (IB).
    # TP16 isn't possible: Qwen3-8B's 8 KV heads cap TP at 8.
    "q8b-tp8-1node": ({"nodes": 1}, "run_experiment.py", f"{Q8B} --tensor-parallelism 8"),
    "q8b-tp8-2nodes": ({"nproc": 4}, "run_experiment.py", f"{Q8B} --tensor-parallelism 8"),
    "q8b-pp2": ({}, "run_experiment.py", f"{Q8B_BASE} --pipeline-parallelism 2"),
    "q8b-seq16k-baseline": ({}, "run_experiment.py", Q8B_LONG),
    "q8b-seq16k-cp2": ({}, "run_experiment.py", f"{Q8B_LONG} --context-parallelism 2"),
    "q8b-seq16k-tp4": ({}, "run_experiment.py", Q8B_LONG.replace("--tensor-parallelism 2", "--tensor-parallelism 4")),
    "q8b-fp8": ({}, "run_experiment.py", f"{Q8B_BASE} --precision bf16_with_fp8_current_scaling_mixed"),
    "q8b-unfused-attn": ({}, "run_experiment.py", f"{Q8B_BASE} --attention-backend unfused"),
    "q8b-cpu-offload": ({}, "run_experiment.py", f"{Q8B_BASE} --cpu-offload"),
    # Expert parallelism on the MoE model: all-to-all within a node vs across IB.
    "q30b-a3b-ep8": ({}, "run_experiment.py", f"{Q30B_A3B} --expert-parallelism 8"),
    "q30b-a3b-ep16": ({}, "run_experiment.py", f"{Q30B_A3B} --expert-parallelism 16"),
    # Combined TP x PP x DP on a model that needs it to fit.
    "q32b-tp4-pp2-dp2": ({}, "run_experiment.py", f"{Q32B} --tensor-parallelism 4 --pipeline-parallelism 2"),
    "q32b-tp8-pp2-dp1": ({}, "run_experiment.py", f"{Q32B} --tensor-parallelism 8 --pipeline-parallelism 2"),
    # Nsight Systems kernel breakdowns.
    "prof-q8b-baseline": ({"profile": True}, "run_experiment.py", Q8B_BASE),
    "prof-q8b-tp8-2nodes": ({"profile": True, "nproc": 4}, "run_experiment.py", f"{Q8B} --tensor-parallelism 8"),
    # End-to-end: real data, loss curve, checkpoints on the shared filesystem.
    # Re-launching after a failure resumes from the latest checkpoint.
    "e2e-q1p7b": ({"retries": 6}, "run_experiment.py", E2E),
    # Shorter copy with its own checkpoints to demo recovery without a
    # human: kill a pod mid-run and the Job's retries resume from the
    # latest checkpoint.
    "e2e-q1p7b-autoresume": ({"retries": 6}, "run_experiment.py",
                             E2E.replace("--train-iters 1000", "--train-iters 300")
                             .replace("--save-interval 250", "--save-interval 100")
                             .replace("checkpoints/e2e-q1p7b", "checkpoints/e2e-q1p7b-autoresume")),
}


def kubectl(*args, stdin=None):
    return subprocess.run(["kubectl", *args], input=stdin, text=True, check=True, capture_output=True).stdout


def mlflow_tracking_uri() -> str:
    """$MLFLOW_TRACKING_URI, else the endpoint of the MLflow that infra/ created."""
    if uri := os.environ.get("MLFLOW_TRACKING_URI"):
        return uri
    try:
        endpoint = subprocess.run(
            ["terraform", f"-chdir={HERE.parent / 'infra'}", "output", "-raw", "mlflow_tracking_endpoint"],
            text=True, check=True, capture_output=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        endpoint = ""
    if not endpoint:
        sys.exit("Set MLFLOW_TRACKING_URI, or apply infra/ so `terraform output mlflow_tracking_endpoint` works.")
    return f"https://{endpoint}"


def rdzv_args(name: str, options: dict) -> str:
    """torchrun rendezvous flags. Static (fixed node ranks) by default.

    Runs with retries use elastic c10d rendezvous instead: when the Job
    replaces a failed pod, the surviving pod's torchrun agent sees a node
    waiting to join, kills its workers (stuck in NCCL waiting on the dead
    peer) and restarts both nodes together, which then resume from the
    latest checkpoint. With static rendezvous the survivor instead hangs
    until NCCL's timeout, and each replacement pod fails against its stale
    store, burning the Job's retries.
    """
    if options.get("retries"):
        return (f'--rdzv-backend=c10d --rdzv-endpoint="$MASTER_ADDR:$MASTER_PORT" '
                f'--rdzv-id={name} --max-restarts=3')
    return '--node-rank="$NODE_RANK" --master-addr="$MASTER_ADDR" --master-port="$MASTER_PORT"'


def render(name: str) -> str:
    options, script, args = EXPERIMENTS[name]
    script_args = f"{args} --mlflow-run-name {name}".strip()
    if options.get("profile"):
        script_args += " --run-kind profile"
    values = {
        "NAME": name,
        "NNODES": str(options.get("nodes", 2)),
        "NPROC": str(options.get("nproc", 8)),
        "SCRIPT": script,
        "SCRIPT_ARGS": script_args,
        "PROFILE": "1" if options.get("profile") else "0",
        "BACKOFF_LIMIT": str(options.get("retries", 0)),
        "RDZV_ARGS": rdzv_args(name, options),
        "NCCL_DEBUG": os.environ.get("NCCL_DEBUG", "WARN"),
        "MLFLOW_TRACKING_URI": mlflow_tracking_uri(),
    }
    text = (HERE / "k8s" / "worker.yaml.tmpl").read_text()
    for key, value in values.items():
        text = text.replace("${" + key + "}", value)
    return text


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in [*EXPERIMENTS, "--list"]:
        sys.exit(f"usage: {sys.argv[0]} <name> | --list\nexperiments: {', '.join(EXPERIMENTS)}")
    if sys.argv[1] == "--list":
        print("\n".join(EXPERIMENTS))
        return
    configmap = kubectl("create", "configmap", "qwen3-training-scripts", f"--from-file={HERE / 'scripts'}",
                        "--dry-run=client", "-o", "yaml")
    print(kubectl("apply", "-f", "-", stdin=configmap), end="")
    print(kubectl("apply", "-f", "-", stdin=render(sys.argv[1])), end="")


if __name__ == "__main__":
    main()
