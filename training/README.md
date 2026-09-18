# Training (Option 1): Qwen3 distributed-strategy experiments

Small-scale, real implementation of the design in
[`docs/training-strategy-outline.md`](../docs/training-strategy-outline.md) —
single-variable experiments that fit exactly on the current live **2 nodes x
1 GPU** cluster, comparing Data/Tensor/Pipeline/Context Parallelism
head-to-head, with results logged to the live MLflow tracking server. All
completed successfully on the real cluster — see [Results](#results).

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
"Bus error".

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
```

First run on each node pulls the ~19GB `nemo` image (one-time per node,
cached by containerd afterward — all experiments reuse the exact same
image, so only experiment 1 pays this cost). Each run also downloads its
Qwen3 tokenizer from Hugging Face Hub on first use (small, public, no token
needed).

## Results

All five runs (experiments 1-4 plus 4b) ran successfully end-to-end (20
iterations + train/valid/test eval) on the live 2-node cluster and logged to
MLflow:
[`dp-baseline-qwen3-1p7b`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/14a3393a0c63406a9487453d382eff50),
[`tp-qwen3-1p7b-2gpu`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/0aa09cd060a940dfadee442e327ea18d),
[`pp-qwen3-1p7b-2gpu`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/02bd574d2db94f018047f503c7a2db80),
[`cp-qwen3-1p7b-2gpu-seq16384`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/167b0ae1dbb243e79e044406bfc70638),
and
[`dp-longseq-baseline-qwen3-1p7b-seq16384`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/65123a0219e049a795e1c867d1c78a42)
under the `qwen3-parallelism-experiments` experiment (link requires the
MLflow admin credentials above). Same model, same recipe module throughout -
only the parallelism degree (and, for 4/4b, sequence length) under test
differs - a clean single-variable comparison in each case.

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

## Deferred / stretch goals

Not attempted in this pass — see
[`docs/training-strategy-outline.md`](../docs/training-strategy-outline.md#deferred--stretch-not-attempted-this-pass)
for the reasoning:

- **Expert Parallelism** (Qwen3-30B-A3B, EP=2) — recipe exists, not yet run.
