# Keys for the Google product APIs the agent reads evidence from.
#
# Created here, restricted to one API each, and stored in Secret Manager, for
# the same reasons as the Gemini key in gemini.tf: the restriction is reviewable
# in a plan, and no key is ever a value someone has to paste into a console or
# a file. A key that can reach every enabled API in the project is a credential,
# not a scoped one.

resource "google_apikeys_key" "places" {
  name         = "${var.service_name}-places"
  display_name = "Google Places for ${var.service_name}"

  restrictions {
    api_targets {
      service = "places.googleapis.com"
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret" "maps_api_key" {
  secret_id = "${var.service_name}-maps-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "maps_api_key" {
  secret      = google_secret_manager_secret.maps_api_key.id
  secret_data = google_apikeys_key.places.key_string
}

# Sending and reading the mailbox. One app password does both — see
# backend/app/adapters/imap_mail.py — so there is a single secret here rather
# than an OAuth client, a consent screen and a refresh token.
resource "google_secret_manager_secret" "smtp_password" {
  secret_id = "${var.service_name}-smtp-password"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

# REQUIRED MANUAL STEP. This root creates the secret but deliberately not its
# value — an app password does not belong in a tfvars file or a state bucket. A
# Cloud Run revision cannot start until a version exists, so do this once,
# before the first apply that creates the service:
#
#   gcloud secrets versions add supply-me-smtp-password --project PROJECT \
#     --data-file=-
#
# Terraform never reads or rotates it afterwards, so a later apply leaves
# whatever version is current alone.
