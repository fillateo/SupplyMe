"""In-process event bus with a real queue.

This is not a shortcut around Pub/Sub — it has the same shape (publish returns
immediately, delivery happens on another task, handlers must be idempotent) so
that code which works here works on Pub/Sub. It also deliberately redelivers a
configurable fraction of messages, because at-least-once delivery is a property
the workflow has to survive, and a bus that never duplicates would hide bugs
until they ran in production.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

from ..domain.events import Event

log = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class LocalBus:
    def __init__(self, *, duplicate_rate: float = 0.0, seed: int | None = None) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._handler: Handler | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._duplicate_rate = duplicate_rate
        self._random = random.Random(seed)
        self._in_flight = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def subscribe(self, handler: Handler) -> None:
        self._handler = handler

    async def publish(self, event: Event) -> None:
        self._idle.clear()
        await self._queue.put(event)
        if self._duplicate_rate and self._random.random() < self._duplicate_rate:
            # At-least-once, simulated. Handlers must cope.
            await self._queue.put(event.model_copy(update={"attempt": event.attempt + 1}))

    async def start(self, concurrency: int = 4) -> None:
        self._workers = [
            asyncio.create_task(self._worker(), name=f"bus-worker-{i}")
            for i in range(concurrency)
        ]

    async def _worker(self) -> None:
        while True:
            event = await self._queue.get()
            self._in_flight += 1
            try:
                if self._handler is not None:
                    await self._handler(event)
            except Exception:
                log.exception("handler failed for %s", event.type)
            finally:
                self._in_flight -= 1
                self._queue.task_done()
                if self._queue.empty() and self._in_flight == 0:
                    self._idle.set()

    async def drain(self, timeout: float = 120.0) -> None:
        """Wait until the queue is empty and nothing is being handled."""
        await asyncio.wait_for(self._idle.wait(), timeout=timeout)

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
