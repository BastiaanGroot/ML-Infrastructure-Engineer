# infra

Terraform to reproduce the PoC infrastructure from scratch in a Nebius
project: VPC network + subnet, an mk8s cluster, one GPU node group, a
container registry for `cluster-validator` (and other) images, and an Object
Storage bucket for run logs (`summary.json` etc. — see
[`cluster-validator/README.md`](../cluster-validator/README.md#uploading-logs-to-object-storage)).

This is meant for standing up a **fresh** environment (e.g. so the client can
recreate the setup themselves). The hand-built PoC cluster has since been
`terraform import`-ed into local state for verification (state stays
local/gitignored, never committed) — see `misc/project-status.md` for
details. Extend it here as the project grows (storage, training/inference
workloads, observability agent via the `helm`/`kubernetes` Terraform
providers, etc.).

## Usage

1. [Install and initialize the Nebius Terraform provider](https://docs.nebius.com/terraform-provider/install)
   (service account or user token auth).
2. From this directory:
   ```bash
   terraform init
   terraform plan -var="project_id=<your_project_id>"
   terraform apply -var="project_id=<your_project_id>"
   ```
3. See [`variables.tf`](variables.tf) for other overridable settings (region,
   GPU platform/preset, node count). The default GPU preset
   (`1gpu-16vcpu-200gb`) reflects what was actually available during this
   PoC — an 8-GPU preset may be capacity-constrained (see the README's
   Design Choices section).
4. Optional GPU node SSH access / shared filesystem mount / extra security
   group — not secrets (an SSH key here is a *public* key), but
   environment-specific, so unset by default. Copy
   [`terraform.tfvars.example`](terraform.tfvars.example) to `terraform.tfvars`
   (gitignored) and fill in to enable them.

Always run `terraform plan` and review the diff before `apply`, especially
against a project that already has resources.
