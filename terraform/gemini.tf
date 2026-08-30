# A Gemini Developer API key, for deployments on a project without Vertex.
#
# Vertex is the default and the better path when it is available: it
# authenticates with the service account this deployment already has, so there
# is no second credential to provision, mount or rotate. This key exists for
# the case where that is not an option.
#
# app/adapters/gemini_llm.py treats the two as interchangeable — it builds a
# Vertex client when use_vertex and a project id are both set, and an API-key
# client otherwise — and Google ADK is handed that same client, so the research
# tool loop follows the same credential without a second code path.
#
# Created here rather than in the console so its API restriction is reviewable
# in a plan, and so the value never has to be pasted anywhere.

resource "google_apikeys_key" "gemini" {
  name         = "${var.service_name}-gemini"
  display_name = "Gemini Developer API for ${var.service_name}"

  restrictions {
    # The only API this key may call. A key that can reach every enabled
    # service in the project is a credential, not a scoped one.
    api_targets {
      service = "generativelanguage.googleapis.com"
    }
  }

  depends_on = [google_project_service.enabled]
}

# Cloud Run reads the key from Secret Manager rather than from a plain
# environment value, so it is not visible in the service description or to
# anyone with viewer access to the revision.
resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "${var.service_name}-gemini-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "gemini_api_key" {
  secret      = google_secret_manager_secret.gemini_api_key.id
  secret_data = google_apikeys_key.gemini.key_string
}
