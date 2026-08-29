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
    MockVoiceProvider,
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
    voice: Any
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
            "voice": type(self.voice).__name__,
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

    if settings.mode is Mode.LIVE and settings.project_id:
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
        if settings.mode is Mode.LIVE:
            notes.append("LIVE mode without VDS_PROJECT_ID: using in-memory store and local bus")

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
            mail=mail, voice=MockVoiceProvider(), notes=notes,
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
    voice_provider: Any = _build_voice(settings, notes)

    return Providers(
        settings=settings, store=store, bus=bus, scheduler=scheduler, llm=llm,
        meter=meter, search=search, maps=maps, video=video, mail=mail_provider,
        voice=voice_provider, notes=notes,
    )


def _build_mail(settings: Settings, bus: Any, scheduler: Any, notes: list[str]) -> Any:
    from pathlib import Path

    token_path = Path("secrets/gmail_token.json")
    if not token_path.exists():
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


def _build_voice(settings: Settings, notes: list[str]) -> Any:
    from .twilio_voice import TwilioVoiceProvider

    provider = TwilioVoiceProvider(settings)
    if provider.configured:
        return provider
    notes.append("telephony not configured: calls run against the mock voice provider")
    return MockVoiceProvider()
