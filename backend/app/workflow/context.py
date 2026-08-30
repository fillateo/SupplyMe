"""Per-mission working context.

Handlers need the same handful of reads (the mission, its nodes, a vendor and
its evidence) constantly. This wraps the store so those reads are one call, and
so every write goes through `save`, which is the single place that stamps
`updated_at` and appends to the activity timeline.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

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
        """

        def _apply(raw: dict[str, Any]) -> dict[str, Any]:
            obj = model.model_validate(raw)
            change(obj)
            obj.touch()
            return obj.model_dump(mode="json")

        updated = await self._store.mutate(COLLECTIONS[model], doc_id, _apply)
        return model.model_validate(updated) if updated else None

    async def load(self, model: type[T], doc_id: str) -> T | None:
        raw = await self._store.get(COLLECTIONS[model], doc_id)
        return model.model_validate(raw) if raw else None

    async def list(self, model: type[T], **where: Any) -> list[T]:
        rows = await self._store.query(COLLECTIONS[model], where=where or None)
        return [model.model_validate(r) for r in rows]

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


class MissionNotFound(LookupError):
    """The mission referenced by an event is gone. The event is unprocessable."""


class VendorNotFound(LookupError):
    """The vendor referenced by an event is gone. The event is unprocessable."""
