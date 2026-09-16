# Reproduces the PoC setup from scratch in a given Nebius project:
# network + subnet, an mk8s cluster, one GPU node group, and a container
# registry for the cluster-validator (and any other) images.
#
# This is meant to stand up a fresh environment (e.g. for the client to
# recreate the setup) — it does NOT manage the ad hoc test cluster we
# created by hand during this PoC. Run `terraform plan` and review before
# ever applying against a project that already has resources.

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
}

resource "nebius_mk8s_v1_cluster" "main" {
  parent_id = var.project_id
  name      = var.cluster_name

  control_plane = {
    subnet_id         = nebius_vpc_v1_subnet.main.id
    version           = var.k8s_version
    etcd_cluster_size = 1 # single control-plane instance is enough for a PoC; use 3 for HA
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
      type           = "NETWORK_SSD"
      size_gibibytes = 128
    }

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
