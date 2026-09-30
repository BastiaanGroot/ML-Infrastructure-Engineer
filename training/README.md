# Training (Option 1): Qwen3 distributed-strategy experiments on 16x H100

The runnable part of
[`docs/training-strategy-outline.md`](../docs/training-strategy-outline.md):
single-variable experiments on **2 nodes x 8 H100 over InfiniBand**
comparing data, tensor, pipeline, context and expert parallelism, 3D
parallelism, FP8, attention backends, CPU offloading and activation
recomputation. Everything is logged to the managed MLflow server and
browsable in the [dashboard](../dashboard/README.md).

## How it runs

- **Image**: stock `nvcr.io/nvidia/nemo:25.09` (ships Megatron-Bridge
  `0.1.0rc4`), no custom Dockerfile. That Megatron-Bridge version predates
  the generic `run_recipe.py` launcher and native MLflow logging, so
  [`scripts/run_experiment.py`](scripts/run_experiment.py) calls each Qwen3
  recipe's `pretrain_config()` and `pretrain()` directly and logs to MLflow
  itself. The scripts reach the pods via the `qwen3-training-scripts`
  ConfigMap.
- **One template for every experiment**: [`k8s/worker.yaml.tmpl`](k8s/worker.yaml.tmpl)
  is an Indexed Job (one `torchrun` pod per node, `JOB_COMPLETION_INDEX` is
  the node rank) plus a headless Service that gives pod 0 a stable DNS name
  for rendezvous. No training operator is needed at this scale.
- **InfiniBand**: pods run privileged with the host's `/dev/infiniband`
  mounted, so NCCL uses `NET/IB` with GPUDirect RDMA on all 8 NICs per node
  (see the root README's
  [Hardware](../README.md#hardware-2x8-h100-with-infiniband) section).
  Privileged containers see all 8 GPUs, so every pod claims the whole node
  and uses only its first `NPROC` GPUs.
- **[`launch.py`](launch.py)** holds the experiment matrix, regenerates the
  ConfigMap, renders the template and applies it.
- **Workload**: the strategy experiments use synthetic (`mock=True`) data,
  20 iterations, no LR warmup, no checkpoint or eval passes. They measure
  parallelism mechanics (throughput, memory, communication), not
  convergence. The [end-to-end run](#end-to-end-run-qwen3-17b-on-fineweb-edu)
  trains on real data with checkpoints. Metrics are
  steady-state averages over iterations 2-20, from Megatron's own
  per-iteration log (`steady_step_time_sec`, `steady_tflops_per_gpu`).
  MFU is against the H100's 989 TFLOP/s bf16 dense peak.

## Running

```bash
# One-time: MLflow credentials as a K8s Secret (password from SecretStash,
# see infra/README.md "MLflow"):
kubectl create secret generic mlflow-creds \
  --from-literal=MLFLOW_TRACKING_USERNAME=admin \
  --from-file=MLFLOW_TRACKING_PASSWORD=<(nebius mysterybox payload get-by-key \
      --secret-id mbsec-e00c36r6fzh80jfkc5 --key password --format json \
      | grep -v "token from" | python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["string_value"],end="")')

./launch.py --list                      # all experiment names
./launch.py q8b-baseline
kubectl logs -f job/q8b-baseline        # node rank 0; results line at the end
kubectl delete job,svc q8b-baseline     # before the next one - each claims both nodes
```

Profile runs (`prof-*`) wrap node rank 0 in `nsys profile` and print the
`cuda_gpu_kern_sum` table at the end of its log. Copy it into
[`profiles/`](profiles/), then summarize it with
`python3 scripts/summarize_kernels.py profiles/*.txt`.

## End-to-end run: Qwen3-1.7B on FineWeb-Edu

`e2e-q1p7b` pretrains Qwen3-1.7B from scratch across both nodes (DP16) on
real text, with checkpoints, to show the whole path a customer training run
takes: data on shared storage, a falling loss curve, and recovery from a
failure.

```bash
kubectl apply -f k8s/prepare-data.yaml   # once: ~5 min
kubectl logs -f job/prepare-data
./launch.py e2e-q1p7b                    # ~40 min
```

1. **Data** ([`k8s/prepare-data.yaml`](k8s/prepare-data.yaml)): two shards
   of [FineWeb-Edu](https://huggingface.co/datasets/HuggingFaceFW/fineweb-edu)
   `sample-10BT` (1.455M documents) are downloaded to a 2Ti network-disk PVC,
   then tokenized with the Qwen3 tokenizer into Megatron's indexed format on
   the shared filesystem: 1.49B tokens, 5.6 GB. It takes 5 minutes on
   64 CPU cores of one GPU node.
2. **Training**: global batch 256 x 4096 tokens, 1000 iterations (1.05B
   tokens, about one epoch), 50 warmup iterations, cosine decay from
   3e-4 to 3e-5. Both nodes read the dataset from the shared filesystem.
   The loss is logged to MLflow live from the last rank (tag
   `run_kind=e2e`).
3. **Checkpoints**: every 250 iterations to
   `/mnt/shared-fs/checkpoints/e2e-q1p7b` (Megatron `torch_dist` format,
   every rank writes its shard in parallel). Each is 22.4 GB (bf16 weights
   plus fp32 master weights and Adam states) and takes about 17 s, less than
   1% of the run at this interval.
4. **Failure and resume**: the Job was deleted at iteration 519, 19
   iterations after the iteration-500 checkpoint, to simulate a node
   failure. Re-running `./launch.py e2e-q1p7b` loaded that checkpoint and
   was training again at iteration 501 65 s later, including a 22 s first
   iteration. The MLflow run continued as the same run. Iterations 501-519
   ran twice and produced identical losses both times (4.231 at 501, 4.169
   at 519), so data order and optimizer state were restored exactly.

| Iteration | 1 | 50 | 100 | 250 | 500 | 750 | 1000 |
|---|---|---|---|---|---|---|---|
| Training loss | 12.32 | 7.27 | 6.53 | 5.35 | 4.24 | 3.86 | **3.68** |

Steady state: **2.09 s** per iteration, **368 TFLOP/s/GPU** (32% MFU),
31.3k tokens/s per GPU (502k tokens/s for the cluster), 44.3 GB peak
memory. That matches the synthetic-data `q1p7b-dp16` run (349 TFLOP/s at
global batch 32), so real data loading from the shared filesystem costs no
throughput.

Next step for serving (not done here): convert the final checkpoint to
Hugging Face format with Megatron-Bridge's `AutoBridge` export, then load it
in an inference server.

## Results

All numbers are steady-state, on 16 GPUs unless stated otherwise. Each
MLflow run is named after its experiment (`qwen3-parallelism-experiments`
experiment, tag `cluster=2x8-h100-ib`).

### NCCL bandwidth

`all_reduce` bus bandwidth from
[`scripts/nccl_bandwidth_sweep.py`](scripts/nccl_bandwidth_sweep.py)
(`nccl-*` experiments):

| Message size | 8 GPUs, NVLink | 16 GPUs, NVLink + IB | 2 GPUs (1 per node), one IB NIC |
|---|---|---|---|
| 1 MiB | 69.5 GB/s | 22.6 GB/s | 16.9 GB/s |
| 16 MiB | 246.1 GB/s | 158.1 GB/s | 38.6 GB/s |
| 256 MiB | 424.4 GB/s | 381.4 GB/s | 45.3 GB/s |
| 1 GiB | **468.0 GB/s** | **442.4 GB/s** | **46.3 GB/s** |

With all 8 NICs per node in use, a 16-GPU all-reduce gets within 6% of
single-node NVLink at large messages. The 2-GPU case reaches 93% of one
400 Gb/s link's line rate. Small messages are where crossing nodes
still costs: at 1 MiB the 16-GPU all-reduce is 3x slower than NVLink. That
matters for tensor parallelism, which sends many medium-sized all-reduces
on the critical path.

### Qwen3-1.7B: DP vs TP vs PP

Micro-batch 2, global batch 32, seq 4096.

| Experiment | Layout | Step | TFLOP/s/GPU | MFU | Peak mem |
|---|---|---|---|---|---|
| `q1p7b-dp16` | DP16 | 0.275 s | **348.9** | 35.3% | 44.3 GB |
| `q1p7b-tp2-dp8` | TP2 x DP8 | 0.338 s | 283.1 | 28.6% | 24.7 GB |
| `q1p7b-pp2-dp8` | PP2 x DP8 | 0.427 s | 225.9 | 22.8% | 27.3 GB |

A model this small fits easily on one GPU, and with NVLink and InfiniBand
DP16's gradient traffic overlaps with the backward pass, so plain DP is
fastest. TP and PP only add overhead: smaller GEMMs per GPU
for TP, and for PP a pipeline bubble of 1 in 2 microbatches (DP8 leaves
only 2 microbatches per step). Their advantage is memory: 24.7-27.3 GB
versus 44.3 GB.

### Qwen3-8B: one change at a time from a TP2 x DP8 baseline

Micro-batch 1, global batch 64, seq 4096 (16384 for the long-sequence rows).

| Experiment | Change | Step | TFLOP/s/GPU | MFU | Peak mem |
|---|---|---|---|---|---|
| `q8b-baseline` | TP2 x DP8 | 1.94 s | **414.9** | 42.0% | 49.2 GB |
| `q8b-dp16` | DP16 | - | - | - | **OOM** |
| `q8b-dp16-recompute` | DP16 + full recompute | 2.17 s | 369.9* | 37.4%* | 65.5 GB |
| `q8b-tp4-dp4` | TP4 x DP4 | 2.60 s | 308.7 | 31.2% | 30.2 GB |
| `q8b-tp8-dp2` | TP8 x DP2 | 5.06 s | 158.8 | 16.1% | 20.7 GB |
| `q8b-tp8-1node` | TP8, one node (8 GPUs) | 9.92 s | 162.0 | 16.4% | 26.8 GB |
| `q8b-tp8-2nodes` | TP8 split 4 + 4 across nodes | 10.04 s | 160.2 | 16.2% | 26.8 GB |
| `q8b-pp2` | TP2 x PP2 x DP4 | 2.29 s | 350.6 | 35.4% | 33.2 GB |
| `q8b-fp8` | FP8 (current scaling) | 1.86 s | **436.2** | 44.1%** | 47.2 GB |
| `q8b-unfused-attn` | unfused attention | 2.61 s | 308.0 | 31.1% | 69.4 GB |
| `q8b-cpu-offload` | activation CPU offload | 7.87 s | 102.1 | 10.3% | 40.5 GB |
| `q8b-seq16k-baseline` | TP2 x DP8, seq 16384 | - | - | - | **OOM** |
| `q8b-seq16k-cp2` | TP2 x CP2 x DP4, seq 16384 | 4.46 s | **440.5** | 44.5% | 66.7 GB |
| `q8b-seq16k-tp4` | TP4 x DP4, seq 16384 | 4.76 s | 412.7 | 41.7% | 63.8 GB |

\* Megatron counts the recomputed forward pass, so this overstates useful
work. Compare step times instead: 2.17 s versus 1.94 s.
\** Against the bf16 peak; against H100's ~1979 TFLOP/s FP8 peak it's 22%.

What this shows:

- **TP costs throughput quickly, even on NVLink.** Going from TP2 to TP4 to
  TP8 drops throughput from 415 to 309 to 159 TFLOP/s/GPU. Each GPU's GEMMs
  shrink while the per-layer all-reduces don't. At 8B, TP2 is enough to fit
  and the best layout. TP16 isn't possible at all: Qwen3-8B's 8 KV heads cap
  TP at 8.
- **Splitting a TP group across nodes cost almost nothing here**: TP8 at
  4 + 4 GPUs over InfiniBand ran within 1% of TP8 on one node. The profile
  below shows why. TP8 is already dominated by communication and small
  kernels inside one node, and 4 NICs per node carry the cross-node half of
  each all-reduce fast enough. That's a result of this fabric (one 400 Gb/s
  NIC per GPU), not a general licence to span TP across nodes. At 1 MiB the
  NCCL sweep above is still 3x slower across nodes.
- **Pure DP runs out of memory, and recompute is the expensive fix.** DP16
  with full replicas OOMs at 80 GB. Full recomputation makes it fit (65.5 GB)
  but 12% slower than simply using TP2, which also halves memory.
- **PP2 on top of TP2 costs 15%** (a 2-stage bubble with 4 microbatches per
  DP rank). It saves memory (33.2 GB), which an 8B model doesn't need here.
- **Long sequences need CP or more TP.** At seq 16384 the TP2 baseline OOMs.
  CP2 (sequence split across two GPUs) fits at 66.7 GB and is 6% faster
  than spending the same two-way split on TP4 (63.8 GB), most likely because
  CP's ring-attention exchange overlaps with compute while TP's per-layer
  all-reduces sit on the critical path.
- **FP8 gives a 4% faster step** (1.94 s to 1.86 s), far from 2x. Only the
  GEMMs run in FP8; attention, norms and communication don't, and current
  scaling computes a scale factor for every tensor on every step.
- **Fused attention matters for memory first**: unfused attention costs 26%
  in step time and 41% more memory (69.4 GB versus 49.2 GB), because it
  materializes the full attention score matrix.
- **CPU offload is a last resort on this hardware**: it saves 18% of memory
  (40.5 GB) but makes the step 4x slower. Moving activations over PCIe can't
  keep up with an H100 at this batch size.

### Qwen3-30B-A3B (MoE): expert parallelism within vs across nodes

128 experts, ~3B active parameters per token, TP1, DP16. Micro-batch 1,
global batch 64. TFLOP/s counts active parameters only.

| Experiment | Layout | Step | TFLOP/s/GPU | MFU | Peak mem |
|---|---|---|---|---|---|
| `q30b-a3b-ep8` | EP8 (all-to-all inside a node) | 3.73 s | **101.2** | 10.2% | 62.1 GB |
| `q30b-a3b-ep16` | EP16 (all-to-all across nodes) | 9.42 s | 40.1 | 4.1% | 51.3 GB |

EP8 fits with 16 experts per GPU (smaller EP degrees leave too many experts,
and their optimizer states, on each GPU). Spreading experts across both nodes (EP16) saves 11 GB
per GPU but makes the step 2.5x slower. The token all-to-all then crosses
InfiniBand twice per MoE layer, forward and backward, and unlike DP's
gradient reduction it can't overlap with compute. Keep EP inside the NVLink
domain, and scale out with DP (or PP) across nodes. That's also how
NVIDIA's 235B-A22B recipe is shaped (EP8 on 8-GPU nodes). Low MFU is
expected for MoE at micro-batch 1: each expert's GEMM only sees the few
tokens routed to it.

### Qwen3-32B: 3D parallelism

Micro-batch 1, global batch 64.

| Experiment | Layout | Step | TFLOP/s/GPU | MFU | Peak mem |
|---|---|---|---|---|---|
| `q32b-tp4-pp2-dp2` | TP4 x PP2 x DP2 | 10.69 s | **313.9** | 31.7% | 52.8 GB |
| `q32b-tp8-pp2-dp1` | TP8 x PP2 (NVIDIA's recipe default) | 14.79 s | 226.9 | 22.9% | 40.2 GB |

A 32B model's weights, gradients and Adam states come to ~525 GB, so it has
to be sharded across at least 8 H100s before counting any activations. The
layout keeps each TP group
inside a node (NVLink), puts the pipeline stage boundary between the
nodes (point-to-point activations over InfiniBand), and uses DP for the
rest. NVIDIA's recipe (TP8 x PP2) uses the least memory, but on 16 GPUs it
leaves no DP. The step is 38% slower than TP4 x PP2 x DP2, which still fits
comfortably at 52.8 GB. Same lesson as for 8B: use the smallest TP that
fits.

### Nsight profiles

`prof-q8b-baseline` and `prof-q8b-tp8-2nodes` re-run two of the layouts
above under `nsys` (tables in [`profiles/`](profiles/)). Profiling overhead
was +5% for the baseline (2.03 s versus 1.94 s) and +37% for the
communication-heavy TP8 run (13.7 s versus 10.0 s).

| Share of summed GPU kernel time | TP2 x DP8 (TP over NVLink) | TP8, 4 + 4 GPUs (TP over IB) |
|---|---|---|
| GEMM | **47.0%** | 19.0% |
| NCCL communication | 26.1% | **63.4%** |
| Fused attention | 7.7% | 4.0% |
| Everything else | 19.2% | 13.6% |

These are shares of kernel time summed over CUDA streams, not wall time;
NCCL runs on its own stream and partly overlaps with compute. In the
baseline, NCCL is split between TP all-reduces (13%, median 0.17 ms per
33.5 MB call over NVLink) and DP's gradient reduce-scatter and parameter
all-gather (12%, overlapped with the backward pass). In the cross-node TP8
run, TP all-reduces alone are 63% of kernel time: 747k calls with a median
of 0.64 ms, about 4x the NVLink TP2 call. This is the kernel-level reason
TP beyond what's needed to fit is expensive.

The `.nsys-rep` files stay in each pod's ephemeral filesystem. To open a
timeline in the Nsight Systems GUI, write the report to a mounted volume or
object storage instead of `/tmp`.
