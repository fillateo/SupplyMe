"""Mission API — everything the console reads and every human decision it writes."""

from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..domain.events import Event, EventType
from ..domain.models import (
    Approval,
    ApprovalStatus,
    BrandRelationship,
    Call,
    Conflict,
    EmailThread,
    Evidence,
    Mission,
    MissionStatus,
    Quote,
    Recommendation,
    ScoringWeights,
    SupplyChainNode,
    Vendor,
)
from ..domain.trust import profile
from ..runtime import Runtime
from ..workflow.handlers import rank_vendors
from .deps import runtime

router = APIRouter(prefix="/api", tags=["missions"])


class CreateMission(BaseModel):
    objective: str = Field(min_length=10, max_length=4000)
    user_id: str = "demo-user"


class Decision(BaseModel):
    approved: bool
    decided_by: str = "operator"
    note: str = ""


class Weights(BaseModel):
    price: float | None = None
    moq_fit: float | None = None
    capability: float | None = None
    lead_time: float | None = None
    evidence: float | None = None
    logistics: float | None = None
    priorities: list[str] = Field(default_factory=list)


@router.get("/health")
async def health(rt: Runtime = Depends(runtime)) -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": rt.settings.mode.value,
        "approval_policy": rt.settings.approval_policy.value,
        "providers": rt.providers.describe(),
        "notes": rt.providers.notes,
    }


@router.post("/missions", status_code=201)
async def create_mission(body: CreateMission, rt: Runtime = Depends(runtime)) -> dict[str, Any]:
    mission = await rt.create_mission(body.objective, user_id=body.user_id)
    return mission.model_dump(mode="json")


@router.get("/missions")
async def list_missions(rt: Runtime = Depends(runtime)) -> list[dict[str, Any]]:
    missions = await rt.repo.list(Mission)
    missions.sort(key=lambda m: m.created_at, reverse=True)
    return [m.model_dump(mode="json") for m in missions]


@router.get("/missions/{mission_id}")
async def get_mission(mission_id: str, rt: Runtime = Depends(runtime)) -> dict[str, Any]:
    mission = await _mission(rt, mission_id)
    nodes = await rt.repo.list(SupplyChainNode, mission_id=mission_id)
    vendors = await rt.repo.list(Vendor, mission_id=mission_id)
    conflicts = await rt.repo.list(Conflict, mission_id=mission_id)
    approvals = await rt.repo.list(Approval, mission_id=mission_id)
    threads = await rt.repo.list(EmailThread, mission_id=mission_id)
    calls = await rt.repo.list(Call, mission_id=mission_id)

    return {
        "mission": mission.model_dump(mode="json"),
        "supply_chain": [n.model_dump(mode="json") for n in nodes],
        "counts": {
            "vendors": len(vendors),
            "qualified": sum(1 for v in vendors if v.status.value == "qualified"),
            "rejected": sum(1 for v in vendors if v.status.value == "rejected"),
            "in_progress": sum(
                1 for v in vendors if v.status.value not in ("qualified", "rejected")
            ),
            "evidence": len(await rt.repo.list(Evidence, mission_id=mission_id)),
            "open_conflicts": sum(1 for c in conflicts if c.status.value != "resolved"),
            "emails_sent": mission.emails_sent,
            "emails_responded": sum(1 for t in threads if t.status.value == "responded"),
            "emails_awaiting": sum(1 for t in threads if t.status.value == "sent"),
            "calls_completed": sum(1 for c in calls if c.status.value == "completed"),
            "pending_approvals": sum(1 for a in approvals if a.status.value == "pending"),
        },
    }


@router.get("/missions/{mission_id}/vendors")
async def mission_vendors(mission_id: str, rt: Runtime = Depends(runtime)) -> list[dict[str, Any]]:
    await _mission(rt, mission_id)
    vendors = await rt.repo.list(Vendor, mission_id=mission_id)
    out = []
    for vendor in vendors:
        evidence = await rt.repo.vendor_evidence(vendor.id)
        relationships = await rt.repo.vendor_relationships(vendor.id)
        conflicts = await rt.repo.vendor_conflicts(vendor.id)
        out.append(
            {
                **vendor.model_dump(mode="json"),
                "trust": profile(vendor, evidence, relationships, conflicts).as_dict(),
                "brand_relationships": [r.model_dump(mode="json") for r in relationships],
                "conflicts": [c.model_dump(mode="json") for c in conflicts],
                "evidence_count": len(evidence),
            }
        )
    out.sort(key=lambda v: (v["status"] != "qualified", v["name"]))
    return out


@router.get("/missions/{mission_id}/vendors/{vendor_id}")
async def vendor_detail(
    mission_id: str, vendor_id: str, rt: Runtime = Depends(runtime)
) -> dict[str, Any]:
    await _mission(rt, mission_id)
    vendor = await rt.repo.load(Vendor, vendor_id)
    if vendor is None or vendor.mission_id != mission_id:
        raise HTTPException(status_code=404, detail="vendor not found")

    evidence = await rt.repo.vendor_evidence(vendor_id)
    relationships = await rt.repo.vendor_relationships(vendor_id)
    conflicts = await rt.repo.vendor_conflicts(vendor_id)
    return {
        "vendor": vendor.model_dump(mode="json"),
        "trust": profile(vendor, evidence, relationships, conflicts).as_dict(),
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "brand_relationships": [r.model_dump(mode="json") for r in relationships],
        "conflicts": [c.model_dump(mode="json") for c in conflicts],
        "quotes": [q.model_dump(mode="json") for q in await rt.repo.vendor_quotes(vendor_id)],
        "threads": [
            t.model_dump(mode="json") for t in await rt.repo.list(EmailThread, vendor_id=vendor_id)
        ],
        "calls": [
            c.model_dump(mode="json") for c in await rt.repo.list(Call, vendor_id=vendor_id)
        ],
    }


@router.get("/missions/{mission_id}/evidence")
async def mission_evidence(
    mission_id: str, field: str | None = None, rt: Runtime = Depends(runtime)
) -> list[dict[str, Any]]:
    await _mission(rt, mission_id)
    records = await rt.repo.list(Evidence, mission_id=mission_id)
    if field:
        records = [r for r in records if r.field == field]
    records.sort(key=lambda r: r.retrieved_at, reverse=True)
    return [r.model_dump(mode="json") for r in records]


@router.get("/missions/{mission_id}/communications")
async def mission_communications(
    mission_id: str, rt: Runtime = Depends(runtime)
) -> dict[str, Any]:
    await _mission(rt, mission_id)
    threads = await rt.repo.list(EmailThread, mission_id=mission_id)
    calls = await rt.repo.list(Call, mission_id=mission_id)
    vendors = {v.id: v.name for v in await rt.repo.list(Vendor, mission_id=mission_id)}
    return {
        "email": {
            "sent": sum(1 for t in threads if t.status.value != "draft"),
            "responded": sum(1 for t in threads if t.status.value == "responded"),
            "awaiting": sum(1 for t in threads if t.status.value == "sent"),
            "threads": [
                {**t.model_dump(mode="json"), "vendor_name": vendors.get(t.vendor_id, "")}
                for t in threads
            ],
        },
        "calls": {
            "completed": sum(1 for c in calls if c.status.value == "completed"),
            "scheduled": sum(1 for c in calls if c.status.value in ("required", "dialing")),
            "failed": sum(1 for c in calls if c.status.value in ("failed", "no_answer")),
            "items": [
                {**c.model_dump(mode="json"), "vendor_name": vendors.get(c.vendor_id, "")}
                for c in calls
            ],
        },
    }


@router.get("/missions/{mission_id}/activity")
async def mission_activity(
    mission_id: str, limit: int = Query(default=300, le=1000), rt: Runtime = Depends(runtime)
) -> list[dict[str, Any]]:
    """The real event log. Nothing here is generated for display."""
    await _mission(rt, mission_id)
    return await rt.providers.store.timeline(mission_id, limit=limit)


@router.get("/missions/{mission_id}/recommendation")
async def mission_recommendation(
    mission_id: str, rt: Runtime = Depends(runtime)
) -> dict[str, Any]:
    await _mission(rt, mission_id)
    recommendations = await rt.repo.list(Recommendation, mission_id=mission_id)
    if not recommendations:
        raise HTTPException(status_code=404, detail="no recommendation yet")
    recommendations.sort(key=lambda r: r.created_at)
    return recommendations[-1].model_dump(mode="json")


@router.get("/missions/{mission_id}/ranking")
async def mission_ranking(mission_id: str, rt: Runtime = Depends(runtime)) -> dict[str, Any]:
    """Live scoring, recomputed on read — this is what makes weight changes visible."""
    mission = await _mission(rt, mission_id)
    nodes = await rt.repo.list(SupplyChainNode, mission_id=mission_id)
    vendors = await rt.repo.list(Vendor, mission_id=mission_id)
    return {
        "weights": mission.weights.as_dict(),
        "ranking": await rank_vendors(rt.orchestrator, mission, nodes, vendors),
    }


@router.put("/missions/{mission_id}/weights")
async def set_weights(
    mission_id: str, body: Weights, rt: Runtime = Depends(runtime)
) -> dict[str, Any]:
    """Change what the mission optimises for. Rankings follow immediately."""
    from ..domain.scoring import apply_priorities

    mission = await _mission(rt, mission_id)
    current = mission.weights.model_dump()
    for field, value in body.model_dump(exclude={"priorities"}).items():
        if value is not None:
            current[field] = value
    weights = ScoringWeights(**current)
    if body.priorities:
        weights = apply_priorities(weights, body.priorities)
        mission.priorities = list(dict.fromkeys(mission.priorities + body.priorities))
    mission.weights = weights.normalized()
    await rt.repo.save(mission)
    return {"weights": mission.weights.as_dict(), "priorities": mission.priorities}


@router.get("/missions/{mission_id}/approvals")
async def list_approvals(mission_id: str, rt: Runtime = Depends(runtime)) -> list[dict[str, Any]]:
    await _mission(rt, mission_id)
    approvals = await rt.repo.list(Approval, mission_id=mission_id)
    approvals.sort(key=lambda a: (a.status.value != "pending", a.created_at))
    return [a.model_dump(mode="json") for a in approvals]


@router.post("/approvals/{approval_id}")
async def decide_approval(
    approval_id: str, body: Decision, rt: Runtime = Depends(runtime)
) -> dict[str, Any]:
    """The human decision point. Granting replays the exact paused event."""
    from ..domain.models import utcnow

    approval = await rt.repo.load(Approval, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if approval.status is not ApprovalStatus.PENDING:
        return approval.model_dump(mode="json")

    approval.status = ApprovalStatus.GRANTED if body.approved else ApprovalStatus.DENIED
    approval.decided_at = utcnow()
    approval.decided_by = body.decided_by
    await rt.repo.save(approval)

    await rt.orchestrator.emit(
        Event(
            type=EventType.APPROVAL_GRANTED if body.approved else EventType.APPROVAL_DENIED,
            mission_id=approval.mission_id,
            payload={"approval_id": approval.id, "decided_by": body.decided_by},
        )
    )
    return approval.model_dump(mode="json")


@router.get("/missions/{mission_id}/map")
async def mission_map(mission_id: str, rt: Runtime = Depends(runtime)) -> list[dict[str, Any]]:
    """Vendors with coordinates, for the geographic view."""
    await _mission(rt, mission_id)
    vendors = await rt.repo.list(Vendor, mission_id=mission_id)
    points = []
    for vendor in vendors:
        if vendor.lat is None or vendor.lng is None:
            continue
        evidence = await rt.repo.vendor_evidence(vendor.id)
        relationships = await rt.repo.vendor_relationships(vendor.id)
        points.append(
            {
                "id": vendor.id, "name": vendor.name, "lat": vendor.lat, "lng": vendor.lng,
                "city": vendor.city, "status": vendor.status.value,
                "node_keys": vendor.node_keys,
                "moq": vendor.moq.value, "unit_price": vendor.unit_price.value,
                "evidence": round(profile(vendor, evidence, relationships).overall, 3),
            }
        )
    return points


async def _mission(rt: Runtime, mission_id: str) -> Mission:
    mission = await rt.repo.load(Mission, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found")
    return mission
