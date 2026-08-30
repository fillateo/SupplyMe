"""Provider wiring.

The one place that decides what the agent is actually talking to. Everything
downstream receives ports and cannot tell how they were built.

There is no simulated mode. A provider is either configured against the real
service or the process refuses to start, and the reason names the variable that
is missing. This used to degrade to a fixture dataset instead, on the argument
that a missing Maps key should cost a mission its geographic evidence rather
than the whole run — which is true, and still produced a system whose most
convincing demonstration was of suppliers that do not exist. Failing at startup
is the only version of this that cannot mislead: a mission either read the real
web or never began.

`Providers.notes` still reports every choice that was made, and `/api/health`
surfaces it, so what a mission is bound to is answerable without reading code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from ..domain.cost import CostMeter
from .local_bus import LocalBus
from .memory_store import MemoryStore
from .scheduler import LocalScheduler

log = logging.getLogger(__name__)


@dataclass
class Providers:
    settings: Settings
    store: Any
    bus: Any
    scheduler: Any
    llm: Any
    meter: CostMeter
    search: Any
    maps: Any
    mail: Any
    notes: list[str] = field(default_factory=list)

    def describe(self) -> dict[str, str]:
        return {
            "store": type(self.store).__name__,
            "bus": type(self.bus).__name__,
            "scheduler": type(self.scheduler).__name__,
            "llm": type(self.llm).__name__,
            "search": type(self.search).__name__,
            "maps": type(self.maps).__name__,
            "mail": type(self.mail).__name__,
        }


def build(settings: Settings, *, llm: Any | None = None) -> Providers:
    notes: list[str] = []
    meter = CostMeter(
        max_calls_per_mission=settings.max_model_calls_per_mission,
        max_usd_per_mission=settings.max_usd_per_mission,
    )

    bus = LocalBus()
    scheduler = LocalScheduler(bus)

    if settings.use_cloud_infra and settings.project_id:
        from .firestore_store import FirestoreStore
        from .pubsub_bus import PubSubBus

        store: Any = FirestoreStore(settings.project_id, settings.firestore_database)
        bus = PubSubBus(settings.project_id, settings.pubsub_topic)
        if settings.tasks_queue:
            from .scheduler import CloudTasksScheduler

            scheduler = CloudTasksScheduler(
                settings.project_id,
                settings.location,
                settings.tasks_queue,
                f"{settings.public_base_url.rstrip('/')}/events/task",
                settings.pubsub_push_token,
            )
    else:
        store = MemoryStore()
        if settings.use_cloud_infra:
            notes.append(
                "SUPPLYME_USE_CLOUD_INFRA is set but SUPPLYME_PROJECT_ID is not: falling back to "
                "the in-process store and bus"
            )
        else:
            notes.append(
                "state is in-process: missions do not survive a restart. Set "
                "SUPPLYME_USE_CLOUD_INFRA=true with a Firestore database to persist them."
            )

    if llm is None:
        if not (settings.project_id or settings.gemini_api_key):
            raise RuntimeError(
                "No model configured. Set SUPPLYME_PROJECT_ID for Vertex AI, or "
                "SUPPLYME_GEMINI_API_KEY for the Gemini Developer API."
            )
        from .gemini_llm import GeminiLLM

        llm = GeminiLLM(settings, meter=meter)

    from .google_providers import GoogleSearchProvider, PlacesProvider

    # Search has two real implementations and no unconfigured state: with a
    # Programmable Search engine it queries one, and without it falls back to
    # Gemini's own search grounding. Both read the live web.
    search: Any = GoogleSearchProvider(settings)
    notes.append(
        "search: Programmable Search engine"
        if settings.search_api_key and settings.search_engine_id
        else "search: Gemini search grounding (no SUPPLYME_SEARCH_ENGINE_ID configured)"
    )

    _require(settings.maps_api_key, "SUPPLYME_MAPS_API_KEY", "Google Places")
    maps: Any = PlacesProvider(settings)

    mail_provider: Any = _build_mail(settings, notes)

    return Providers(
        settings=settings, store=store, bus=bus, scheduler=scheduler, llm=llm,
        meter=meter, search=search, maps=maps, mail=mail_provider,
        notes=notes,
    )


def _require(value: str, variable: str, what: str) -> None:
    """Refuse to start rather than quietly substituting something invented."""
    if not value:
        raise RuntimeError(
            f"{variable} is not set, so {what} cannot be reached. "
            "This system has no simulated providers: set it, or do not run."
        )


def _build_mail(settings: Settings, notes: list[str]) -> Any:
    return _redirected(_real_mail(settings, notes), settings, notes)


def _real_mail(settings: Settings, notes: list[str]) -> Any:
    """Gmail over OAuth when a token exists, otherwise SMTP plus IMAP.

    Both send and both read, which is what the workflow needs — a mission that
    cannot hear an answer follows up on silence forever. They differ in how the
    answer arrives: Gmail pushes, and IMAP has to be asked, which is what the
    Cloud Scheduler job in terraform/scheduler.tf is for.
    """
    from pathlib import Path

    token_path = Path("secrets/gmail_token.json")
    if token_path.exists():
        import json

        from .gmail_provider import GmailProvider, credentials_from_dict

        notes.append("mail: Gmail API, replies arrive by push notification")
        return GmailProvider(settings, credentials_from_dict(json.loads(token_path.read_text())))

    from .imap_mail import SmtpImapMailProvider

    provider = SmtpImapMailProvider(settings)
    _require(
        settings.smtp_user and settings.smtp_password,
        "SUPPLYME_SMTP_USER / SUPPLYME_SMTP_PASSWORD",
        "the mailbox",
    )
    notes.append(
        f"mail: SMTP out and IMAP in as {settings.smtp_user}; replies are read on a poll "
        "rather than pushed"
    )
    return provider


def _redirected(provider: Any, settings: Settings, notes: list[str]) -> Any:
    """Wrap the mail provider when a test recipient is configured.

    Applied here rather than inside a provider so it holds whichever one is
    bound, and so `/api/health` can state plainly where mail is going. An
    operator who cannot tell from the health endpoint whether the next approval
    writes to a supplier will eventually find out the hard way.
    """
    target = settings.mail_redirect_to.strip()
    if not target:
        return provider

    from .mail_redirect import RedirectingMailProvider

    notes.append(
        f"SUPPLYME_MAIL_REDIRECT_TO is set: every outbound email really sends, but to "
        f"{target} rather than to the supplier"
    )
    return RedirectingMailProvider(provider, target)
