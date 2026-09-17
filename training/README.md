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
| 2 | [`k8s/experiment-02-tensor-parallel.yaml`](k8s/experiment-02-tensor-parallel.yaml) | Qwen3-4B | `megatron.bridge.recipes.qwen.qwen3_4b` | TP=2/PP=1 | 2 |

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
[`tp-qwen3-4b-2gpu`](https://public-tracking-e00-qq5esxe7w0zwk32-tyaqmja4khghyam-mlflow.gw.msp.eu-north1.nebius.cloud/#/experiments/1/runs/16bdeb9f518b43aca88dc4c815815786)
under the `qwen3-parallelism-experiments` experiment (link requires the
MLflow admin credentials above).

Two sets of numbers, for two different questions:

| Metric (MLflow-logged, wall-clock inclusive) | DP=2 (Qwen3-1.7B) | TP=2 (Qwen3-4B) |
|---|---|---|
| `wall_time_sec` (20 iters + full setup/teardown) | 174.6 | 383.7 |
| `tokens_per_sec_per_gpu` | 938 | 213 |
| `peak_gpu_memory_gb` | 53.3 | 65.3 |
| `approx_mfu_pct` (6ND approximation, see caveat) | 0.97% | 0.52% |

The MLflow-logged numbers above measure the *entire* `pretrain()` call,
including one-time model/optimizer construction and HF tokenizer download —
at only 20 iterations that fixed setup cost (roughly 150s for DP, longer for
TP's bigger 4B model + validation/test eval passes) dominates the average,
so **these aren't a fair steady-state comparison** between the two
strategies. That's a real limitation of this quick demo, called out
honestly rather than hidden.

For the actual strategy comparison, use Megatron's own per-iteration console
log (`elapsed time per iteration`, `throughput per GPU (TFLOP/s/GPU)`),
averaged over the steady-state iterations 2-20 (iteration 1 includes
CUDA-graph/kernel warmup and isn't representative):

| Steady-state metric (iters 2-20 avg) | DP=2 (Qwen3-1.7B) | TP=2 (Qwen3-4B) |
|---|---|---|
| Step time | 2.29s | 2.83s |
| Throughput per GPU | 42.0 TFLOP/s | 40.3 TFLOP/s |
| MFU (vs H200 989 TFLOP/s bf16 peak) | 4.25% | 4.07% |

**Takeaway**: TP=2 across our two nodes (no InfiniBand — plain VPC Ethernet)
is only **~23% slower per step** than DP=2, and reaches comparable per-GPU
FLOP efficiency (~40 vs ~42 TFLOP/s/GPU). This is a more modest penalty than
the outline doc's working hypothesis ("markedly slower... no InfiniBand")
predicted going in — plausible explanation: at this model size (4B) and
per-GPU batch (micro_batch_size=2, seq_length=4096), TP=2's per-layer
all-reduce message size is small enough that even plain cross-node Ethernet
within the same VPC doesn't bottleneck it badly. This would very likely
change at larger TP degrees (4, 8) or larger hidden sizes, where per-layer
communication volume grows - exactly the case InfiniBand exists to solve,
per the outline doc's 32B/8-GPU and 235B-A22B/128-GPU recipe rows, both of
which specify TP=4/8. Both MFU figures (~4%) are also low in absolute terms
versus real large-batch pretraining runs (commonly 30-50%+) - expected here,
since `global_batch_size` was deliberately shrunk to remove gradient
accumulation for a clean per-step comparison, and 20 iterations is far too
short for any of Megatron's overlap/warmup optimizations to fully kick in.

Both peak GPU memory figures (53GB DP / 65GB TP) comfortably fit an H200's
143GB, consistent with the outline doc's framing that today's 2-GPU cluster
is far below where 3D parallelism becomes memory-necessary rather than
throughput-optional.

## Deferred / stretch goals

Not attempted in this pass — see
[`docs/training-strategy-outline.md`](../docs/training-strategy-outline.md#deferred--stretch-not-attempted-this-pass)
for the reasoning:

- **Expert Parallelism** (Qwen3-30B-A3B, EP=2) — recipe exists, not yet run.
- **Context Parallelism** (CP=2, long sequence) — recipe exists, not yet run.
- **Pipeline Parallelism** (PP>1) — our 2 GPUs are fully spent on the DP/TP
  comparison above.
