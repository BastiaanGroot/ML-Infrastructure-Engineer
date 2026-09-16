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
  description = "Resource preset for the GPU node group. Note: at time of writing, 8-GPU presets on this platform may be capacity-constrained (see docs/observability.md and README design choices) — this defaults to the 1-GPU preset that was actually available. Future target once capacity allows: \"8gpu-128vcpu-1600gb\" (2 nodes x 8 GPUs = 16 GPUs total, matching the PoC spec) — confirmed as the correct preset name for InfiniBand-connected 8-GPU nodes by the Nebius Solutions Library's k8s-training module (https://github.com/nebius/nebius-solutions-library/tree/main/k8s-training)."
  type        = string
  default     = "1gpu-16vcpu-200gb"
}

variable "gpu_node_count" {
  description = "Number of GPU nodes in the node group. Currently 2 (1 GPU each); future target is still 2 once switched to the 8-GPU preset above (2x8 = 16 GPUs total)."
  type        = number
  default     = 2
}

# The three variables below are all optional and environment-specific (not
# secrets - an SSH key here is a *public* key, and the other two are just
# resource IDs - but not meaningful defaults for a fresh deployment either).
# Left unset, node groups come up with no SSH access, no extra filesystem
# mount, and no extra security group, same as before these were added. Set
# them via a local, gitignored terraform.tfvars (see terraform.tfvars.example)
# to adopt an already-existing node group's config, e.g. after `terraform
# import`.

variable "node_group_ssh_public_key" {
  description = "Optional SSH public key to grant access to GPU nodes via cloud-init. Also used as the cloud-init trigger: if unset, no cloud-init user-data is set at all (no filesystem mount script either)."
  type        = string
  default     = null
}

variable "node_group_ssh_user" {
  description = "Username for node_group_ssh_public_key's cloud-init user. Only used if node_group_ssh_public_key is set."
  type        = string
  default     = "ubuntu"
}

variable "node_group_filesystem_id" {
  description = "Optional existing Nebius Shared Filesystem ID to mount on GPU nodes (e.g. for shared checkpoints/data). Only mounted if node_group_ssh_public_key is also set, since the mount happens via the same cloud-init runcmd."
  type        = string
  default     = null
}

variable "node_group_filesystem_mount_path" {
  description = "Mount path inside GPU nodes for node_group_filesystem_id."
  type        = string
  default     = "/mnt/shared"
}

variable "node_group_filesystem_mount_tag" {
  description = "Mount tag (virtiofs device tag) for node_group_filesystem_id. Must match between the node group's filesystems block and the cloud-init mount command, which this variable drives for both."
  type        = string
  default     = "filesystem-0"
}

variable "node_group_security_group_ids" {
  description = "Optional additional VPC security group IDs to attach to GPU node network interfaces."
  type        = list(string)
  default     = []
}
