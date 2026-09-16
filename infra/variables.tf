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
  default     = "1.35"
}

variable "gpu_platform" {
  description = "Compute platform for the GPU node group."
  type        = string
  default     = "gpu-h200-sxm"
}

variable "gpu_preset" {
  description = "Resource preset for the GPU node group. Note: at time of writing, 8-GPU presets on this platform may be capacity-constrained (see docs/observability.md and README design choices) — this defaults to the 1-GPU preset that was actually available."
  type        = string
  default     = "1gpu-16vcpu-200gb"
}

variable "gpu_node_count" {
  description = "Number of GPU nodes in the node group."
  type        = number
  default     = 2
}
