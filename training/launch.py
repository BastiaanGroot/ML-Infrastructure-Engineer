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
MLFLOW_TRACKING_URI = "https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud"

Q1P7B = "--model qwen3-1p7b --approx-num-params 1.7e9 --micro-batch-size 2 --global-batch-size 32"
Q8B = "--model qwen3-8b --approx-num-params 8.2e9 --micro-batch-size 1 --global-batch-size 64"
Q8B_BASE = f"{Q8B} --tensor-parallelism 2"
Q8B_LONG = "--model qwen3-8b --approx-num-params 8.2e9 --micro-batch-size 1 --global-batch-size 32 --seq-length 16384 --tensor-parallelism 2"
# Active (not total) params: 6ND FLOPs only count the experts a token visits.
Q30B_A3B = "--model qwen3-30b-a3b --approx-num-params 3.3e9 --micro-batch-size 1 --global-batch-size 64"
Q32B = "--model qwen3-32b --approx-num-params 32.8e9 --micro-batch-size 1 --global-batch-size 64"

# name -> (options, script, args). Options: nodes (default 2), nproc (GPUs per
# node, default 8), profile (wrap node rank 0 in nsys).
EXPERIMENTS = {
    # NCCL all_reduce bandwidth: NVLink within a node, 16 GPUs over
    # InfiniBand, and 1 GPU per node (directly comparable to the old
    # Ethernet cluster's 2-GPU sweep).
    "nccl-8gpu-nvlink": ({"nodes": 1}, "nccl_bandwidth_sweep.py", ""),
    "nccl-16gpu-ib": ({}, "nccl_bandwidth_sweep.py", ""),
    "nccl-2gpu-ib": ({"nproc": 1}, "nccl_bandwidth_sweep.py", ""),
    # Qwen3-1.7B: same model as the earlier 2-GPU runs, now at 16 GPUs.
    "q1p7b-dp16": ({}, "run_experiment.py", Q1P7B),
    "q1p7b-tp2-dp8": ({}, "run_experiment.py", f"{Q1P7B} --tensor-parallelism 2"),
    "q1p7b-pp2-dp8": ({}, "run_experiment.py", f"{Q1P7B} --pipeline-parallelism 2"),
    # Qwen3-8B single-variable suite around a TP2 x DP8 baseline.
    "q8b-baseline": ({}, "run_experiment.py", Q8B_BASE),
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
}


def kubectl(*args, stdin=None):
    return subprocess.run(["kubectl", *args], input=stdin, text=True, check=True, capture_output=True).stdout


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
        "NCCL_DEBUG": os.environ.get("NCCL_DEBUG", "WARN"),
        "MLFLOW_TRACKING_URI": MLFLOW_TRACKING_URI,
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
