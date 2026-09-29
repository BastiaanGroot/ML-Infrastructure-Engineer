variable "project_id" {
  description = "Nebius project ID to create resources in."
  type        = string
}

variable "tenant_id" {
  description = "Nebius tenant ID that owns the project (its \"editors\" group is looked up for mlflow-sa)."
  type        = string
  default     = "tenant-e00txje2rqact2jtfd"
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
  default     = "gpu-h100-sxm"
}

variable "gpu_preset" {
  description = "Resource preset for the GPU node group: 8 GPUs per node, InfiniBand-connected via the GPU cluster below."
  type        = string
  default     = "8gpu-128vcpu-1600gb"
}

variable "gpu_fabric" {
  description = "InfiniBand fabric for the GPU cluster. Must offer gpu_platform/gpu_preset in the region; check `nebius capacity resource-advice list` (fabric-4 had full on-demand availability for 8x H100 when chosen)."
  type        = string
  default     = "fabric-4"
}

variable "gpu_node_count" {
  description = "Number of GPU nodes in the node group (2 x 8 GPUs = 16 total)."
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
# work actually starts. This also creates MLflow's service account
# ("mlflow-sa") and adds it to the tenant's "editors" group.
variable "enable_mlflow" {
  description = "Whether to create the Nebius-managed MLflow cluster. Off by default (real ongoing cost) — see infra/README.md."
  type        = bool
  default     = false
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

variable "enable_dashboard" {
  description = "Whether to create the Streamlit dashboard VM (see infra/dashboard.tf). Requires enable_mlflow=true."
  type        = bool
  default     = false
}

variable "dashboard_platform" {
  description = "CPU compute platform for the dashboard VM."
  type        = string
  default     = "cpu-d3"
}

variable "dashboard_preset" {
  description = "Resource preset for the dashboard VM."
  type        = string
  default     = "4vcpu-16gb"
}

variable "dashboard_git_repo_url" {
  description = "Public git repo the dashboard VM clones to get dashboard/ and training/profiles/."
  type        = string
  default     = "https://github.com/BastiaanGroot/ML-Infrastructure-Engineer.git"
}

variable "dashboard_git_ref" {
  description = "Branch or tag of dashboard_git_repo_url to deploy."
  type        = string
  default     = "main"
}

variable "dashboard_ssh_public_key" {
  description = "Optional SSH public key for the dashboard VM (user node_group_ssh_user). If unset, no SSH user is created and port 22 stays closed."
  type        = string
  default     = null
}

variable "logs_bucket_retention_days" {
  description = "Days before an object in the logs bucket (cluster-validator summary.json etc.) auto-expires, via the bucket's lifecycle_configuration."
  type        = number
  default     = 90
}
