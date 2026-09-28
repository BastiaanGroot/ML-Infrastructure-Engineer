# ML Infrastructure Engineer — Take-Home

PoC for the [ML Infrastructure Engineer take-home assignment](docs/ML-Infrastructure-Engineer.md):
validate a Nebius GPU cluster's capabilities, then run a training/inference
workload on it (spec: 16x H200 GPUs, 2TB SSD network disk, 2TB SSD shared filesystem;
the live cluster uses 16x H100 over InfiniBand instead, see [Hardware](#hardware-2x8-h100-with-infiniband)).

**Nebius project:** [`ml-infra-poc`](https://console.nebius.com/project-e00rdtrppr0083wkrkw4td) (tenant `csa-hiring-sandbox2`)

## Infrastructure as Code

[`infra/`](infra/) has Terraform to reproduce the setup (network, mk8s cluster, GPU node group, shared filesystem, container registry, Object Storage logs bucket, plus flag-gated managed MLflow and the dashboard VM) from scratch in a Nebius project — applied and drift-free against the live PoC project. See its [README](infra/README.md).

## Cluster Validator

[`cluster-validator/`](cluster-validator/) is a lightweight, portable container that checks GPU health, NCCL/GPU-interconnect bandwidth, and storage throughput before running training/inference jobs on the cluster. See its [README](cluster-validator/README.md) for build, push, and run instructions.

## Training (Option 1)

[`docs/training-strategy-outline.md`](docs/training-strategy-outline.md) designs the full distributed-training strategy for Qwen3 (600M through the genuine >100B 235B-A22B MoE) for the 2x8-GPU/InfiniBand cluster (now live), mapping model size to NVIDIA-recommended TP/PP/CP/EP degrees and GPU counts. [`training/`](training/) then implements and runs a small, honest subset of that outline on the earlier 2x1 H200 cluster — single-variable experiments on Qwen3 covering DP, TP, PP, CP, EP, FP8, attention backend, CPU offloading, a cross-node NCCL bandwidth sweep, and Nsight Systems profiles, logged to MLflow. See its [README](training/README.md#results) for the results.

[`dashboard/`](dashboard/) is a Streamlit app over those results (live from MLflow): strategy comparison, NCCL/Nsight communication view, and an analytical TP x PP x DP planner validated against the measured runs. Hosted on a Terraform-managed VM (public, no auth for now) — see its [README](dashboard/README.md).

## Nebius MCP Server

This repo has the [Nebius MCP Server](https://github.com/nebius/mcp-server) configured for Cursor (see `.cursor/mcp.json`, run via a self-contained `uvx` invocation — no local install needed), letting the agent query and manage Nebius Cloud resources directly — e.g. list/create compute instances, manage storage buckets, and look up available platforms.

## Design Choices

Decisions to make (and record, once made) while executing the [take-home exercise](docs/ML-Infrastructure-Engineer.md), informed by the [Nebius services overview](docs/nebius-services-overview.md).

- [x] Option 1 (training) vs. Option 2 (inference) — starting with **training** (Option 1), inference (Option 2) to follow later.
- [x] Scheduler: Soperator (Slurm) vs. Kubernetes — going with **plain Kubernetes-native scheduling**. Wanted to explore Soperator, but it requires a GPU capacity *reservation* (not just quota) that isn't currently available — asked Nebius for clarification, may revisit.
- [x] Storage split across the 2TB network disk vs. 2TB shared filesystem — both provisioned and benchmarked (see [cluster-validator/README.md#results-last-validated-run](cluster-validator/README.md#results-last-validated-run)): network disk (PVC, `compute-csi-default-sc`) as per-job/per-pod scratch, shared filesystem (`virtiofs`, mounted on every GPU node, ~10x faster in `fio`) for shared checkpoints/data across nodes.
- [ ] Use the **vLLM** turnkey Application, or a custom-built inference server, for Option 2 — needs further exploration before deciding.
- [x] Benchmark methodology — not running the actual **MLPerf** suite itself (its fixed reference models/datasets and submission/compliance process are a mismatch for a "lightweight, portable" validator and this exercise's scope), but using its metric *definitions* as the reference vocabulary for Option 1/2 results — e.g. throughput per accelerator and time-to-train for Option 1's distribution-strategy comparisons, p50/p99 latency + throughput for Option 2's two configs — so efficiency numbers are explainable in industry-standard terms on demo day.
- [x] Metrics/observability stack — **Nebius-hosted** (Metrics/Logs/Traces): native Monitoring (PromQL) + Logging (LogQL), fed by the Nebius Observability Agent for Kubernetes, visualized in Grafana. See [docs/observability.md](docs/observability.md).
- [x] Run logs (e.g. `summary.json`) — optionally uploaded to a Nebius **Object Storage** bucket (`ml-infra-poc-logs`) for retention past Logging's 14-day default; see [cluster-validator/README.md](cluster-validator/README.md#uploading-logs-to-object-storage).
- [x] Training framework — **NVIDIA NeMo Framework / Megatron-Bridge (Megatron-Core)** over plain FSDP2/DeepSpeed-ZeRO: FSDP/ZeRO shard memory across data-parallel ranks but don't split individual layers/matmuls (tensor parallelism), layers across GPUs (pipeline parallelism), the sequence dimension (context parallelism), or expert routing (expert parallelism) — all first-class in Megatron-Core and necessary building blocks for genuine +100B training. Matches the vacancy doc's explicit mention of Megatron-LM. See [docs/training-strategy-outline.md](docs/training-strategy-outline.md).
- [x] Model family — **Qwen3** (dense 600M-32B + MoE 30B-A3B/235B-A22B): Apache-2.0, first-class Megatron-Bridge support, and the only family in scope that exercises every strategy above within one lineage, with 235B-A22B as the genuine >100B target.

## Hardware: 2x8 H100 with InfiniBand

*(This is the single canonical note on this — other docs just link here.)*

**Now:** the GPU node group runs **2 nodes x 8 H100** (`gpu-h100-sxm`,
`8gpu-128vcpu-1600gb`, 16 GPUs total), attached to a
`nebius_compute_v1_gpu_cluster` on **`fabric-4`** so the nodes share an
InfiniBand fabric (see [`infra/main.tf`](infra/main.tf)). fabric-4 was picked
because `nebius capacity resource-advice list` showed full on-demand
availability for this preset there (4/4 VMs, "high"), the most spare
capacity of the H100 fabrics in `eu-north1`. Tenant quota is 32 H100s.

**Before:** until 2026-09-28 the cluster ran **2 nodes x 1 H200**
(`gpu-h200-sxm`, `1gpu-16vcpu-200gb`), with no InfiniBand, because 8-GPU H200
nodes weren't available. Every result recorded so far in
[`training/README.md`](training/README.md#results) and
[`cluster-validator/README.md`](cluster-validator/README.md#results-last-validated-run)
comes from that cluster, where cross-node traffic went over plain Ethernet
(~2.35 GB/s measured).

**Still to do on the new cluster:**

1. Confirm pods can actually use InfiniBand. The nodes don't advertise
   InfiniBand/RDMA devices to Kubernetes, so pods probably need
   `/dev/infiniband` access (privileged, or a device plugin) for NCCL to use
   it rather than falling back to sockets.
2. Install the [MPI Operator](https://github.com/kubeflow/mpi-operator) and
   run `cluster-validator/k8s/job-nccl-multinode.yaml` (written, never run)
   for a real InfiniBand bandwidth number. Nebius Solutions Library's
   [`modules/nccl-test`](https://github.com/nebius/nebius-solutions-library/tree/main/modules/nccl-test)
   shows how to install it from Terraform.
3. Re-run the training experiments at 8 GPUs per node (update the
   `training/k8s/` manifests' `nproc_per_node` and GPU requests).
