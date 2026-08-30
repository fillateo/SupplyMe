# Workflow events. One topic, one push subscription back into the service.
#
# The subscription is where at-least-once delivery becomes real: it retries on
# any non-2xx, which is why the ingress endpoints answer 204 to messages they
# cannot use, and why every handler is keyed on the event's dedup key.

resource "google_pubsub_topic" "workflow" {
  name = "${var.service_name}-workflow"

  message_retention_duration = "86600s" # 24h — long enough to replay a bad deploy

  depends_on = [google_project_service.enabled]
}

resource "google_pubsub_topic" "dead_letter" {
  name = "${var.service_name}-dead-letter"

  depends_on = [google_project_service.enabled]
}

resource "google_pubsub_subscription" "workflow_push" {
  name  = "${var.service_name}-workflow-push"
  topic = google_pubsub_topic.workflow.id

  # Generous: a research handler makes several model calls before it acks.
  ack_deadline_seconds = 300

  push_config {
    # A push subscription cannot set request headers, so the shared secret the
    # endpoint checks travels in the query string. OIDC below is the first lock;
    # this is the second, and the one that still holds while the service is
    # public for a demo.
    push_endpoint = "${google_cloud_run_v2_service.api.uri}/events/pubsub?token=${random_password.push_token.result}"

    oidc_token {
      service_account_email = google_service_account.push.email
    }

    attributes = {
      "x-goog-version" = "v1"
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  # After five failed attempts the message is parked rather than retried
  # forever. A handler that fails five times is a bug to look at, not a
  # transient the workflow will ride out.
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 5
  }

  expiration_policy {
    ttl = "" # never expire
  }
}

# Gmail push notifications land on their own topic; Gmail's own service account
# must be allowed to publish to it.
resource "google_pubsub_topic" "gmail" {
  count = var.gmail_push ? 1 : 0

  name       = "${var.service_name}-gmail"
  depends_on = [google_project_service.enabled]
}

resource "google_pubsub_topic_iam_member" "gmail_publisher" {
  count = var.gmail_push ? 1 : 0

  topic  = google_pubsub_topic.gmail[0].name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:gmail-api-push@system.gserviceaccount.com"
}

resource "google_pubsub_subscription" "gmail_push" {
  count = var.gmail_push ? 1 : 0

  name  = "${var.service_name}-gmail-push"
  topic = google_pubsub_topic.gmail[0].id

  ack_deadline_seconds = 60

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.api.uri}/webhooks/gmail?token=${random_password.push_token.result}"

    oidc_token {
      service_account_email = google_service_account.push.email
    }
  }
}

# Delayed work: follow-ups, non-response timeouts, retry backoff.
resource "google_cloud_tasks_queue" "followups" {
  name     = "${var.service_name}-followups"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 5
    max_concurrent_dispatches = 20
  }

  retry_config {
    max_attempts       = 5
    min_backoff        = "10s"
    max_backoff        = "600s"
    max_retry_duration = "3600s"
  }

  depends_on = [google_project_service.enabled]
}
