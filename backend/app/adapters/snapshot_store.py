"""File-backed store: the in-process store, made to survive a restart.

This exists so a local run can be driven by real data. `MemoryStore` loses
everything on exit, and Firestore costs a project and a network round trip, so
demonstrating the console offline used to mean either provisioning cloud
infrastructure or showing an empty list. This reads a Firestore snapshot at
startup and writes every change back to the same file.

The file *is* the export format from `scripts/export_firestore.py` — documents
keyed by their full Firestore path — deliberately, so that a backup can be
opened as a local database with no conversion step, and a local database can be
diffed against the live one. Reservations live under `idempotency/<key>` and a
mission's activity events under `missions/<id>/workflow_events/<event id>`,
exactly where the Firestore adapter puts them.

Every write rewrites the whole file, through a temporary file and a rename, so
an interrupted save cannot leave a half-written database behind. That is only
reasonable because the file is small — a mission with a full timeline is well
under a megabyte — and it keeps this adapter to the one thing it is for.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from .memory_store import MemoryStore

log = logging.getLogger(__name__)

_TIMELINE = "workflow_events"
_RESERVATIONS = "idempotency"


def decode(value: Any) -> Any:
    """Undo the tagged encoding the exporter writes for non-JSON values."""
    if isinstance(value, dict):
        kind = value.get("__type__")
        if kind == "datetime":
            return value["value"]
        if kind == "bytes":
            import base64

            return base64.b64decode(value["value"])
        if kind == "reference":
            return value["value"]
        if kind == "geopoint":
            return {"lat": value["lat"], "lng": value["lng"]}
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


class SnapshotStore(MemoryStore):
    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = Path(path)
        #: Anything at a path this adapter has no special handling for. Kept so
        #: that saving cannot silently drop part of a snapshot it did not
        #: understand — a store that quietly loses documents is worse than one
        #: that refuses to open them.
        self._passthrough: dict[str, Any] = {}
        self._meta: dict[str, Any] = {}
        self._load()

    # --- persistence ------------------------------------------------------
    def _load(self) -> None:
        if not self._path.exists():
            log.info("local store %s does not exist yet; starting empty", self._path)
            return

        payload = json.loads(self._path.read_text())
        self._meta = payload.get("meta", {})
        timelines: dict[str, list[dict[str, Any]]] = {}

        for doc_path, raw in (payload.get("documents") or {}).items():
            data = decode(raw)
            parts = doc_path.split("/")
            if len(parts) == 2:
                collection, doc_id = parts
                if collection == _RESERVATIONS:
                    self._reservations[doc_id] = data
                else:
                    self._data.setdefault(collection, {})[doc_id] = data
            elif len(parts) == 4 and parts[0] == "missions" and parts[2] == _TIMELINE:
                timelines.setdefault(parts[1], []).append(data)
            else:
                self._passthrough[doc_path] = data

        # Firestore serves the timeline ordered by `created_at`; the in-process
        # store serves it in append order. Sorting on load is what makes those
        # the same answer.
        for mission_id, events in timelines.items():
            events.sort(key=lambda e: (e.get("created_at") or "", e.get("id") or ""))
            self._timeline[mission_id] = events

        log.info(
            "local store %s: %d collections, %d missions with timelines, %d reservations",
            self._path, len(self._data), len(self._timeline), len(self._reservations),
        )

    def _serialize(self) -> dict[str, Any]:
        documents: dict[str, Any] = dict(self._passthrough)
        for collection, docs in self._data.items():
            for doc_id, data in docs.items():
                documents[f"{collection}/{doc_id}"] = data
        for key, record in self._reservations.items():
            documents[f"{_RESERVATIONS}/{key}"] = record
        for mission_id, events in self._timeline.items():
            for index, event in enumerate(events):
                event_id = event.get("id") or f"evt_{index:05d}"
                documents[f"missions/{mission_id}/{_TIMELINE}/{event_id}"] = event
        return {"meta": {**self._meta, "store": "SnapshotStore"}, "documents": documents}

    async def _flush(self) -> None:
        async with self._lock:
            payload = self._serialize()

        def _save() -> None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(self._path.suffix + ".tmp")
            temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
            os.replace(temporary, self._path)

        try:
            await asyncio.to_thread(_save)
        except OSError:
            # A local database that cannot be written is a reason to say so, not
            # a reason to lose the request that was being served.
            log.exception("could not write the local store at %s", self._path)

    # --- writes -----------------------------------------------------------
    async def put(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        await super().put(collection, doc_id, data)
        await self._flush()

    async def mutate(self, collection: str, doc_id: str, mutator: Any) -> dict[str, Any] | None:
        result = await super().mutate(collection, doc_id, mutator)
        await self._flush()
        return result

    async def append_event(self, mission_id: str, event: dict[str, Any]) -> None:
        await super().append_event(mission_id, event)
        await self._flush()

    async def reserve(
        self, key: str, payload: dict[str, Any], *, lease_seconds: float = 300.0
    ) -> bool:
        claimed = await super().reserve(key, payload, lease_seconds=lease_seconds)
        await self._flush()
        return claimed

    async def complete(self, key: str, result: dict[str, Any] | None = None) -> None:
        await super().complete(key, result)
        await self._flush()
