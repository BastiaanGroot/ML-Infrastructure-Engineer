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
