variable "project_id" {
  description = "Nebius project ID to create resources in."
  type        = string
}

variable "region" {
  description = "Nebius region."
  type        = string
  default     = "eu-north1"
}

variable "cluster_name" {
  description = "Name for the mk8s cluster and related resources."
  type        = string
  default     = "ml-infra-poc"
}

variable "k8s_version" {
  description = "Kubernetes version for the mk8s cluster."
  type        = string
  default     = "1.36"
}

variable "gpu_platform" {
  description = "Compute platform for the GPU node group."
  type        = string
  default     = "gpu-h200-sxm"
}

variable "gpu_preset" {
  description = "Resource preset for the GPU node group. Defaults to the 1-GPU preset actually available at time of writing (8-GPU presets are capacity-constrained) — see the root README's \"Future hardware: 2x8-GPU nodes with InfiniBand\" section for the target preset and the rest of the switch plan (incl. a currently-missing nebius_compute_v1_gpu_cluster resource)."
  type        = string
  default     = "1gpu-16vcpu-200gb"
}

variable "gpu_node_count" {
  description = "Number of GPU nodes in the node group. Currently 2 (1 GPU each); future target is still 2 once switched to the 8-GPU preset above (2x8 = 16 GPUs total)."
  type        = number
  default     = 2
}

variable "filesystem_size_gibibytes" {
  description = "Size of the shared filesystem mounted on GPU nodes, in GiB. 2048 (2 TiB) matches the exercise's PoC environment spec."
  type        = number
  default     = 2048
}

variable "node_group_filesystem_mount_path" {
  description = "Mount path inside GPU nodes for the shared filesystem."
  type        = string
  default     = "/mnt/filesystem-s6"
}

variable "node_group_filesystem_mount_tag" {
  description = "Mount tag (virtiofs device tag) for the shared filesystem. Must match between the node group's filesystems block and the cloud-init mount command, which this variable drives for both."
  type        = string
  default     = "filesystem-s6"
}

# The two variables below are optional and environment-specific (not
# secrets - an SSH key here is a *public* key, and the other is just a list
# of resource IDs - but not a meaningful default for a fresh deployment
# either). Left unset, node groups come up with no SSH access and no extra
# security group, same as before these were added. Set them via a local,
# gitignored terraform.tfvars (see terraform.tfvars.example) to adopt an
# already-existing node group's config, e.g. after `terraform import`.

variable "node_group_ssh_public_key" {
  description = "Optional SSH public key to grant access to GPU nodes via cloud-init. If unset, nodes still come up (and still mount the shared filesystem) but with no SSH user configured."
  type        = string
  default     = null
}

variable "node_group_ssh_user" {
  description = "Username for node_group_ssh_public_key's cloud-init user. Only used if node_group_ssh_public_key is set."
  type        = string
  default     = "ubuntu"
}

variable "node_group_security_group_ids" {
  description = "Optional additional VPC security group IDs to attach to GPU node network interfaces."
  type        = list(string)
  default     = []
}

# Nebius-managed MLflow (msp mlflow), for tracking Option 1's training
# efficiency across distribution-strategy experiments. Off by default since
# it's a real, ongoing-cost managed service (compute + managed Postgres +
# storage) — flip enable_mlflow to true (and `terraform apply`) when Option 1
# work actually starts. mlflow_service_account_id defaults to the "mlflow-sa"
# service account already created in the project for this purpose.
variable "enable_mlflow" {
  description = "Whether to create the Nebius-managed MLflow cluster. Off by default (real ongoing cost) — see infra/README.md."
  type        = bool
  default     = false
}

variable "mlflow_service_account_id" {
  description = "Service account MLflow uses to access its Object Storage bucket. Defaults to the pre-existing \"mlflow-sa\" service account in this project."
  type        = string
  default     = "serviceaccount-e00fdpk94g3qnyh4ca"
}

variable "mlflow_admin_username" {
  description = "MLflow admin username."
  type        = string
  default     = "admin"
}

variable "mlflow_size" {
  description = "Size (compute allocation) for the MLflow cluster. Left unset uses the smallest available size in the region."
  type        = string
  default     = null
}
