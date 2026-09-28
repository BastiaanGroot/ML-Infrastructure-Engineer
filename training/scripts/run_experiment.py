#!/usr/bin/env python3
"""Thin launch script: run one Qwen3 Megatron-Bridge pretrain recipe under
torchrun and log throughput/memory/MFU to MLflow.

Why this exists: the Megatron-Bridge version shipped in nvcr.io/nvidia/nemo
(0.1.0rc4) predates both its generic `run_recipe.py` CLI launcher and its
native MLflow LoggerConfig integration (both added upstream since) - so we
call the model's pretrain_config() recipe function directly and log the
handful of metrics we care about ourselves. See ../README.md.

Covers all distributed/hardware knobs used across ../k8s/experiment-*.yaml:
TP/PP/CP/EP parallelism degrees, --precision (bf16 vs FP8 mixed-precision
recipes), --attention-backend (flash/fused/unfused/local/auto), and
--cpu-offload (activation CPU offloading). All confirmed against the pinned
Megatron-Bridge 0.1.0rc4 API via a debug pod - see git history for details.

Usage (invoked by torchrun from the K8s Pod manifests in ../k8s/):
    torchrun --nnodes=2 --nproc-per-node=1 --node-rank=$NODE_RANK \
        --master-addr=$MASTER_ADDR --master-port=$MASTER_PORT \
        run_experiment.py --model qwen3-1p7b --tensor-parallelism 1 \
        --train-iters 20 --global-batch-size 4 --micro-batch-size 2 \
        --approx-num-params 1.7e9 --mlflow-run-name dp-baseline-qwen3-1p7b
"""

import argparse
import os
import re
import time

import torch

from megatron.bridge.training.gpt_step import forward_step
from megatron.bridge.training.pretrain import pretrain
from megatron.bridge.training.utils import train_utils

STEP_LINE = re.compile(r"Step Time : ([\d.]+)s GPU utilization: ([\d.]+)TFLOP/s/GPU")


def capture_step_logs() -> list[tuple[float, float]]:
    """Record (step_time_sec, tflops_per_gpu) for every training iteration.

    Megatron-Bridge 0.1.0rc4 has no callback for its per-iteration timing;
    it only prints it via train_utils.print_rank_0 (rank 0, every
    log_interval iterations). Wrapping that one function captures exactly the
    numbers shown in the pod logs.
    """
    steps: list[tuple[float, float]] = []
    original = train_utils.print_rank_0

    def print_and_capture(message, *args, **kwargs):
        match = STEP_LINE.search(str(message))
        if match:
            steps.append((float(match.group(1)), float(match.group(2))))
        return original(message, *args, **kwargs)

    train_utils.print_rank_0 = print_and_capture
    return steps

# H200 SXM tensor-core peaks per NVIDIA's datasheet - used only as the
# denominator for the approximate MFU estimate below. FP8 dense peak is ~2x
# bf16 on Hopper, so we pick the right one based on --precision.
H200_BF16_PEAK_FLOPS_PER_GPU = 989e12
H200_FP8_PEAK_FLOPS_PER_GPU = 1979e12

# module path, HF id, is_moe (whether the recipe's pretrain_config() accepts
# expert_parallelism - true only for the qwen3_*_a3b sparse/MoE recipes).
MODEL_RECIPES = {
    "qwen3-1p7b": ("megatron.bridge.recipes.qwen.qwen3_1p7b", "Qwen/Qwen3-1.7B", False),
    "qwen3-4b": ("megatron.bridge.recipes.qwen.qwen3_4b", "Qwen/Qwen3-4B", False),
    "qwen3-30b-a3b": ("megatron.bridge.recipes.qwen.qwen3_30b_a3b", "Qwen/Qwen3-30B-A3B", True),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=sorted(MODEL_RECIPES))
    parser.add_argument("--tensor-parallelism", type=int, default=1)
    parser.add_argument("--pipeline-parallelism", type=int, default=1)
    parser.add_argument("--context-parallelism", type=int, default=1)
    parser.add_argument(
        "--expert-parallelism",
        type=int,
        default=1,
        help="Only valid for MoE recipes (e.g. qwen3-30b-a3b); ignored otherwise.",
    )
    parser.add_argument("--train-iters", type=int, default=20)
    parser.add_argument("--global-batch-size", type=int, default=4)
    parser.add_argument("--micro-batch-size", type=int, default=2)
    parser.add_argument("--seq-length", type=int, default=4096)
    parser.add_argument(
        "--precision",
        default="bf16_mixed",
        help="Name of a megatron.bridge.training.mixed_precision recipe, e.g. "
        "bf16_mixed (default) or bf16_with_fp8_current_scaling_mixed.",
    )
    parser.add_argument(
        "--attention-backend",
        choices=["flash", "fused", "unfused", "local", "auto"],
        default=None,
        help="Overrides the recipe's default megatron.core.transformer.enums.AttnBackend.",
    )
    parser.add_argument(
        "--cpu-offload",
        action="store_true",
        help="Enable activation CPU offloading (model.cpu_offloading*) for all layers.",
    )
    parser.add_argument(
        "--approx-num-params",
        type=float,
        required=True,
        help="Labeled model size (e.g. 1.7e9) used for the approximate MFU estimate "
        "- not a profiler-measured FLOP count, see README's Results section caveat.",
    )
    parser.add_argument("--mlflow-experiment", default="qwen3-parallelism-experiments")
    parser.add_argument("--mlflow-run-name", required=True)
    parser.add_argument(
        "--run-kind",
        choices=["experiment", "profile"],
        default="experiment",
        help="MLflow run_kind tag. The dashboard hides 'profile' runs (e.g. "
        "under nsys, which adds overhead) from the strategy comparison.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    module_name, _hf_model_id, is_moe = MODEL_RECIPES[args.model]
    recipes = __import__(module_name, fromlist=["pretrain_config"])

    recipe_kwargs = dict(
        mock=True,
        tensor_parallelism=args.tensor_parallelism,
        pipeline_parallelism=args.pipeline_parallelism,
        context_parallelism=args.context_parallelism,
        train_iters=args.train_iters,
        global_batch_size=args.global_batch_size,
        micro_batch_size=args.micro_batch_size,
        seq_length=args.seq_length,
        precision_config=args.precision,
        # This is a short mechanism/throughput demo (mock data, no real
        # convergence goal) - skip the recipe's default 500-iter LR warmup,
        # which would otherwise violate `lr_warmup_steps < lr_decay_steps`
        # once train_iters is this small.
        lr_warmup_iters=0,
    )
    if is_moe:
        recipe_kwargs["expert_parallelism"] = args.expert_parallelism
    # Sequence parallelism requires tensor_parallelism > 1 (Megatron-Core
    # asserts otherwise), but the qwen3_30b_a3b MoE recipe defaults it to True
    # regardless. Only force it off at TP=1; at TP>1 keep each recipe's own
    # default (False for qwen3_1p7b) so experiment-02's documented config holds.
    if args.tensor_parallelism == 1:
        recipe_kwargs["sequence_parallelism"] = False
    cfg = recipes.pretrain_config(**recipe_kwargs)

    # Attention backend and CPU offloading aren't pretrain_config() kwargs in
    # this pinned Megatron-Bridge version - apply them post-hoc on the model
    # config, same object the recipe already built.
    if args.attention_backend is not None:
        from megatron.core.transformer.enums import AttnBackend

        cfg.model.attention_backend = AttnBackend[args.attention_backend]
    if args.cpu_offload:
        cfg.model.cpu_offloading = True
        cfg.model.cpu_offloading_activations = True
        # Megatron-Core requires cpu_offloading_num_layers < num_layers
        # (strictly less, not <=) - offload all-but-one layer's activations.
        cfg.model.cpu_offloading_num_layers = cfg.model.num_layers - 1

    # No persistent storage mounted for this mock/demo run - checkpointing to
    # local ephemeral storage only, and never triggers within train_iters.
    cfg.logger.log_throughput = True
    cfg.logger.log_interval = 1

    steps = capture_step_logs()
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
    peak_flops_per_gpu = H200_FP8_PEAK_FLOPS_PER_GPU if "fp8" in args.precision else H200_BF16_PEAK_FLOPS_PER_GPU
    mfu = achieved_flops_per_sec / (world_size * peak_flops_per_gpu)

    metrics = {
        "wall_time_sec": elapsed_sec,
        "step_time_sec": step_time_sec,
        "tokens_per_sec": tokens_per_sec,
        "tokens_per_sec_per_gpu": tokens_per_sec_per_gpu,
        "peak_gpu_memory_gb": peak_mem_gb,
        "approx_mfu_pct": mfu * 100,
    }
    # Iteration 1 includes kernel warmup/compilation - the README's
    # steady-state tables average iterations 2..N, and so does this.
    steady = steps[1:]
    if steady:
        metrics["steady_step_time_sec"] = sum(s for s, _ in steady) / len(steady)
        metrics["steady_tflops_per_gpu"] = sum(t for _, t in steady) / len(steady)
    params = {
        "model": args.model,
        "tensor_parallelism": args.tensor_parallelism,
        "pipeline_parallelism": args.pipeline_parallelism,
        "context_parallelism": args.context_parallelism,
        "expert_parallelism": args.expert_parallelism if is_moe else 1,
        "data_parallelism": world_size
        // (args.tensor_parallelism * args.pipeline_parallelism * args.context_parallelism),
        "world_size": world_size,
        "train_iters": args.train_iters,
        "global_batch_size": args.global_batch_size,
        "micro_batch_size": args.micro_batch_size,
        "seq_length": args.seq_length,
        "precision": args.precision,
        "attention_backend": args.attention_backend or "default",
        "cpu_offload": args.cpu_offload,
        "approx_num_params": args.approx_num_params,
    }

    print(f"=== Results: {metrics} ===")
    import mlflow  # Installed at container startup - see ../k8s/*.yaml.

    mlflow.set_experiment(args.mlflow_experiment)
    with mlflow.start_run(run_name=args.mlflow_run_name):
        mlflow.set_tags({"run_kind": args.run_kind})
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        for iteration, (step_time, tflops) in enumerate(steps, start=1):
            mlflow.log_metric("iter_step_time_sec", step_time, step=iteration)
            mlflow.log_metric("iter_tflops_per_gpu", tflops, step=iteration)


if __name__ == "__main__":
    main()
