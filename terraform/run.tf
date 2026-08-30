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
      # Not var.region. See variables.tf: the model endpoint and the
      # service's region are different decisions.
      env {
        name  = "VDS_LOCATION"
        value = var.vertex_location
      }
      env {
        name  = "VDS_USE_VERTEX"
        value = tostring(var.use_vertex)
      }
      env {
        # Firestore, Pub/Sub and Cloud Tasks instead of the in-process store,
        # bus and scheduler. Independent of var.mode on purpose — see
        # Settings.use_cloud_infra.
        name  = "VDS_USE_CLOUD_INFRA"
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
        name  = "VDS_PUBLIC_BASE_URL"
        value = local.service_url
      }
      env {
        name  = "VDS_PUBSUB_TOPIC"
        value = google_pubsub_topic.workflow.name
      }
      env {
        name  = "VDS_TASKS_QUEUE"
        value = google_cloud_tasks_queue.followups.name
      }
      # Spend guards. These are hard stops in the application, not alerts.
      env {
        name  = "VDS_MAX_USD_PER_MISSION"
        value = tostring(var.max_usd_per_mission)
      }

      # Only when it is the credential actually in use. Mounting a key the
      # service will not read is a secret handed out for nothing.
      dynamic "env" {
        for_each = var.use_vertex ? [] : [1]

        content {
          name = "VDS_GEMINI_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.gemini_api_key.secret_id
              version = "latest"
            }
          }
        }
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
