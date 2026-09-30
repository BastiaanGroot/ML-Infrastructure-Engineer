# Training strategy outline (Option 1)

Design reference for Option 1 ("multi-node training run of an open-source
LLM... run multiple experiments with various training distribution
strategies... illustrate how the client may set up training on their
cluster for a larger model (+100B)" — see
[`docs/ML-Infrastructure-Engineer.md`](ML-Infrastructure-Engineer.md)).

This doc is the design for the PoC's **16x H100** cluster (2 nodes x 8,
InfiniBand; see the root README's
["Hardware"](../README.md#hardware-2x8-h100-with-infiniband) section) and
how it extrapolates to 100B+ models. [`training/README.md`](../training/README.md)
has the experiments we ran on that cluster and their results.

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
| Qwen3-4B | Pretrain | 2 | 1 | 1 | – | 2 | <1 |
| Qwen3-8B | Pretrain | 4 | 1 | 1 | – | 4 | <1 |
| Qwen3-8B | Pretrain (convergence cohort) | 1 | 1 | 1 | – | 16 (DP=16) | 2 |
| Qwen3-14B | Pretrain / SFT | 8 | 1 | 1 | – | 8 | 1 |
| **Qwen3-32B** | **Pretrain / SFT** | **8** | **2** | 1 | – | **16** | **2** |
| Qwen3-30B-A3B (MoE) | Pretrain | 4 | 2 | 1 | 4 | 8 | 1 |
| **Qwen3-235B-A22B (MoE)** | **Pretrain** | 4 | 16 | **2** | **8** | **128** | **16** |
| Qwen3-235B-A22B (MoE) | SFT | 4 | 16 | 1 | 4 | 64 | 8 |
| Qwen3-235B-A22B (MoE) | PEFT (LoRA/DoRA) | 4 | 4 | 1 | 4 | 64 | 8 |

Bolded rows are the two that matter most for this project: **Qwen3-32B's
recipe is exactly our 16 GPUs**, and **Qwen3-235B-A22B is the real >100B
target** the assignment references. The table is Megatron-Bridge's H100
recipe set, the same GPU as both the PoC and the customer's 512x H100 target.

## Sizing insight: what actually fits on the PoC's 16 GPUs

This is the useful takeaway for the client, now backed by measured runs:

- The 16-GPU cluster covers real 3D parallelism up to **dense Qwen3-32B**
  and the **30B-A3B MoE** tier. We ran both: Qwen3-32B at TP4 x PP2 x DP2
  (315 TFLOP/s/GPU, 53 GB) and 30B-A3B at EP8 (101 TFLOP/s/GPU, 62 GB).
- **Scaling out with DP over InfiniBand is nearly free.** Qwen3-8B at
  TP2 x DP ran 416.6 TFLOP/s/GPU on one node and 415.3 on two with the same
  per-GPU batch: 99.7% weak-scaling efficiency across the node boundary.
- **Keep TP and EP inside a node, and cross nodes with DP or PP.** On this
  fabric, a 16-GPU all-reduce reaches 442 GB/s, nearly NVLink's 468 GB/s,
  but small messages and all-to-all still pay for leaving the node:
  EP16 across nodes was 2.6x slower than EP8. The 512-H100 layout should
  follow the same rule.
- **Use the smallest TP that fits.** Qwen3-8B loses 25% throughput going
  from TP2 to TP4 and 61% at TP8. NVIDIA's own TP8 x PP2 for 32B was 39%
  slower on 16 GPUs than TP4 x PP2 x DP2, because it leaves no data
  parallelism.
- The **235B-A22B flagship needs 64-128 GPUs** per NVIDIA's recipe (TP=4,
  PP=16, CP=2, EP=8 for pretrain), 4-8x the PoC. 16 GPUs is right-sized for
  fine-tuning or PEFT in the 30-32B tier, not for pretraining a 100B+ model.
- The customer's 512-H100 reservation (32x the PoC) comfortably clears the
  235B-A22B SFT/PEFT tier (64 GPUs) with room for concurrent experiments,
  or one 128-GPU pretraining run with 4x data parallelism on top.

## What we ran

[`training/README.md`](../training/README.md#results) has the full matrix and
results. In short:

- **NCCL all-reduce sweeps** over NVLink (8 GPUs), NVLink + InfiniBand
  (16 GPUs), and a single NIC (2 GPUs, one per node: 46 GB/s).
- **Qwen3-1.7B** DP16 vs TP2 x DP8 vs PP2 x DP8: plain DP is fastest for a
  model this small.
- **Qwen3-8B** single-variable suite around a TP2 x DP8 baseline: DP16
  (OOM, then with recompute), TP4, TP8 within one node vs split across
  nodes, PP2, CP2 vs TP4 at seq 16384 (where the baseline OOMs), FP8,
  unfused attention and CPU offload.
- **Qwen3-30B-A3B** EP8 vs EP16, and **Qwen3-32B** TP4 x PP2 x DP2 vs
  TP8 x PP2.
- **Nsight Systems profiles** of the 8B baseline and the cross-node TP8 run.

*Note*: the NVIDIA-named convenience recipes in the table above
(`qwen3_1p7b_pretrain_1gpu_h100_bf16_config` etc.) come from a newer
Megatron-Bridge release than the one in `nvcr.io/nvidia/nemo:25.09`
(`0.1.0rc4`). Our runs call that version's generic
`pretrain_config(tensor_parallelism=..., ...)` on the same Qwen3 model
configs; see [`training/README.md`](../training/README.md#how-it-runs).

The sizing reasoning is also an interactive planner in the
[dashboard](../dashboard/README.md) ([`recommender.py`](../dashboard/recommender.py)).
It ranks TP x PP x DP layouts for a model, cluster and link bandwidth. On
the measured 8B and 32B runs it gets the ranking right, but underestimates
TP8's cost by ~2x (it assumes constant MFU) and memory by up to ~27%.

## Not covered

Everything on the vacancy's list of topics has a measured run: DP, TP, PP,
CP, EP, 3D parallelism, FP8, attention backend, CPU offloading and
activation recomputation. Real data, a converging loss, checkpointing to the
shared filesystem and resume after a failure are covered by the
[end-to-end run](../training/README.md#end-to-end-run-qwen3-17b-on-fineweb-edu).
Not covered: anything above 16 GPUs, and long pretraining runs (the strategy
experiments are 20 iterations on mock data; the end-to-end run is ~1B tokens).

## References

- [Megatron-Bridge](https://github.com/NVIDIA-NeMo/Megatron-Bridge) — Qwen3
  recipes: `src/megatron/bridge/recipes/qwen/h100/qwen3.py`,
  `src/megatron/bridge/recipes/qwen/qwen3_moe.py`.
- [NeMo Framework parallelism guide](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/features/parallelisms.html)
- [Nebius Solutions Library — `k8s-training`](https://github.com/nebius/nebius-solutions-library/tree/main/k8s-training)
