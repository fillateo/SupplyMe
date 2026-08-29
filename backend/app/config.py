"""Runtime configuration.

Everything that differs between LIVE and DEMO mode is resolved here and nowhere
else. The agent/workflow code never reads environment variables directly.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Mode(StrEnum):
    LIVE = "live"
    DEMO = "demo"


class ApprovalPolicy(StrEnum):
    """How much the agent may do without a human in the loop."""

    AUTONOMOUS = "autonomous"          # no approvals; used for tests and offline demo
    EXTERNAL_ACTIONS = "external"      # approve first email/call per vendor (default)
    STRICT = "strict"                  # approve every outbound action


# Preference ladder. The first model that actually answers wins; see
# scripts/check_models.py and app.adapters.gemini_llm.resolve_model.
MODEL_LADDER = (
    "gemini-3.5-pro",
    "gemini-3.5-flash",
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VDS_", env_file=".env", extra="ignore", protected_namespaces=()
    )

    mode: Mode = Mode.DEMO
    approval_policy: ApprovalPolicy = ApprovalPolicy.EXTERNAL_ACTIONS

    # --- Google Cloud -------------------------------------------------------
    project_id: str = ""
    location: str = "us-central1"
    use_vertex: bool = True

    # Model routing: cheap model for extraction/classification, strong model for
    # planning and adjudication. Empty string means "resolve from MODEL_LADDER".
    reasoning_model: str = ""
    fast_model: str = ""
    gemini_api_key: str = ""

    # --- Infrastructure -----------------------------------------------------
    firestore_database: str = "(default)"
    pubsub_topic: str = "vds-workflow"
    pubsub_push_token: str = ""            # shared secret on the push endpoint
    tasks_queue: str = "vds-followups"
    public_base_url: str = "http://localhost:8080"

    # --- External product integrations -------------------------------------
    maps_api_key: str = ""
    search_api_key: str = ""
    search_engine_id: str = ""
    youtube_api_key: str = ""
    gmail_sender: str = ""
    gmail_topic: str = ""                  # Gmail watch -> Pub/Sub topic
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # --- Cost / depth guards ------------------------------------------------
    max_vendors_per_category: int = Field(default=8, ge=1, le=50)
    max_research_depth: int = Field(default=3, ge=1, le=10)
    max_outreach_per_mission: int = Field(default=12, ge=0, le=200)
    max_calls_per_mission: int = Field(default=3, ge=0, le=50)
    max_event_retries: int = Field(default=5, ge=0, le=20)
    llm_timeout_seconds: float = 90.0

    @property
    def is_demo(self) -> bool:
        return self.mode is Mode.DEMO


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
