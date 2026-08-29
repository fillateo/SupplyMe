"""Delayed execution.

Follow-ups ("no reply after 48h"), retry backoff and non-response timeouts all
need an event delivered later. In the cloud that is Cloud Tasks posting back to
the service; locally it is an asyncio timer with a compressed clock so a
two-day follow-up is observable inside a demo.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..domain.events import Event
from ..domain.ids import new_id


class LocalScheduler:
    """asyncio-backed. `speedup` compresses wall-clock delays for demos."""

    def __init__(self, bus: Any, *, speedup: float = 1.0) -> None:
        self._bus = bus
        self._speedup = max(speedup, 1e-6)
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def schedule(
        self, event: Event, *, delay_seconds: float, compressible: bool = True
    ) -> str:
        task_id = new_id("task")
        # Only business waits compress. An infrastructure backoff that gets
        # divided by 2000 stops being a backoff.
        delay = delay_seconds / self._speedup if compressible else delay_seconds

        async def _fire() -> None:
            try:
                await asyncio.sleep(delay)
                await self._bus.publish(event)
            finally:
                # Runs on cancellation too, so a cancelled timer is not leaked.
                self._tasks.pop(task_id, None)

        self._tasks[task_id] = asyncio.create_task(_fire(), name=task_id)
        return task_id

    async def cancel_all(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    @property
    def pending(self) -> int:
        return len(self._tasks)


class CloudTasksScheduler:
    """Cloud Tasks -> HTTP POST back to this service's /events/task endpoint."""

    def __init__(
        self, project: str, location: str, queue: str, target_url: str, token: str = ""
    ) -> None:
        from google.cloud import tasks_v2

        self._client = tasks_v2.CloudTasksAsyncClient()
        self._parent = self._client.queue_path(project, location, queue)
        self._target_url = target_url
        self._token = token

    async def schedule(self, event: Event, *, delay_seconds: float) -> str:
        import time

        from google.cloud import tasks_v2
        from google.protobuf import timestamp_pb2

        schedule_time = timestamp_pb2.Timestamp()
        schedule_time.FromSeconds(int(time.time() + delay_seconds))

        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["X-VDS-Token"] = self._token

        task = tasks_v2.Task(
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=self._target_url,
                headers=headers,
                body=event.model_dump_json().encode(),
            ),
            schedule_time=schedule_time,
            # Cloud Tasks dedups on name; the event key makes a retry a no-op.
            name=f"{self._parent}/tasks/{event.key}",
        )
        try:
            created = await self._client.create_task(parent=self._parent, task=task)
        except Exception as exc:  # AlreadyExists means it is already scheduled
            if "AlreadyExists" in type(exc).__name__ or "already exists" in str(exc).lower():
                return event.key
            raise
        return created.name
