#!/usr/bin/env python3
"""Thin launch script: run one Qwen3 Megatron-Bridge pretrain recipe under
torchrun and log throughput/memory/MFU to MLflow. With --data-path it trains
on a real tokenized dataset instead of mock data, logs the loss live, and
(with --checkpoint-dir) saves and resumes checkpoints.

Why this exists: the Megatron-Bridge version shipped in nvcr.io/nvidia/nemo
(0.1.0rc4) predates both its generic `run_recipe.py` CLI launcher and its
native MLflow LoggerConfig integration (both added upstream since) - so we
call the model's pretrain_config() recipe function directly and log the
handful of metrics we care about ourselves. See ../README.md.

Covers all distributed/hardware knobs used in ../launch.py's matrix:
TP/PP/CP/EP parallelism degrees, --precision (bf16 vs FP8 mixed-precision
recipes), --attention-backend (flash/fused/unfused/local/auto),
--cpu-offload (activation CPU offloading) and --recompute (full activation
recomputation). All confirmed against the pinned Megatron-Bridge 0.1.0rc4
API via a debug pod - see git history for details.

Usage (invoked by torchrun from ../k8s/worker.yaml.tmpl via ../launch.py):
    torchrun --nnodes=2 --nproc-per-node=8 --node-rank=$NODE_RANK \
        --master-addr=$MASTER_ADDR --master-port=$MASTER_PORT \
        run_experiment.py --model qwen3-8b --tensor-parallelism 2 \
        --global-batch-size 64 --micro-batch-size 1 \
        --approx-num-params 8.2e9 --mlflow-run-name q8b-baseline
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
ITER_LINE = re.compile(
    r"iteration\s+(\d+)/\s*\d+ \|.*?elapsed time per iteration \(ms\): ([\d.]+) \|"
    r".*?throughput per GPU \(TFLOP/s/GPU\): ([\d.]+) \|.*?lm loss: ([\d.E+-]+) \|"
)


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


def log_iterations_live(mlflow) -> list[tuple[int, float, float, float]]:
    """Log loss, step time and TFLOP/s to the active MLflow run as each
    iteration finishes, and return (iteration, step_time_sec, tflops, loss).

    Megatron prints the per-iteration line (the one with the loss) on the
    last rank only, via train_utils.print_rank_last, so this runs there.
    Logging live keeps the loss curve of a run that gets killed midway.
    """
    iters: list[tuple[int, float, float, float]] = []
    original = train_utils.print_rank_last

    def print_and_log(message, *args, **kwargs):
        match = ITER_LINE.search(str(message))
        if match:
            iteration, step_ms, tflops, loss = int(match[1]), float(match[2]), float(match[3]), float(match[4])
            iters.append((iteration, step_ms / 1000, tflops, loss))
            mlflow.log_metrics(
                {"lm_loss": loss, "iter_step_time_sec": step_ms / 1000, "iter_tflops_per_gpu": tflops},
                step=iteration,
            )
        return original(message, *args, **kwargs)

    train_utils.print_rank_last = print_and_log
    return iters


def start_or_resume_run(mlflow, experiment: str, run_name: str, run_kind: str):
    """Resume the MLflow run with this name and run_kind if there is one, so
    a job restarted from a checkpoint keeps one continuous loss curve."""
    exp = mlflow.set_experiment(experiment)
    existing = mlflow.MlflowClient().search_runs(
        [exp.experiment_id],
        f"tags.mlflow.runName = '{run_name}' and tags.run_kind = '{run_kind}'",
        max_results=1,
    )
    if existing:
        return mlflow.start_run(run_id=existing[0].info.run_id)
    return mlflow.start_run(run_name=run_name)

# H100 SXM dense tensor-core peaks per NVIDIA's datasheet - used only as the
# denominator for the approximate MFU estimate below. FP8 dense peak is ~2x
# bf16 on Hopper, so we pick the right one based on --precision.
H100_BF16_PEAK_FLOPS_PER_GPU = 989e12
H100_FP8_PEAK_FLOPS_PER_GPU = 1979e12
CLUSTER_TAGS = {"cluster": "2x8-h100-ib", "gpu": "H100"}

# module path, HF id, is_moe (whether the recipe's pretrain_config() accepts
# expert_parallelism - true only for the qwen3_*_a3b sparse/MoE recipes).
MODEL_RECIPES = {
    "qwen3-1p7b": ("megatron.bridge.recipes.qwen.qwen3_1p7b", "Qwen/Qwen3-1.7B", False),
    "qwen3-8b": ("megatron.bridge.recipes.qwen.qwen3_8b", "Qwen/Qwen3-8B", False),
    "qwen3-32b": ("megatron.bridge.recipes.qwen.qwen3_32b", "Qwen/Qwen3-32B", False),
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
    parser.add_argument("--lr-warmup-iters", type=int, default=0)
    parser.add_argument(
        "--data-path",
        help="Megatron indexed dataset prefix (without .bin/.idx). Without it, "
        "the run uses synthetic (mock) data.",
    )
    parser.add_argument(
        "--checkpoint-dir",
        help="Save checkpoints here and resume from the latest one on restart. "
        "Without it, no checkpoints are written.",
    )
    parser.add_argument("--save-interval", type=int, default=250)
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
        "--recompute",
        action="store_true",
        help="Full activation recomputation for every layer (trades ~1/3 more compute for activation memory).",
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
        choices=["experiment", "profile", "e2e"],
        default="experiment",
        help="MLflow run_kind tag. The dashboard hides 'profile' runs (e.g. "
        "under nsys, which adds overhead) and 'e2e' runs (real data, "
        "checkpointing) from the strategy comparison by default.",
    )
    return parser.parse_args()


def run_params(args: argparse.Namespace, world_size: int) -> dict:
    return {
        "model": args.model,
        "tensor_parallelism": args.tensor_parallelism,
        "pipeline_parallelism": args.pipeline_parallelism,
        "context_parallelism": args.context_parallelism,
        "expert_parallelism": args.expert_parallelism if MODEL_RECIPES[args.model][2] else 1,
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
        "recompute": args.recompute,
        "approx_num_params": args.approx_num_params,
        "nnodes": world_size // int(os.environ["LOCAL_WORLD_SIZE"]),
        "gpus_per_node": int(os.environ["LOCAL_WORLD_SIZE"]),
    }


def log_live_summary(mlflow, args: argparse.Namespace, iters: list, world_size: int) -> None:
    """Steady-state averages for this job's segment of a real-data run (the
    first iteration after a start or resume includes warmup), then close the
    MLflow run. Re-logging identical params on resume is allowed."""
    mlflow.log_params({
        **run_params(args, world_size),
        "data_path": args.data_path,
        "checkpoint_dir": args.checkpoint_dir or "none",
        "save_interval": args.save_interval,
        "lr_warmup_iters": args.lr_warmup_iters,
    })
    steady = iters[1:]
    if steady:
        step_time = sum(s for _, s, _, _ in steady) / len(steady)
        tokens_per_sec_per_gpu = args.global_batch_size * args.seq_length / step_time / world_size
        peak_flops_per_gpu = H100_FP8_PEAK_FLOPS_PER_GPU if "fp8" in args.precision else H100_BF16_PEAK_FLOPS_PER_GPU
        metrics = {
            "steady_step_time_sec": step_time,
            "steady_tflops_per_gpu": sum(t for _, _, t, _ in steady) / len(steady),
            "tokens_per_sec_per_gpu": tokens_per_sec_per_gpu,
            "approx_mfu_pct": 100 * 6 * args.approx_num_params * tokens_per_sec_per_gpu / peak_flops_per_gpu,
            "peak_gpu_memory_gb": torch.cuda.max_memory_allocated() / 1e9,
            "final_lm_loss": iters[-1][3],
        }
        print(f"=== Results: {metrics} ===")
        mlflow.log_metrics(metrics)
    mlflow.end_run()


def main() -> None:
    args = parse_args()
    module_name, _hf_model_id, is_moe = MODEL_RECIPES[args.model]
    recipes = __import__(module_name, fromlist=["pretrain_config"])

    recipe_kwargs = dict(
        mock=args.data_path is None,
        data_paths=[args.data_path] if args.data_path else None,
        tensor_parallelism=args.tensor_parallelism,
        pipeline_parallelism=args.pipeline_parallelism,
        context_parallelism=args.context_parallelism,
        train_iters=args.train_iters,
        global_batch_size=args.global_batch_size,
        micro_batch_size=args.micro_batch_size,
        seq_length=args.seq_length,
        precision_config=args.precision,
        # The recipe's default 500-iter LR warmup must stay below
        # train_iters (`lr_warmup_steps < lr_decay_steps`), so the short
        # throughput runs use 0.
        lr_warmup_iters=args.lr_warmup_iters,
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
    if args.recompute:
        cfg.model.recompute_granularity = "full"
        cfg.model.recompute_method = "uniform"
        cfg.model.recompute_num_layers = 1

    # Throughput runs write no checkpoint. With --checkpoint-dir, save and
    # load point at the same directory, so a restarted job resumes from the
    # latest checkpoint. No validation/test passes either way.
    if args.checkpoint_dir:
        cfg.checkpoint.save = args.checkpoint_dir
        cfg.checkpoint.load = args.checkpoint_dir
        cfg.checkpoint.save_interval = args.save_interval
    else:
        cfg.checkpoint.save = None
    cfg.train.eval_iters = 0
    cfg.logger.log_throughput = True
    cfg.logger.log_interval = 1

    rank = int(os.environ.get("RANK", "0"))
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    # Real-data runs log live from the last rank, which prints the loss.
    live = args.data_path is not None
    if live and rank == world_size - 1:
        import mlflow  # Installed at container startup - see ../k8s/*.yaml.

        start_or_resume_run(mlflow, args.mlflow_experiment, args.mlflow_run_name, args.run_kind)
        mlflow.set_tags({"run_kind": args.run_kind, **CLUSTER_TAGS})
        iters = log_iterations_live(mlflow)

    steps = capture_step_logs()
    torch.cuda.reset_peak_memory_stats()
    start = time.monotonic()
    pretrain(cfg, forward_step)
    elapsed_sec = time.monotonic() - start

    if live:
        if rank == world_size - 1:
            log_live_summary(mlflow, args, iters, world_size)
        return
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
    peak_flops_per_gpu = H100_FP8_PEAK_FLOPS_PER_GPU if "fp8" in args.precision else H100_BF16_PEAK_FLOPS_PER_GPU
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

    print(f"=== Results: {metrics} ===")
    import mlflow  # Installed at container startup - see ../k8s/*.yaml.

    mlflow.set_experiment(args.mlflow_experiment)
    with mlflow.start_run(run_name=args.mlflow_run_name):
        mlflow.set_tags({"run_kind": args.run_kind, **CLUSTER_TAGS})
        mlflow.log_params(run_params(args, world_size))
        mlflow.log_metrics(metrics)
        for iteration, (step_time, tflops) in enumerate(steps, start=1):
            mlflow.log_metric("iter_step_time_sec", step_time, step=iteration)
            mlflow.log_metric("iter_tflops_per_gpu", tflops, step=iteration)


if __name__ == "__main__":
    main()
