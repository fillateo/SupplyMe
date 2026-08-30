# The console, as its own Cloud Run service.
#
# Separate from the API rather than bundled with it because they scale on
# different things and fail independently: the API is woken by Pub/Sub pushes
# and Cloud Tasks with no browser involved, and a mission continues whether or
# not anyone has the console open. Deploying them together would tie the
# workflow's availability to a UI it does not need.
#
# The browser talks only to this service. `next.config.mjs` rewrites /api/* to
# the API server-side, so no API origin, token or credential is ever in client
# JavaScript, and there is no CORS preflight in production.

resource "google_service_account" "console" {
  account_id   = "${var.service_name}-console"
  display_name = "SupplyMe console"
}

# The console reaches the API as itself. In demo mode the API is public anyway,
# but granting this explicitly is what lets `mode = "live"` lock the API down
# to named callers without the console losing access.
resource "google_cloud_run_v2_service_iam_member" "console_can_call_api" {
  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.console.email}"
}

resource "google_cloud_run_v2_service" "console" {
  name     = "${var.service_name}-console"
  location = var.region

  # The provider defaults this on, which turns any rename of the service into a
  # plan that cannot apply. The data worth protecting is Firestore, and that has
  # its own prevent_destroy; a Cloud Run service is a container and a URL, both
  # reproducible from this file.
  deletion_protection = false

  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.console.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    max_instance_request_concurrency = 40

    containers {
      image = var.console_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      # Read when the Next server boots and resolves its rewrites, so the
      # console follows whichever API this root deployed rather than a URL
      # anyone had to paste.
      env {
        name  = "API_BASE_URL"
        value = google_cloud_run_v2_service.api.uri
      }

      startup_probe {
        tcp_socket {
          port = 8080
        }
        initial_delay_seconds = 3
        period_seconds        = 3
        failure_threshold     = 15
      }
    }
  }

  depends_on = [google_project_service.enabled]
}

# Same rule as the API, for the same reason. See var.publicly_readable.
resource "google_cloud_run_v2_service_iam_member" "console_public_read" {
  count = var.publicly_readable ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.console.location
  name     = google_cloud_run_v2_service.console.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
