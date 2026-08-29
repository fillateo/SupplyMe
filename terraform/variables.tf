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
  description = "demo binds the mock providers; live binds Gmail, Places and telephony."

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
    the application (VDS_MAX_USD_PER_MISSION, VDS_MAX_MODEL_CALLS_PER_MISSION)
    and in the caps below. Set this well under your remaining credit so the
    warning arrives while you can still act on it.
  EOT
}

variable "max_calls_per_mission" {
  type        = number
  default     = 3
  description = "Telephony is the one line item that can cost real money per unit."
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
