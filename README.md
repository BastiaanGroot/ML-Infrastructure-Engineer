# ML-Infrastructure-Engineer

- LLM benchmarks
- Build container checking cluster capabilities for training/inference
- 

Nebius Console:
- https://console.nebius.com/project-e00av8n3pr00m43x3c6qd7
csa-hiring-sandbox2
aurora-hiring-poc

## Cluster Validator

[`cluster-validator/`](cluster-validator/) is a lightweight, portable container that checks GPU health, NCCL/GPU-interconnect bandwidth, and storage throughput before running training/inference jobs on the cluster. See its [README](cluster-validator/README.md) for build, push, and run instructions.

## Nebius MCP Server

This repo has the [Nebius MCP Server](https://github.com/nebius/mcp-server) configured for Cursor (see `.cursor/mcp.json`, env in `.venv`), letting the agent query and manage Nebius Cloud resources directly — e.g. list/create compute instances, manage storage buckets, and look up available platforms.

## Design Choices

Decisions to make (and record, once made) while executing the [take-home exercise](docs/ML-Infrastructure-Engineer.md), informed by the [Nebius services overview](docs/nebius-services-overview.md).

- [x] Option 1 (training) vs. Option 2 (inference) — starting with **training** (Option 1), inference (Option 2) to follow later.
- [x] Scheduler: Soperator (Slurm) vs. Kubernetes — going with **plain Kubernetes-native scheduling**. Wanted to explore Soperator, but it requires a GPU capacity *reservation* (not just quota) that isn't currently available — asked Nebius for clarification, may revisit.
- [ ] Storage split across the 2TB network disk vs. 2TB shared filesystem — to be defined later.
- [ ] Use the **vLLM** turnkey Application, or a custom-built inference server, for Option 2 — needs further exploration before deciding.
- [x] Metrics/observability stack — **Nebius-hosted** (Metrics/Logs/Traces).
