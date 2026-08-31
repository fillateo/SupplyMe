"""Provider wiring.

The one place that decides what the agent is actually talking to. Everything
downstream receives ports and cannot tell how they were built.

No provider is ever simulated. One is either configured against the real service
or the process refuses to start, and the reason names the variable that is
missing. This used to degrade to a fixture dataset instead, on the argument that
a missing Maps key should cost a mission its geographic evidence rather than the
whole run — which is true, and still produced a system whose most convincing
demonstration was of suppliers that do not exist. Failing at startup is the only
version of this that cannot mislead: a mission either read the real web or never
began.

`SUPPLYME_MOCK` is the one path that does not run a mission, and it does not
weaken that. It binds *nothing* — the inert providers below raise on any call —
and replays a recording of a mission that really ran. There is still no fixture
supplier anywhere in `app/`, and a replay cannot be turned on in the deployment.

`Providers.notes` still reports every choice that was made, and `/api/health`
surfaces it, so what a mission is bound to is answerable without reading code.
"""

from __future__ import annotations

import logging
import os
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
    if settings.mock and settings.use_cloud_infra:
        raise RuntimeError(
            "SUPPLYME_MOCK cannot be used with SUPPLYME_USE_CLOUD_INFRA. A replayed "
            "mission written into the real Firestore would be indistinguishable from "
            "one that actually ran."
        )
    meter = CostMeter(
        max_calls_per_mission=settings.max_model_calls_per_mission,
        max_usd_per_mission=settings.max_usd_per_mission,
    )

    bus = LocalBus()
    scheduler = LocalScheduler(bus)

    if settings.firestore_emulator_host:
        # The Google client libraries route to the emulator off this variable,
        # so export it rather than passing a host down: a client built anywhere
        # else in the process then reaches the same database this one does.
        os.environ["FIRESTORE_EMULATOR_HOST"] = settings.firestore_emulator_host
        from .firestore_store import FirestoreStore

        project = settings.project_id or "supplyme-local"
        store: Any = FirestoreStore(project, settings.firestore_database)
        notes.append(
            f"store: Firestore emulator at {settings.firestore_emulator_host}, project "
            f"{project} — the deployed store adapter against a local process, so nothing "
            "reaches Google and nothing is billed. The bus and scheduler stay in-process."
        )
    elif settings.use_cloud_infra and settings.project_id:
        from .firestore_store import FirestoreStore
        from .pubsub_bus import PubSubBus

        store = FirestoreStore(settings.project_id, settings.firestore_database)
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
    elif settings.local_store_path:
        from .snapshot_store import SnapshotStore

        store = SnapshotStore(settings.local_store_path)
        notes.append(
            f"state is a local file at {settings.local_store_path}: missions survive a restart "
            "and nothing is read from or written to Firestore"
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
                "SUPPLYME_FIRESTORE_EMULATOR_HOST for a local Firestore, "
                "SUPPLYME_LOCAL_STORE_PATH for a snapshot file, or "
                "SUPPLYME_USE_CLOUD_INFRA=true for the real one."
            )

    if settings.mock:
        # Nothing is bound. `runtime.create_mission` replays a recording instead
        # of running the workflow, so no provider should ever be reached — and
        # if one is, these say so rather than answering.
        from .inert import InertProvider

        notes.append(
            "SUPPLYME_MOCK is on: missions are replayed from a recording of a run that "
            "really happened. No model, search, Places or mail provider is bound, and "
            "nothing here can start a new investigation."
        )
        return Providers(
            settings=settings, store=store, bus=bus, scheduler=scheduler,
            llm=InertProvider("model"), meter=meter,
            search=InertProvider("search provider"),
            maps=InertProvider("maps provider"),
            mail=InertProvider("mail provider"),
            notes=notes,
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
    search: Any = GoogleSearchProvider(settings, meter=meter)
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


def _masked(address: str) -> str:
    """An address an operator can recognise but a stranger cannot harvest.

    These notes are surfaced by `/api/health`, which is reachable by anyone the
    deployment is public for — and it has to be, because it is the answer to "is
    this thing actually wired to anything". The notes exist so that whoever runs
    it can tell at a glance where the next email lands, and the first two
    characters plus the domain answer that as well as the whole address does.

    Printing it in full published the operator's own mailbox instead: the
    redirect address, and the sending one, which is the worse of the two to hand
    out because it is a live SMTP account. A demo console linked from a public
    submission page should not also be an address book.
    """
    local, _, domain = address.strip().partition("@")
    if not domain:
        return "(set)"
    return f"{local[:2]}***@{domain}" if local else f"***@{domain}"


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
        f"mail: SMTP out and IMAP in as {_masked(settings.smtp_user)}; replies are read on a "
        "poll rather than pushed"
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
        f"{_masked(target)} rather than to the supplier"
    )
    return RedirectingMailProvider(provider, target)
