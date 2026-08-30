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

resource "google_apikeys_key" "youtube" {
  name         = "${var.service_name}-youtube"
  display_name = "YouTube Data API for ${var.service_name}"

  restrictions {
    api_targets {
      service = "youtube.googleapis.com"
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

resource "google_secret_manager_secret" "youtube_api_key" {
  secret_id = "${var.service_name}-youtube-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "youtube_api_key" {
  secret      = google_secret_manager_secret.youtube_api_key.id
  secret_data = google_apikeys_key.youtube.key_string
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

# The value is not in this repository and is not created by this root. Put it in
# once, by hand, from the machine that has it:
#
#   gcloud secrets versions add vendor-discovery-smtp-password --data-file=-
#
# `ignore_changes` on the secret keeps a later apply from arguing with that.
