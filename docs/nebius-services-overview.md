# Nebius AI Cloud — Services Overview

Source: [https://docs.nebius.com](https://docs.nebius.com)

A reference list of Nebius platform services, grouped by category, with notes on relevance to the [take-home exercise](./ML-Infrastructure-Engineer.md) (cluster validation + training or inference PoC on 16x H200, 2TB SSD network disk, 2TB SSD shared filesystem).

## Getting started

- **Host a model** — deploy/run models on GPU-backed VMs
- **Deploy a Kubernetes cluster** — scalable, containerized workloads
- **Launch a container VM** — run Docker containers directly on a VM

## Compute


| Service                      | Description                                              | Relevant?                                                                            |
| ---------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Virtual machines             | GPU-backed VMs (NVIDIA) for ML/AI workloads              | Base compute for the PoC                                                             |
| GPU clusters                 | InfiniBand networks for high-speed distributed computing | Needed for multi-node training / multi-GPU inference                                 |
| **Soperator clusters**       | Managed Slurm clusters for ML/AI experiments             | Listed as a resource in the assignment — candidate scheduler for Option 1 (training) |
| Kubernetes clusters          | Containerized deployment, GPU + InfiniBand support       | Candidate scheduler/orchestrator for either option                                   |
| Disks and shared filesystems | Block + file storage for VMs/K8s nodes                   | Maps directly to the provided 2TB SSD network disk + 2TB SSD shared filesystem       |




## Storage


| Service                | Description                                        | Relevant?                                                             |
| ---------------------- | -------------------------------------------------- | --------------------------------------------------------------------- |
| Object Storage buckets | S3-compatible storage for datasets/model artifacts | Good fit for checkpoints, dataset staging, or benchmark results       |
| PostgreSQL clusters    | Managed DB for datasets/app data                   | Likely not needed unless we want structured experiment tracking       |
| Container Registry     | Docker image storage/distribution                  | Needed to publish the cluster-validation container and any job images |




## AI services


| Service                  | Description                                          | Relevant?                                                                                         |
| ------------------------ | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Serverless AI            | Endpoints/jobs for containerized AI workloads        | Alternative to self-managed inference server (Option 2) — worth comparing against a custom server |
| MLflow clusters          | Managed experiment tracking / model registry         | Useful for Option 1 to log training efficiency across distribution-strategy experiments           |
| Applications             | Turnkey apps: JupyterLab, **vLLM**, Open WebUI, etc. | vLLM app is directly relevant to Option 2 (inference server)                                      |
| Third-party integrations | Tools to orchestrate AI workloads                    | Check for existing training/inference framework integrations before building custom               |




## Observability


| Service            | Description                                      | Relevant?                                                                                                                                 |
| ------------------ | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Metrics and alerts | Metrics visualization + threshold alerting       | Needed either way — required for Option 2's "server metrics for observability" and useful for monitoring the cluster-validation container |
| Logs               | Log collection, search, export, custom ingestion | Useful for debugging training/inference jobs                                                                                              |
| Traces             | Distributed tracing for app performance          | Likely more relevant to Option 2 (inference server request tracing)                                                                       |




## Network

- **Network** — isolated VPCs, subnets, IP pools. Needed to network the cluster and expose the inference server if applicable.



## Management

- IAM, Quotas, Billing, Regions, Audit Logs, Support — operational concerns, not core to the exercise but worth a mention in client-facing docs on cluster setup/access.



## Security and cryptography

- Key Management Service, SecretStash (secrets storage) — relevant if the PoC needs to store credentials/tokens (e.g. model registry access, API keys) securely.



## Developer tools


| Tool               | Description                               | Relevant?                                                                              |
| ------------------ | ----------------------------------------- | -------------------------------------------------------------------------------------- |
| CLI                | Command-line resource management          | Used already (`nebius` CLI) for cluster/profile setup                                  |
| Terraform provider | Declarative infra-as-code                 | Good option for reproducible cluster provisioning docs (client can recreate the setup) |
| gRPC / REST API    | Programmatic resource management          | Backing for CLI/Terraform; only needed if scripting custom automation                  |
| Agent Resources    | Resources for AI agents using Nebius docs | Powers the Nebius MCP server already set up in this repo                               |




## Resources referenced in the assignment

- Solutions library: [https://github.com/nebius/nebius-solutions-library](https://github.com/nebius/nebius-solutions-library)
- K8s training: [https://github.com/nebius/nebius-solutions-library/tree/main/k8s-training](https://github.com/nebius/nebius-solutions-library/tree/main/k8s-training)
- Soperator (operator repo): [https://github.com/nebius/soperator](https://github.com/nebius/soperator)
- Soperator (deployment module): [https://github.com/nebius/nebius-solutions-library/tree/main/soperator](https://github.com/nebius/nebius-solutions-library/tree/main/soperator)
- Managed Soperator docs: [https://docs.nebius.com/slurm-soperator](https://docs.nebius.com/slurm-soperator)

