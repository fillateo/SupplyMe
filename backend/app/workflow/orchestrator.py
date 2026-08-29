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

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ..config import Settings
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
LEASE_SECONDS = 300.0
#: Retry backoff, in seconds, indexed by attempt.
BACKOFF = (5.0, 15.0, 60.0, 300.0, 900.0)


class Orchestrator:
    def __init__(self, providers: Any, agents: Any) -> None:
        self.providers = providers
        self.settings: Settings = providers.settings
        self.store = providers.store
        self.bus = providers.bus
        self.scheduler = providers.scheduler
        self.repo = Repo(providers.store)
        self.agents = agents
        self.stats: dict[str, int] = {}

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

        await self._record(event, status="started")
        started = time.perf_counter()
        try:
            next_events = await handler(self, event)
        except (MissionNotFound, VendorNotFound) as exc:
            # Nothing to retry against; retrying cannot make the record reappear.
            await self.store.complete(f"evt:{event.key}", {"dropped": str(exc)})
            await self._record(event, status="dropped", error=str(exc))
            self._count("dropped")
            return
        except Exception as exc:
            await self._on_failure(event, exc)
            return

        await self.store.complete(
            f"evt:{event.key}", {"emitted": [e.type.value for e in next_events]}
        )
        await self._record(
            event,
            status="ok",
            latency_ms=int((time.perf_counter() - started) * 1000),
            emitted=[e.type.value for e in next_events],
        )
        self._count(event.type.value)

        for next_event in next_events:
            await self.emit(next_event)

    async def emit(self, event: Event) -> None:
        if not event.mission_id:
            raise ValueError(f"event {event.type} has no mission_id")
        await self.bus.publish(event)

    async def schedule(self, event: Event, *, delay_seconds: float) -> None:
        await self.scheduler.schedule(event, delay_seconds=delay_seconds)

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
            await self._fail_mission(event.mission_id, f"{event.type.value}: {exc}")
            return

        # Release the key so the retry can claim it, then reschedule with backoff.
        await self.store.complete(f"evt:{event.key}", {"error": str(exc), "retrying": attempt})
        retry = event.model_copy(
            update={"attempt": attempt, "payload": {**event.payload, "retry": attempt}}
        )
        await self.schedule(retry, delay_seconds=BACKOFF[min(attempt - 1, len(BACKOFF) - 1)])
        await self._record(event, status="retrying", error=str(exc))

    async def _fail_mission(self, mission_id: str, reason: str) -> None:
        mission = await self.repo.load(Mission, mission_id)
        if mission is None:
            return
        mission.status = MissionStatus.FAILED
        mission.failure_reason = reason
        await self.repo.save(mission)

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
