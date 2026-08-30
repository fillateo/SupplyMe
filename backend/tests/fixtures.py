"""Assembling a runtime out of test doubles.

`app/adapters/registry.py` builds real providers or refuses to start, which is
what makes a mission's evidence trustworthy and what makes it useless for
tests. So the suite bypasses the registry and constructs `Providers` itself:
the same dataclass, the same ports, the same orchestrator and handlers — only
the four things that would otherwise reach the network are doubles.
"""

from __future__ import annotations

from typing import Any

from app.adapters.local_bus import LocalBus
from app.adapters.memory_store import MemoryStore
from app.adapters.registry import Providers
from app.adapters.scheduler import LocalScheduler
from app.config import Settings
from app.domain.cost import CostMeter
from app.runtime import Runtime

from .doubles_llm import (  # noqa: F401  — re-exported for tests that build their own
    NODES,
    _discovery,
    _extract_quote,
    build_scripted_llm,
)
from .doubles_providers import (
    MockMailProvider,
    MockMapsProvider,
    MockSearchProvider,
    MockVideoProvider,
)


def build_providers(
    settings: Settings,
    *,
    llm: Any | None = None,
    speedup: float = 200_000.0,
    duplicate_rate: float = 0.0,
) -> Providers:
    """Everything a mission needs, with the outside world replaced.

    `speedup` compresses the scheduler's clock so a 48-hour follow-up timer does
    not make a test take two days. `duplicate_rate` redelivers that fraction of
    events, which is how the suite asserts that redelivery is a no-op rather
    than a second email.
    """
    bus = LocalBus(duplicate_rate=duplicate_rate)
    scheduler = LocalScheduler(bus, speedup=speedup)
    mail = MockMailProvider()
    mail.bind(bus, scheduler)

    return Providers(
        settings=settings,
        store=MemoryStore(),
        bus=bus,
        scheduler=scheduler,
        llm=llm or build_scripted_llm(),
        meter=CostMeter(
            max_calls_per_mission=settings.max_model_calls_per_mission,
            max_usd_per_mission=settings.max_usd_per_mission,
        ),
        search=MockSearchProvider(),
        maps=MockMapsProvider(),
        video=MockVideoProvider(),
        mail=mail,
        notes=[],
    )


def build_runtime(settings: Settings, **kw: Any) -> Runtime:
    return Runtime(build_providers(settings, **kw))
