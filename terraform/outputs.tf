output "service_url" {
  value       = google_cloud_run_v2_service.api.uri
  description = "Base URL of the API. The console proxies to this."
}

output "workflow_topic" {
  value = google_pubsub_topic.workflow.name
}

output "gmail_topic" {
  value       = var.mode == "live" ? google_pubsub_topic.gmail[0].id : ""
  description = "Pass this to users.watch to start Gmail push notifications."
}

output "app_service_account" {
  value = google_service_account.app.email
}

output "next_steps" {
  value = join("\n", [
    "1. Confirm which Gemini model the deployment resolved:",
    "     curl -s ${google_cloud_run_v2_service.api.uri}/api/health | jq .providers",
    "     (/healthz is the container's own probe; the public health endpoint is /api/health.)",
    var.mode == "live" ?
    "2. Start Gmail push: python scripts/gmail_auth.py --watch ${google_pubsub_topic.gmail[0].id}" :
    "2. Demo mode: mock providers are bound. Nothing will email or call a real supplier.",
  ])
}
