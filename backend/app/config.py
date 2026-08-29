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

    #: How many vendors may be researched at once. Discovery fans out over every
    #: supply-chain node simultaneously, and each research branch is a tool loop
    #: making several model calls, so without a bound a single mission issues
    #: dozens of concurrent requests and rate-limits itself. Parallelism is still
    #: the point — this caps it at a width the quota can actually serve.
    max_concurrent_research: int = Field(default=3, ge=1, le=32)

    # --- spend guards ---------------------------------------------------
    #: Hard caps per mission. Reaching either fails the mission with a reason
    #: rather than continuing to spend. A healthy perfume mission uses roughly
    #: 40-60 model calls; the defaults leave headroom without leaving a runaway
    #: room to matter.
    max_model_calls_per_mission: int = Field(default=120, ge=1, le=5000)
    max_usd_per_mission: float = Field(default=0.50, gt=0.0, le=1000.0)

    #: Ceiling on one ADK research agent's tool-use loop. ADK's own default is
    #: 500, which is three orders of magnitude more than this agent needs and is
    #: the single largest runaway risk in the system.
    max_research_llm_calls: int = Field(default=12, ge=1, le=200)

    #: Thinking tokens are billed as output, and on 2.5-flash they were roughly
    #: 60% of a measured mission's output spend. Extraction and classification —
    #: reading a price out of an email, deciding whether a search result is a
    #: manufacturer — do not benefit from it, so the fast tier gets none.
    #: Planning and adjudication do benefit, so the reasoning tier keeps a
    #: bounded allowance. -1 means "let the model decide", which is the default
    #: and the expensive option.
    fast_thinking_budget: int = Field(default=0, ge=-1, le=32768)
    reasoning_thinking_budget: int = Field(default=2048, ge=-1, le=32768)
    llm_timeout_seconds: float = 90.0

    #: Compresses scheduled delays in DEMO mode. A 48-hour follow-up timer is
    #: correct behaviour and useless in a four-minute demo, so the clock — not
    #: the workflow — is what gets sped up. Ignored in LIVE mode, where the
    #: scheduler is Cloud Tasks and the delays are real.
    demo_speedup: float = Field(default=1.0, ge=1.0, le=1_000_000.0)
    #: Redelivers this fraction of events, to demonstrate idempotency on demand.
    demo_duplicate_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    #: Bind the deterministic scripted model instead of Gemini. The entire
    #: system then runs with no Google Cloud project, no API key and no network
    #: — same agents, same events, same storage, same scoring. Intended for
    #: local development, for the test suite, and for anyone who wants to see
    #: the workflow before setting up credentials.
    use_scripted_model: bool = False

    #: Run vendor research as a Google ADK tool-use loop, letting the agent
    #: decide which sources to read, instead of pre-fetching a fixed set. Off
    #: when the model is scripted, because the tests assert on workflow
    #: behaviour and a tool loop is not deterministic.
    use_adk_research: bool = True

    @property
    def is_demo(self) -> bool:
        return self.mode is Mode.DEMO


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
