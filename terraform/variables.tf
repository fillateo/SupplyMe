variable "project_id" {
  type        = string
  description = "Google Cloud project that owns every resource here."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Region for Cloud Run, Cloud Tasks and Artifact Registry."
}

variable "image" {
  type        = string
  description = "Fully qualified container image for the service."
}

variable "console_image" {
  type        = string
  description = "Fully qualified container image for the Next.js console."
}

variable "service_name" {
  type    = string
  default = "supply-me"
}

variable "gmail_push" {
  type    = bool
  default = false

  description = <<-EOT
    Read replies through the Gmail API instead of over IMAP.

    Truer to how a mailbox should be watched — Google pushes rather than being
    asked — and it needs an OAuth client, a consent screen and a browser
    sign-in from whoever owns the mailbox. Off by default because the app
    password that already sends can also read, and one credential that works
    beats two that need a console. See backend/app/adapters/imap_mail.py.
  EOT
}

variable "publicly_readable" {
  type    = bool
  default = true

  description = <<-EOT
    Let anyone with the link open the console and the API.

    True because the point of deploying is that someone can look. What bounds
    the damage is not the door but the caps: SUPPLYME_MAX_USD_PER_MISSION and
    SUPPLYME_MAX_MODEL_CALLS_PER_MISSION stop a mission rather than warning about
    it, outreach is capped per mission, and while mail_redirect_to is set every
    message goes to that address rather than to a supplier.

    Turn it off before pointing this at real suppliers with the redirect unset.
  EOT
}

variable "mail_redirect_to" {
  type    = string
  default = ""

  description = <<-EOT
    Deliver every outbound message to this address instead of to the supplier.

    The addresses in a mission belong to real businesses, read off their real
    websites. Set this to a mailbox you own unless you have decided, on purpose,
    to write to them. /api/health states which it is.
  EOT
}

variable "smtp_user" {
  type        = string
  default     = ""
  description = "The mailbox that sends and is read back. Its app password lives in Secret Manager."
}

variable "approval_policy" {
  type        = string
  default     = "external"
  description = "autonomous | external | strict — see app/domain/policy.py."
}

variable "use_vertex" {
  type    = bool
  default = true

  description = <<-EOT
    Reach Gemini through Vertex AI rather than the Gemini Developer API.

    True is the right answer whenever the project has Vertex access, because
    Vertex authenticates with the service account this deployment already has
    and needs no separate credential. Set it false only on a project without
    Vertex; gemini.tf then supplies an API key instead.
  EOT
}

variable "vertex_location" {
  type    = string
  default = "global"

  description = <<-EOT
    Which Vertex endpoint serves the model. Deliberately separate from
    var.region, and it has to be: Gemini 3.x is served from `global` and
    returns 404 from a named region, while Cloud Tasks rejects `global` as an
    invalid location. There is no single value that satisfies both, which is
    why there are two variables.

    Cloud Run, Cloud Tasks and Artifact Registry live in var.region. Run
    backend/scripts/check_models.py to see what a project and location resolve
    to before changing this.
  EOT
}

variable "reasoning_model" {
  type        = string
  default     = ""
  description = "Empty resolves the newest reachable model from the ladder in app/config.py."
}

variable "fast_model" {
  type    = string
  default = ""
}

variable "max_instances" {
  type        = number
  default     = 4
  description = "Instance cap. The workflow is idempotent, so extra instances are safe, but this bounds spend."
}

variable "budget_amount_usd" {
  type    = number
  default = 20

  description = <<-EOT
    Monthly budget that triggers alerts. Set to 0 to skip creating one.

    A budget alert does NOT stop spending — it emails you. The hard stops live in
    the application (SUPPLYME_MAX_USD_PER_MISSION, SUPPLYME_MAX_MODEL_CALLS_PER_MISSION)
    and in the caps below. Set this well under your remaining credit so the
    warning arrives while you can still act on it.
  EOT
}

variable "max_usd_per_mission" {
  type        = number
  default     = 1.00
  description = "Hard stop. A mission that reaches this fails with a reason instead of spending more."
}

variable "billing_account" {
  type        = string
  default     = ""
  description = "Required only when budget_amount_usd > 0."
}

variable "alert_email" {
  type        = string
  default     = ""
  description = "Where budget alerts go."
}
