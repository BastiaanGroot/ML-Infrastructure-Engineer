output "cluster_id" {
  value = nebius_mk8s_v1_cluster.main.id
}

output "registry_id" {
  description = "Registry ID. Strip the 'registry-' prefix to get the image path segment, e.g. cr.<region>.nebius.cloud/<this_without_prefix>/<image>:<tag>."
  value       = nebius_registry_v1_registry.cluster_validator.id
}

output "network_id" {
  value = nebius_vpc_v1_network.main.id
}

output "subnet_id" {
  value = nebius_vpc_v1_subnet.main.id
}

output "logs_bucket_name" {
  description = "Object Storage bucket name for cluster-validator/job logs (UPLOAD_LOGS_BUCKET)."
  value       = nebius_storage_v1_bucket.logs.name
}

output "mlflow_admin_password" {
  description = "Generated MLflow admin password (only set when enable_mlflow=true). Push into SecretStash, don't leave it in local state/shell history any longer than needed."
  value       = try(random_password.mlflow_admin[0].result, null)
  sensitive   = true
}

output "mlflow_tracking_endpoint" {
  description = "Private MLflow tracking endpoint (only set when enable_mlflow=true), reachable from inside the VPC/mk8s cluster."
  value       = try(nebius_msp_mlflow_v1alpha1_cluster.main[0].status.tracking_endpoint, null)
}
