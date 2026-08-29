# Everything the service needs, in dependency order. Nothing here is created
# imperatively: `tofu plan` is the review surface for the whole deployment.

locals {
  services = [
    "run.googleapis.com",
    "firestore.googleapis.com",
    "pubsub.googleapis.com",
    "cloudtasks.googleapis.com",
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
  ]
}

resource "google_project_service" "enabled" {
  for_each = toset(local.services)

  service = each.value
  # Turning an API off can break resources outside this root. Leave them on.
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = var.service_name
  format        = "DOCKER"
  description   = "Container images for ${var.service_name}"

  depends_on = [google_project_service.enabled]
}

# --- Identity ---------------------------------------------------------------
# One service account for the workload, one for the push subscriptions. The
# push identity may only invoke the service; it has no data access at all.

resource "google_service_account" "app" {
  account_id   = "${var.service_name}-app"
  display_name = "VendorDiscoveryShortcut workload"
}

resource "google_service_account" "push" {
  account_id   = "${var.service_name}-push"
  display_name = "Pub/Sub and Cloud Tasks push identity"
}

resource "google_project_iam_member" "app_roles" {
  for_each = toset([
    "roles/datastore.user",      # Firestore documents
    "roles/pubsub.publisher",    # emit workflow events
    "roles/cloudtasks.enqueuer", # schedule follow-ups
    "roles/aiplatform.user",     # Gemini on Vertex AI
    "roles/secretmanager.secretAccessor",
    "roles/logging.logWriter",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.app.email}"
}

resource "google_cloud_run_v2_service_iam_member" "push_can_invoke" {
  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.push.email}"
}

# --- State ------------------------------------------------------------------

resource "google_firestore_database" "main" {
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  # Mission history is the audit trail behind every recommendation, and it is
  # cheap. Never let a `tofu destroy` take it.
  deletion_policy = "ABANDON"

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret" "push_token" {
  secret_id = "${var.service_name}-push-token"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "random_password" "push_token" {
  length  = 40
  special = false
}

resource "google_secret_manager_secret_version" "push_token" {
  secret      = google_secret_manager_secret.push_token.id
  secret_data = random_password.push_token.result
}
