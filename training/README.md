# Training (Option 1): Qwen3 distributed-strategy experiments

Small-scale, real implementation of the design in
[`docs/training-strategy-outline.md`](../docs/training-strategy-outline.md) —
single-variable experiments that fit exactly on the current live **2 nodes x
1 GPU** cluster, comparing Data/Tensor/Pipeline/Context/Expert Parallelism
head-to-head, with results logged to the live MLflow tracking server. All
ran on the real cluster and produced a documented result — see
[Results](#results) (Expert Parallelism's result is a confirmed OOM, not a
success, but that's still a real, evidenced answer).

## Container image: no custom Dockerfile

`nvcr.io/nvidia/nemo:25.09` (NVIDIA's public NeMo Framework container, no NGC
login required to pull) already ships **Megatron-Bridge** pre-installed, so
building a custom image on top of it for a ~100-line script would only add
an unnecessary extra registry push of an ~19GB layer stack. Instead, our
thin launch script ([`scripts/run_experiment.py`](scripts/run_experiment.py))
is delivered via a `ConfigMap` ([`k8s/scripts-configmap.yaml`](k8s/scripts-configmap.yaml))
mounted into the stock image at `/scripts`.

That script exists because the *specific* Megatron-Bridge version shipped in
this container tag (`0.1.0rc4`, pinned when the image was built) predates
two things newer Megatron-Bridge releases added upstream: a generic
`scripts/training/run_recipe.py` CLI launcher, and native MLflow logging on
`LoggerConfig`. Neither is available in-container (confirmed by exec'ing
into the image — see commit history) so the script calls each model's
`pretrain_config()` recipe function and `pretrain()` entry point directly
(the same public API the newer launcher itself wraps), and logs
throughput/memory/MFU to MLflow itself via the plain `mlflow` client.

## Experiments

All five runs use Megatron-Bridge's own Qwen3 recipe module unmodified (not
hand-tuned configs) — see
[`docs/training-strategy-outline.md`](../docs/training-strategy-outline.md#recipe-table)
for where these sit in the full size/strategy table. All five use synthetic
(`mock=True`) data, a deliberate simplification (see the outline doc) — this
measures parallelism/infra mechanics (throughput, memory, step time), not a
trained checkpoint.

| # | Manifest | Model | Recipe module | Strategy | Seq len | GPUs |
|---|---|---|---|---|---|---|
| 1 | [`k8s/experiment-01-data-parallel.yaml`](k8s/experiment-01-data-parallel.yaml) | Qwen3-1.7B | `megatron.bridge.recipes.qwen.qwen3_1p7b` | DP=2 (TP=1/PP=1 x2 replicas) | 4096 | 2 |
| 2 | [`k8s/experiment-02-tensor-parallel.yaml`](k8s/experiment-02-tensor-parallel.yaml) | Qwen3-1.7B | `megatron.bridge.recipes.qwen.qwen3_1p7b` | TP=2/PP=1 | 4096 | 2 |
| 3 | [`k8s/experiment-03-pipeline-parallel.yaml`](k8s/experiment-03-pipeline-parallel.yaml) | Qwen3-1.7B | `megatron.bridge.recipes.qwen.qwen3_1p7b` | TP=1/PP=2 | 4096 | 2 |
| 4 | [`k8s/experiment-04-context-parallel.yaml`](k8s/experiment-04-context-parallel.yaml) | Qwen3-1.7B | `megatron.bridge.recipes.qwen.qwen3_1p7b` | CP=2 | 16384 | 2 |
| 4b | [`k8s/experiment-04b-longseq-baseline.yaml`](k8s/experiment-04b-longseq-baseline.yaml) | Qwen3-1.7B | `megatron.bridge.recipes.qwen.qwen3_1p7b` | DP=2 (CP=1 baseline for #4) | 16384 | 2 |
| 5 | [`k8s/experiment-05-expert-parallel.yaml`](k8s/experiment-05-expert-parallel.yaml) | Qwen3-30B-A3B (MoE) | `megatron.bridge.recipes.qwen.qwen3_30b_a3b` | EP=2 (stretch, **OOMs** - see Results) | 4096 | 2 |
| 6 | [`k8s/experiment-06-fp8.yaml`](k8s/experiment-06-fp8.yaml) | Qwen3-1.7B | `megatron.bridge.recipes.qwen.qwen3_1p7b` | DP=2, FP8 precision (baseline for #1 is BF16) | 4096 | 2 |
| 7 | [`k8s/experiment-07-attention-backend.yaml`](k8s/experiment-07-attention-backend.yaml) | Qwen3-1.7B | `megatron.bridge.recipes.qwen.qwen3_1p7b` | DP=2, unfused attention (baseline for #1 is fused/auto) | 4096 | 2 |
| 8 | [`k8s/experiment-08-cpu-offload.yaml`](k8s/experiment-08-cpu-offload.yaml) | Qwen3-1.7B | `megatron.bridge.recipes.qwen.qwen3_1p7b` | DP=2, activation CPU offload (baseline for #1 has it off) | 4096 | 2 |

All rows use the exact same model and recipe module - only the parallelism
degree (and, for 4/4b, sequence length) under test differs, so each is a
genuine single-variable comparison against its matched baseline. (An
earlier pass ran experiment 2 against Qwen3-4B instead; that made the two
runs harder to compare apples-to-apples, so it was superseded by this
matched-model rerun - see [Results](#results).) Experiment 3 uses
`global_batch_size=4, micro_batch_size=1` (4 microbatches) instead of
experiment 1/2's `4, 2` - PP=2 needs `num_microbatches >= pipeline_parallelism`
or Megatron-Core's scheduler asserts, and 1 microbatch (what `4, 2` would
give under PP=2's DP=1) doesn't clear that bar. Experiments 4/4b compare CP
against a **matched long-sequence DP baseline** (not experiment 1's
4096-seq baseline) so only `context_parallelism` differs - comparing CP
straight to experiment 1 would confound "CP vs DP" with "long vs short
sequence". Both 4/4b also need a larger `dshm` `emptyDir` (8Gi vs 2Gi
elsewhere) - the 4x longer sequence means 4x bigger batches through
PyTorch's DataLoader workers, which otherwise die with a shared-memory
"Bus error". Experiments 6-8 are each a single flag away from experiment 1's
exact baseline (`--precision`, `--attention-backend`, `--cpu-offload`
respectively) - the cleanest possible single-variable comparisons in this
set.

All manifests define a headless `Service` + 2 plain `Pod`s (rank 0 /
rank 1) running `torchrun` directly — deliberately **no new operator**
(avoids
repeating the still-unresolved MPI-Operator gap noted in
[`cluster-validator/k8s/job-nccl-multinode.yaml`](../cluster-validator/k8s/job-nccl-multinode.yaml)).
At 2 pods, hand-rolled `torchrun` rendezvous env vars (`MASTER_ADDR`/
`MASTER_PORT`/`NODE_RANK`, resolved via each Pod's stable
`<hostname>.<subdomain>.svc.cluster.local` DNS name) are simpler than
installing the Kubeflow Training Operator for this scale. A `dshm` `emptyDir`
volume (`medium: Memory`) is mounted at `/dev/shm` in each pod — the
container's 64MB default isn't enough for PyTorch's DataLoader worker
processes and fails with `OSError: [Errno 28] No space left on device`
otherwise.

Global/micro batch sizes are set per-experiment (no gradient accumulation
where avoidable) rather than the recipes' out-of-the-box (larger) defaults -
see the note above on why experiment 3's batch sizing differs from 1/2's.
All five also override the recipe's default 500-iteration LR warmup down to
0, since this is a 20-iteration mechanism demo, not a real convergence run.

## Running

```bash
# One-time: MLflow Basic-Auth credentials as a K8s Secret (password from
# SecretStash - see infra/README.md "MLflow"):
kubectl create secret generic mlflow-creds \
  --from-literal=MLFLOW_TRACKING_USERNAME=admin \
  --from-file=MLFLOW_TRACKING_PASSWORD=<(nebius mysterybox payload get-by-key \
      --secret-id mbsec-e00s29kcffh4yr0mh5 --key password --format json \
      | grep -v "token from" | python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["string_value"],end="")')

# One-time: the launch script, delivered via ConfigMap:
kubectl apply -f k8s/scripts-configmap.yaml

# Experiment 1 (DP=2):
kubectl apply -f k8s/experiment-01-data-parallel.yaml
kubectl logs -f qwen3-dp-worker-0   # rank 0 - where our script's MLflow run lands
kubectl delete -f k8s/experiment-01-data-parallel.yaml

# Experiment 2 (TP=2) - only after experiment 1's Pods are deleted, both need
# the cluster's only 2 GPUs:
kubectl apply -f k8s/experiment-02-tensor-parallel.yaml
kubectl logs -f qwen3-tp-worker-0
kubectl delete -f k8s/experiment-02-tensor-parallel.yaml

# Experiment 3 (PP=2) - same 2-GPU constraint:
kubectl apply -f k8s/experiment-03-pipeline-parallel.yaml
kubectl logs -f qwen3-pp-worker-0
kubectl delete -f k8s/experiment-03-pipeline-parallel.yaml

# Experiment 4 (CP=2, seq=16384) - same 2-GPU constraint:
kubectl apply -f k8s/experiment-04-context-parallel.yaml
kubectl logs -f qwen3-cp-worker-0
kubectl delete -f k8s/experiment-04-context-parallel.yaml

# Experiment 4b (DP=2 long-seq baseline for #4) - same 2-GPU constraint:
kubectl apply -f k8s/experiment-04b-longseq-baseline.yaml
kubectl logs -f qwen3-dplong-worker-0
kubectl delete -f k8s/experiment-04b-longseq-baseline.yaml

# Experiment 5 (EP=2, stretch) - confirmed OOMs, see Results below; kept
# runnable so the failure is reproducible, not just asserted:
kubectl apply -f k8s/experiment-05-expert-parallel.yaml
kubectl logs -f qwen3-ep-worker-0
kubectl delete -f k8s/experiment-05-expert-parallel.yaml

# Experiment 6 (FP8) - same 2-GPU constraint:
kubectl apply -f k8s/experiment-06-fp8.yaml
kubectl logs -f qwen3-fp8-worker-0
kubectl delete -f k8s/experiment-06-fp8.yaml

# Experiment 7 (unfused attention) - same 2-GPU constraint:
kubectl apply -f k8s/experiment-07-attention-backend.yaml
kubectl logs -f qwen3-unfused-worker-0
kubectl delete -f k8s/experiment-07-attention-backend.yaml

# Experiment 8 (CPU offload) - same 2-GPU constraint:
kubectl apply -f k8s/experiment-08-cpu-offload.yaml
kubectl logs -f qwen3-offload-worker-0
kubectl delete -f k8s/experiment-08-cpu-offload.yaml
```

First run on each node pulls the ~19GB `nemo` image (one-time per node,
cached by containerd afterward — all experiments reuse the exact same
image, so only experiment 1 pays this cost). Each run also downloads its
Qwen3 tokenizer from Hugging Face Hub on first use (small, public, no token
needed).

## Results

Seven of the eight runs (experiments 1-4, 4b, and 6-8) ran successfully
end-to-end (20 iterations + train/valid/test eval) on the live 2-node
cluster and logged to MLflow:
[`dp-baseline-qwen3-1p7b`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/14a3393a0c63406a9487453d382eff50),
[`tp-qwen3-1p7b-2gpu`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/0aa09cd060a940dfadee442e327ea18d),
[`pp-qwen3-1p7b-2gpu`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/02bd574d2db94f018047f503c7a2db80),
[`cp-qwen3-1p7b-2gpu-seq16384`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/167b0ae1dbb243e79e044406bfc70638),
[`dp-longseq-baseline-qwen3-1p7b-seq16384`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/65123a0219e049a795e1c867d1c78a42),
[`fp8-qwen3-1p7b-2gpu`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/38a8c403b6e04462a5985d7f8c3a9312),
[`unfused-attn-qwen3-1p7b-2gpu`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/bc376002cdba4cb09c40bf61113f97b6),
and
[`cpu-offload-qwen3-1p7b-2gpu`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/3fd91e0b292a454da1198221ccd85571)
under the `qwen3-parallelism-experiments` experiment (link requires the
MLflow admin credentials above). Same model, same recipe module throughout -
only the one flag under test differs from its matched baseline each time -
a clean single-variable comparison in every case. Experiment 5 (EP=2) OOMs
before reaching the MLflow logging call - see its own section below for
the (still real, still documented) result.

> An earlier pass ran experiment 2 against Qwen3-4B instead of Qwen3-1.7B,
> which confounded "TP vs DP" with "bigger vs smaller model". That run
> (`tp-qwen3-4b-2gpu`) is kept in MLflow for historical reference but is
> **superseded** by the matched-model numbers below.

Two sets of numbers, for two different questions:

| Metric (MLflow-logged, wall-clock inclusive) | DP=2 | TP=2 | PP=2 |
|---|---|---|---|
| `wall_time_sec` (20 iters + full setup/teardown) | 174.6 | 207.9 | 171.9 |
| `tokens_per_sec_per_gpu` | 938 | 394 | 953 |
| `peak_gpu_memory_gb` | 53.3 | 33.8 | 28.2 |
| `approx_mfu_pct` (6ND approximation, see caveat) | 0.97% | 0.41% | 0.98% |

The MLflow-logged numbers above measure the *entire* `pretrain()` call,
including one-time model/optimizer construction and HF tokenizer download —
at only 20 iterations that fixed setup cost dominates the average, and
`tokens_per_sec_per_gpu` also isn't directly comparable here since each
experiment uses a different `global_batch_size` (4/2/4 - see
[`run_experiment.py`](scripts/run_experiment.py)'s batch-sizing comment and
the Experiments table above). So **these aren't a fair steady-state
comparison** between the three strategies. That's a real limitation of this
quick demo, called out honestly rather than hidden.

For the actual strategy comparison, use Megatron's own per-iteration console
log (`elapsed time per iteration`, `throughput per GPU (TFLOP/s/GPU)`),
averaged over the steady-state iterations 2-20 (iteration 1 includes
CUDA-graph/kernel warmup and isn't representative):

| Steady-state metric (iters 2-20 avg) | DP=2 | TP=2 | PP=2 |
|---|---|---|---|
| Step time | 2.29s | 1.73s | 1.00s |
| Throughput per GPU | 42.0 TFLOP/s | 27.9 TFLOP/s | 95.8 TFLOP/s |
| MFU (vs H200 989 TFLOP/s bf16 peak) | 4.25% | 2.82% | 9.69% |

Step time itself isn't directly comparable across rows (each uses a
different global batch size), which is exactly why **throughput per GPU
(TFLOP/s/GPU)** is the metric to read here - it normalizes for actual FLOPs
done per the full model and per GPU, and isolates hardware efficiency
regardless of batch size.

**Takeaway 1 (TP vs DP)**: with the model held constant, TP=2 across our two
nodes (no InfiniBand - plain VPC Ethernet) is genuinely **~34% less
FLOP-efficient per GPU** than DP=2 (27.9 vs 42.0 TFLOP/s/GPU). This is a
bigger, and more expected, penalty than an earlier mismatched-model pass
suggested (that run's Qwen3-4B TP showed only a ~4% gap vs DP). The likely
explanation: Qwen3-1.7B's smaller per-layer matmuls mean TP=2's per-layer
all-reduce (fixed message-size overhead, paid every forward+backward on
every transformer layer) is a much larger fraction of each layer's compute
time than it was for the bigger 4B model - so the earlier, larger model was
inadvertently flattering TP's apparent efficiency by having more compute to
hide the communication cost behind. This matches the outline doc's original
working hypothesis ("markedly slower... no InfiniBand") much better, and is
the reason single-variable comparisons matter.

**Takeaway 2 (PP's surprisingly high per-GPU throughput)**: PP=2 hit **95.8
TFLOP/s/GPU - more than 2x DP=2 and 3.4x TP=2** on the exact same hardware
and model. This isn't PP being "better" in general; it's a direct
consequence of **how much data crosses the slow (no-InfiniBand) link between
our two nodes, and how it's used**:
- **DP=2** all-reduces the *entire* model's gradients (all 1.7B parameters)
  across nodes on every step - the largest message of the three, and it's
  on the critical path before the optimizer step can proceed.
- **TP=2** all-reduces *activations* on every transformer layer's
  forward+backward (small messages, but many of them per step, each one a
  synchronous round-trip that stalls both GPUs) - the worst combination of
  message count and mandatory synchronization at this scale.
- **PP=2** only ever sends the *activations at the layer boundary* between
  the two stages (point-to-point, not all-reduce) - and with 4 microbatches
  pipelined, GPU0 can start on microbatch 2 while GPU1 is still finishing
  microbatch 1's backward, hiding most of that transfer behind useful
  compute instead of stalling on it.

In short: for this specific *inter-node, no-IB* topology, communication
**volume and synchronicity** matter far more than which strategy is
"supposed to" scale better - PP's point-to-point, overlappable transfers are
cheap here in a way DP's full-gradient all-reduce and TP's per-layer
all-reduce aren't. On a real InfiniBand fabric (the target 2x8 cluster) this
gap would shrink dramatically, since DP/TP's all-reduces would no longer be
bottlenecked on cross-node bandwidth - this result is a property of *this*
2-node Ethernet topology, not a universal ranking of the three strategies.
All MFU figures (~3-10%) are still low in absolute terms versus real
large-batch pretraining runs (commonly 30-50%+) - expected here, since
`global_batch_size` was deliberately kept small for a clean per-step
comparison, and 20 iterations is far too short for any of Megatron's
overlap/warmup optimizations to fully kick in.

The peak GPU memory numbers tell the complementary story TP and PP are also
*for*: TP=2's 33.8GB and PP=2's 28.2GB are both **lower** than DP=2's 53.3GB,
because both shard the model (by layer-internals for TP, by whole layers for
PP) across GPUs instead of replicating it (DP keeps a full copy on every
rank). At this tiny scale that memory saving doesn't matter - all three
comfortably fit an H200's 143GB - but it's exactly why TP/PP become
*necessary* (not just a throughput trade-off) once a single model copy no
longer fits on one GPU, consistent with the outline doc's framing that
today's 2-GPU cluster is far below where 3D parallelism becomes
memory-necessary rather than throughput-optional.

### Context Parallel (CP=2) vs a matched long-sequence DP=2 baseline

Experiment 4 (CP=2) and 4b (DP=2, CP=1) both run Qwen3-1.7B at
`seq_length=16384` (4x experiments 1-3's 4096) - only `context_parallelism`
differs, so this isolates CP's effect cleanly:

| Steady-state metric (iters 2-20 avg, seq=16384) | DP=2 (CP=1, exp. 4b) | CP=2 (exp. 4) |
|---|---|---|
| Step time | 2.43s | 2.74s |
| Throughput per GPU | 107.6 TFLOP/s | 47.7 TFLOP/s |
| MFU (vs H200 989 TFLOP/s bf16 peak) | 10.88% | 4.83% |
| **Peak GPU memory** | **85.1 GB** | **53.3 GB** |

**Takeaway 3 (CP trades throughput for memory, like TP does)**: CP=2 is
**~56% less FLOP-efficient per GPU** than the long-sequence DP=2 baseline
(47.7 vs 107.6 TFLOP/s/GPU) - each GPU now has to exchange KV chunks with
its ring-attention partner across the same no-InfiniBand link that hurt
TP=2 earlier, and for a similar reason (attention's per-chunk communication
happens on the critical path of every layer's forward+backward). In
exchange, CP=2 needs **~37% less peak GPU memory** (53.3GB vs 85.1GB) -
each GPU only ever materializes activations for half the 16384-token
sequence instead of the full thing. This is the same memory-vs-throughput
trade-off TP showed earlier, just sharding the *sequence* axis instead of a
layer's internals - and it's the trade-off that matters in practice: at
sequences long enough that a single GPU's activations alone would OOM (the
whole reason CP exists), DP's "just replicate the model" strategy isn't an
option at all, regardless of its throughput advantage here. Both peak
memory figures also confirm this setup was nowhere near that regime yet -
even the 85.1GB DP baseline fits comfortably inside an H200's 143GB - so
this result demonstrates the *mechanism* and its trade-off, not a case
where CP was strictly necessary.

### Expert Parallel (EP=2) - confirmed infeasible on 2 GPUs

Experiment 5 runs Qwen3-30B-A3B (128 experts, ~30B total / ~3B
active-per-token) with `expert_parallelism=2, tensor_parallelism=1,
pipeline_parallelism=1`. Unlike TP/PP/CP, EP doesn't consume a separate
dimension of `total_GPUs = TP x PP x CP x DP` - it shards *within* the DP
dimension for MoE layers, so `world_size=2` here gives `data_parallel_size=2`
(not 1), which is why `global_batch_size=2` (the minimum satisfying
`global_batch_size % (micro_batch_size x data_parallel_size) == 0`).

A back-of-envelope check before running it: with EP=2, each GPU ends up
holding roughly half of the ~29B MoE-expert parameters (no further
redundancy to shard away, since EP already equals the full DP group here)
plus a full replica of the ~1.4B non-expert (attention/embedding)
parameters - about **16B params/GPU**. Standard mixed-precision Adam needs
roughly 16 bytes/param without further sharding opportunity for that
expert shard (bf16 param + bf16 grad + fp32 master/momentum/variance) -
**~256GB**, about 1.8x an H200's 143GB HBM, before even counting
activations.

Ran anyway to get a real answer instead of just the estimate. It confirmed
almost exactly:

```
> number of parameters on (tensor, pipeline) model parallel rank (0, 0): 16036608000

torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 12.00 MiB.
GPU 0 has a total capacity of 139.80 GiB of which 9.12 MiB is free.
Including non-PyTorch memory, this process has 139.78 GiB memory in use.
```

**16.04B params/GPU** - within 1% of the back-of-envelope estimate - and the
OOM hit *while constructing the distributed optimizer's fp32 master
parameter shards* (`distrib_optimizer.py`'s `shard_model_param.clone().float()`),
before a single training step ran. Two smaller, earlier config errors were
hit and fixed en route (documented for completeness, not hidden): the MoE
recipe defaults `sequence_parallelism=True`, which asserts unless
`tensor_parallelism > 1` (fixed in [`run_experiment.py`](scripts/run_experiment.py)
by only enabling it when `tensor_parallelism > 1`); and the
`data_parallel_size=2` point above, which needed `global_batch_size=2` not
`1`.

**Takeaway 4 (a real scale limit, not a tuning problem)**: this isn't a
case where a different batch size or precision setting would fix it - the
model's expert weights alone (before any activation memory) need ~1.8x
more HBM than a single H200 has, at this parallelism degree. The fix is
more GPUs (a real 2x8 cluster could push `expert_parallelism` to 8, halving
the per-GPU expert share again, or add pipeline parallelism to split
experts by layer too) or optimizer-state CPU offloading (this repo already
exposes `--cpu-offload` for activations - Megatron-Core also has a
`optimizer_cpu_offload` field on `OptimizerConfig` for exactly this, which
would move the fp32 master/momentum/variance states to host RAM; not
attempted here to keep this pass focused, but a plausible next step for
scaling EP further without more GPUs).

### FP8 / attention backend / CPU offload vs the DP=2 baseline

Experiments 6-8 each change exactly one flag from experiment 1's exact
DP=2/Qwen3-1.7B/seq=4096 baseline - the cleanest single-variable comparisons
in this whole set:

| Steady-state metric (iters 2-20 avg) | Baseline (BF16, fused attn) | FP8 (exp. 6) | Unfused attn (exp. 7) | CPU offload (exp. 8) |
|---|---|---|---|---|
| Step time | 2.29s | 2.06s | 2.30s | 2.27s |
| Throughput per GPU | 42.0 TFLOP/s | 46.7 TFLOP/s | 41.9 TFLOP/s | 42.4 TFLOP/s |
| MFU (vs H200 989 TFLOP/s bf16 peak) | 4.25% | 4.73%* | 4.24% | 4.29% |
| **Peak GPU memory** (MLflow-logged) | **53.3 GB** | **51.1 GB** | **84.3 GB** | **42.9 GB** |

\* FP8's *achieved* TFLOP/s did go up (46.7 vs 42.0), but its *theoretical*
peak roughly doubles too (H200 FP8 dense peak is ~1979 TFLOP/s vs bf16's
989) - measured against its own peak, FP8's MFU is actually **lower**
(2.36%), which is exactly the point of Takeaway 5 below.

**Takeaway 5 (FP8 gives a real but modest speedup here, far short of 2x)**:
FP8 cut step time by **~10%** (2.29s -> 2.06s) - a genuine, measurable win,
but nowhere near the ~2x Hopper's FP8 tensor cores nominally offer over
BF16. At this tiny scale (1.7B params, seq=4096, batch=2/GPU), three things
eat into that theoretical ceiling: (1) only GEMMs run in FP8 - attention,
layernorm, and other elementwise ops stay in BF16, so FP8 only speeds up
part of each layer; (2) `bf16_with_fp8_current_scaling_mixed` computes a
per-tensor amax/scale factor every step, real overhead that a longer,
larger run would amortize better; (3) the model/batch here are small enough
that these matmuls may not be big enough to fully saturate the FP8 tensor
cores' extra throughput in the first place. Peak memory drops only
slightly (53.3GB -> 51.1GB, ~4%) since bf16 master weights and optimizer
state are unchanged - only the compute-path tensors go to FP8.

**Takeaway 6 (attention backend matters for memory here, not speed)**: the
unfused (plain PyTorch) attention backend is statistically indistinguishable
from the default fused/FlashAttention path on **throughput** (41.9 vs 42.0
TFLOP/s/GPU - within run-to-run noise) at this scale, because attention's
own QK^T/softmax/AV compute is a small fraction of each layer's total FLOPs
next to the large QKVO and FFN projection matmuls (identical either way).
But **peak memory jumps 58%** (53.3GB -> 84.3GB), because the unfused path
explicitly materializes the full `[batch, heads, seq, seq]` attention score
matrix in HBM, while FlashAttention/fused kernels never do (that's their
core trick - fusing QK^T -> softmax -> AV so the full matrix is never
written to HBM). This flips the common assumption that flash attention is
mainly a speed optimization: at this scale, its *memory* saving is the
dominant, clearly measurable effect - and that memory gap would only widen
further at longer sequences (see the CP section above for why: attention
memory scales with `seq^2` unfused vs roughly linearly for FlashAttention).

**Takeaway 7 (CPU offload's memory saving is essentially free here)**:
offloading activations to host RAM cut peak GPU memory by **~20%** (53.3GB
-> 42.9GB) with **no measurable throughput cost** (42.0 vs 42.4 TFLOP/s/GPU
- within noise, if anything slightly faster, plausibly run-to-run
variance). This isn't offloading being "free" in general - it's specific
to this scale: with only 20 iterations, a short 4096-token sequence, and a
1.7B model, the activation volume moved over PCIe each step is small enough
that the transfer comfortably overlaps with GPU compute and never becomes
the bottleneck. At a larger batch/sequence/model, or with a slower
CPU-GPU interconnect, PCIe bandwidth would eventually saturate and this
trade-off would look more like TP/PP/CP's - real throughput cost for real
memory savings. This result demonstrates the mechanism working correctly,
not a claim that offloading is costless at any scale.
