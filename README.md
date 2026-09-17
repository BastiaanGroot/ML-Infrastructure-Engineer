# ML Infrastructure Engineer — Take-Home

PoC for the [ML Infrastructure Engineer take-home assignment](docs/ML-Infrastructure-Engineer.md):
validate a Nebius GPU cluster's capabilities, then run a training/inference
workload on it (16x H200 GPUs, 2TB SSD network disk, 2TB SSD shared filesystem).

**Nebius project:** [`ml-infra-poc`](https://console.nebius.com/project-e00rdtrppr0083wkrkw4td) (tenant `csa-hiring-sandbox2`)

## Infrastructure as Code

[`infra/`](infra/) has Terraform to reproduce the setup (network, mk8s cluster, GPU node group, shared filesystem, container registry, Object Storage logs bucket) from scratch in a Nebius project — applied and drift-free against the live PoC project. See its [README](infra/README.md).

## Cluster Validator

[`cluster-validator/`](cluster-validator/) is a lightweight, portable container that checks GPU health, NCCL/GPU-interconnect bandwidth, and storage throughput before running training/inference jobs on the cluster. See its [README](cluster-validator/README.md) for build, push, and run instructions.

## Nebius MCP Server

This repo has the [Nebius MCP Server](https://github.com/nebius/mcp-server) configured for Cursor (see `.cursor/mcp.json`, run via a self-contained `uvx` invocation — no local install needed), letting the agent query and manage Nebius Cloud resources directly — e.g. list/create compute instances, manage storage buckets, and look up available platforms.

## Design Choices

Decisions to make (and record, once made) while executing the [take-home exercise](docs/ML-Infrastructure-Engineer.md), informed by the [Nebius services overview](docs/nebius-services-overview.md).

- [x] Option 1 (training) vs. Option 2 (inference) — starting with **training** (Option 1), inference (Option 2) to follow later.
- [x] Scheduler: Soperator (Slurm) vs. Kubernetes — going with **plain Kubernetes-native scheduling**. Wanted to explore Soperator, but it requires a GPU capacity *reservation* (not just quota) that isn't currently available — asked Nebius for clarification, may revisit.
- [x] Storage split across the 2TB network disk vs. 2TB shared filesystem — both provisioned and benchmarked (see [cluster-validator/README.md#results-last-validated-run](cluster-validator/README.md#results-last-validated-run)): network disk (PVC, `compute-csi-default-sc`) as per-job/per-pod scratch, shared filesystem (`virtiofs`, mounted on every GPU node, ~10x faster in `fio`) for shared checkpoints/data across nodes.
- [ ] Use the **vLLM** turnkey Application, or a custom-built inference server, for Option 2 — needs further exploration before deciding.
- [x] Metrics/observability stack — **Nebius-hosted** (Metrics/Logs/Traces): native Monitoring (PromQL) + Logging (LogQL), fed by the Nebius Observability Agent for Kubernetes, visualized in Grafana. See [docs/observability.md](docs/observability.md).
- [x] Run logs (e.g. `summary.json`) — optionally uploaded to a Nebius **Object Storage** bucket (`ml-infra-poc-logs`) for retention past Logging's 14-day default; see [cluster-validator/README.md](cluster-validator/README.md#uploading-logs-to-object-storage).

## Future hardware: 2x8-GPU nodes with InfiniBand

*(This is the single canonical note on this — other docs just link here.)*

The test cluster currently runs **2 nodes x 1 GPU each** (2 GPUs total, not
the PoC spec's 16). An 8-GPU-per-node preset on `gpu-h200-sxm`/`fabric-7` in
`eu-north1` was capacity-constrained when checked (confirmed via `nebius
capacity resource-advice` as a real physical constraint, not a quota/policy
limit — tenant quota is 32 H200s) — flagged to the Nebius contact, still
unresolved. Even the 1-GPU preset hit a transient `NotEnoughResources` during
this session's node replacement (resolved on its own after ~40 min), so
capacity here is generally tight, not just for the 8-GPU preset.

**The plan once capacity allows**, switching to 2 nodes x 8 GPUs (16 total):

1. Change `gpu_preset` in [`infra/variables.tf`](infra/variables.tf) to
   `8gpu-128vcpu-1600gb` — confirmed as the correct preset name for
   InfiniBand-connected 8-GPU nodes by the Nebius Solutions Library's
   [`k8s-training`](https://github.com/nebius/nebius-solutions-library/tree/main/k8s-training)
   module.
2. **Add a `nebius_compute_v1_gpu_cluster` resource** to
   [`infra/main.tf`](infra/main.tf) (referencing `infiniband_fabric =
   "fabric-7"`) and attach the node group to it — only nodes in a GPU
   cluster get the InfiniBand fabric connection between them. This resource
   doesn't exist in `main.tf` yet; it's a gap found during this review, not
   yet implemented (deliberately deferred, per user decision, until the
   switch actually happens).
3. Install the [MPI Operator](https://github.com/kubeflow/mpi-operator) —
   needed to actually run `cluster-validator/k8s/job-nccl-multinode.yaml`
   (already written, never run). The Solutions Library's
   [`modules/nccl-test`](https://github.com/nebius/nebius-solutions-library/tree/main/modules/nccl-test)
   has a working Terraform pattern for installing it via a bootstrap
   `kubernetes_job`, instead of by hand.
4. Re-run `cluster-validator` — `nccl_bench`'s current "fail" (0 GB/s on a
   single GPU, see [cluster-validator/README.md#results-last-validated-run](cluster-validator/README.md#results-last-validated-run))
   should then produce a real InfiniBand bandwidth number instead.
