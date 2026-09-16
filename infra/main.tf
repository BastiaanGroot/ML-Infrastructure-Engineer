# Reproduces the PoC setup from scratch in a given Nebius project:
# network + subnet, an mk8s cluster, one GPU node group, and a container
# registry for the cluster-validator (and any other) images.
#
# The hand-built PoC cluster (created via the Nebius console wizard) has
# since been imported into local state for verification (`terraform import`,
# not committed — state stays local/gitignored). Values below (etcd size,
# k8s version, boot disk, GPU driver/OS) were reconciled to match it, since
# those are sensible defaults for any deployment. Three things are
# deliberately NOT templated here, since they're specific to that one
# environment (a personal SSH key, an existing shared filesystem ID, and a
# security group ID) — `terraform plan` against the imported state will
# keep showing those as pending removals until someone adds them back
# explicitly. Do not `apply` against that state without addressing them
# first (also note the console wizard gave the network/subnet/node group
# auto-generated names, e.g. "default-network"; the safe rename in this
# config to consistent names would show as a plan diff too, but is not
# destructive on its own).

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
    etcd_cluster_size = 3 # HA (3 control-plane instances); use 1 to save cost for a disposable PoC
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

    network_interfaces = [
      {
        subnet_id         = nebius_vpc_v1_subnet.main.id
        public_ip_address = {}
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
