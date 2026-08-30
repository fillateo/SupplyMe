# What asks the mailbox whether a supplier has answered.
#
# IMAP has no push, so something has to ask. This is also what wakes the
# service: Cloud Run scales to zero between missions, and a reply that arrives
# while nothing is running would otherwise sit unread until the next time a
# human happened to open the console.
#
# One minute is chosen against what it costs rather than against how fast mail
# needs to be read. A poll is one Cloud Run request and one IMAP round trip, no
# model call and no Firestore write when nothing is new, so the floor is close
# to free — and a supplier who answers at 2am is picked up at 2am rather than
# whenever someone next looks.

# Cloud Scheduler mints the OIDC token as the push identity, which requires
# permission to impersonate it. Granted explicitly rather than relied on: the
# default service-agent role has covered this, and a job that cannot mint its
# token fails by going quiet — ENABLED, schedule elapsing, nothing arriving —
# which is an expensive silence to diagnose.
resource "google_service_account_iam_member" "scheduler_can_mint_push_tokens" {
  service_account_id = google_service_account.push.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
}

resource "google_cloud_scheduler_job" "mail_poll" {
  name        = "${var.service_name}-mail-poll"
  description = "Read supplier replies out of the mailbox and resume their missions."
  schedule    = "* * * * *"
  time_zone   = "Etc/UTC"
  region      = var.region

  # A poll that overruns is not worth retrying: another one is a minute away,
  # and the cursor was not advanced, so nothing was skipped.
  attempt_deadline = "60s"

  retry_config {
    retry_count = 0
  }

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.api.uri}/webhooks/mail/poll"

    # Two locks, as on the Pub/Sub push endpoint: OIDC proves the caller is this
    # scheduler, and the shared secret still holds when the service is
    # deliberately public so a judge can open it.
    headers = {
      "Content-Type" = "application/json"
      # The same shared secret the Pub/Sub push and Cloud Tasks endpoints carry.
      # OIDC alone would not get past verify_push_token, and finding that out
      # from a silent 403 once a minute is a poor way to spend an afternoon.
      "X-VDS-Token" = random_password.push_token.result
    }

    oidc_token {
      service_account_email = google_service_account.push.email
      audience              = google_cloud_run_v2_service.api.uri
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_cloud_run_v2_service_iam_member.push_can_invoke,
    google_service_account_iam_member.scheduler_can_mint_push_tokens,
  ]
}
