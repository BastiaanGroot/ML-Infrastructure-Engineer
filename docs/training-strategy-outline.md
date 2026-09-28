# Training strategy outline (Option 1)

Design reference for Option 1 ("multi-node training run of an open-source
LLM... run multiple experiments with various training distribution
strategies... illustrate how the client may set up training on their
cluster for a larger model (+100B)" — see
[`docs/ML-Infrastructure-Engineer.md`](ML-Infrastructure-Engineer.md)).

This doc is the full design for the **2x8-GPU/InfiniBand cluster** (16x
H100, now live — see the root README's
["Hardware"](../README.md#hardware-2x8-h100-with-infiniband) section) and
beyond. [`training/README.md`](../training/README.md) covers what we actually
ran on the earlier 2x1 H200 cluster, a deliberately small, honest subset of
this outline.

## Framework: NeMo Framework / Megatron-Bridge (Megatron-Core)

The [vacancy posting](ML-Infrastructure-Engineer-vacancy.md) calls out
"data/tensor/context/expert parallelism, offloading, custom kernels...
attention optimisations" as core skills, and explicitly names Megatron-LM
among expected framework experience. That's not incidental: for a client
planning genuine +100B training, **plain FSDP/DeepSpeed-ZeRO is not
sufficient on its own**.

- **FSDP2 / ZeRO-3** shard parameters, gradients, and optimizer state across
  data-parallel ranks. This reduces *memory per GPU*, not *communication per
  layer* — every GPU still computes every matmul in full. It scales
  reasonably to tens of billions of parameters, but doesn't have an answer
  for reducing per-layer compute/activation memory the way tensor
  parallelism does, nor for splitting layers across GPUs (pipeline
  parallelism), splitting long sequences (context parallelism), or routing
  to a subset of experts per GPU (expert parallelism, MoE-specific).
- **NeMo Framework / Megatron-Bridge** (built on Megatron-Core) implements
  TP, PP, CP, and EP as first-class, composable config fields
  (`tensor_model_parallel_size`, `pipeline_model_parallel_size`,
  `context_parallel_size`, `expert_model_parallel_size`) alongside DP. This
  is the same toolkit real 100B+ runs use in practice (e.g. Llama 3 405B,
  DeepSeek-V3), and it's what Nebius's own
  [Solutions Library](https://github.com/nebius/nebius-solutions-library)
  patterns assume for `k8s-training`.

Confirmed live via NVIDIA's docs (not invented for this doc): Megatron-Bridge
ships ready-made, NVIDIA-validated recipes with exact parallelism degrees per
model size and GPU count — see the table below.

## Model: Qwen3 family (dense + MoE)

Qwen3 uniquely covers **every** strategy the vacancy doc calls out, within
one lineage:

- **Dense** variants (600M, 1.7B, 4B, 8B, 14B, 32B) — for DP/TP/PP/CP
  experiments.
- **MoE** variants (30B-A3B, 235B-A22B) — for expert-parallelism, with
  **235B-A22B as the genuine >100B extrapolation target** the assignment
  asks for.
- Apache-2.0 licensed; first-class support in both Hugging Face and
  Megatron-Bridge (`AutoBridge.from_hf_pretrained("Qwen/Qwen3-4B")` converts
  a HF checkpoint straight into a Megatron-parallel model).

## Recipe table

NVIDIA-recommended parallelism degrees per Megatron-Bridge's built-in Qwen3
recipes (`src/megatron/bridge/recipes/qwen/h100/qwen3.py` in
[NVIDIA-NeMo/Megatron-Bridge](https://github.com/NVIDIA-NeMo/Megatron-Bridge)),
spanning our exact target range:

| Model | Scenario | TP | PP | CP | EP | GPUs | Nodes (@8 GPU/node) |
|---|---|---|---|---|---|---|---|
| Qwen3-600M | Pretrain | 1 | 1 | 1 | – | 1 | <1 |
| Qwen3-600M | SFT, long-context (YaRN 128K) | 1 | 1 | **8** | – | 8 | 1 |
| Qwen3-1.7B | Pretrain | 1 | 1 | 1 | – | 1 | <1 |
| Qwen3-1.7B | SFT | 1 | 1 | 1 | – | 8 (DP=8) | 1 |
| **Qwen3-4B** | **Pretrain** | **2** | 1 | 1 | – | **2** | <1 |
| Qwen3-8B | Pretrain | 4 | 1 | 1 | – | 4 | <1 |
| Qwen3-8B | Pretrain (convergence cohort) | 1 | 1 | 1 | – | 16 (DP=16) | 2 |
| Qwen3-14B | Pretrain / SFT | 8 | 1 | 1 | – | 8 | 1 |
| Qwen3-32B | Pretrain / SFT | 8 | 2 | 1 | – | 16 | 2 |
| Qwen3-30B-A3B (MoE) | Pretrain | 4 | 2 | 1 | 4 | 8 | 1 |
| **Qwen3-235B-A22B (MoE)** | **Pretrain** | 4 | 16 | **2** | **8** | **128** | **16** |
| Qwen3-235B-A22B (MoE) | SFT | 4 | 16 | 1 | 4 | 64 | 8 |
| Qwen3-235B-A22B (MoE) | PEFT (LoRA/DoRA) | 4 | 4 | 1 | 4 | 64 | 8 |

Bolded rows are the two data points that matter most for this project: the
**Qwen3-4B/2-GPU recipe was an exact fit for the earlier 2x1-GPU cluster**
(see below), and **Qwen3-235B-A22B is the real >100B target** the assignment
references.

## A note on H100 vs H200

The table above is Megatron-Bridge's **H100** recipe set (see the file path
above), and the live PoC cluster now runs **H100**s too (2x8, InfiniBand),
matching both the table and the customer's real target hardware (the
assignment's overview specifies a 512x H100 deployment). The earlier
experiments in [`training/`](../training/README.md#results) ran on **H200**s,
which is still comparable:

- **Compute is identical.** H100 and H200 are the same GH100 die at the same
  clocks - both peak at 989 TFLOP/s bf16 (dense, non-sparse) tensor-core
  throughput per GPU, so the H200 runs' **throughput and MFU numbers
  transfer directly** to H100.
- **H200 is purely a memory upgrade**: 141GB HBM3e @ ~4.8TB/s vs H100's 80GB
  HBM3 @ ~3.35TB/s. On H100, a model can need a higher TP/PP degree just to
  *fit* than it did on H200.
- Concretely for re-running our experiments: most peaked at 28-65GB and
  still fit in 80GB, but the long-sequence DP baseline (seq 16384, **85.1GB**)
  and the unfused-attention run (**84.3GB**) won't fit on one H100 as-is -
  they need recompute, a smaller micro-batch, or CP/TP.

## Sizing insight: what actually fits on the PoC's 16 GPUs

This is the useful, honest takeaway for the client, not just a table:

- The 16-GPU (2x8 H100, InfiniBand) PoC cluster comfortably covers real
  3D parallelism up to **dense Qwen3-32B** (TP=8, PP=2) or the **30B-A3B MoE**
  tier (TP=4, PP=2, EP=4) — both fit in a single 8-GPU node's worth of TP/EP
  fan-out plus modest pipeline depth.
- The **235B-A22B flagship needs 64-128 GPUs** per NVIDIA's own validated
  recipe (TP=4, PP=16, CP=2, EP=8 for pretrain) — 4-8x our target PoC
  capacity. A client wanting to actually pretrain a 235B-class MoE model
  would need a materially larger reservation than the 16 H100s discussed
  here; 16 GPUs is right-sized for fine-tuning/PEFT on something in the
  30-32B tier, not for pretraining a 100B+ model from scratch.
- This maps directly onto the original 512-H100 reservation mentioned in
  the assignment's overview — that capacity (32x our 16-GPU PoC) would
  comfortably clear the 235B-A22B SFT/PEFT tier (64 GPUs) with room for
  multiple concurrent experiments.

## What we actually ran (the earlier 2x1 H200 cluster)

At the time, the cluster had **2 nodes x 1 H200 each** (2 GPUs total, no
InfiniBand — see the root README's "Hardware" note). That's below
even the smallest multi-GPU recipe above, so the real, small-scale
implementation deliberately picks single-variable experiments that fit
exactly and teach the most, all using the same Qwen3-1.7B model/recipe
module so only the parallelism degree under test changes each time:

1. **Baseline / Data Parallel** — Qwen3-1.7B (TP=1/PP=1), DP=2 across our two
   nodes.
2. **Tensor Parallel** — Qwen3-1.7B (same model as the DP baseline) with
   TP=2/PP=1 — our two single-GPU nodes become one TP group instead of two
   DP replicas. Using the same model as experiment 1 (rather than the
   larger Qwen3-4B recipe row above) keeps this a single-variable
   comparison: only `tensor_parallelism` differs between the two runs.
3. **Pipeline Parallel** — Qwen3-1.7B (same model again), TP=1/PP=2 — the two
   nodes now hold different halves of the model's layers instead of a full
   replica (DP) or a sharded layer (TP). Global/micro batch sizes are chosen
   so there are enough microbatches (4) to actually pipeline given PP=2.
4. **Context Parallel** — Qwen3-1.7B, CP=2, at a 4x longer sequence
   (16384 vs the 4096 used above) - CP shards the *sequence* dimension
   instead of layers (PP) or a layer's internals (TP). Compared against a
   matched **DP=2 long-sequence baseline** (CP=1, same 16384 seq_length) so
   only `context_parallelism` differs - comparing straight to experiment 1's
   4096-seq DP baseline would confound "CP vs DP" with "long vs short
   sequence".
5. **Expert Parallel (stretch)** — Qwen3-30B-A3B MoE, EP=2. Deliberately
   attempted even though a back-of-envelope check predicted it wouldn't fit
   - and it didn't: a confirmed `torch.OutOfMemoryError` building the
   optimizer's fp32 master parameters, before a single training step. Kept
   in the repo and written up honestly (not hidden) as a demonstration of a
   real hardware/scale limit - see `training/README.md`'s Results section
   for the exact numbers and error.

The vacancy doc also calls out "offloading, custom kernels, hardware
features, attention optimisations" specifically, beyond the five
parallelism strategies above - three more single-variable experiments
against the same DP=2/Qwen3-1.7B baseline cover that:

6. **FP8 mixed precision** — same as the DP=2 baseline, only `--precision
   bf16_with_fp8_current_scaling_mixed` instead of the default `bf16_mixed`
   - Hopper's native low-precision GEMM path.
7. **Attention backend** — same baseline, `--attention-backend unfused`
   (plain PyTorch matmul+softmax+matmul) instead of Megatron-Core's default
   fused/FlashAttention kernel, to make the custom-kernel effect measurable.
8. **CPU offload** — same baseline, `--cpu-offload` (activation CPU
   offloading for all-but-one layer).
9. **NCCL bandwidth sweep** — no model at all, just a direct
   `torch.distributed.all_reduce` sweep across the same two nodes at
   message sizes from 1 MiB to 1 GiB, to put a real GB/s number behind the
   "no InfiniBand" explanation used throughout the other experiments'
   write-ups rather than leaving it as an assumption.
10. **Nsight Systems profiles** — experiments 1 (DP=2) and 2 (TP=2) re-run
    under `nsys profile`, with a per-kernel time breakdown showing NCCL
    communication at 84% (DP) and 95% (TP) of GPU kernel time, and per-call
    NCCL times that match experiment 9's measured bandwidth.

Experiments 1-4 and 6-9 ran successfully end-to-end and logged to MLflow —
see [`training/README.md`](../training/README.md#results) for the
implementation and results, including a real (if modest, at this scale)
measured slowdown from running TP across nodes without InfiniBand, a more
surprising result for PP (see the README's takeaway on communication
volume), a clean memory-vs-throughput trade-off for CP at long sequence
length, a smaller-than-naively-expected FP8 speedup, attention backend
mattering for memory far more than throughput at this scale, and CPU
offload's memory saving coming essentially free at this scale. Experiment 5
(EP) confirmed infeasible on this hardware, also documented there.

*Note*: the exact NVIDIA-named convenience recipes in the table above
(`qwen3_1p7b_pretrain_1gpu_h100_bf16_config` etc.) come from a newer
Megatron-Bridge release than the one pinned inside `nvcr.io/nvidia/nemo:25.09`
(`0.1.0rc4`). Our implementation calls that older version's equivalent
generic `pretrain_config(tensor_parallelism=..., pipeline_parallelism=...)`
API directly on the same underlying Qwen3 model configs - same architecture
and parallelism degrees, just not the newer named wrapper. See
`training/README.md`'s "Container image" section.

The sizing reasoning in this outline is also implemented as an interactive
planner in the [dashboard](../dashboard/README.md)
([`recommender.py`](../dashboard/recommender.py)): it ranks TP x PP x DP
layouts for a given model/cluster/link bandwidth and is validated against
the measured DP/TP/PP runs above (step time within ~17%, memory
underestimated by ~8-23% since it ignores framework/allocator overhead).

## Deferred / stretch (not attempted this pass)

Nothing left deliberately unattempted from the vacancy's list of topics -
DP, TP, PP, CP, EP, FP8 precision, attention backend, and CPU offloading all
have a real run and a documented result (EP's result being "confirmed
infeasible on 2 GPUs", not a success, but that's
still an honest, evidenced answer rather than a skip).

## References

- [Megatron-Bridge](https://github.com/NVIDIA-NeMo/Megatron-Bridge) — Qwen3
  recipes: `src/megatron/bridge/recipes/qwen/h100/qwen3.py`,
  `src/megatron/bridge/recipes/qwen/qwen3_moe.py`.
- [NeMo Framework parallelism guide](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/features/parallelisms.html)
- [Nebius Solutions Library — `k8s-training`](https://github.com/nebius/nebius-solutions-library/tree/main/k8s-training)
