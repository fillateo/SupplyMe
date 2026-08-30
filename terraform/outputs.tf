output "service_url" {
  value       = google_cloud_run_v2_service.api.uri
  description = "Base URL of the API. The console proxies to this."
}

output "console_url" {
  value       = google_cloud_run_v2_service.console.uri
  description = "The operations console. This is the link to open, and to put in a demo."
}

output "workflow_topic" {
  value = google_pubsub_topic.workflow.name
}

output "gmail_topic" {
  value       = var.gmail_push ? google_pubsub_topic.gmail[0].id : ""
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
    var.gmail_push ?
    "2. Start Gmail push: python scripts/gmail_auth.py --watch ${google_pubsub_topic.gmail[0].id}" :
    "2. Replies are read over IMAP on a one-minute Cloud Scheduler poll.",
  ])
}
