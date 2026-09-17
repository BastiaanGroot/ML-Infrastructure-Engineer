#!/usr/bin/env python3
"""Thin launch script: run one Qwen3 Megatron-Bridge pretrain recipe under
torchrun and log throughput/memory/MFU to MLflow.

Why this exists: the Megatron-Bridge version shipped in nvcr.io/nvidia/nemo
(0.1.0rc4) predates both its generic `run_recipe.py` CLI launcher and its
native MLflow LoggerConfig integration (both added upstream since) - so we
call the model's pretrain_config() recipe function directly and log the
handful of metrics we care about ourselves. See ../README.md.

Usage (invoked by torchrun from the K8s Pod manifests in ../k8s/):
    torchrun --nnodes=2 --nproc-per-node=1 --node-rank=$NODE_RANK \
        --master-addr=$MASTER_ADDR --master-port=$MASTER_PORT \
        run_experiment.py --model qwen3-1p7b --tensor-parallelism 1 \
        --train-iters 20 --global-batch-size 4 --micro-batch-size 2 \
        --approx-num-params 1.7e9 --mlflow-run-name dp-baseline-qwen3-1p7b
"""

import argparse
import os
import time

import torch

from megatron.bridge.training.gpt_step import forward_step
from megatron.bridge.training.pretrain import pretrain

# H200 SXM bf16 (dense, non-sparse) tensor-core peak per NVIDIA's datasheet -
# used only as the denominator for the approximate MFU estimate below.
H200_BF16_PEAK_FLOPS_PER_GPU = 989e12

MODEL_RECIPES = {
    "qwen3-1p7b": ("megatron.bridge.recipes.qwen.qwen3_1p7b", "Qwen/Qwen3-1.7B"),
    "qwen3-4b": ("megatron.bridge.recipes.qwen.qwen3_4b", "Qwen/Qwen3-4B"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=sorted(MODEL_RECIPES))
    parser.add_argument("--tensor-parallelism", type=int, default=1)
    parser.add_argument("--pipeline-parallelism", type=int, default=1)
    parser.add_argument("--train-iters", type=int, default=20)
    parser.add_argument("--global-batch-size", type=int, default=4)
    parser.add_argument("--micro-batch-size", type=int, default=2)
    parser.add_argument("--seq-length", type=int, default=4096)
    parser.add_argument(
        "--approx-num-params",
        type=float,
        required=True,
        help="Labeled model size (e.g. 1.7e9) used for the approximate MFU estimate "
        "- not a profiler-measured FLOP count, see README's Results section caveat.",
    )
    parser.add_argument("--mlflow-experiment", default="qwen3-parallelism-experiments")
    parser.add_argument("--mlflow-run-name", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    module_name, _hf_model_id = MODEL_RECIPES[args.model]
    recipes = __import__(module_name, fromlist=["pretrain_config"])

    cfg = recipes.pretrain_config(
        mock=True,
        tensor_parallelism=args.tensor_parallelism,
        pipeline_parallelism=args.pipeline_parallelism,
        train_iters=args.train_iters,
        global_batch_size=args.global_batch_size,
        micro_batch_size=args.micro_batch_size,
        seq_length=args.seq_length,
        # This is a short mechanism/throughput demo (mock data, no real
        # convergence goal) - skip the recipe's default 500-iter LR warmup,
        # which would otherwise violate `lr_warmup_steps < lr_decay_steps`
        # once train_iters is this small.
        lr_warmup_iters=0,
    )
    # No persistent storage mounted for this mock/demo run - checkpointing to
    # local ephemeral storage only, and never triggers within train_iters.
    cfg.logger.log_throughput = True
    cfg.logger.log_interval = 1

    torch.cuda.reset_peak_memory_stats()
    start = time.monotonic()
    pretrain(cfg, forward_step)
    elapsed_sec = time.monotonic() - start

    rank = int(os.environ.get("RANK", "0"))
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    if rank != 0:
        return  # Only rank 0 writes results - avoid duplicate MLflow runs.

    peak_mem_gb = torch.cuda.max_memory_allocated() / 1e9
    tokens_per_iter = args.global_batch_size * args.seq_length
    total_tokens = tokens_per_iter * args.train_iters
    tokens_per_sec = total_tokens / elapsed_sec
    tokens_per_sec_per_gpu = tokens_per_sec / world_size
    step_time_sec = elapsed_sec / args.train_iters

    # Standard 6ND approximation (forward+backward FLOPs per token = 6 x
    # param count) for achieved FLOPs/sec, divided by (world_size x per-GPU
    # peak) for MFU. Approximate - see --approx-num-params help above.
    achieved_flops_per_sec = 6 * args.approx_num_params * total_tokens / elapsed_sec
    mfu = achieved_flops_per_sec / (world_size * H200_BF16_PEAK_FLOPS_PER_GPU)

    metrics = {
        "wall_time_sec": elapsed_sec,
        "step_time_sec": step_time_sec,
        "tokens_per_sec": tokens_per_sec,
        "tokens_per_sec_per_gpu": tokens_per_sec_per_gpu,
        "peak_gpu_memory_gb": peak_mem_gb,
        "approx_mfu_pct": mfu * 100,
    }
    params = {
        "model": args.model,
        "tensor_parallelism": args.tensor_parallelism,
        "pipeline_parallelism": args.pipeline_parallelism,
        "data_parallelism": world_size // (args.tensor_parallelism * args.pipeline_parallelism),
        "world_size": world_size,
        "train_iters": args.train_iters,
        "global_batch_size": args.global_batch_size,
        "micro_batch_size": args.micro_batch_size,
        "seq_length": args.seq_length,
        "approx_num_params": args.approx_num_params,
    }

    print(f"=== Results: {metrics} ===")
    import mlflow  # Installed at container startup - see ../k8s/*.yaml.

    mlflow.set_experiment(args.mlflow_experiment)
    with mlflow.start_run(run_name=args.mlflow_run_name):
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)


if __name__ == "__main__":
    main()
