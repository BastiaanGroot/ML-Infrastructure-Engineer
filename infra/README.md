# infra

Terraform to reproduce the PoC infrastructure from scratch in a Nebius
project: VPC network + subnet, an mk8s cluster, one GPU node group, and a
container registry for `cluster-validator` (and other) images.

This is meant for standing up a **fresh** environment (e.g. so the client can
recreate the setup themselves) — it does not manage or import the ad hoc test
cluster created by hand during this PoC. Extend it here as the project grows
(storage, training/inference workloads, observability agent via the
`helm`/`kubernetes` Terraform providers, etc.).

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

Always run `terraform plan` and review the diff before `apply`, especially
against a project that already has resources.
