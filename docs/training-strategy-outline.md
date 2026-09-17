# Training strategy outline (Option 1)

Design reference for Option 1 ("multi-node training run of an open-source
LLM... run multiple experiments with various training distribution
strategies... illustrate how the client may set up training on their
cluster for a larger model (+100B)" — see
[`docs/ML-Infrastructure-Engineer.md`](ML-Infrastructure-Engineer.md)).

This doc is written **as if the future 2x8-GPU/InfiniBand cluster** (see the
root README's ["Future hardware"](../README.md#future-hardware-2x8-gpu-nodes-with-infiniband)
section) were already live — it's the full design the client would use at
target PoC capacity (16 H200s) and beyond. [`training/README.md`](../training/README.md)
covers what we actually ran on today's real 2x1-GPU cluster, which is a
deliberately small, honest subset of this outline.

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
**Qwen3-4B/2-GPU recipe is an exact fit for our current live cluster** (see
below), and **Qwen3-235B-A22B is the real >100B target** the assignment
references.

## Sizing insight: what actually fits on the PoC's 16 GPUs

This is the useful, honest takeaway for the client, not just a table:

- The *future* 16-GPU (2x8, InfiniBand) PoC cluster comfortably covers real
  3D parallelism up to **dense Qwen3-32B** (TP=8, PP=2) or the **30B-A3B MoE**
  tier (TP=4, PP=2, EP=4) — both fit in a single 8-GPU node's worth of TP/EP
  fan-out plus modest pipeline depth.
- The **235B-A22B flagship needs 64-128 GPUs** per NVIDIA's own validated
  recipe (TP=4, PP=16, CP=2, EP=8 for pretrain) — 4-8x our target PoC
  capacity. A client wanting to actually pretrain a 235B-class MoE model
  would need a materially larger reservation than the 16 H200s discussed
  here; 16 GPUs is right-sized for fine-tuning/PEFT on something in the
  30-32B tier, not for pretraining a 100B+ model from scratch.
- This maps directly onto the original 512-H100 reservation mentioned in
  the assignment's overview — that capacity (32x our current PoC) would
  comfortably clear the 235B-A22B SFT/PEFT tier (64 GPUs) with room for
  multiple concurrent experiments.

## What we actually ran (today's 2x1-GPU cluster)

The live cluster has **2 nodes x 1 GPU each** (2 GPUs total, no
InfiniBand — see the root README's "Future hardware" note). That's below
even the smallest multi-GPU recipe above, so the real, small-scale
implementation deliberately picks the two experiments that fit exactly and
teach the most:

1. **Baseline / Data Parallel** — Qwen3-1.7B (TP=1/PP=1), DP=2 across our two
   nodes.
2. **Tensor Parallel** — Qwen3-1.7B (same model as the DP baseline) with
   TP=2/PP=1 — our two single-GPU nodes become one TP group instead of two
   DP replicas. Using the same model as experiment 1 (rather than the
   larger Qwen3-4B recipe row above) keeps this a single-variable
   comparison: only `tensor_parallelism` differs between the two runs.

Both ran successfully end-to-end and logged to MLflow — see
[`training/README.md`](../training/README.md#results) for the implementation
and results, including a real (if modest, at this scale) measured slowdown
from running TP across nodes without InfiniBand.

*Note*: the exact NVIDIA-named convenience recipes in the table above
(`qwen3_1p7b_pretrain_1gpu_h100_bf16_config` etc.) come from a newer
Megatron-Bridge release than the one pinned inside `nvcr.io/nvidia/nemo:25.09`
(`0.1.0rc4`). Our implementation calls that older version's equivalent
generic `pretrain_config(tensor_parallelism=..., pipeline_parallelism=...)`
API directly on the same underlying Qwen3 model configs - same architecture
and parallelism degrees, just not the newer named wrapper. See
`training/README.md`'s "Container image" section.

## Deferred / stretch (not attempted this pass)

Consistent with how the 2x8-GPU switch and the MPI Operator gap were already
deferred elsewhere in this repo:

- **Expert Parallelism** (Qwen3-30B-A3B, EP=2 override) — mechanically
  possible on 2 GPUs (the recipe exists above) but adds real memory/scope
  risk for a first pass; written up here, not yet run.
- **Context Parallelism** (CP=2, long sequence) — same treatment; the
  600M/YaRN-128K SFT recipe above is the reference once CP is attempted.
- Pipeline Parallelism at PP>1 similarly isn't exercised — our 2 GPus are
  fully spent on the DP and TP experiments above.

## References

- [Megatron-Bridge](https://github.com/NVIDIA-NeMo/Megatron-Bridge) — Qwen3
  recipes: `src/megatron/bridge/recipes/qwen/h100/qwen3.py`,
  `src/megatron/bridge/recipes/qwen/qwen3_moe.py`.
- [NeMo Framework parallelism guide](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/features/parallelisms.html)
- [Nebius Solutions Library — `k8s-training`](https://github.com/nebius/nebius-solutions-library/tree/main/k8s-training)
