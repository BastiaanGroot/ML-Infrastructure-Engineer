# Training (Option 1): Qwen3 distributed-strategy experiments

Small-scale, real implementation of the design in
[`docs/training-strategy-outline.md`](../docs/training-strategy-outline.md) —
two experiments that fit exactly on the current live **2 nodes x 1 GPU**
cluster, comparing Data Parallelism vs Tensor Parallelism head-to-head, with
results logged to the live MLflow tracking server. Both completed
successfully on the real cluster — see [Results](#results).

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

Both use Megatron-Bridge's own Qwen3 recipe modules unmodified (not
hand-tuned configs) — see
[`docs/training-strategy-outline.md`](../docs/training-strategy-outline.md#recipe-table)
for where these sit in the full size/strategy table. Both use synthetic
(`mock=True`) data, a deliberate simplification (see the outline doc) — this
measures parallelism/infra mechanics (throughput, memory, step time), not a
trained checkpoint.

| # | Manifest | Model | Recipe module | Strategy | GPUs |
|---|---|---|---|---|---|
| 1 | [`k8s/experiment-01-data-parallel.yaml`](k8s/experiment-01-data-parallel.yaml) | Qwen3-1.7B | `megatron.bridge.recipes.qwen.qwen3_1p7b` | DP=2 (TP=1/PP=1 x2 replicas) | 2 |
| 2 | [`k8s/experiment-02-tensor-parallel.yaml`](k8s/experiment-02-tensor-parallel.yaml) | Qwen3-1.7B | `megatron.bridge.recipes.qwen.qwen3_1p7b` | TP=2/PP=1 | 2 |

Both rows use the exact same model and recipe module - `tensor_parallelism`
is the only thing that differs between them, so this is a genuine
single-variable comparison of DP vs TP. (An earlier pass ran experiment 2
against Qwen3-4B instead; that made the two runs harder to compare
apples-to-apples, so it was superseded by this matched-model rerun - see
[Results](#results).)

Both manifests define a headless `Service` + 2 plain `Pod`s (rank 0 / rank 1)
running `torchrun` directly — deliberately **no new operator** (avoids
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

Global/micro batch sizes are set per-experiment so each GPU processes the
same per-step work in both runs (`global_batch_size = micro_batch_size *
data_parallel_size`, no gradient accumulation) — an apples-to-apples
comparison of the two strategies rather than the recipes' out-of-the-box
(larger) defaults. Both also override the recipe's default 500-iteration LR
warmup down to 0, since this is a 20-iteration mechanism demo, not a real
convergence run.

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
```

First run on each node pulls the ~19GB `nemo` image (one-time per node,
cached by containerd afterward — both experiments reuse the exact same
image, so only experiment 1 pays this cost). Each run also downloads its
Qwen3 tokenizer from Hugging Face Hub on first use (small, public, no token
needed).

## Results

Both experiments ran successfully end-to-end (20 iterations + train/valid/test
eval) on the live 2-node cluster and logged to MLflow:
[`dp-baseline-qwen3-1p7b`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/14a3393a0c63406a9487453d382eff50) and
[`tp-qwen3-1p7b-2gpu`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/0aa09cd060a940dfadee442e327ea18d)
under the `qwen3-parallelism-experiments` experiment (link requires the
MLflow admin credentials above). Same model, same recipe module, only
`tensor_parallelism` differs - a clean single-variable comparison.

> An earlier pass ran experiment 2 against Qwen3-4B instead of Qwen3-1.7B,
> which confounded "TP vs DP" with "bigger vs smaller model". That run
> (`tp-qwen3-4b-2gpu`) is kept in MLflow for historical reference but is
> **superseded** by the matched-model numbers below.

Two sets of numbers, for two different questions:

| Metric (MLflow-logged, wall-clock inclusive) | DP=2 (Qwen3-1.7B) | TP=2 (Qwen3-1.7B) |
|---|---|---|
| `wall_time_sec` (20 iters + full setup/teardown) | 174.6 | 207.9 |
| `tokens_per_sec_per_gpu` | 938 | 394 |
| `peak_gpu_memory_gb` | 53.3 | 33.8 |
| `approx_mfu_pct` (6ND approximation, see caveat) | 0.97% | 0.41% |

The MLflow-logged numbers above measure the *entire* `pretrain()` call,
including one-time model/optimizer construction and HF tokenizer download —
at only 20 iterations that fixed setup cost dominates the average, and
`tokens_per_sec_per_gpu` also isn't directly comparable here since DP's
`global_batch_size=4` pushes twice the tokens/step through the same fixed
overhead as TP's `global_batch_size=2` (see [`run_experiment.py`](scripts/run_experiment.py)'s
batch-sizing comment). So **these aren't a fair steady-state comparison**
between the two strategies. That's a real limitation of this quick demo,
called out honestly rather than hidden.

For the actual strategy comparison, use Megatron's own per-iteration console
log (`elapsed time per iteration`, `throughput per GPU (TFLOP/s/GPU)`),
averaged over the steady-state iterations 2-20 (iteration 1 includes
CUDA-graph/kernel warmup and isn't representative):

| Steady-state metric (iters 2-20 avg) | DP=2 (Qwen3-1.7B) | TP=2 (Qwen3-1.7B) |
|---|---|---|
| Step time | 2.29s | 1.73s |
| Throughput per GPU | 42.0 TFLOP/s | 27.9 TFLOP/s |
| MFU (vs H200 989 TFLOP/s bf16 peak) | 4.25% | 2.82% |

Step time itself isn't directly comparable across the two rows either (TP's
step covers half the global batch DP's does), which is exactly why
**throughput per GPU (TFLOP/s/GPU)** is the metric to read here - it
normalizes for actual FLOPs done and isolates hardware efficiency.

**Takeaway**: with the model held constant, TP=2 across our two nodes (no
InfiniBand - plain VPC Ethernet) is genuinely **~34% less FLOP-efficient
per GPU** than DP=2 (27.9 vs 42.0 TFLOP/s/GPU). This is a bigger, and more
expected, penalty than the earlier mismatched-model pass suggested (that
run's Qwen3-4B TP showed only a ~4% gap vs DP). The likely explanation:
Qwen3-1.7B's smaller per-layer matmuls mean TP=2's per-layer all-reduce
(fixed message-size overhead, paid every forward+backward on every
transformer layer) is a much larger fraction of each layer's compute time
than it was for the bigger 4B model - so the earlier, larger model was
inadvertently flattering TP's apparent efficiency by having more compute to
hide the communication cost behind. This matches the outline doc's original
working hypothesis ("markedly slower... no InfiniBand") much better, and is
the reason single-variable comparisons matter. Both MFU figures (~3-4%) are
still low in absolute terms versus real large-batch pretraining runs
(commonly 30-50%+) - expected here, since `global_batch_size` was
deliberately shrunk to remove gradient accumulation for a clean per-step
comparison, and 20 iterations is far too short for any of Megatron's
overlap/warmup optimizations to fully kick in.

The peak GPU memory numbers tell the complementary story TP is *for*: TP=2's
33.8GB is **lower** than DP=2's 53.3GB, because TP shards the model's
parameters/activations across both GPUs instead of replicating them (DP
keeps a full copy on every rank). At this tiny scale that memory saving
doesn't matter - both comfortably fit an H200's 143GB - but it's exactly
why TP becomes *necessary* (not just a throughput trade-off) once a single
model copy no longer fits on one GPU, consistent with the outline doc's
framing that today's 2-GPU cluster is far below where 3D parallelism
becomes memory-necessary rather than throughput-optional.

## Deferred / stretch goals

Not attempted in this pass — see
[`docs/training-strategy-outline.md`](../docs/training-strategy-outline.md#deferred--stretch-not-attempted-this-pass)
for the reasoning:

- **Expert Parallelism** (Qwen3-30B-A3B, EP=2) — recipe exists, not yet run.
- **Context Parallelism** (CP=2, long sequence) — recipe exists, not yet run.
- **Pipeline Parallelism** (PP>1) — our 2 GPUs are fully spent on the DP/TP
  comparison above.
