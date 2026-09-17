# Reproduces the PoC setup from scratch in a given Nebius project:
# network + subnet, an mk8s cluster, one GPU node group, a shared filesystem,
# a container registry, and an Object Storage bucket for logs.
#
# The hand-built PoC cluster (created via the Nebius console wizard) has
# since been imported into local state for verification (`terraform import`,
# not committed — state stays local/gitignored). Values below (etcd size,
# k8s version, boot disk, GPU driver/OS, filesystem size) were reconciled to
# match it (then the filesystem was grown to 2 TiB to match the exercise
# spec), since those are sensible defaults for any deployment. The node
# group's SSH access and extra security group remain environment-specific
# (not secrets, but not sane defaults for a fresh deploy either) — they're
# optional variables, unset by default; see terraform.tfvars.example. Set
# them via a local terraform.tfvars (gitignored) to adopt an already-existing
# node group's config without an `apply` trying to strip them. The console
# wizard also gave the network/subnet/node group/filesystem auto-generated
# names (e.g. "default-network") — renaming them to the names below is a
# safe, non-destructive diff whenever this is applied.

# Cloud-init for GPU nodes: the shared-filesystem mount (runcmd) always runs.
# The SSH user/key block is only added if a key was provided (see
# variables.tf) — without one, nodes still come up and mount the filesystem,
# just with no SSH access. The mount_tag here must match the one used in the
# node group's `filesystems` block below.
locals {
  # NOTE: left-flush (no `<<-` dedent) — mixing `<<-` indentation-stripping
  # with a `%{if~}` directive as the first line of a block has a sharp edge
  # where the first content line right after the directive doesn't get
  # dedented correctly. Left-flush avoids that entirely.
  node_group_cloud_init_user_data = <<EOT
%{if var.node_group_ssh_public_key != null~}
users:
 - name: ${var.node_group_ssh_user}
   sudo: ALL=(ALL) NOPASSWD:ALL
   shell: /bin/bash
   ssh_authorized_keys:
    - ${var.node_group_ssh_public_key}
%{endif~}
runcmd:
  - sudo mkdir -p ${var.node_group_filesystem_mount_path}
  - sudo mount -t virtiofs ${var.node_group_filesystem_mount_tag} ${var.node_group_filesystem_mount_path}
  - echo ${var.node_group_filesystem_mount_tag} ${var.node_group_filesystem_mount_path} "virtiofs" "defaults,nofail" "0" "0" | sudo tee -a /etc/fstab
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

# Shared filesystem mounted read/write on every GPU node (e.g. for shared
# checkpoints/data). Sized to match the exercise's PoC environment spec.
resource "nebius_compute_v1_filesystem" "shared" {
  parent_id        = var.project_id
  name             = "${var.cluster_name}-filesystem"
  type             = "NETWORK_SSD"
  size_gibibytes   = var.filesystem_size_gibibytes
  block_size_bytes = 4096
}

resource "nebius_mk8s_v1_cluster" "main" {
  parent_id = var.project_id
  name      = var.cluster_name
  # The console wizard's internal progress-tracking label; the API keeps
  # re-adding it regardless, so it's declared here to match reality instead
  # of fighting it every apply.
  labels = {
    "mk8s-wizard-create-progress" = "true"
  }

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

    filesystems = [
      {
        attach_mode = "READ_WRITE"
        mount_tag   = var.node_group_filesystem_mount_tag
        existing_filesystem = {
          id = nebius_compute_v1_filesystem.shared.id
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

# Nebius-managed MLflow, for tracking Option 1's training runs across
# distribution-strategy experiments. Gated behind enable_mlflow (see
# variables.tf) since it's a real, ongoing-cost managed service — this
# resource block exists so it's one `terraform apply` away, without
# accidentally provisioning it today. The admin password is generated by
# Terraform (random_password), stored only in local state (gitignored,
# never committed) — see infra/README.md for pushing it into SecretStash
# for retrieval after creation.
resource "random_password" "mlflow_admin" {
  count            = var.enable_mlflow ? 1 : 0
  length           = 24
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "nebius_msp_mlflow_v1alpha1_cluster" "main" {
  count       = var.enable_mlflow ? 1 : 0
  parent_id   = var.project_id
  name        = "${var.cluster_name}-mlflow"
  description = "MLflow tracking server for Option 1 (training) distribution-strategy experiments."

  network_id         = nebius_vpc_v1_network.main.id
  service_account_id = var.mlflow_service_account_id
  admin_username     = var.mlflow_admin_username
  admin_password     = random_password.mlflow_admin[0].result
  size               = var.mlflow_size
  public_access      = true # PoC: browser access to the tracking UI; still gated by admin_username/admin_password
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
