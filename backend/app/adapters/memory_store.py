"""In-process store.

What a local run uses when `SUPPLYME_USE_CLOUD_INFRA` is off, so the workflow can
be exercised without provisioning Firestore. It implements the same contract as
the Firestore adapter, including the atomic reservation that makes external
actions idempotent — so what works against one works against the other.

The difference that matters: nothing here survives a restart, and `/api/health`
says so rather than leaving it to be found out.
"""

from __future__ import annotations

import asyncio
import copy
import time
from typing import Any


class MemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._timeline: dict[str, list[dict[str, Any]]] = {}
        self._reservations: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def put(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        async with self._lock:
            self._data.setdefault(collection, {})[doc_id] = copy.deepcopy(data)

    async def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        async with self._lock:
            found = self._data.get(collection, {}).get(doc_id)
            return copy.deepcopy(found) if found else None

    async def query(
        self, collection: str, *, where: dict[str, Any] | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        async with self._lock:
            rows = list(self._data.get(collection, {}).values())
        if where:
            rows = [r for r in rows if all(_matches(r, k, v) for k, v in where.items())]
        return copy.deepcopy(rows[:limit])

    async def mutate(self, collection: str, doc_id: str, mutator: Any) -> dict[str, Any] | None:
        async with self._lock:
            current = self._data.get(collection, {}).get(doc_id)
            if current is None:
                return None
            updated = mutator(copy.deepcopy(current))
            if updated is None:
                return copy.deepcopy(current)
            self._data.setdefault(collection, {})[doc_id] = copy.deepcopy(updated)
            return copy.deepcopy(updated)

    async def append_event(self, mission_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            self._timeline.setdefault(mission_id, []).append(copy.deepcopy(event))

    async def timeline(self, mission_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        async with self._lock:
            return copy.deepcopy(self._timeline.get(mission_id, [])[-limit:])

    async def reserve(
        self, key: str, payload: dict[str, Any], *, lease_seconds: float = 300.0
    ) -> bool:
        now = time.time()
        async with self._lock:
            existing = self._reservations.get(key)
            if existing is not None:
                if existing.get("status") == "done":
                    return False
                if existing.get("expires_at", 0) > now:
                    return False
                # Lease expired: the previous holder died. Take it over.
            self._reservations[key] = {
                **copy.deepcopy(payload),
                "status": "in_flight",
                "expires_at": now + lease_seconds,
                "attempts": (existing or {}).get("attempts", 0) + 1,
            }
            return True

    async def complete(self, key: str, result: dict[str, Any] | None = None) -> None:
        async with self._lock:
            record = self._reservations.setdefault(key, {})
            record.update({"status": "done", "result": copy.deepcopy(result or {})})

    async def reservation(self, key: str) -> dict[str, Any] | None:
        async with self._lock:
            found = self._reservations.get(key)
            return copy.deepcopy(found) if found else None


def _matches(row: dict[str, Any], key: str, expected: Any) -> bool:
    actual = row.get(key)
    if isinstance(expected, (list, tuple, set)):
        return actual in expected
    if isinstance(actual, list):
        return expected in actual
    return actual == expected
