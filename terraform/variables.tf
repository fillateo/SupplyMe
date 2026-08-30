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

variable "service_name" {
  type    = string
  default = "vendor-discovery"
}

variable "mode" {
  type        = string
  default     = "demo"
  description = "demo binds the mock providers; live binds Gmail, Search and Places."

  validation {
    condition     = contains(["demo", "live"], var.mode)
    error_message = "mode must be demo or live."
  }
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

variable "demo_speedup" {
  type    = number
  default = 1.0

  description = <<-EOT
    Divides scheduled delays, in demo mode only.

    A 48-hour follow-up timer is correct behaviour and useless to anyone
    watching: a demo deployment left at 1.0 shows a mission that reaches
    `awaiting_response` and then appears to stall for two days, because Cloud
    Tasks is faithfully holding the timer. 2000 turns that wait into about 90
    seconds.

    It compresses the clock, never the workflow, and it cannot shorten a retry
    backoff — shortening those would land the retries inside the same
    overloaded window they exist to avoid. Ignored entirely when mode is live.
  EOT

  validation {
    condition     = var.mode == "demo" || var.demo_speedup == 1.0
    error_message = "demo_speedup only applies in demo mode; leave it at 1.0 for live."
  }
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
    the application (VDS_MAX_USD_PER_MISSION, VDS_MAX_MODEL_CALLS_PER_MISSION)
    and in the caps below. Set this well under your remaining credit so the
    warning arrives while you can still act on it.
  EOT
}

variable "max_usd_per_mission" {
  type        = number
  default     = 0.50
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
