# NeuroCI — Terraform Outputs

output "webhook_url" {
  description = "URL of the NeuroCI webhook server"
  value = var.cloud_provider == "gcp" ? (
    length(google_cloud_run_v2_service.neuroci_webhook) > 0 ?
    google_cloud_run_v2_service.neuroci_webhook[0].uri : ""
  ) : "Configure ALB/NLB for ECS service"
}

output "redis_host" {
  description = "Redis host address"
  value = var.cloud_provider == "gcp" ? (
    length(google_redis_instance.neuroci) > 0 ?
    google_redis_instance.neuroci[0].host : ""
  ) : (
    length(aws_elasticache_cluster.neuroci) > 0 ?
    aws_elasticache_cluster.neuroci[0].cache_nodes[0].address : ""
  )
}
