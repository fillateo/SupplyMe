"""Application assembly.

Builds providers, agents and the orchestrator, and wires the bus to the
orchestrator's handler. In the cloud, delivery arrives over HTTP from a Pub/Sub
push subscription instead of the local bus, but the object graph is identical —
`Runtime.handle` is the single entry point either way.
"""

from __future__ import annotations

import logging
from typing import Any

from .adapters import registry
from .agents import Agents
from .config import Mode, Settings, get_settings
from .domain.events import Event, EventType
from .domain.models import Mission, MissionStatus
from .workflow import handlers as _handlers  # noqa: F401  (registers handlers)
from .workflow.context import Repo
from .workflow.orchestrator import Orchestrator

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, providers: Any) -> None:
        self.providers = providers
        self.settings: Settings = providers.settings
        self.agents = Agents.build(providers.llm, providers.store)
        self.orchestrator = Orchestrator(providers, self.agents)
        self.repo = Repo(providers.store)
        if hasattr(providers.bus, "subscribe"):
            providers.bus.subscribe(self.handle)

    @classmethod
    def build(
        cls,
        settings: Settings | None = None,
        *,
        llm: Any | None = None,
        demo_speedup: float = 1.0,
        duplicate_rate: float = 0.0,
    ) -> "Runtime":
        settings = settings or get_settings()
        providers = registry.build(
            settings, llm=llm, demo_speedup=demo_speedup, duplicate_rate=duplicate_rate
        )
        return cls(providers)

    async def start(self, concurrency: int = 6) -> None:
        if hasattr(self.providers.bus, "start"):
            await self.providers.bus.start(concurrency)

    async def stop(self) -> None:
        if hasattr(self.providers.scheduler, "cancel_all"):
            await self.providers.scheduler.cancel_all()
        if hasattr(self.providers.bus, "stop"):
            await self.providers.bus.stop()

    async def handle(self, event: Event) -> None:
        await self.orchestrator.handle(event)

    async def create_mission(self, objective: str, *, user_id: str = "demo-user") -> Mission:
        mission = Mission(
            objective=objective.strip(), user_id=user_id,
            status=MissionStatus.CREATED, mode=self.settings.mode.value,
        )
        await self.repo.save(mission)
        await self.orchestrator.emit(
            Event(type=EventType.MISSION_CREATED, mission_id=mission.id)
        )
        return mission

    async def drain(self, timeout: float = 300.0) -> None:
        """Wait for the local bus to go idle. Only meaningful for LocalBus."""
        if hasattr(self.providers.bus, "drain"):
            await self.providers.bus.drain(timeout=timeout)
