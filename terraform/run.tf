# A Cloud Run v2 URL is derivable before the service exists — service name,
# project number and region — so the service can be told its own address at
# creation time. Reading it back off the resource would be a cycle, and setting
# it afterwards with `gcloud run services update` leaves the value out of the
# configuration, so the next apply removes it and the Gmail push callback breaks.
data "google_project" "current" {}

locals {
  service_url = "https://${var.service_name}-${data.google_project.current.number}.${var.region}.run.app"
}

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
        name  = "SUPPLYME_APPROVAL_POLICY"
        value = var.approval_policy
      }
      env {
        name  = "SUPPLYME_PROJECT_ID"
        value = var.project_id
      }
      # The region the service's own Google Cloud dependencies live in.
      # Cloud Tasks rejects `global`, so this must stay a real region.
      env {
        name  = "SUPPLYME_LOCATION"
        value = var.region
      }
      # Where Vertex serves the model — a different question, and a different
      # answer. See variables.tf.
      env {
        name  = "SUPPLYME_VERTEX_LOCATION"
        value = var.vertex_location
      }
      env {
        name  = "SUPPLYME_USE_VERTEX"
        value = tostring(var.use_vertex)
      }
      env {
        # Firestore, Pub/Sub and Cloud Tasks instead of the in-process store,
        # bus and scheduler. See
        # Settings.use_cloud_infra.
        name  = "SUPPLYME_USE_CLOUD_INFRA"
        value = "true"
      }
      env {
        name  = "SUPPLYME_REASONING_MODEL"
        value = var.reasoning_model
      }
      env {
        name  = "SUPPLYME_FAST_MODEL"
        value = var.fast_model
      }
      env {
        name  = "SUPPLYME_PUBLIC_BASE_URL"
        value = local.service_url
      }
      env {
        name  = "SUPPLYME_PUBSUB_TOPIC"
        value = google_pubsub_topic.workflow.name
      }
      env {
        name  = "SUPPLYME_TASKS_QUEUE"
        value = google_cloud_tasks_queue.followups.name
      }
      # Spend guards. These are hard stops in the application, not alerts.
      env {
        name  = "SUPPLYME_MAX_USD_PER_MISSION"
        value = tostring(var.max_usd_per_mission)
      }

      # Only when it is the credential actually in use. Mounting a key the
      # service will not read is a secret handed out for nothing.
      dynamic "env" {
        for_each = var.use_vertex ? [] : [1]

        content {
          name = "SUPPLYME_GEMINI_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.gemini_api_key.secret_id
              version = "latest"
            }
          }
        }
      }

      env {
        name  = "SUPPLYME_SMTP_USER"
        value = var.smtp_user
      }
      env {
        name  = "SUPPLYME_MAIL_REDIRECT_TO"
        value = var.mail_redirect_to
      }

      # The two product credentials. Secrets rather than plain values: a
      # revision's environment is readable by anyone with viewer on the project,
      # and an API key in it is an API key published to them.
      env {
        name = "SUPPLYME_MAPS_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.maps_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SUPPLYME_SMTP_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.smtp_password.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "SUPPLYME_PUBSUB_PUSH_TOKEN"
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

resource "google_cloud_run_v2_service_iam_member" "public_read" {
  count = var.publicly_readable ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
