"""Provider wiring.

The only place in the system that branches on LIVE vs DEMO. Everything
downstream receives ports and cannot tell which mode it is running in.

A live provider that is not configured degrades to its mock rather than
failing the mission — a missing Maps key should cost the mission its geographic
evidence, not the whole run. Every such substitution is reported in
`Providers.notes` and surfaced in the API so a demo never silently claims to
have used a Google API it did not call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..config import Mode, Settings
from ..domain.cost import CostMeter
from .demo_world import DISCLAIMER
from .local_bus import LocalBus
from .memory_store import MemoryStore
from .mock_providers import (
    MockMailProvider,
    MockMapsProvider,
    MockSearchProvider,
    MockVideoProvider,
)
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
    video: Any
    mail: Any
    notes: list[str] = field(default_factory=list)

    def describe(self) -> dict[str, str]:
        return {
            "mode": self.settings.mode.value,
            "store": type(self.store).__name__,
            "bus": type(self.bus).__name__,
            "scheduler": type(self.scheduler).__name__,
            "llm": type(self.llm).__name__,
            "search": type(self.search).__name__,
            "maps": type(self.maps).__name__,
            "video": type(self.video).__name__,
            "mail": type(self.mail).__name__,
        }


def build(
    settings: Settings,
    *,
    llm: Any | None = None,
    demo_speedup: float = 1.0,
    duplicate_rate: float = 0.0,
) -> Providers:
    notes: list[str] = []
    meter = CostMeter(
        max_calls_per_mission=settings.max_model_calls_per_mission,
        max_usd_per_mission=settings.max_usd_per_mission,
    )

    bus = LocalBus(duplicate_rate=duplicate_rate)
    scheduler = LocalScheduler(bus, speedup=demo_speedup)

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
                # A demo deployment on real infrastructure still needs the demo
                # clock, or it sits on a 48-hour timer while someone watches.
                speedup=demo_speedup if settings.is_demo else 1.0,
            )
    else:
        store = MemoryStore()
        if settings.use_cloud_infra:
            notes.append(
                "VDS_USE_CLOUD_INFRA is set but VDS_PROJECT_ID is not: falling back to "
                "the in-process store and bus"
            )
        elif settings.mode is Mode.LIVE:
            notes.append(
                "state is in-process: missions do not survive a restart. Set "
                "VDS_USE_CLOUD_INFRA=true with a Firestore database to persist them."
            )

    if llm is None:
        if settings.use_scripted_model:
            from .scripted_world import build_scripted_llm

            llm = build_scripted_llm()
            notes.append(
                "VDS_USE_SCRIPTED_MODEL is on: responses are deterministic and no "
                "Gemini call is made. The workflow, events, storage and scoring are "
                "unchanged."
            )
        elif settings.mode is Mode.LIVE or settings.project_id or settings.gemini_api_key:
            from .gemini_llm import GeminiLLM

            llm = GeminiLLM(settings, meter=meter)
        else:
            raise RuntimeError(
                "No model configured. Either set VDS_PROJECT_ID (Vertex AI) or "
                "VDS_GEMINI_API_KEY, or set VDS_USE_SCRIPTED_MODEL=true to run the "
                "whole system deterministically with no credentials."
            )

    if settings.mode is Mode.DEMO:
        notes.append(DISCLAIMER)
        mail = MockMailProvider()
        mail.bind(bus, scheduler)
        return Providers(
            settings=settings, store=store, bus=bus, scheduler=scheduler, llm=llm,
            meter=meter,
            search=MockSearchProvider(), maps=MockMapsProvider(), video=MockVideoProvider(),
            mail=mail, notes=notes,
        )

    from .google_providers import GoogleSearchProvider, PlacesProvider, YouTubeProvider

    search: Any = GoogleSearchProvider(settings)
    if not (settings.search_api_key and settings.search_engine_id):
        notes.append("no Programmable Search engine configured: using Gemini search grounding")

    if settings.maps_api_key:
        maps: Any = PlacesProvider(settings)
    else:
        maps = MockMapsProvider()
        notes.append("VDS_MAPS_API_KEY unset: Places evidence comes from the demo dataset")

    if settings.youtube_api_key:
        video: Any = YouTubeProvider(settings)
    else:
        video = MockVideoProvider()
        notes.append("VDS_YOUTUBE_API_KEY unset: video evidence comes from the demo dataset")

    mail_provider: Any = _build_mail(settings, bus, scheduler, notes)

    return Providers(
        settings=settings, store=store, bus=bus, scheduler=scheduler, llm=llm,
        meter=meter, search=search, maps=maps, video=video, mail=mail_provider,
        notes=notes,
    )


def _build_mail(settings: Settings, bus: Any, scheduler: Any, notes: list[str]) -> Any:
    return _redirected(_real_mail(settings, bus, scheduler, notes), settings, notes)


def _real_mail(settings: Settings, bus: Any, scheduler: Any, notes: list[str]) -> Any:
    from pathlib import Path

    token_path = Path("secrets/gmail_token.json")
    if not token_path.exists():
        # No OAuth token, but an app password is enough to actually send. Chosen
        # ahead of the mock so that "configured to send" beats "configured to
        # pretend", and reported either way.
        from .smtp_mail import SmtpMailProvider

        smtp = SmtpMailProvider(settings)
        if smtp.configured:
            notes.append(
                f"sending real email over SMTP as {settings.smtp_user}; replies are not "
                "read back into the mission (Gmail OAuth does that — see scripts/gmail_auth.py)"
            )
            return smtp

        notes.append(
            "no Gmail credentials at secrets/gmail_token.json: outreach runs against the "
            "mock mail provider (see scripts/gmail_auth.py)"
        )
        mock = MockMailProvider()
        mock.bind(bus, scheduler)
        return mock
    import json

    from .gmail_provider import GmailProvider, credentials_from_dict

    return GmailProvider(settings, credentials_from_dict(json.loads(token_path.read_text())))


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

    if isinstance(provider, MockMailProvider):
        # The mock decides whether to schedule a scripted reply by looking at who
        # the message was addressed to. Redirecting it would send every demo
        # supplier's reply into the void and leave the mission waiting on an
        # answer that cannot arrive — and the mock reaches nobody anyway, so
        # there is nothing here to protect.
        notes.append(
            f"VDS_MAIL_REDIRECT_TO={target} is set but mail is mocked, so nothing "
            "is sent at all and the redirect does nothing"
        )
        return provider

    from .mail_redirect import RedirectingMailProvider

    notes.append(
        f"VDS_MAIL_REDIRECT_TO is set: every outbound email really sends, but to "
        f"{target} rather than to the supplier"
    )
    return RedirectingMailProvider(provider, target)
