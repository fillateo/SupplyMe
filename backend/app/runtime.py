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
from .domain.models import utcnow as _utcnow
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
        self.replay = _replay(providers)
        self._replays: set[Any] = set()
        if hasattr(providers.bus, "subscribe"):
            providers.bus.subscribe(self.handle)

    @classmethod
    def build(
        cls,
        settings: Settings | None = None,
        *,
        llm: Any | None = None,
    ) -> Runtime:
        settings = settings or get_settings()
        return cls(registry.build(settings, llm=llm))

    async def start(self, concurrency: int = 6) -> None:
        if hasattr(self.providers.bus, "start"):
            await self.providers.bus.start(concurrency)
        await self.release_stale_approvals()
        await self.resume_pending_follow_ups()

    async def release_stale_approvals(self) -> int:
        """Let go of approvals the current policy would never have asked for.

        An approval is raised under whatever policy was in force at the time, and
        the policy outlives it. Loosen the policy — `external` to `autonomous`,
        say — and every approval already pending stays pending, because nothing
        revisits a decision that has already been recorded as needed. The mission
        is then blocked on a question the system has stopped asking, and the
        console tells whoever opens it that a human is required by a deployment
        whose whole claim is that no human is.

        So the policy is re-evaluated on startup. Anything it would now allow is
        granted automatically and the paused event replayed; anything it would
        still hold — a follow-up under `strict`, an order under any policy — is
        left exactly where it is.
        """
        from .domain.models import Approval, ApprovalStatus
        from .domain.policy import ActionType, approval_for

        try:
            approvals = await self.repo.list(Approval, status=ApprovalStatus.PENDING.value)
        except Exception:  # a store that cannot list is not a reason to fail startup
            log.exception("could not read approvals while releasing stale ones")
            return 0

        released = 0
        for approval in approvals:
            try:
                action = ActionType(approval.action_type)
            except ValueError:
                continue  # an action type this build no longer has
            # `first_contact_with_vendor` is the strictest reading, so anything
            # cleared here would be cleared however the thread actually stands.
            if approval_for(
                action, self.settings.approval_policy, first_contact_with_vendor=True
            ).requires_approval:
                continue
            if approval.resume_event is None:
                continue

            approval.status = ApprovalStatus.AUTO_GRANTED
            approval.decided_by = "policy"
            approval.decided_at = _utcnow()
            await self.repo.save(approval)
            await self.orchestrator.emit(Event.model_validate(approval.resume_event))
            released += 1

        if released:
            log.warning(
                "stale_approvals_released",
                extra={
                    "status": f"{released} approval(s) predated "
                    f"policy={self.settings.approval_policy.value} and were auto-granted"
                },
            )
        return released

    async def resume_pending_follow_ups(self) -> int:
        """Restart whatever a lost scheduler queue left stranded.

        A follow-up is a scheduled event, and an in-process scheduler loses its
        queue when the process dies. The state that matters survives — the thread
        is in the store, marked sent, with its follow-up count — but nothing is
        left to fire, so a supplier who never replies keeps a vendor waiting
        forever and the mission never reaches a recommendation.

        Cloud Tasks persists its own queue, so this returns immediately there —
        which is what the comment claimed for a while without the code checking.
        It did not: every cold start on Cloud Run read the whole email-threads
        collection out of Firestore and wrote a Cloud Tasks entry per sent
        thread, and a service that scales to zero between a scheduled mailbox
        poll has a great many cold starts. The dedup key spared it from creating
        duplicates; it did not spare it the reads.

        So this now matters exactly where it always claimed to: a run whose
        timers live in the process that just died.
        """
        from .domain.models import EmailThread, ThreadStatus
        from .workflow.handlers import MAX_FOLLOW_UPS

        if getattr(self.providers.scheduler, "persistent", False):
            return 0

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
        # The search, Places and Firestore adapters each hold a long-lived
        # client. They had a `close` nothing called, so every shutdown leaked
        # an httpx connection pool and an asyncio warning with it. Guarded
        # because a test double has no client to close.
        for provider in (self.providers.search, self.providers.maps, self.providers.store):
            closer = getattr(provider, "close", None)
            if closer is None:
                continue
            try:
                await closer()
            except Exception:  # a failed close must not fail a shutdown
                log.warning("provider_close_failed", extra={"status": type(provider).__name__})

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
        if self.replay is not None:
            return await self._replay_mission(user_id=user_id)

        mission = Mission(
            objective=objective.strip(), user_id=user_id,
            status=MissionStatus.CREATED,
            location=(location or "").strip() or None, search_scope=scope,
        )
        await self.repo.save(mission)
        await self.orchestrator.emit(
            Event(type=EventType.MISSION_CREATED, mission_id=mission.id)
        )
        return mission

    async def _replay_mission(self, *, user_id: str) -> Mission:
        """Play a recorded mission back under a new id.

        The objective returned is the recorded one, not the one that was typed.
        A replay can only show the mission it has, and saying so through the
        mission itself is better than accepting a brief it will not work on.
        """
        import asyncio

        from .domain.ids import new_id

        mission_id = new_id("msn")
        opening = self.replay.opening_mission(mission_id, user_id=user_id)
        await self.providers.store.put("missions", mission_id, opening)

        task = asyncio.create_task(self.replay.play(mission_id, user_id=user_id))
        # Held so the loop cannot garbage-collect a running replay mid-mission.
        self._replays.add(task)
        task.add_done_callback(self._replays.discard)

        return Mission.model_validate(opening)

    async def drain(self, timeout: float = 300.0) -> None:
        """Wait for the local bus to go idle. Only meaningful for LocalBus."""
        if hasattr(self.providers.bus, "drain"):
            await self.providers.bus.drain(timeout=timeout)


def _replay(providers: Any) -> Any:
    """The recording `SUPPLYME_MOCK` replays, or None when it is off.

    A mock run with no recording to play is a dead end that would only be found
    by pressing the button, so it fails here, naming the file it looked for.
    """
    settings: Settings = providers.settings
    if not settings.mock:
        return None

    from .adapters.replay import Recording, Replay, find_recording

    source = find_recording(settings)
    if source is None:
        raise RuntimeError(
            "SUPPLYME_MOCK is on but there is no recording to replay. Export one "
            "with scripts/export_firestore.py, or set SUPPLYME_MOCK_RECORDING to a "
            "snapshot file."
        )
    recording = Recording.load(source)
    if recording is None:
        raise RuntimeError(f"{source} holds no mission timeline to replay")

    log.info("mock mode: replaying %s from %s", recording.mission_id, source)
    return Replay(
        recording,
        providers.store,
        duration_seconds=settings.mock_duration_seconds,
        max_gap_seconds=settings.mock_max_gap_seconds,
    )


def _research_agent(providers: Any) -> Any:
    """Build the ADK research agent when a real model is in play.

    A tool-use loop is the right shape for research and the wrong shape for a
    test: it is non-deterministic by design. A test that binds its own model
    therefore gets the pre-fetching agent, and the workflow assertions stay
    stable — both satisfy the same `investigate` contract.
    """
    settings: Settings = providers.settings
    if not settings.use_adk_research:
        return None
    if type(providers.llm).__name__ != "GeminiLLM":
        return None
    try:
        from .adapters.gemini_llm import resolved_models
        from .config import MODEL_LADDER

        # Last resort is the head of the ladder, not a hardcoded older model:
        # the ladder's first entry is the newest model this project prefers,
        # and a literal here had quietly drifted a generation behind it.
        model = (
            settings.reasoning_model
            or resolved_models().get("reasoning")
            or MODEL_LADDER[0]
        )
        from .agents.adk_research import AdkResearchAgent

        return AdkResearchAgent(providers, model, providers.store, llm=providers.llm)
    except Exception:
        log.exception("could not build the ADK research agent; falling back")
        return None
