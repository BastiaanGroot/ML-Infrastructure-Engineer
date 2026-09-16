# Reproduces the PoC setup from scratch in a given Nebius project:
# network + subnet, an mk8s cluster, one GPU node group, and a container
# registry for the cluster-validator (and any other) images.
#
# The hand-built PoC cluster (created via the Nebius console wizard) has
# since been imported into local state for verification (`terraform import`,
# not committed — state stays local/gitignored). Values below (etcd size,
# k8s version, boot disk, GPU driver/OS) were reconciled to match it, since
# those are sensible defaults for any deployment. The node group's SSH
# access, filesystem mount, and extra security group are environment
# -specific (not secrets, but not sane defaults for a fresh deploy either)
# — they're optional variables, unset by default; see
# terraform.tfvars.example. Set them via a local terraform.tfvars (gitignored)
# to adopt an already-existing node group's config without an `apply` trying
# to strip them. The console wizard also gave the network/subnet/node group
# auto-generated names (e.g. "default-network") — renaming them to the names
# below is a safe, non-destructive diff whenever this is applied.

# Cloud-init for GPU nodes: only set at all if an SSH key was provided (see
# variables.tf). The filesystem mount step is only appended if a filesystem
# ID was also provided; the mount_tag here must match the one used in the
# node group's `filesystems` block below.
locals {
  node_group_cloud_init_user_data = var.node_group_ssh_public_key == null ? null : <<-EOT
    users:
     - name: ${var.node_group_ssh_user}
       sudo: ALL=(ALL) NOPASSWD:ALL
       shell: /bin/bash
       ssh_authorized_keys:
        - ${var.node_group_ssh_public_key}
    %{if var.node_group_filesystem_id != null~}
    runcmd:
      - sudo mkdir -p ${var.node_group_filesystem_mount_path}
      - sudo mount -t virtiofs ${var.node_group_filesystem_mount_tag} ${var.node_group_filesystem_mount_path}
      - echo ${var.node_group_filesystem_mount_tag} ${var.node_group_filesystem_mount_path} "virtiofs" "defaults,nofail" "0" "0" | sudo tee -a /etc/fstab
    %{endif~}
  EOT
}

resource "nebius_vpc_v1_network" "main" {
  parent_id = var.project_id
  name      = "${var.cluster_name}-network"
}

resource "nebius_vpc_v1_subnet" "main" {
  parent_id  = var.project_id
  name       = "${var.cluster_name}-subnet"
  network_id = nebius_vpc_v1_network.main.id

  ipv4_private_pools = {
    use_network_pools = true
  }
  ipv4_public_pools = {
    use_network_pools = true
  }
}

resource "nebius_mk8s_v1_cluster" "main" {
  parent_id = var.project_id
  name      = var.cluster_name

  control_plane = {
    subnet_id         = nebius_vpc_v1_subnet.main.id
    version           = var.k8s_version
    etcd_cluster_size = 3  # HA (3 control-plane instances); use 1 to save cost for a disposable PoC
    audit_logs        = {} # push k8s audit logs to Nebius Logging
    endpoints = {
      public_endpoint = {}
    }
  }
}

resource "nebius_mk8s_v1_node_group" "gpu" {
  parent_id        = nebius_mk8s_v1_cluster.main.id
  name             = "gpu"
  fixed_node_count = var.gpu_node_count
  version          = var.k8s_version

  template = {
    resources = {
      platform = var.gpu_platform
      preset   = var.gpu_preset
    }

    boot_disk = {
      type             = "NETWORK_SSD"
      size_gibibytes   = 279
      block_size_bytes = 4096
    }

    gpu_settings = {
      drivers_preset = "cuda13.0"
    }
    os = "ubuntu24.04"

    cloud_init_user_data = local.node_group_cloud_init_user_data

    filesystems = var.node_group_filesystem_id == null ? null : [
      {
        attach_mode = "READ_WRITE"
        mount_tag   = var.node_group_filesystem_mount_tag
        existing_filesystem = {
          id = var.node_group_filesystem_id
        }
      }
    ]

    network_interfaces = [
      {
        subnet_id         = nebius_vpc_v1_subnet.main.id
        public_ip_address = {}
        security_groups = length(var.node_group_security_group_ids) == 0 ? null : [
          for id in var.node_group_security_group_ids : { id = id }
        ]
      }
    ]
  }
}

resource "nebius_registry_v1_registry" "cluster_validator" {
  parent_id   = var.project_id
  name        = "cluster-validator"
  description = "Images for the cluster-validator GPU/NCCL/storage validation container."
}

# Object Storage bucket for cluster-validator run logs (summary.json), and
# any other job logs we later want to keep past Nebius Logging's 14-day
# retention. See cluster-validator/README.md for the UPLOAD_LOGS_* env vars
# and credentials needed to actually upload into this bucket from a Job.
resource "nebius_storage_v1_bucket" "logs" {
  parent_id = var.project_id
  name      = "${var.cluster_name}-logs"

  default_storage_class = "STANDARD"
  versioning_policy     = "DISABLED"
}
