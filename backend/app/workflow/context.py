"""Per-mission working context.

Handlers need the same handful of reads (the mission, its nodes, a vendor and
its evidence) constantly. This wraps the store so those reads are one call, and
so every write goes through `save`, which is the single place that stamps
`updated_at`.

Reads are deliberately forgiving of documents older than the schema reading
them — see `_readable`.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from pydantic import ValidationError

from ..domain.models import (
    Approval,
    BrandRelationship,
    Conflict,
    EmailThread,
    Evidence,
    Mission,
    Quote,
    Recommendation,
    SupplyChainNode,
    Vendor,
)

log = logging.getLogger(__name__)

T = TypeVar("T")

COLLECTIONS: dict[type, str] = {
    Mission: "missions",
    SupplyChainNode: "supply_chain_nodes",
    Vendor: "vendors",
    Evidence: "evidence",
    BrandRelationship: "brand_relationships",
    EmailThread: "email_threads",
    Quote: "quotes",
    Conflict: "conflicts",
    Approval: "approvals",
    Recommendation: "recommendations",
}


class Repo:
    def __init__(self, store: Any) -> None:
        self._store = store

    async def save(self, obj: Any) -> Any:
        obj.touch()
        await self._store.put(
            COLLECTIONS[type(obj)], obj.id, obj.model_dump(mode="json")
        )
        return obj

    async def mutate(self, model: type[T], doc_id: str, change: Any) -> T | None:
        """Apply `change(obj)` to a stored document atomically.

        Use this instead of load/save whenever the same document may be written
        by another handler running concurrently — which, for vendors, is almost
        always.

        Returns None both for a document that is not there and for one this build
        cannot parse, because a handler can do nothing useful with either. That
        is the same answer `load` gives, and callers already treat None as "no
        document": `updated = await repo.mutate(...) or existing`.
        """
        unreadable = False

        def _apply(raw: dict[str, Any]) -> dict[str, Any] | None:
            nonlocal unreadable
            obj = _readable(model, raw, doc_id)
            if obj is None:
                # Returning None leaves the stored document exactly as it is.
                unreadable = True
                return None
            change(obj)
            obj.touch()
            return obj.model_dump(mode="json")

        updated = await self._store.mutate(COLLECTIONS[model], doc_id, _apply)
        if unreadable or updated is None:
            return None
        return _readable(model, updated, doc_id)

    async def load(self, model: type[T], doc_id: str) -> T | None:
        raw = await self._store.get(COLLECTIONS[model], doc_id)
        if raw is None:
            return None
        return _readable(model, raw, doc_id)

    async def list(self, model: type[T], **where: Any) -> list[T]:
        rows = await self._store.query(COLLECTIONS[model], where=where or None)
        found = (_readable(model, row, row.get("id", "?")) for row in rows)
        return [obj for obj in found if obj is not None]

    async def mission(self, mission_id: str) -> Mission:
        found = await self.load(Mission, mission_id)
        if found is None:
            raise MissionNotFound(mission_id)
        return found

    async def vendor(self, vendor_id: str) -> Vendor:
        found = await self.load(Vendor, vendor_id)
        if found is None:
            raise VendorNotFound(vendor_id)
        return found

    async def vendor_evidence(self, vendor_id: str) -> list[Evidence]:
        return await self.list(Evidence, vendor_id=vendor_id)

    async def vendor_conflicts(self, vendor_id: str) -> list[Conflict]:
        return await self.list(Conflict, vendor_id=vendor_id)

    async def vendor_relationships(self, vendor_id: str) -> list[BrandRelationship]:
        return await self.list(BrandRelationship, vendor_id=vendor_id)

    async def vendor_quotes(self, vendor_id: str) -> list[Quote]:
        return await self.list(Quote, vendor_id=vendor_id)


def _readable[M](model: type[M], raw: dict[str, Any], doc_id: str) -> M | None:
    """Validate one stored document, or drop it and say so.

    Firestore has no migrations, so a document written by an older build outlives
    the schema that wrote it. Validating strictly meant one such document took
    down every read of its collection: five evidence records carrying a
    `source_type` from a since-removed integration turned three endpoints into a
    500 and the console into "API Unreachable".

    A record nobody can parse is a record the mission has to do without, which is
    the same position it is in for a page that would not load. Losing it is a
    thinner dossier; refusing to answer at all is an outage.
    """
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        log.warning(
            "unreadable_document",
            extra={
                "status": f"{model.__name__} {doc_id} predates the current schema",
                "error": "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3]
                ),
            },
        )
        return None


class MissionNotFound(LookupError):
    """The mission referenced by an event is gone. The event is unprocessable."""


class VendorNotFound(LookupError):
    """The vendor referenced by an event is gone. The event is unprocessable."""
