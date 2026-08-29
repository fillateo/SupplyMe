# The Cloud Run service. Scale-to-zero is deliberate: a mission's progress lives
# in Firestore and arrives as Pub/Sub pushes, so there is nothing to keep warm
# between events — which is also what makes the cost of a long-running mission
# close to zero while it waits days for a supplier to reply.

resource "google_cloud_run_v2_service" "api" {
  name     = var.service_name
  location = var.region

  # Only the load balancer and the push identity reach it; see the IAM binding.
  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.app.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    max_instance_request_concurrency = 20

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        # CPU only while a request is in flight. Everything the workflow does is
        # inside a request or a push, so there is no background work to starve.
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "VDS_MODE"
        value = var.mode
      }
      env {
        name  = "VDS_APPROVAL_POLICY"
        value = var.approval_policy
      }
      env {
        name  = "VDS_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "VDS_LOCATION"
        value = var.region
      }
      env {
        name  = "VDS_USE_VERTEX"
        value = "true"
      }
      env {
        name  = "VDS_REASONING_MODEL"
        value = var.reasoning_model
      }
      env {
        name  = "VDS_FAST_MODEL"
        value = var.fast_model
      }
      env {
        name  = "VDS_PUBSUB_TOPIC"
        value = google_pubsub_topic.workflow.name
      }
      env {
        name  = "VDS_TASKS_QUEUE"
        value = google_cloud_tasks_queue.followups.name
      }
      env {
        name = "VDS_PUBSUB_PUSH_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.push_token.secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        http_get {
          path = "/healthz"
        }
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 10
      }
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_project_iam_member.app_roles,
  ]
}

# The service URL is needed by the push subscription and by the service itself
# (it builds voice webhook URLs from it), which is circular. Setting it after
# creation breaks the cycle.
resource "google_cloud_run_v2_service_iam_member" "public_read" {
  count = var.mode == "demo" ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  # A demo deployment is meant to be openable by a judge from a link. A live
  # deployment is not: it holds a real mailbox and can spend money on calls.
  member = "allUsers"
}
