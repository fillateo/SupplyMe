terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State lives in GCS in the same project. This is a standalone hackathon
  # project and deliberately does not touch the nesso or cato state buckets —
  # those planes stay isolated. Run `tofu init -backend-config=backend.hcl`.
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region

  # The API Keys API bills each request to a quota project, and Application
  # Default Credentials do not set one. Without these two lines, creating the
  # Gemini key fails with a 403 naming a Google-owned project number rather
  # than yours, which is a confusing way to be told to set a quota project.
  billing_project       = var.project_id
  user_project_override = true
}
