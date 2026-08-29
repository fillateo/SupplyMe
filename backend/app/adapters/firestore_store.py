"""Firestore-backed store.

Two things matter beyond plain reads and writes:

* `reserve` uses a `create` on a document id derived from the idempotency key.
  Firestore rejects a create on an existing document, which gives us a
  compare-and-set without a transaction — that is the whole basis for not
  sending a supplier the same email twice.
* Every mission's events go into a subcollection, so the activity timeline is a
  single indexed range read rather than a scan.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from google.cloud import firestore

_TIMELINE = "workflow_events"
_RESERVATIONS = "idempotency"


class FirestoreStore:
    def __init__(self, project: str, database: str = "(default)") -> None:
        self._client = firestore.AsyncClient(project=project, database=database)

    async def put(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        await self._client.collection(collection).document(doc_id).set(data)

    async def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        snapshot = await self._client.collection(collection).document(doc_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    async def query(
        self, collection: str, *, where: dict[str, Any] | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        query = self._client.collection(collection)
        for key, value in (where or {}).items():
            operator = (
                "array_contains"
                if isinstance(value, str) and key.endswith("_keys")
                else "=="
            )
            if isinstance(value, (list, tuple, set)):
                operator, value = "in", list(value)
            query = query.where(filter=firestore.FieldFilter(key, operator, value))
        return [doc.to_dict() async for doc in query.limit(limit).stream()]

    async def mutate(self, collection: str, doc_id: str, mutator: Any) -> dict[str, Any] | None:
        reference = self._client.collection(collection).document(doc_id)

        @firestore.async_transactional
        async def _apply(transaction: Any) -> dict[str, Any] | None:
            snapshot = await reference.get(transaction=transaction)
            if not snapshot.exists:
                return None
            current = snapshot.to_dict() or {}
            updated = mutator(current)
            if updated is None:
                return current
            transaction.set(reference, updated)
            return updated

        return await _apply(self._client.transaction())

    async def append_event(self, mission_id: str, event: dict[str, Any]) -> None:
        await (
            self._client.collection("missions")
            .document(mission_id)
            .collection(_TIMELINE)
            .document(event["id"])
            .set(event)
        )

    async def timeline(self, mission_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        stream = (
            self._client.collection("missions")
            .document(mission_id)
            .collection(_TIMELINE)
            .order_by("created_at")
            .limit(limit)
            .stream()
        )
        return [doc.to_dict() async for doc in stream]

    async def reserve(
        self, key: str, payload: dict[str, Any], *, lease_seconds: float = 300.0
    ) -> bool:
        """Claim `key` for a bounded lease, inside a transaction.

        The transaction is what makes this safe across Cloud Run instances: two
        instances handling the same redelivered message cannot both win.
        """
        reference = self._client.collection(_RESERVATIONS).document(key)
        now = time.time()

        @firestore.async_transactional
        async def _claim(transaction: Any) -> bool:
            snapshot = await reference.get(transaction=transaction)
            if snapshot.exists:
                current = snapshot.to_dict() or {}
                if current.get("status") == "done":
                    return False
                if float(current.get("expires_at", 0)) > now:
                    return False
                attempts = int(current.get("attempts", 0))
            else:
                attempts = 0
            transaction.set(
                reference,
                {
                    **payload,
                    "status": "in_flight",
                    "expires_at": now + lease_seconds,
                    "attempts": attempts + 1,
                },
            )
            return True

        return await _claim(self._client.transaction())

    async def complete(self, key: str, result: dict[str, Any] | None = None) -> None:
        await self._client.collection(_RESERVATIONS).document(key).set(
            {"status": "done", "result": result or {}, "completed_at": time.time()},
            merge=True,
        )

    async def reservation(self, key: str) -> dict[str, Any] | None:
        return await self.get(_RESERVATIONS, key)

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)
