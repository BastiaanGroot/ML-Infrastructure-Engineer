# ML Infrastructure Engineer — Take-Home

PoC for the [ML Infrastructure Engineer take-home assignment](docs/ML-Infrastructure-Engineer.md):
validate a Nebius GPU cluster's capabilities, then run multi-node LLM
training on it (Option 1) on **16x H100 GPUs** (2 nodes x 8, InfiniBand, see
[Hardware](#hardware-2x8-h100-with-infiniband)), a 2TB SSD network disk and a 2TB SSD
shared filesystem.

**Nebius project:** [`ml-infra-poc`](https://console.nebius.com/project-e00rdtrppr0083wkrkw4td) (tenant `csa-hiring-sandbox2`)

## Reproduce from scratch

Each step links to the README with the details. Values specific to this
project (project ID, registry ID, SecretStash secret IDs, MLflow endpoint)
appear in those READMEs; in a new project, take them from `terraform output`
or the Nebius CLI instead, as noted in each step.

1. **Infrastructure** ([`infra/`](infra/README.md#usage)): network, mk8s
   cluster with 2x8 H100 on an InfiniBand GPU cluster, shared filesystem,
   container registry, logs bucket, managed MLflow and the dashboard VM.
   ```bash
   cd infra && terraform init
   terraform apply -var="project_id=<project-id>" -var="enable_mlflow=true" -var="enable_dashboard=true"
   nebius mk8s cluster get-credentials --id "$(terraform output -raw cluster_id)" --external
   ```
   Store the generated MLflow admin password in SecretStash as described in
   [infra/README.md "MLflow"](infra/README.md#mlflow-for-option-1-experiment-tracking).
2. **Validator image** ([`cluster-validator/`](cluster-validator/README.md#build--push)):
   build and push to your registry (`terraform output registry_id`, without
   the `registry-` prefix), then update the image in `cluster-validator/k8s/*.yaml`.
3. **Validate the cluster** ([run on the cluster](cluster-validator/README.md#run-on-the-cluster)):
   create the pull, logs-upload and SSH Secrets, then run the per-node Job
   (`job-validate.yaml`) and the cross-node InfiniBand Job
   (`job-validate-multinode.yaml`). Results appear in the Job logs and on the
   `cluster-validator` [Grafana dashboard](cluster-validator/README.md#grafana-dashboard).
4. **Training data** ([`training/`](training/README.md#end-to-end-run-qwen3-17b-on-fineweb-edu)):
   `kubectl apply -f training/k8s/prepare-data.yaml` downloads FineWeb-Edu to
   the network disk and tokenizes it onto the shared filesystem (~5 min).
5. **Train** ([`training/`](training/README.md#running)): create the
   `mlflow-creds` Secret, set `MLFLOW_TRACKING_URI` in `training/launch.py` to
   `terraform output mlflow_tracking_endpoint`, then
   `./training/launch.py e2e-q1p7b` for the end-to-end run or any
   experiment from `./training/launch.py --list`.
6. **Monitor**: loss and throughput in MLflow, GPU metrics and logs in the
   cluster's Grafana ([docs/observability.md](docs/observability.md)), and the
   results [dashboard](dashboard/README.md) (`terraform output dashboard_url`).

## Infrastructure as Code

[`infra/`](infra/) has Terraform to reproduce the setup (network, mk8s cluster, GPU node group, shared filesystem, container registry, Object Storage logs bucket, plus flag-gated managed MLflow and the dashboard VM) from scratch in a Nebius project — applied and drift-free against the live PoC project. See its [README](infra/README.md).

## Cluster Validator

[`cluster-validator/`](cluster-validator/) is a lightweight, portable container that checks every node's GPU health, NVLink bandwidth, PyTorch/LLM stack and storage throughput, plus NCCL bandwidth across both nodes over InfiniBand, before running training jobs on the cluster. See its [README](cluster-validator/README.md) for build, push, run instructions and results.

## Training (Option 1)

[`docs/training-strategy-outline.md`](docs/training-strategy-outline.md) designs the full distributed-training strategy for Qwen3 (600M through the genuine >100B 235B-A22B MoE) and maps model size to NVIDIA-recommended TP/PP/CP/EP degrees and GPU counts. [`training/`](training/) runs the part of it that fits on the 16x H100 cluster:

- An **end-to-end run**: Qwen3-1.7B pretrained on ~1B tokens of FineWeb-Edu across both nodes, with checkpoints on the shared filesystem and a resume after a simulated failure.
- **Single-variable experiments** on Qwen3-1.7B/8B/32B and Qwen3-30B-A3B covering DP, TP, PP, CP, EP, 3D parallelism, FP8, attention backend, CPU offloading and activation recomputation, plus NVLink and InfiniBand NCCL bandwidth sweeps and Nsight Systems profiles.

Everything is logged to MLflow. See the [README](training/README.md#results) for the results.

[`dashboard/`](dashboard/) is a Streamlit app over those results (live from MLflow): strategy comparison, NCCL/Nsight communication view, and an analytical TP x PP x DP planner validated against the measured runs. Hosted on a Terraform-managed VM (public, no auth for now) — see its [README](dashboard/README.md).

## Nebius MCP Server

This repo has the [Nebius MCP Server](https://github.com/nebius/mcp-server) configured for Cursor (see `.cursor/mcp.json`, run via a self-contained `uvx` invocation — no local install needed), letting the agent query and manage Nebius Cloud resources directly — e.g. list/create compute instances, manage storage buckets, and look up available platforms.

## Design Choices

Choices made for the [take-home exercise](docs/ML-Infrastructure-Engineer.md), informed by the [Nebius services overview](docs/nebius-services-overview.md).

- **Option 1 (training).** The customer's first goal is training their own LLM, and the 512-H100 reservation is sized for it. Option 2 (inference) is out of scope for this PoC.
- Scheduler — **plain Kubernetes** (Nebius mk8s): multi-node jobs are Indexed Jobs running `torchrun` (training) or `mpirun` over SSH (the cross-node validator), with no Slurm, training operator or MPI Operator on top.
- Storage — both 2TB volumes are in use and benchmarked (see [cluster-validator/README.md#results-last-validated-run](cluster-validator/README.md#results-last-validated-run)). The **network disk** (PVC, `compute-csi-default-sc`) is per-job scratch: the raw dataset download, and each validator pod's storage test. The **shared filesystem** (`virtiofs`, mounted on every GPU node, ~7x faster in `fio`) holds what every node reads or writes: the tokenized dataset, the HF cache and the training checkpoints.
- Benchmark methodology — not running the actual **MLPerf** suite itself (its fixed reference models/datasets and submission/compliance process are a mismatch for a "lightweight, portable" validator and this exercise's scope), but using its metric *definitions* (throughput per accelerator, time-to-train) as the reference vocabulary for the distribution-strategy comparisons, so efficiency numbers are explainable in industry-standard terms on demo day.
- Metrics/observability stack — **Nebius-hosted** (Metrics/Logs/Traces): native Monitoring (PromQL) + Logging (LogQL), fed by the Nebius Observability Agent for Kubernetes, visualized in Grafana. See [docs/observability.md](docs/observability.md).
- Run logs (e.g. `summary.json`) — optionally uploaded to a Nebius **Object Storage** bucket (`ml-infra-poc-logs`) for retention past Logging's 14-day default; see [cluster-validator/README.md](cluster-validator/README.md#uploading-logs-to-object-storage).
- Training framework — **NVIDIA NeMo Framework / Megatron-Bridge (Megatron-Core)** over plain FSDP2/DeepSpeed-ZeRO: FSDP/ZeRO shard memory across data-parallel ranks but don't split individual layers/matmuls (tensor parallelism), layers across GPUs (pipeline parallelism), the sequence dimension (context parallelism), or expert routing (expert parallelism) — all first-class in Megatron-Core and necessary building blocks for genuine +100B training. Matches the vacancy doc's explicit mention of Megatron-LM. See [docs/training-strategy-outline.md](docs/training-strategy-outline.md).
- Model family — **Qwen3** (dense 600M-32B + MoE 30B-A3B/235B-A22B): Apache-2.0, first-class Megatron-Bridge support, and the only family in scope that exercises every strategy above within one lineage, with 235B-A22B as the genuine >100B target.

## Hardware: 2x8 H100 with InfiniBand

*(This is the single canonical note on this — other docs just link here.)*

The GPU node group runs **2 nodes x 8 H100** (`gpu-h100-sxm`,
`8gpu-128vcpu-1600gb`, 16 GPUs total), attached to a
`nebius_compute_v1_gpu_cluster` on **`fabric-4`** so the nodes share an
InfiniBand fabric (see [`infra/main.tf`](infra/main.tf)). fabric-4 was picked
because `nebius capacity resource-advice list` showed full on-demand
availability for this preset there (4/4 VMs, "high"), the most spare
capacity of the H100 fabrics in `eu-north1`. Tenant quota is 32 H100s.

Each node has 8 `mlx5` InfiniBand HCAs, one per GPU on the same PCIe switch.
The nodes don't advertise RDMA devices to Kubernetes, so training pods run
**privileged with the host's `/dev/infiniband` mounted**
([`training/k8s/worker.yaml.tmpl`](training/k8s/worker.yaml.tmpl)). NCCL then
uses `NET/IB` with GPUDirect RDMA on all 8 NICs, with no socket fallback.
Measured `all_reduce` bus bandwidth at 1 GiB: **468 GB/s** over NVLink within
a node, **442 GB/s** across all 16 GPUs, and **46 GB/s** for one GPU per node
over a single 400 Gb/s NIC (see
[`training/README.md`](training/README.md#nccl-bandwidth)). The
alternative, `gpu_settings.dra=true` on the node group (Nebius's managed
DRA network driver), wasn't needed.

Privileged containers see every GPU on the node, whatever they requested, so
each training pod claims the whole node and uses only its first `NPROC` GPUs.
