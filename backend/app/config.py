"""Runtime configuration.

Every setting is read here and nowhere else: the agents, the workflow and the
adapters are handed a `Settings` and never reach for the environment themselves.
A provider is bound to the real service or the process refuses to start (see
app/adapters/registry.py); none is ever simulated. `mock` below is not an
exception to that — it binds no provider at all and replays a recorded mission.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApprovalPolicy(StrEnum):
    """How much the agent may do without a human in the loop."""

    AUTONOMOUS = "autonomous"          # the default: nothing waits for a human
    EXTERNAL_ACTIONS = "external"      # approve the first email to each vendor
    STRICT = "strict"                  # approve every outbound action


# Preference ladder. The first model that actually answers wins; see
# scripts/check_models.py and app.adapters.gemini_llm.resolve_model.
#
# Reachability is per project and per location, not a property of the model
# name: on one project `gemini-3.5-flash` answers from `global` and 404s from
# `us-central1`, while `gemini-2.5-pro` does the opposite. That is why this is a
# ladder that gets probed rather than a constant.
# Flash first, deliberately. Pro costs roughly an order of magnitude more per
# token and this workload is extraction and adjudication over short excerpts,
# not long-horizon reasoning — flash answers it for a fraction of the money. The
# pro entries stay only so a project that cannot reach any flash model still
# starts.
MODEL_LADDER = (
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-3.5-pro",
    "gemini-3-pro-preview",
    "gemini-2.5-pro",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUPPLYME_", env_file=".env", extra="ignore", protected_namespaces=()
    )

    #: Autonomous by default. The agent is the product: a mission that stops to
    #: ask permission before every email is a form with extra steps, and the
    #: thing worth demonstrating is that it does not need one.
    #:
    #: What makes that safe is `mail_redirect_to`, not a human in the loop. With
    #: it set, every message really sends but reaches the address you nominated
    #: rather than a supplier, so the blast radius of full autonomy is your own
    #: inbox. Unset it and you are writing to real businesses unattended — that
    #: is the moment to choose `external` instead.
    approval_policy: ApprovalPolicy = ApprovalPolicy.AUTONOMOUS

    #: Replay a recorded mission instead of running one. For demonstrating the
    #: system without a model bill, a mailbox, or an hour of wall clock.
    #:
    #: This is not a fixture world. No provider is bound at all — the ones in
    #: `adapters/inert.py` raise if anything reaches them — and every supplier,
    #: price and source URL on screen came out of a mission that really ran
    #: against the live web. The only thing added is a shorter clock.
    #:
    #: Refused when `use_cloud_infra` is on, so it cannot be turned on in the
    #: deployment: a replayed mission in the real Firestore would be
    #: indistinguishable from a real one to anybody reading the console.
    #: `MOCK` as well as the prefixed name, because this is the one setting a
    #: person types on the command line in front of an audience.
    mock: bool = Field(
        default=False, validation_alias=AliasChoices("SUPPLYME_MOCK", "MOCK")
    )

    #: Snapshot to replay. Empty means: the local store file if there is one,
    #: else the newest export in ~/supplyme-firestore-backups.
    mock_recording: str = ""

    #: How long a replayed mission takes end to end. The recorded run took
    #: about an hour and three quarters; 90 seconds is a demo.
    mock_duration_seconds: float = Field(default=90.0, ge=0.0, le=3600.0)

    #: The longest the console may sit still during a replay. Most of a real
    #: mission is waiting for a supplier to answer, and compressing an hour
    #: faithfully puts that whole wait on screen as a dead minute. Gaps longer
    #: than this are shortened to it, which keeps the order and the relative
    #: pacing of everything that actually happened and drops only the silence.
    mock_max_gap_seconds: float = Field(default=3.0, ge=0.0, le=600.0)

    #: Whether to use Firestore, Pub/Sub and Cloud Tasks instead of the
    #: in-process store, bus and scheduler.
    #:
    #: Running against the real Google product APIs and running on Google's own
    #: infrastructure are separate decisions: locally you usually want real
    #: Search and Places with an in-process store, because provisioning
    #: Firestore just to try the thing out is a tax on curiosity. Terraform sets
    #: this true on Cloud Run.
    use_cloud_infra: bool = False

    #: Path to a JSON file the in-process store reads at startup and writes
    #: every change back to. Empty means the store is memory only.
    #:
    #: This is how a local run is driven by real data: point it at a snapshot
    #: from `scripts/export_firestore.py` and the console shows the missions
    #: that actually ran, offline and at no cost. Ignored when
    #: `use_cloud_infra` is on, because Firestore is then the database.
    local_store_path: str = ""

    # --- Google Cloud -------------------------------------------------------
    project_id: str = ""

    #: Region for the Google Cloud services this runs on: Cloud Tasks, and
    #: anything else that takes a location. Must be a real region — Cloud Tasks
    #: rejects `global` outright, which is how these two settings came to be
    #: separate in the first place.
    location: str = "us-central1"

    #: Where Vertex serves the model, which is a different question. Gemini 3.x
    #: answers from the `global` endpoint and returns 404 from a named region,
    #: with nothing in the error to suggest it exists elsewhere. Reachability is
    #: a property of the project and the location together, not of the model
    #: name: on one project `gemini-3.5-flash` answers from `global` while
    #: `gemini-2.5-pro` answers from `us-central1`. See scripts/check_models.py.
    vertex_location: str = "global"
    use_vertex: bool = True

    # Model routing: cheap model for extraction/classification, strong model for
    # planning and adjudication. Empty string means "resolve from MODEL_LADDER".
    reasoning_model: str = ""
    fast_model: str = ""
    gemini_api_key: str = ""

    # --- Infrastructure -----------------------------------------------------
    firestore_database: str = "(default)"

    #: `host:port` of a running Firestore emulator. Set it and the store is the
    #: real `FirestoreStore` — the same client, the same transactions, the same
    #: subcollections — talking to a local process instead of Google, while the
    #: bus and scheduler stay in-process. This is the closest a laptop gets to
    #: the deployed data path, and it costs nothing.
    #:
    #: Read from `FIRESTORE_EMULATOR_HOST` as well as the prefixed name, because
    #: that is the variable the Google client libraries themselves look at: a
    #: shell that has one set and the other not would otherwise have the client
    #: and this file disagreeing about which database is in use.
    firestore_emulator_host: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SUPPLYME_FIRESTORE_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST"
        ),
    )
    #: Terraform sets both from `var.service_name`; these defaults only matter
    #: to a local run that has turned cloud infrastructure on by hand.
    pubsub_topic: str = "supply-me-workflow"
    pubsub_push_token: str = ""            # shared secret on the push endpoint
    tasks_queue: str = "supply-me-followups"
    public_base_url: str = "http://localhost:8080"

    #: Origins allowed to call the API from a browser directly. In the
    #: deployment nothing does — the console proxies every call server-side, so
    #: there is no preflight — and this exists for a developer pointing a
    #: browser at the API while working on it.
    cors_origins: str = "http://localhost:3000"

    # --- External product integrations -------------------------------------
    maps_api_key: str = ""
    search_api_key: str = ""
    search_engine_id: str = ""
    gmail_sender: str = ""

    #: Who the outreach is signed by. The model has no name to sign with and
    #: will invent a bracketed placeholder if left to decide, which is what put
    #: "[Your Name]" into three live supplier emails. Empty means no sign-off
    #: block at all, which is honest; a name here is better.
    buyer_name: str = ""

    #: SMTP, as the short path to real delivery. Gmail accepts an app password
    #: here, which needs no OAuth client and no consent screen. Outbound only:
    #: replies land in the inbox, not back in the mission.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    #: Reading the same mailbox back. The app password that sends also reads, so
    #: closing the loop needs no second credential — see adapters/imap_mail.py.
    imap_host: str = "imap.gmail.com"
    imap_port: int = Field(default=993, ge=1, le=65535)

    #: Send every outbound email here instead of to the supplier. The addresses
    #: in a live mission belong to real businesses, so this is how you prove the
    #: mail path works without writing to one. Empty means mail goes where the
    #: workflow addressed it.
    mail_redirect_to: str = ""

    # --- Cost / depth guards ------------------------------------------------
    max_vendors_per_category: int = Field(default=8, ge=1, le=50)

    #: Ceiling across the whole mission, not per category. Discovery fans out
    #: over every supply-chain node at once, so a per-category cap of 6 across 7
    #: nodes still admits 42 suppliers — and every one of them is then researched
    #: with a tool loop. Researching 40 candidates to recommend 5 is the
    #: expensive way to be thorough; a smaller shortlist researched properly
    #: beats a long one researched cheaply.
    max_vendors_per_mission: int = Field(default=12, ge=1, le=200)
    max_research_depth: int = Field(default=3, ge=1, le=10)
    max_outreach_per_mission: int = Field(default=12, ge=0, le=200)
    max_event_retries: int = Field(default=5, ge=0, le=20)

    #: Ceiling on Gemini requests in flight from this process, across every
    #: agent. `max_concurrent_research` bounds research branches, but discovery
    #: fans out over every supply-chain node at once and each branch calls the
    #: model, so without a gate here a mission opens a dozen simultaneous
    #: requests and Vertex answers 429 to most of them. Rate limits are a
    #: queueing problem: the cheapest fix is to queue.
    max_concurrent_model_calls: int = Field(default=4, ge=1, le=64)

    #: Minimum seconds between the start of one model request and the next.
    #: 0 disables pacing. On a project with no provisioned throughput, a small
    #: value (0.5-1.0) turns a burst that mostly 429s into a queue that mostly
    #: succeeds.
    min_model_call_interval_seconds: float = Field(default=0.0, ge=0.0, le=30.0)

    #: How many vendors may be researched at once. Discovery fans out over every
    #: supply-chain node simultaneously, and each research branch is a tool loop
    #: making several model calls, so without a bound a single mission issues
    #: dozens of concurrent requests and rate-limits itself. Parallelism is still
    #: the point — this caps it at a width the quota can actually serve.
    max_concurrent_research: int = Field(default=3, ge=1, le=32)

    # --- spend guards ---------------------------------------------------
    #: Hard caps per mission. Reaching either fails the mission with a reason
    #: rather than continuing to spend.
    #:
    #: Measured against the live web rather than guessed: a mission over eight
    #: real suppliers made 98 model calls and cost $0.29, on 562,000 input
    #: tokens. Reading real pages is what dominates that — a supplier's site is
    #: tens of thousands of tokens where a fixture was a paragraph — so the
    #: earlier ceiling of 120 calls, set when a mission cost $0.09, would now
    #: fail a mission of twelve suppliers partway through discovery.
    max_model_calls_per_mission: int = Field(default=300, ge=1, le=5000)
    max_usd_per_mission: float = Field(default=1.00, gt=0.0, le=1000.0)

    #: Ceiling on one ADK research agent's tool-use loop. ADK's own default is
    #: 500, which is three orders of magnitude more than this agent needs and is
    #: the single largest runaway risk in the system.
    max_research_llm_calls: int = Field(default=12, ge=1, le=200)

    #: Google Places is billed per request and is the most expensive call this
    #: system makes — roughly an order of magnitude more than a Gemini call. A
    #: mission fans out over every supply-chain node, so this caps how many
    #: locality searches each node may run. 1 is usually enough; the web search
    #: finds the same suppliers and costs far less.
    max_maps_queries_per_node: int = Field(default=1, ge=0, le=5)

    #: Thinking tokens are billed as output, and on 2.5-flash they were roughly
    #: 60% of a measured mission's output spend. Extraction and classification —
    #: reading a price out of an email, deciding whether a search result is a
    #: manufacturer — do not benefit from it, so the fast tier gets none.
    #: Planning and adjudication do benefit, so the reasoning tier keeps a
    #: bounded allowance. -1 means "let the model decide", which is the
    #: expensive option.
    fast_thinking_budget: int = Field(default=0, ge=-1, le=32768)
    reasoning_thinking_budget: int = Field(default=2048, ge=-1, le=32768)
    llm_timeout_seconds: float = 90.0

    #: Run vendor research as a Google ADK tool-use loop, letting the agent
    #: decide which sources to read, instead of pre-fetching a fixed set.
    use_adk_research: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
