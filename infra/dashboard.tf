# Streamlit dashboard VM (dashboard/): a small CPU VM that queries MLflow
# live and serves the strategy comparison + parallelism planner over plain
# HTTP on port 80. Gated by enable_dashboard (on by default); requires
# enable_mlflow.
#
# NOTE: no authentication — anyone with the URL can view the dashboard
# (read-only MLflow data; the MLflow password itself never leaves the VM).
#
# Credentials: the VM runs as dashboard-sa, which can read only the MLflow
# password secret (nebius_mysterybox_v1_secret.mlflow in main.tf) via a group
# access permit, and fetches it at boot — nothing secret is baked into
# cloud-init.

locals {
  dashboard_count = var.enable_dashboard ? 1 : 0
}

resource "nebius_iam_v1_service_account" "dashboard" {
  count       = local.dashboard_count
  parent_id   = var.project_id
  name        = "dashboard-sa"
  description = "Identity of the dashboard VM; can only read the MLflow password secret."

  lifecycle {
    precondition {
      condition     = var.enable_mlflow
      error_message = "enable_dashboard requires enable_mlflow=true (the dashboard reads from MLflow)."
    }
  }
}

# Access permits target a group, not a service account directly.
resource "nebius_iam_v1_group" "dashboard_secret_readers" {
  count     = local.dashboard_count
  parent_id = var.project_id
  name      = "dashboard-secret-readers"
}

resource "nebius_iam_v1_group_membership" "dashboard" {
  count     = local.dashboard_count
  parent_id = nebius_iam_v1_group.dashboard_secret_readers[0].id
  member_id = nebius_iam_v1_service_account.dashboard[0].id
}

resource "nebius_iam_v1_access_permit" "dashboard_secret" {
  count       = local.dashboard_count
  parent_id   = nebius_iam_v1_group.dashboard_secret_readers[0].id
  resource_id = nebius_mysterybox_v1_secret.mlflow[0].id
  role        = "mysterybox.payload-viewer"
}

# Dedicated security group: the network's default group allows all ingress,
# this one only exposes HTTP (and SSH when a key is configured).
resource "nebius_vpc_v1_security_group" "dashboard" {
  count      = local.dashboard_count
  parent_id  = var.project_id
  name       = "${var.cluster_name}-dashboard"
  network_id = nebius_vpc_v1_network.main.id
}

resource "nebius_vpc_v1_security_rule" "dashboard_http" {
  count     = local.dashboard_count
  parent_id = nebius_vpc_v1_security_group.dashboard[0].id
  name      = "allow-http"
  access    = "ALLOW"
  protocol  = "TCP"
  ingress = {
    source_cidrs      = ["0.0.0.0/0"]
    destination_ports = [80]
  }
}

resource "nebius_vpc_v1_security_rule" "dashboard_ssh" {
  count     = var.enable_dashboard && var.dashboard_ssh_public_key != null ? 1 : 0
  parent_id = nebius_vpc_v1_security_group.dashboard[0].id
  name      = "allow-ssh"
  access    = "ALLOW"
  protocol  = "TCP"
  ingress = {
    source_cidrs      = ["0.0.0.0/0"]
    destination_ports = [22]
  }
}

resource "nebius_vpc_v1_security_rule" "dashboard_egress" {
  count     = local.dashboard_count
  parent_id = nebius_vpc_v1_security_group.dashboard[0].id
  name      = "allow-all-egress"
  access    = "ALLOW"
  protocol  = "ANY"
  egress = {
    destination_cidrs = ["0.0.0.0/0"]
  }
}

resource "nebius_compute_v1_instance" "dashboard" {
  count              = local.dashboard_count
  parent_id          = var.project_id
  name               = "${var.cluster_name}-dashboard"
  service_account_id = nebius_iam_v1_service_account.dashboard[0].id

  resources = {
    platform = var.dashboard_platform
    preset   = var.dashboard_preset
  }

  boot_disk = {
    attach_mode = "READ_WRITE"
    managed_disk = {
      name = "${var.cluster_name}-dashboard-boot"
      spec = {
        type                = "NETWORK_SSD"
        size_gibibytes      = 30
        source_image_family = { image_family = "ubuntu24.04-driverless" }
      }
    }
  }

  network_interfaces = [{
    name              = "eth0"
    subnet_id         = nebius_vpc_v1_subnet.main.id
    ip_address        = {}
    public_ip_address = {}
    security_groups   = [{ id = nebius_vpc_v1_security_group.dashboard[0].id }]
  }]

  cloud_init_user_data = templatefile("${path.module}/dashboard-cloud-init.yaml.tftpl", {
    secret_id           = nebius_mysterybox_v1_secret.mlflow[0].id
    mlflow_tracking_uri = "https://${nebius_msp_mlflow_v1alpha1_cluster.main[0].status.tracking_endpoint}"
    mlflow_username     = var.mlflow_admin_username
    git_repo_url        = var.dashboard_git_repo_url
    git_ref             = var.dashboard_git_ref
    ssh_public_key      = var.dashboard_ssh_public_key
    ssh_user            = var.node_group_ssh_user
  })

  depends_on = [nebius_iam_v1_access_permit.dashboard_secret, nebius_iam_v1_group_membership.dashboard]
}
