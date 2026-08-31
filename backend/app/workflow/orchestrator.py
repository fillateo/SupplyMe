"""The event loop.

One rule holds the whole system together: a handler receives an event, reads and
writes state, and returns the events that should happen next. It never calls
another handler, and it never decides anything by talking to a model in prose.

Everything that makes the workflow survivable lives here rather than in the
handlers:

* **Deduplication.** Every event carries a `key`. The orchestrator claims that
  key before doing any work and marks it done afterwards, so a Pub/Sub
  redelivery is a no-op instead of a second email.
* **Leases.** A claim expires. If Cloud Run kills an instance mid-handler, the
  redelivery takes the lease over and the work completes.
* **Bounded retries.** A handler that raises gets rescheduled with exponential
  backoff up to `max_event_retries`, then the mission records the failure
  instead of retrying forever.
* **Unprocessable events are dropped, not retried.** An event pointing at a
  vendor that no longer exists will never succeed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ..adapters.gemini_llm import current_mission
from ..config import Settings
from ..domain.cost import BudgetExceeded
from ..domain.events import EXTERNAL_ACTION_EVENTS, Event, EventType
from ..domain.models import Mission, MissionStatus
from .context import MissionNotFound, Repo, VendorNotFound

log = logging.getLogger(__name__)

Handler = Callable[["Orchestrator", Event], Awaitable[list[Event]]]

#: Handlers register here at import time; see app/workflow/handlers.py.
HANDLERS: dict[EventType, Handler] = {}


def on(event_type: EventType) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        if event_type in HANDLERS:
            raise RuntimeError(f"duplicate handler for {event_type}")
        HANDLERS[event_type] = handler
        return handler

    return register


#: How long a handler may hold an event's key before another worker may retry it.
#:
#: Tied to the Pub/Sub ack deadline (600s, see terraform/pubsub.tf), not chosen
#: independently. It must not be shorter, or a redelivery arriving on the
#: deadline would claim a key whose first attempt is still running and do the
#: work twice; it must not be much longer, or a worker that really did die
#: leaves the event unclaimable until well after Pub/Sub has given up retrying
#: it. Cloud Run kills the request at 540s, so at 600s the previous attempt is
#: dead and the key is free at the moment the retry needs it.
LEASE_SECONDS = 600.0
#: Retry backoff, in seconds, indexed by attempt.
BACKOFF = (5.0, 15.0, 60.0, 300.0, 900.0)
#: A rate limit is a queueing problem: back off much harder than for a bug,
#: because retrying it at the same cadence just extends the storm.
RATE_LIMIT_BACKOFF = (30.0, 90.0, 240.0, 600.0, 1800.0)
RATE_LIMIT_MARKERS = ("429", "resource_exhausted", "resource exhausted", "quota")

#: Events the mission genuinely cannot continue without. Anything else that
#: exhausts its retries costs the mission one supplier, not the whole run — a
#: rate limit while researching the fifth vendor should produce a shorter
#: shortlist with the gap explained, not a failed mission.
MISSION_CRITICAL_EVENTS = frozenset(
    {
        EventType.MISSION_CREATED,
        EventType.REQUIREMENTS_CREATED,
        EventType.SUPPLY_CHAIN_PLANNED,
        EventType.RECOMMENDATION_READY,
    }
)


class Orchestrator:
    def __init__(self, providers: Any, agents: Any) -> None:
        self.providers = providers
        self.settings: Settings = providers.settings
        self.store = providers.store
        self.bus = providers.bus
        self.scheduler = providers.scheduler
        self.repo = Repo(providers.store)
        self.meter = getattr(providers, "meter", None)
        self.agents = agents
        self.stats: dict[str, int] = {}
        #: What this process has already written onto each mission's record, so
        #: what it writes next is the difference. See _persist_spend.
        self._persisted_spend: dict[str, Any] = {}
        #: Bounds the widest fan-out in the system. See Settings.max_concurrent_research.
        self.research_slots = asyncio.Semaphore(self.settings.max_concurrent_research)

    # -- entry point --------------------------------------------------------

    async def handle(self, event: Event) -> None:
        """Process one event. Safe to call twice with the same event."""
        handler = HANDLERS.get(event.type)
        if handler is None:
            log.warning("no handler for %s", event.type)
            return

        claimed = await self.store.reserve(
            f"evt:{event.key}",
            {"event_id": event.id, "type": event.type.value, "mission_id": event.mission_id},
            lease_seconds=LEASE_SECONDS,
        )
        if not claimed:
            self._count("deduplicated")
            log.info(
                "event_deduplicated",
                extra={"event_id": event.id, "event_type": event.type.value,
                       "mission_id": event.mission_id, "dedup_key": event.key},
            )
            return

        await self._restore_spend(event.mission_id)
        await self._record(event, status="started")
        started = time.perf_counter()
        # Names the mission for every model call this handler causes, including
        # the ones made somewhere that never sees a mission id: grounded search,
        # reached through the Search port, and ADK's own model wrapper.
        attribution = current_mission.set(event.mission_id)
        try:
            next_events = await handler(self, event)
        except BudgetExceeded as exc:
            # Not retryable: retrying is exactly the thing the cap exists to stop.
            await self.store.complete(f"evt:{event.key}", {"budget": str(exc)})
            await self._record(event, status="over_budget", error=str(exc))
            await self._fail_mission(event.mission_id, f"stopped on cost: {exc}")
            self._count("over_budget")
            return
        except (MissionNotFound, VendorNotFound) as exc:
            # Nothing to retry against; retrying cannot make the record reappear.
            await self.store.complete(f"evt:{event.key}", {"dropped": str(exc)})
            await self._record(event, status="dropped", error=str(exc))
            self._count("dropped")
            return
        except Exception as exc:
            await self._on_failure(event, exc)
            return
        finally:
            current_mission.reset(attribution)

        await self._record(
            event,
            status="ok",
            latency_ms=int((time.perf_counter() - started) * 1000),
            emitted=[e.type.value for e in next_events],
        )
        self._count(event.type.value)
        await self._persist_spend(event.mission_id)

        for next_event in next_events:
            await self.emit(next_event)

        # Complete only after every child event is actually published: if
        # publish fails partway through, this event stays uncompleted and a
        # retry re-runs the handler and re-emits everything. That is safe —
        # each child event dedupes on its own key — whereas completing first
        # would let a publish failure silently drop the events it named.
        await self.store.complete(
            f"evt:{event.key}", {"emitted": [e.type.value for e in next_events]}
        )

    async def _restore_spend(self, mission_id: str) -> None:
        """Teach this process what the mission has already spent elsewhere.

        The meter lives in memory, and a mission does not. Cloud Run scales to
        zero between events and runs several instances at once, so a mission
        routinely spans processes that have never met — and each one started
        counting from zero. The cap then bounded what one instance spent rather
        than what the mission spent, and the totals written back onto the record
        were whichever instance wrote last, which is how a mission that had made
        a hundred calls came to report two.

        Read once per mission per process: the meter is authoritative from then
        on, and re-reading on every event would spend a document read to learn
        what it already knows.
        """
        if self.meter is None or not mission_id:
            return
        if self.meter.usage(mission_id).calls:
            return
        mission = await self.repo.load(Mission, mission_id)
        if mission is None or not mission.model_calls:
            return
        from ..domain.cost import Usage

        already = Usage(
            calls=mission.model_calls,
            input_tokens=mission.input_tokens,
            output_tokens=mission.output_tokens,
            usd=mission.estimated_cost_usd,
        )
        self.meter.seed(mission_id, already)
        # Seeded, therefore already on the record: this process owes the mission
        # only what it goes on to spend from here.
        self._persisted_spend[mission_id] = already

    async def _persist_spend(self, mission_id: str) -> None:
        """Add what this process has spent since last time onto the record.

        A delta inside the transaction, not an absolute. Cloud Run runs several
        instances of a mission at once and each meter counts only its own calls,
        so writing absolutes made the record whatever the last writer happened
        to hold: two instances that had each made fifty calls wrote fifty, and
        the mission reported half of what it spent. Half is the dangerous
        direction — the cap reads this number back after a scale-to-zero.
        """
        if self.meter is None or not mission_id:
            return
        from ..domain.cost import Usage

        usage = self.meter.usage(mission_id)
        written = self._persisted_spend.get(mission_id) or Usage()
        delta = Usage(
            calls=usage.calls - written.calls,
            input_tokens=usage.input_tokens - written.input_tokens,
            output_tokens=usage.output_tokens - written.output_tokens,
            usd=usage.usd - written.usd,
        )
        if delta.calls <= 0:
            return

        def _apply(mission: Mission) -> None:
            mission.model_calls += delta.calls
            mission.input_tokens += delta.input_tokens
            mission.output_tokens += delta.output_tokens
            mission.estimated_cost_usd = round(
                mission.estimated_cost_usd + delta.usd, 6
            )

        if await self.repo.mutate(Mission, mission_id, _apply) is not None:
            self._persisted_spend[mission_id] = usage

    async def emit(self, event: Event) -> None:
        if not event.mission_id:
            raise ValueError(f"event {event.type} has no mission_id")
        await self.bus.publish(event)

    async def schedule(
        self, event: Event, *, delay_seconds: float, compressible: bool = True
    ) -> None:
        await self.scheduler.schedule(
            event, delay_seconds=delay_seconds, compressible=compressible
        )

    # -- external action guard ---------------------------------------------

    async def reserve_action(
        self, mission_id: str, vendor_id: str, action_type: str, version: int | str = 0
    ) -> bool:
        """Claim the right to perform an irreversible external action.

        Returns False when this exact action has already been performed. Callers
        must treat False as "already done", not as an error.
        """
        from ..domain.idempotency import action_key

        key = action_key(mission_id, vendor_id, action_type, version)
        claimed = await self.store.reserve(
            key,
            {"mission_id": mission_id, "vendor_id": vendor_id, "action": action_type},
            lease_seconds=LEASE_SECONDS,
        )
        if not claimed:
            log.info(
                "external_action_suppressed",
                extra={"mission_id": mission_id, "vendor_id": vendor_id, "action": action_type},
            )
        return claimed

    async def confirm_action(
        self, mission_id: str, vendor_id: str, action_type: str, version: int | str = 0,
        result: dict[str, Any] | None = None,
    ) -> None:
        from ..domain.idempotency import action_key

        await self.store.complete(
            action_key(mission_id, vendor_id, action_type, version), result
        )

    # -- failure handling ---------------------------------------------------

    async def _on_failure(self, event: Event, exc: Exception) -> None:
        attempt = event.attempt + 1
        log.warning(
            "handler_failed",
            extra={
                "event_id": event.id, "event_type": event.type.value,
                "mission_id": event.mission_id, "retry_count": attempt,
                "error": f"{type(exc).__name__}: {exc}",
            },
            exc_info=exc,
        )
        self._count("failed")

        if event.type in EXTERNAL_ACTION_EVENTS:
            # An external action that failed part-way may have already reached the
            # supplier. Do not replay it blindly; require a fresh decision upstream.
            await self.store.complete(
                f"evt:{event.key}", {"error": str(exc), "not_retried": "external action"}
            )
            await self._record(event, status="failed", error=str(exc))
            return

        if attempt > self.settings.max_event_retries:
            await self.store.complete(f"evt:{event.key}", {"error": str(exc), "exhausted": True})
            await self._record(event, status="exhausted", error=str(exc))
            if event.type in MISSION_CRITICAL_EVENTS:
                await self._fail_mission(event.mission_id, f"{event.type.value}: {exc}")
            else:
                await self._abandon_branch(event, exc)
            return

        # Release the key so the retry can claim it, then reschedule with backoff.
        await self.store.complete(f"evt:{event.key}", {"error": str(exc), "retrying": attempt})
        retry = event.model_copy(
            update={"attempt": attempt, "payload": {**event.payload, "retry": attempt}}
        )
        schedule = (
            RATE_LIMIT_BACKOFF if _is_rate_limited(exc) else BACKOFF
        )
        await self.schedule(
            retry,
            delay_seconds=schedule[min(attempt - 1, len(schedule) - 1)],
            compressible=False,
        )
        await self._record(event, status="retrying", error=str(exc))

    async def _abandon_branch(self, event: Event, exc: Exception) -> None:
        """Close out the supplier a failed branch was about; keep the mission.

        The vendor is rejected with the real reason, so the recommendation
        reports a gap it can name instead of quietly ranking a supplier nobody
        managed to research. If that was the last vendor in play, the mission
        moves on to its recommendation rather than waiting for a branch that is
        never coming back.
        """
        vendor_id = event.payload.get("vendor_id")
        if not vendor_id:
            return

        from ..domain.models import Vendor, VendorStatus

        vendor = await self.repo.load(Vendor, vendor_id)
        if vendor is None or vendor.status in (VendorStatus.QUALIFIED, VendorStatus.REJECTED):
            return

        reason = (
            f"{event.type.value} did not complete after "
            f"{self.settings.max_event_retries} retries: {str(exc)[:180]}"
        )

        def _close_out(record: Vendor) -> None:
            record.status = VendorStatus.REJECTED
            record.rejection_reasons = [reason]

        # Mutated rather than saved: a parallel branch may be writing to the same
        # vendor, and a plain put would drop whichever landed first.
        await self.repo.mutate(Vendor, vendor_id, _close_out)
        self._count("branch_abandoned")
        log.warning(
            "branch_abandoned",
            extra={"event_type": event.type.value, "mission_id": event.mission_id,
                   "vendor_id": vendor_id, "error": str(exc)[:200]},
        )

        # Imported here rather than at module scope: handlers imports this module.
        from .handlers import _maybe_finish

        for follow_up in await _maybe_finish(self, event):
            await self.emit(follow_up)

    async def _fail_mission(self, mission_id: str, reason: str) -> None:
        mission = await self.repo.load(Mission, mission_id)
        if mission is None:
            return
        mission.status = MissionStatus.FAILED
        mission.failure_reason = reason
        await self.repo.save(mission)
        await self._reap_stranded_vendors(mission_id, reason)
        # So the terminal state actually appears on the activity timeline:
        # mission.failed is a first-class event, not a status flag.
        await self.emit(
            Event(type=EventType.MISSION_FAILED, mission_id=mission_id, payload={"reason": reason})
        )

    async def _reap_stranded_vendors(self, mission_id: str, reason: str) -> None:
        """Give every supplier a verdict, including the ones we stopped paying for.

        A budget stop is deliberately not retried, which is right: the whole
        point of a ceiling is that reaching it ends the spending. But the
        vendors whose research was mid-flight when it fired were left in
        `researching`, and `_maybe_finish` will not produce a recommendation
        while any vendor is still in play. Nothing else ever moved them, so the
        mission could not finish even after the cap was raised — a live mission
        sat with four suppliers stuck that way and no recommendation reachable.

        Stopping work on a supplier is a verdict about that supplier, so it is
        recorded as one, with the reason on the record rather than implied by a
        status nobody will revisit.
        """
        from ..domain.models import Vendor, VendorStatus

        terminal = (VendorStatus.QUALIFIED, VendorStatus.REJECTED)
        stranded = [
            v for v in await self.repo.list(Vendor, mission_id=mission_id)
            if v.status not in terminal
        ]
        for vendor in stranded:
            def _reject(record: Vendor) -> None:
                record.status = VendorStatus.REJECTED
                record.rejection_reasons.append(f"research stopped: {reason}")

            await self.repo.mutate(Vendor, vendor.id, _reject)
        if stranded:
            log.info(
                "vendors_reaped",
                extra={"mission_id": mission_id, "status": f"{len(stranded)} stranded"},
            )

    # -- observability ------------------------------------------------------

    async def _record(
        self,
        event: Event,
        *,
        status: str,
        error: str | None = None,
        latency_ms: int | None = None,
        emitted: list[str] | None = None,
    ) -> None:
        """Append to the mission's activity timeline. This is the proof of action."""
        entry = {
            "id": f"{event.id}:{status}",
            "event_id": event.id,
            "type": event.type.value,
            "mission_id": event.mission_id,
            "status": status,
            "payload": _redact(event.payload),
            "caused_by": event.caused_by,
            "attempt": event.attempt,
            "created_at": event.created_at.isoformat(),
            "recorded_at": time.time(),
            "latency_ms": latency_ms,
            "emitted": emitted or [],
            "error": error,
        }
        await self.store.append_event(event.mission_id, entry)
        log.info(
            "workflow_event",
            extra={
                "event_id": event.id, "event_type": event.type.value,
                "mission_id": event.mission_id, "workflow_state": status,
                "latency_ms": latency_ms, "retry_count": event.attempt, "error": error,
            },
        )

    def _count(self, name: str) -> None:
        self.stats[name] = self.stats.get(name, 0) + 1


def _is_rate_limited(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


#: Payload keys whose values are large or sensitive and never belong in the log.
_REDACT_KEYS = frozenset({"body", "transcript", "raw_text", "text"})


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _REDACT_KEYS and isinstance(value, str):
            out[key] = f"<{len(value)} chars>"
        elif isinstance(value, (dict, list)) and len(str(value)) > 500:
            out[key] = f"<{type(value).__name__} omitted>"
        else:
            out[key] = value
    return out
