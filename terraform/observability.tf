# Cost control and the two alerts worth waking up for.

resource "google_billing_budget" "monthly" {
  count = var.budget_amount_usd > 0 && var.billing_account != "" ? 1 : 0

  billing_account = var.billing_account
  display_name    = "${var.service_name} monthly"

  budget_filter {
    projects = ["projects/${var.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.budget_amount_usd)
    }
  }

  # 50% is a heads-up, 90% is act now, 100% is stop.
  dynamic "threshold_rules" {
    for_each = [0.5, 0.9, 1.0]
    content {
      threshold_percent = threshold_rules.value
    }
  }

  all_updates_rule {
    monitoring_notification_channels = var.alert_email != "" ? [
      google_monitoring_notification_channel.email[0].id
    ] : []
    disable_default_iam_recipients = false
  }
}

resource "google_monitoring_notification_channel" "email" {
  count = var.alert_email != "" ? 1 : 0

  display_name = "${var.service_name} alerts"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.enabled]
}

# A message reaching the dead-letter topic means a handler failed five times.
# That is always a bug, never a transient.
resource "google_monitoring_alert_policy" "dead_letter" {
  count = var.alert_email != "" ? 1 : 0

  display_name = "${var.service_name}: events are being dead-lettered"
  combiner     = "OR"

  conditions {
    display_name = "dead-letter topic received a message"

    condition_threshold {
      filter = join(" AND ", [
        "resource.type = \"pubsub_topic\"",
        "resource.labels.topic_id = \"${google_pubsub_topic.dead_letter.name}\"",
        "metric.type = \"pubsub.googleapis.com/topic/send_message_operation_count\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "60s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email[0].id]

  documentation {
    content = join("\n", [
      "A workflow event failed five delivery attempts and was parked.",
      "",
      "Find it with:",
      "  gcloud pubsub subscriptions pull ${google_pubsub_topic.dead_letter.name}-sub --auto-ack",
      "",
      "Then filter the mission's own log by the event id:",
      "  resource.type=cloud_run_revision AND jsonPayload.event_id=\"<id>\"",
      "",
      "Every handler is idempotent, so replaying a fixed event to the workflow",
      "topic is safe once the cause is understood.",
    ])
  }
}

# A log-based metric for the one thing a reviewer will ask about: how often does
# a supplier's own content try to give the agent instructions?
resource "google_logging_metric" "injection_attempts" {
  name   = "${var.service_name}_injection_flagged"
  filter = "resource.type=\"cloud_run_revision\" AND jsonPayload.message=\"untrusted_content_flagged\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.enabled]
}
