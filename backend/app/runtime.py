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
from .config import Settings, get_settings
from .domain.events import Event, EventType
from .domain.models import Mission, MissionStatus, SearchScope
from .workflow import handlers as _handlers  # noqa: F401  (registers handlers)
from .workflow.context import Repo
from .workflow.orchestrator import Orchestrator

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, providers: Any) -> None:
        self.providers = providers
        self.settings: Settings = providers.settings
        self.agents = Agents.build(
            providers.llm, providers.store, research=_research_agent(providers)
        )
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
    ) -> Runtime:
        settings = settings or get_settings()
        providers = registry.build(
            settings, llm=llm, demo_speedup=demo_speedup, duplicate_rate=duplicate_rate
        )
        return cls(providers)

    async def start(self, concurrency: int = 6) -> None:
        if hasattr(self.providers.bus, "start"):
            await self.providers.bus.start(concurrency)
        await self.resume_pending_follow_ups()

    async def resume_pending_follow_ups(self) -> int:
        """Restart whatever a lost scheduler queue left stranded.

        A follow-up is a scheduled event, and an in-process scheduler loses its
        queue when the process dies. The state that matters survives — the thread
        is in the store, marked sent, with its follow-up count — but nothing is
        left to fire, so a supplier who never replies keeps a vendor waiting
        forever and the mission never reaches a recommendation.

        Cloud Tasks persists its own queue, so this is a no-op there. It matters
        exactly where the README says state does not survive a restart, which is
        every local run.
        """
        from .domain.models import EmailThread, ThreadStatus
        from .workflow.handlers import MAX_FOLLOW_UPS

        try:
            threads = await self.repo.list(EmailThread)
        except Exception:  # a store that cannot list is not a reason to fail startup
            log.exception("could not read threads while resuming follow-ups")
            return 0

        rearmed = 0
        for thread in threads:
            if thread.status is not ThreadStatus.SENT:
                continue
            if thread.follow_up_count >= MAX_FOLLOW_UPS:
                # No follow-up left to send, so a timer would do nothing. What
                # this thread needs is for the router to look at it again: it may
                # be holding a disagreement that can no longer be asked about,
                # and until something says so the vendor never reaches a
                # terminal state and the mission never finishes.
                await self.orchestrator.emit(
                    Event(
                        type=EventType.VENDOR_UPDATED,
                        mission_id=thread.mission_id,
                        payload={"vendor_id": thread.vendor_id, "stage": "resumed",
                                 "version": f"{thread.id}:resumed"},
                    )
                )
                rearmed += 1
                continue
            await self.providers.scheduler.schedule(
                Event(
                    type=EventType.FOLLOW_UP_REQUIRED,
                    mission_id=thread.mission_id,
                    payload={
                        "vendor_id": thread.vendor_id, "thread_id": thread.id,
                        "reason": "no response",
                        # Deliberately not the version the live timer uses. An
                        # identical payload is an identical dedup key, so a
                        # re-armed timer would claim the key first and the real
                        # one would then be discarded as a redelivery — leaving
                        # the thread with no timer at all, which is the thing
                        # this is here to prevent.
                        "version": f"{thread.id}:resumed:{thread.follow_up_count}",
                    },
                ),
                delay_seconds=48 * 3600,
            )
            rearmed += 1
        if rearmed:
            log.info("threads_resumed", extra={"status": f"{rearmed} thread(s) picked back up"})
        return rearmed

    async def stop(self) -> None:
        if hasattr(self.providers.scheduler, "cancel_all"):
            await self.providers.scheduler.cancel_all()
        if hasattr(self.providers.bus, "stop"):
            await self.providers.bus.stop()

    async def handle(self, event: Event) -> None:
        await self.orchestrator.handle(event)

    async def create_mission(
        self,
        objective: str,
        *,
        user_id: str = "demo-user",
        location: str | None = None,
        scope: SearchScope = SearchScope.COUNTRY,
    ) -> Mission:
        mission = Mission(
            objective=objective.strip(), user_id=user_id,
            status=MissionStatus.CREATED, mode=self.settings.mode.value,
            location=(location or "").strip() or None, search_scope=scope,
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


def _research_agent(providers: Any) -> Any:
    """Build the ADK research agent when a real model is in play.

    A tool-use loop is the right shape for research and the wrong shape for a
    test: it is non-deterministic by design. So a scripted model always gets the
    pre-fetching agent, and the workflow assertions stay stable either way —
    both satisfy the same `investigate` contract.
    """
    settings: Settings = providers.settings
    if settings.use_scripted_model or not settings.use_adk_research:
        return None
    if type(providers.llm).__name__ != "GeminiLLM":
        return None
    try:
        from .adapters.gemini_llm import _RESOLVED

        model = settings.reasoning_model or _RESOLVED.get("reasoning") or "gemini-2.5-flash"
        from .agents.adk_research import AdkResearchAgent

        return AdkResearchAgent(providers, model, providers.store, llm=providers.llm)
    except Exception:
        log.exception("could not build the ADK research agent; falling back")
        return None
