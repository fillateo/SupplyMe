"""Workflow handlers.

Reading order follows the mission: planning, discovery, research, adjudication,
outreach, response, resolution, recommendation. Each handler is small on
purpose — the interesting decisions are delegated to the deterministic engines
in app/domain/, and what remains here is routing.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from ..domain import conflicts as conflict_engine
from ..domain import evidence as evidence_engine
from ..domain import identity, numbers, scoring, trust
from ..domain import quotes as quote_engine
from ..domain.events import Event, EventType
from ..domain.ids import slug, stable_id
from ..domain.models import (
    Approval,
    ApprovalStatus,
    BrandRelationship,
    Call,
    CallStatus,
    Conflict,
    ConflictStatus,
    EmailThread,
    Evidence,
    Fact,
    Message,
    Mission,
    MissionStatus,
    NodeStatus,
    Provenance,
    Quote,
    Recommendation,
    SourceType,
    SupplyChainNode,
    ThreadStatus,
    Vendor,
    VendorStatus,
)
from ..domain.policy import ActionType, approval_for, should_call
from ..security import sanitize
from .orchestrator import Orchestrator, on

log = logging.getLogger(__name__)

#: Fields the workflow will contact a supplier to obtain. Ordered by how much
#: they matter to a go/no-go decision on a first production run.
CRITICAL_FIELDS = ("moq", "unit_price", "lead_time_days")
CONTACTABLE_FIELDS = (
    *CRITICAL_FIELDS,
    "sample_lead_time_days",
    "customization",
    "payment_terms",
)

#: How long to wait for a supplier before following up, and how many times.
FOLLOW_UP_DELAY_SECONDS = 48 * 3600
MAX_FOLLOW_UPS = 2

#: Per-vendor attempt ceilings. Beyond these the vendor is closed out with a
#: reason rather than left in play: a supplier who has not answered two emails
#: and a phone call is not going to, and a mission that waits for them forever
#: never produces a recommendation.
MAX_THREADS_PER_VENDOR = 2
MAX_CALLS_PER_VENDOR = 2

#: Calls reserved for settling disagreements. A call that resolves a conflict is
#: worth more than one that merely fills a blank: the blank can be asked by
#: email, and the disagreement — by definition — already survived being asked in
#: writing. Without this reserve a mission spends its whole call budget
#: cold-calling suppliers who never published an email address, and then has
#: nothing left when the MOQ on its best candidate turns out to be disputed.
CALLS_RESERVED_FOR_CONFLICTS = 1


# ==========================================================================
# 1. Planning
# ==========================================================================


@on(EventType.MISSION_CREATED)
async def handle_mission_created(orc: Orchestrator, event: Event) -> list[Event]:
    mission = await orc.repo.mission(event.mission_id)
    brief = await orc.agents.mission.brief(mission.objective, mission_id=mission.id)

    mission.product = brief.product
    mission.quantity = brief.quantity
    mission.unit_spec = brief.unit_spec
    mission.market = brief.market
    mission.budget_note = brief.budget_note
    mission.priorities = brief.priorities
    mission.success_criteria = brief.success_criteria
    # The user's stated priorities move the scoring weights, once, here — so the
    # ranking later is reproducible from the mission record alone.
    mission.weights = scoring.apply_priorities(mission.weights, brief.priorities)
    mission.status = MissionStatus.PLANNING
    await orc.repo.save(mission)

    return [
        event.child(
            EventType.REQUIREMENTS_CREATED,
            target_lead_time_days=brief.target_lead_time_days,
        )
    ]


@on(EventType.REQUIREMENTS_CREATED)
async def handle_requirements_created(orc: Orchestrator, event: Event) -> list[Event]:
    mission = await orc.repo.mission(event.mission_id)
    brief = _brief_from_mission(mission, event.payload.get("target_lead_time_days"))
    plan = await orc.agents.supply_chain.plan(brief, mission_id=mission.id)

    seen: set[str] = set()
    nodes: list[SupplyChainNode] = []
    for planned in plan.nodes:
        key = slug(planned.key or planned.name)
        if not key or key in seen:
            continue
        seen.add(key)
        nodes.append(
            SupplyChainNode(
                id=stable_id("scn", mission.id, key),
                mission_id=mission.id,
                key=key,
                name=planned.name,
                description=planned.description,
                required=planned.required,
                depends_on=[slug(d) for d in planned.depends_on],
                consolidates_with=[slug(c) for c in planned.consolidates_with],
                search_terms=planned.search_terms,
                rationale=planned.rationale,
            )
        )
    for node in nodes:
        await orc.repo.save(node)

    mission.status = MissionStatus.DISCOVERING
    await orc.repo.save(mission)

    return [
        event.child(
            EventType.SUPPLY_CHAIN_PLANNED,
            node_count=len(nodes),
            consolidation_note=plan.consolidation_note,
        )
    ]


@on(EventType.SUPPLY_CHAIN_PLANNED)
async def handle_supply_chain_planned(orc: Orchestrator, event: Event) -> list[Event]:
    """Fan out: one discovery branch per required node, all running in parallel."""
    nodes = await orc.repo.list(SupplyChainNode, mission_id=event.mission_id)
    return [
        event.child(EventType.VENDOR_DISCOVERY_STARTED, node_id=node.id, node_key=node.key)
        for node in nodes
        if node.required
    ]


# ==========================================================================
# 2. Discovery and identity
# ==========================================================================


@on(EventType.VENDOR_DISCOVERY_STARTED)
async def handle_discovery_started(orc: Orchestrator, event: Event) -> list[Event]:
    mission = await orc.repo.mission(event.mission_id)
    node = await orc.repo.load(SupplyChainNode, event.payload["node_id"])
    if node is None:
        return []

    node.status = NodeStatus.DISCOVERING
    await orc.repo.save(node)

    plan = await orc.agents.discovery.queries(
        node_name=node.name,
        node_description=node.description,
        search_terms=node.search_terms,
        market=mission.market,
        mission_id=mission.id,
    )

    hits, places = await _gather_sources(orc, plan.queries, plan.maps_queries, mission.market)
    if not hits and not places:
        node.status = NodeStatus.BLOCKED
        await orc.repo.save(node)
        return []

    result = await orc.agents.discovery.extract(
        node_key=node.key, node_name=node.name, hits=hits[:12], places=places[:8],
        market=mission.market, mission_id=mission.id,
    )

    # Identity resolution runs against everything already found for this mission,
    # not just this node, so a vendor discovered under "bottle" and again under
    # "cap" becomes one record that can supply both.
    existing = await orc.repo.list(Vendor, mission_id=mission.id)
    emitted: list[Event] = []
    place_by_name = {p.name.lower(): p for p in places}

    for found in result.vendors[: orc.settings.max_vendors_per_category]:
        place = place_by_name.get(found.name.lower())
        candidate = Vendor(
            mission_id=mission.id,
            name=found.name.strip(),
            website=found.website or (place.website if place else None),
            domain=identity.normalize_domain(found.website or (place.website if place else None)),
            city=found.city or (_city_from(place.address) if place else None),
            country=found.country or mission.market,
            phone=place.phone if place else None,
            address=place.address if place else None,
            lat=place.lat if place else None,
            lng=place.lng if place else None,
            place_id=place.place_id if place else None,
            node_keys=[k for k in (found.node_keys or [node.key])],
            missing_fields=list(CONTACTABLE_FIELDS),
        )
        resolved, match = identity.resolve(candidate, existing)
        is_new = match is None

        if found.source_url and found.excerpt:
            await _record_evidence(
                orc, mission.id, resolved.id,
                claim=found.why_relevant or f"{found.name} supplies {node.name}",
                field=None, value=None,
                source_type=SourceType.SEARCH_RESULT if not place else SourceType.MAPS_LISTING,
                source_url=found.source_url, source_title=found.name,
                excerpt=found.excerpt,
            )

        if node.key not in resolved.node_keys:
            resolved.node_keys.append(node.key)
        await orc.repo.save(resolved)
        if is_new:
            existing.append(resolved)
            emitted.append(
                event.child(
                    EventType.VENDOR_DISCOVERED, vendor_id=resolved.id, node_key=node.key
                )
            )
        else:
            log.info(
                "vendor_merged",
                extra={"mission_id": mission.id, "vendor_id": resolved.id,
                       "reason": match.reason if match else ""},
            )

    node.status = NodeStatus.RESEARCHING
    await orc.repo.save(node)
    return emitted


@on(EventType.VENDOR_DISCOVERED)
async def handle_vendor_discovered(orc: Orchestrator, event: Event) -> list[Event]:
    return [event.child(EventType.VENDOR_RESEARCH_STARTED, vendor_id=event.payload["vendor_id"])]


async def _gather_sources(
    orc: Orchestrator, queries: list[str], maps_queries: list[str], market: str | None
) -> tuple[list[Any], list[Any]]:
    """Run web and Maps lookups in parallel; a failing source costs its results only."""
    region = _region_code(market)
    search_tasks = [orc.providers.search.search(q, limit=6) for q in queries[:4]]
    maps_tasks = [orc.providers.maps.search_places(q, region=region) for q in maps_queries[:3]]
    results = await asyncio.gather(*search_tasks, *maps_tasks, return_exceptions=True)

    hits, places = [], []
    for index, result in enumerate(results):
        if isinstance(result, BaseException):
            log.warning("source_lookup_failed", extra={"error": str(result)})
            continue
        (hits if index < len(search_tasks) else places).extend(result)

    seen_urls: set[str] = set()
    unique_hits = []
    for hit in hits:
        if hit.url in seen_urls:
            continue
        seen_urls.add(hit.url)
        unique_hits.append(hit)

    seen_places: set[str] = set()
    unique_places = []
    for place in places:
        if place.place_id in seen_places:
            continue
        seen_places.add(place.place_id)
        unique_places.append(place)
    return unique_hits, unique_places


# ==========================================================================
# 3. Research and evidence
# ==========================================================================


@on(EventType.VENDOR_RESEARCH_STARTED)
async def handle_research_started(orc: Orchestrator, event: Event) -> list[Event]:
    mission = await orc.repo.mission(event.mission_id)
    vendor = await orc.repo.vendor(event.payload["vendor_id"])
    await _set_status(orc, vendor, VendorStatus.RESEARCHING)

    pages, hits, place, videos = await _research_sources(orc, vendor, mission)

    node_names = await _node_names(orc, mission.id, vendor.node_keys)
    research = await orc.agents.research.investigate(
        vendor_name=vendor.name, node_names=node_names, pages=pages, hits=hits,
        place=place, videos=videos, wanted_fields=list(CONTACTABLE_FIELDS),
        mission_id=mission.id, vendor_id=vendor.id,
    )

    if research.suspicious_content:
        log.warning(
            "untrusted_content_flagged",
            extra={"mission_id": mission.id, "vendor_id": vendor.id, "stage": "research"},
        )

    for field in ("legal_name", "email", "phone", "address", "city", "country"):
        value = getattr(research, field, None)
        if value and not getattr(vendor, field, None):
            setattr(vendor, field, value)
    vendor.capabilities = list(dict.fromkeys(vendor.capabilities + research.capabilities))
    vendor.node_keys = list(dict.fromkeys(vendor.node_keys + [slug(k) for k in research.node_keys]))

    for claim in research.claims:
        await _record_evidence(
            orc, mission.id, vendor.id,
            claim=claim.claim, field=claim.field,
            value=claim.numeric_value if claim.numeric_value is not None else claim.text_value,
            source_type=claim.source_type, source_url=claim.source_url,
            source_title=claim.source_title, excerpt=claim.excerpt,
        )

    all_evidence = await orc.repo.vendor_evidence(vendor.id)
    _apply_facts(vendor, all_evidence, await orc.repo.vendor_conflicts(vendor.id))
    vendor.missing_fields = [f for f in CONTACTABLE_FIELDS if not vendor.fact(f).known]
    vendor.version += 1
    await orc.repo.save(vendor)

    emitted: list[Event] = [
        event.child(EventType.EVIDENCE_FOUND, vendor_id=vendor.id, count=len(research.claims))
    ]
    for brand in dict.fromkeys(research.brand_claims):
        emitted.append(
            event.child(
                EventType.BRAND_CLAIM_FOUND, vendor_id=vendor.id, brand=brand, version=brand
            )
        )
    emitted.extend(await _detect_conflicts(orc, event, vendor, all_evidence))
    emitted.append(
        event.child(
            EventType.VENDOR_UPDATED, vendor_id=vendor.id, stage="research",
            version=f"{vendor.id}:v{vendor.version}",
        )
    )
    return emitted


@on(EventType.EVIDENCE_FOUND)
async def handle_evidence_found(orc: Orchestrator, event: Event) -> list[Event]:
    """Terminal by design: evidence is recorded during research; this marks the timeline."""
    return []


async def _research_sources(
    orc: Orchestrator, vendor: Vendor, mission: Mission
) -> tuple[list[Any], list[Any], Any, list[Any]]:
    depth = orc.settings.max_research_depth
    query = f"{vendor.name} {mission.market or ''}".strip()

    tasks: list[Any] = [orc.providers.search.search(query, limit=6)]
    if vendor.website:
        tasks.append(orc.providers.search.fetch(vendor.website))
    if vendor.place_id:
        tasks.append(orc.providers.maps.place_details(vendor.place_id))
    tasks.append(orc.providers.video.search_videos(f"{vendor.name} factory", limit=3))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    hits = _ok(results[0], [])
    cursor = 1
    pages = []
    if vendor.website:
        page = _ok(results[cursor], None)
        cursor += 1
        if page is not None:
            pages.append(page)
    place = None
    if vendor.place_id:
        place = _ok(results[cursor], None)
        cursor += 1
    videos = _ok(results[cursor], [])

    # Follow a bounded number of the vendor's own pages. Other domains are read
    # only when they are about this vendor, which the search snippet establishes.
    own_domain = identity.normalize_domain(vendor.domain or vendor.website)
    follow = [
        hit.url for hit in hits
        if own_domain and sanitize.sole_domain(hit.url) == own_domain
        and hit.url not in {p.url for p in pages}
    ][: max(depth - len(pages), 0)]
    if follow:
        fetched = await asyncio.gather(
            *(orc.providers.search.fetch(url) for url in follow), return_exceptions=True
        )
        pages.extend(p for p in (_ok(f, None) for f in fetched) if p is not None)

    return pages, hits, place, videos


def _ok(result: Any, default: Any) -> Any:
    return default if isinstance(result, BaseException) else result


# ==========================================================================
# 4. Brand claim adjudication
# ==========================================================================


@on(EventType.BRAND_CLAIM_FOUND)
async def handle_brand_claim(orc: Orchestrator, event: Event) -> list[Event]:
    mission = await orc.repo.mission(event.mission_id)
    vendor = await orc.repo.vendor(event.payload["vendor_id"])
    brand = event.payload["brand"]

    queries = [
        f'"{vendor.name}" "{brand}"',
        f"{brand} supplier {vendor.name}",
        f"{brand} manufacturing partner {mission.market or ''}".strip(),
    ]
    searched = await asyncio.gather(
        *(orc.providers.search.search(q, limit=5) for q in queries), return_exceptions=True
    )
    hits: list[Any] = []
    seen: set[str] = set()
    for result in searched:
        for hit in _ok(result, []):
            if hit.url not in seen:
                seen.add(hit.url)
                hits.append(hit)

    # Read the pages that could actually confirm it — anything not on the
    # supplier's own domain.
    own_domain = identity.normalize_domain(vendor.domain or vendor.website)
    to_read = [h.url for h in hits if sanitize.sole_domain(h.url) != own_domain][:3]
    fetched = await asyncio.gather(
        *(orc.providers.search.fetch(url) for url in to_read), return_exceptions=True
    )
    pages = [p for p in (_ok(f, None) for f in fetched) if p is not None]
    (video_result,) = await asyncio.gather(
        orc.providers.video.search_videos(f"{vendor.name} {brand}", limit=3),
        return_exceptions=True,
    )
    videos = _ok(video_result, [])

    investigation = await orc.agents.brand_evidence.investigate(
        vendor_name=vendor.name, brand=brand, hits=hits[:8], pages=pages, videos=videos,
        mission_id=mission.id, vendor_id=vendor.id,
    )

    supporting: list[Evidence] = []
    for finding in investigation.findings:
        if not finding.supports_relationship:
            continue
        record = await _record_evidence(
            orc, mission.id, vendor.id,
            claim=f"{vendor.name} produces for {brand}",
            field="brand_relationship", value=brand,
            source_type=finding.source_type, source_url=finding.source_url,
            source_title=finding.source_title, excerpt=finding.excerpt,
        )
        supporting.append(record)

    # The supplier's own claim is itself evidence — of the claim, not the fact.
    supplier_claim = await _record_evidence(
        orc, mission.id, vendor.id,
        claim=f"{vendor.name} states it produces for {brand}",
        field="brand_relationship", value=brand,
        source_type=SourceType.OFFICIAL_WEBSITE,
        source_url=vendor.website, source_title=vendor.name,
        excerpt=f"Supplier states a relationship with {brand}.",
    )
    considered = [*supporting, supplier_claim]

    classification, relationship_type, confidence, independent = (
        evidence_engine.classify_brand_relationship(considered)
    )
    relationship = BrandRelationship(
        id=stable_id("br", mission.id, vendor.id, brand),
        mission_id=mission.id, vendor_id=vendor.id, brand=brand,
        relationship_type=relationship_type, classification=classification,
        confidence=confidence, independent_sources=independent,
        evidence_ids=[e.id for e in considered],
        notes=investigation.summary,
    )
    await orc.repo.save(relationship)

    # Research, outreach and other brand claims run concurrently with this
    # handler, so append the id transactionally instead of writing the whole doc.
    await orc.repo.mutate(
        Vendor, vendor.id, lambda v: _append_unique(v.brand_relationship_ids, relationship.id)
    )

    return [
        event.child(
            EventType.BRAND_CLAIM_ADJUDICATED,
            vendor_id=vendor.id, brand=brand, version=brand,
            classification=classification.value,
            independent_sources=independent,
        )
    ]


@on(EventType.BRAND_CLAIM_ADJUDICATED)
async def handle_brand_adjudicated(orc: Orchestrator, event: Event) -> list[Event]:
    return []


# ==========================================================================
# 5. Deciding what to do next about a vendor
# ==========================================================================


@on(EventType.VENDOR_UPDATED)
async def handle_vendor_updated(orc: Orchestrator, event: Event) -> list[Event]:
    """The routing decision: is this vendor done, blocked, or worth contacting?

    This is the handler that makes the system a Taskmaster rather than a
    pipeline. Nothing here is scripted by the user — the vendor's own state
    decides whether the next step is an email, a call, a rejection, or nothing.
    """
    mission = await orc.repo.mission(event.mission_id)
    vendor = await orc.repo.vendor(event.payload["vendor_id"])

    vendor_conflicts = await orc.repo.vendor_conflicts(vendor.id)
    # A conflict already being resolved has an email or a call in flight against
    # it; handle_conflict_detected owns that. Only untouched conflicts belong to
    # this handler, or the two paths both dial the same supplier.
    open_conflicts = [c for c in vendor_conflicts if c.status is ConflictStatus.OPEN]
    if any(c.status is ConflictStatus.RESOLVING for c in vendor_conflicts):
        return []
    missing_critical = [f for f in CRITICAL_FIELDS if not vendor.fact(f).known]

    # A vendor that cannot serve this order at all is rejected now, with the
    # reason recorded, rather than being emailed and rejected later.
    vendor_moq = numbers.as_number(vendor.moq.value) if vendor.moq.known else None
    if vendor_moq is not None and mission.quantity and vendor_moq > mission.quantity * 4:
        await _set_status(
            orc, vendor, VendorStatus.REJECTED,
            [f"MOQ {vendor_moq:g} against a first batch of {mission.quantity}"],
        )
        return [
            event.child(EventType.VENDOR_REJECTED, vendor_id=vendor.id, version=vendor.version),
            *await _maybe_finish(orc, event),
        ]

    if not missing_critical and not open_conflicts:
        await _set_status(orc, vendor, VendorStatus.QUALIFIED)
        return [
            event.child(EventType.VENDOR_QUALIFIED, vendor_id=vendor.id, version=vendor.version),
            *await _maybe_finish(orc, event),
        ]

    threads = await orc.repo.list(EmailThread, vendor_id=vendor.id)
    # The supplier has the ball only while a follow-up is still owed to them. A
    # thread that has used its whole follow-up budget and still has no reply is
    # not "in progress" — waiting on it forever is how a mission never finishes.
    awaiting = [
        t for t in threads
        if t.status in (ThreadStatus.SENT, ThreadStatus.AWAITING_APPROVAL)
        and t.follow_up_count < MAX_FOLLOW_UPS
    ]
    if awaiting:
        return []

    call_wanted, call_reason = should_call(
        missing_critical_fields=missing_critical,
        has_open_conflict=bool(open_conflicts),
        email_unanswered_days=_days_since_last_outbound(threads),
        has_email=bool(vendor.email),
        has_phone=bool(vendor.phone),
    )

    # Attempts are counted per vendor, including the ones that failed. A carrier
    # that rejects the call still used the vendor's patience and our budget, and
    # counting only completed calls would retry a bad number forever.
    calls = await orc.repo.list(Call, vendor_id=vendor.id)
    if call_wanted and len(calls) < MAX_CALLS_PER_VENDOR:
        return [
            event.child(
                EventType.CALL_REQUIRED, vendor_id=vendor.id,
                version=f"{vendor.id}:call:{len(calls)}",
                reason=call_reason,
                conflict_id=open_conflicts[0].id if open_conflicts else None,
            )
        ]

    if (
        vendor.email
        and len(threads) < MAX_THREADS_PER_VENDOR
        and mission.emails_sent < orc.settings.max_outreach_per_mission
    ):
        return [
            event.child(
                EventType.VENDOR_CONTACT_REQUIRED, vendor_id=vendor.id,
                version=f"{vendor.id}:thread:{len(threads)}",
                missing=missing_critical,
            )
        ]

    # Every route has been tried. Close the vendor out with the reason, so the
    # recommendation can explain the gap instead of the mission stalling.
    await _set_status(
        orc, vendor, VendorStatus.REJECTED,
        _no_route_reasons(vendor, missing_critical, len(threads), len(calls)),
    )
    return [
        event.child(EventType.VENDOR_REJECTED, vendor_id=vendor.id, version=vendor.version),
        *await _maybe_finish(orc, event),
    ]


async def _abandon_conflicts(orc: Orchestrator, vendor: Vendor, why: str) -> None:
    """Close out disagreements whose resolution attempt has failed.

    The preferred value stands — it is still the best-sourced answer — but it is
    now marked as unconfirmed rather than in progress, so the recommendation
    reports it as an open risk instead of the mission waiting on it.
    """
    abandoned = []
    for conflict in await orc.repo.vendor_conflicts(vendor.id):
        if conflict.status is not ConflictStatus.RESOLVING:
            continue
        conflict.status = ConflictStatus.UNRESOLVABLE
        conflict.preferred_reason += f"; {why}"
        await orc.repo.save(conflict)
        abandoned.append(conflict.id)
    if abandoned:
        await orc.repo.mutate(
            Vendor, vendor.id,
            lambda v: v.open_conflicts.__setitem__(
                slice(None), [c for c in v.open_conflicts if c not in abandoned]
            ),
        )


async def _take_budget(
    orc: Orchestrator, mission_id: str, field: str, cap: int, *, reserve: int = 0
) -> bool:
    """Atomically consume one unit of a mission budget.

    The check has to happen in the same transaction as the increment. Doing it
    from a mission snapshot read earlier lets a dozen parallel vendor branches
    all observe `calls_made = 2` and all decide they are within a cap of three.

    `reserve` withholds the last N units from lower-priority callers.
    """
    granted = False
    effective = max(cap - reserve, 0)

    def _apply(mission: Mission) -> None:
        nonlocal granted
        current = getattr(mission, field)
        if current >= effective:
            return
        setattr(mission, field, current + 1)
        granted = True

    await orc.repo.mutate(Mission, mission_id, _apply)
    return granted


@on(EventType.VENDOR_QUALIFIED)
async def handle_vendor_qualified(orc: Orchestrator, event: Event) -> list[Event]:
    return []


@on(EventType.VENDOR_REJECTED)
async def handle_vendor_rejected(orc: Orchestrator, event: Event) -> list[Event]:
    return []


def _no_route_reasons(
    vendor: Vendor, missing: list[str], threads: int = 0, calls: int = 0
) -> list[str]:
    if not vendor.email and not vendor.phone:
        return ["no email or phone found, so nothing could be confirmed"]
    if not missing:
        return ["no remaining route, though the required facts were obtained"]
    attempted = ", ".join(
        filter(None, [
            f"{threads} email thread(s)" if threads else "",
            f"{calls} call(s)" if calls else "",
        ])
    )
    return [
        f"still missing {', '.join(missing)} after {attempted or 'no reachable contact'}"
    ]


def _days_since_last_outbound(threads: list[EmailThread]) -> float | None:
    outbound = [
        m.sent_at for t in threads for m in t.messages if m.direction == "outbound"
    ]
    if not outbound:
        return None
    latest = max(outbound)
    return (datetime.now(UTC) - latest).total_seconds() / 86400.0


# ==========================================================================
# 6. Email outreach
# ==========================================================================


@on(EventType.VENDOR_CONTACT_REQUIRED)
async def handle_contact_required(orc: Orchestrator, event: Event) -> list[Event]:
    mission = await orc.repo.mission(event.mission_id)
    vendor = await orc.repo.vendor(event.payload["vendor_id"])
    if not vendor.email:
        return []

    # Identify this outreach attempt. Deriving the thread id from the vendor's
    # version instead let a second attempt reuse the first attempt's id, which
    # overwrote the live thread and reset its follow-up count to zero.
    attempt = str(event.payload.get("version") or f"{vendor.id}:thread:0")

    facts = await _personalization_facts(orc, vendor)
    node_names = await _node_names(orc, mission.id, vendor.node_keys)
    draft = await orc.agents.communication.draft_email(
        vendor_name=vendor.name, vendor_facts=facts, product=mission.product or mission.objective,
        quantity=mission.quantity, unit_spec=mission.unit_spec, market=mission.market,
        node_names=node_names,
        missing_fields=list(event.payload.get("missing") or vendor.missing_fields),
        mission_id=mission.id, vendor_id=vendor.id,
    )

    thread = EmailThread(
        id=stable_id("thr", mission.id, vendor.id, attempt),
        mission_id=mission.id, vendor_id=vendor.id, to_address=vendor.email,
        subject=draft.subject, asked=draft.questions_asked, unanswered=list(draft.questions_asked),
        status=ThreadStatus.DRAFT,
        messages=[Message(direction="outbound", subject=draft.subject, body=draft.body)],
    )
    await orc.repo.save(thread)
    await orc.repo.mutate(Vendor, vendor.id, lambda v: _append_unique(v.thread_ids, thread.id))

    decision = approval_for(
        ActionType.SEND_EMAIL, orc.settings.approval_policy,
        first_contact_with_vendor=len(vendor.thread_ids) <= 1,
    )
    send_event = event.child(
        EventType.EMAIL_SENT, vendor_id=vendor.id, thread_id=thread.id, version=attempt
    )

    if not decision.requires_approval:
        return [
            event.child(EventType.EMAIL_DRAFT_CREATED, vendor_id=vendor.id, thread_id=thread.id),
            send_event,
        ]

    approval = Approval(
        id=stable_id("apr", mission.id, vendor.id, "send_email", attempt),
        mission_id=mission.id, vendor_id=vendor.id, action_type=ActionType.SEND_EMAIL.value,
        summary=f"Send a quotation request to {vendor.name} <{vendor.email}>",
        preview={
            "to": vendor.email, "subject": draft.subject, "body": draft.body,
            "personalization_basis": draft.personalization_basis,
            "reason_for_approval": decision.reason,
        },
        resume_event=send_event.model_dump(mode="json"),
    )
    await orc.repo.save(approval)
    thread.status = ThreadStatus.AWAITING_APPROVAL
    await orc.repo.save(thread)
    mission.status = MissionStatus.AWAITING_APPROVAL
    await orc.repo.save(mission)

    return [
        event.child(EventType.EMAIL_DRAFT_CREATED, vendor_id=vendor.id, thread_id=thread.id),
        event.child(
            EventType.APPROVAL_REQUESTED, vendor_id=vendor.id, approval_id=approval.id,
            action=ActionType.SEND_EMAIL.value, version=attempt,
        ),
    ]


@on(EventType.EMAIL_DRAFT_CREATED)
async def handle_email_draft_created(orc: Orchestrator, event: Event) -> list[Event]:
    return []


@on(EventType.APPROVAL_REQUESTED)
async def handle_approval_requested(orc: Orchestrator, event: Event) -> list[Event]:
    """Terminal until a human decides. The API publishes approval.granted/denied."""
    return []


@on(EventType.APPROVAL_GRANTED)
async def handle_approval_granted(orc: Orchestrator, event: Event) -> list[Event]:
    approval = await orc.repo.load(Approval, event.payload["approval_id"])
    if approval is None or approval.resume_event is None:
        return []
    if approval.status not in (ApprovalStatus.GRANTED, ApprovalStatus.AUTO_GRANTED):
        return []
    # Replay the exact event that was paused. Its dedup key is unchanged, so a
    # double approval cannot produce a second send.
    return [Event.model_validate(approval.resume_event)]


@on(EventType.APPROVAL_DENIED)
async def handle_approval_denied(orc: Orchestrator, event: Event) -> list[Event]:
    approval = await orc.repo.load(Approval, event.payload["approval_id"])
    if approval is None or approval.vendor_id is None:
        return []
    vendor = await orc.repo.vendor(approval.vendor_id)
    await _set_status(
        orc, vendor, VendorStatus.REJECTED, ["outreach was declined by the operator"]
    )
    return [event.child(EventType.VENDOR_REJECTED, vendor_id=vendor.id, version=vendor.version)]


@on(EventType.EMAIL_SENT)
async def handle_email_sent(orc: Orchestrator, event: Event) -> list[Event]:
    """The one place an email actually leaves the system."""
    mission = await orc.repo.mission(event.mission_id)
    vendor = await orc.repo.vendor(event.payload["vendor_id"])
    thread = await orc.repo.load(EmailThread, event.payload["thread_id"])
    if thread is None or not thread.messages:
        return []

    # The idempotency key must distinguish the original request from a follow-up
    # on the same thread. Keying on the thread alone suppresses every follow-up
    # as a duplicate of the first message, and the thread never leaves draft.
    action_version = event.payload.get("version") or thread.id
    claimed = await orc.reserve_action(mission.id, vendor.id, "send_email", action_version)
    if not claimed:
        return []  # already sent; a redelivery must not send it again

    outbound = thread.messages[-1]
    sent = await orc.providers.mail.send(
        to=thread.to_address, subject=thread.subject, body=outbound.body,
        thread_id=thread.provider_thread_id, mission_id=mission.id,
    )

    def _mark_delivered(record: EmailThread) -> None:
        if record.messages:
            record.messages[-1].provider_message_id = sent.provider_message_id
        record.provider_thread_id = sent.provider_thread_id
        record.status = ThreadStatus.SENT

    updated = await orc.repo.mutate(EmailThread, thread.id, _mark_delivered)
    thread = updated or thread

    await _set_status(orc, vendor, VendorStatus.CONTACTED)

    def _mark_sent(record: Mission) -> None:
        record.emails_sent += 1
        record.status = MissionStatus.AWAITING_RESPONSE

    await orc.repo.mutate(Mission, mission.id, _mark_sent)

    await orc.confirm_action(
        mission.id, vendor.id, "send_email", action_version,
        {"provider_thread_id": sent.provider_thread_id},
    )

    # If the supplier never replies, the mission must still move on.
    await orc.schedule(
        event.child(
            EventType.FOLLOW_UP_REQUIRED, vendor_id=vendor.id, thread_id=thread.id,
            reason="no response", version=f"{thread.id}:followup:{thread.follow_up_count}",
        ),
        delay_seconds=FOLLOW_UP_DELAY_SECONDS,
    )
    return []


# ==========================================================================
# 7. Inbound supplier response
# ==========================================================================


@on(EventType.EMAIL_RECEIVED)
async def handle_email_received(orc: Orchestrator, event: Event) -> list[Event]:
    """Where the mission wakes up.

    Nothing about this path assumes a browser is open or that a user pressed
    anything. Gmail pushed a notification, or the demo mail provider scheduled
    one; either way the workflow resumes from stored state.
    """
    mission = await orc.repo.mission(event.mission_id)
    thread = await _thread_for(orc, event)
    if thread is None:
        log.warning(
            "inbound_mail_unmatched",
            extra={"mission_id": event.mission_id,
                   "provider_thread_id": event.payload.get("provider_thread_id")},
        )
        return []

    vendor = await orc.repo.vendor(thread.vendor_id)
    body = event.payload.get("body", "")

    thread.messages.append(
        Message(
            direction="inbound", subject=event.payload.get("subject", ""), body=body,
            provider_message_id=event.payload.get("provider_message_id"),
        )
    )
    thread.status = ThreadStatus.RESPONDED
    await orc.repo.save(thread)

    extraction = await orc.agents.communication.extract_quote(
        body=body, questions_asked=thread.asked,
        currency_hint=_currency_for(mission.market), mission_id=mission.id, vendor_id=vendor.id,
    )
    if extraction.suspicious_content:
        log.warning(
            "untrusted_content_flagged",
            extra={"mission_id": mission.id, "vendor_id": vendor.id, "stage": "email"},
        )

    await _set_status(orc, vendor, VendorStatus.RESPONDED)

    committed_to_something = bool(
        extraction.line_items
        or extraction.moq is not None
        or extraction.lead_time_days is not None
        or extraction.sample_lead_time_days is not None
        or extraction.payment_terms
    )
    if extraction.not_a_quote or not committed_to_something:
        thread.status = ThreadStatus.CLOSED if _is_bounce(body) else ThreadStatus.SENT
        await orc.repo.save(thread)
        return [
            event.child(
                EventType.FOLLOW_UP_REQUIRED, vendor_id=vendor.id, thread_id=thread.id,
                reason="reply contained no quotation",
                version=f"{thread.id}:{len(thread.messages)}",
            )
        ]

    quote = Quote(
        id=stable_id("qte", mission.id, vendor.id, thread.id, str(len(thread.messages))),
        mission_id=mission.id, vendor_id=vendor.id,
        node_key=vendor.node_keys[0] if vendor.node_keys else None,
        source="email", currency=extraction.currency or _currency_for(mission.market),
        quantity=extraction.quantity, line_items=extraction.line_items, moq=extraction.moq,
        lead_time_days=extraction.lead_time_days,
        sample_lead_time_days=extraction.sample_lead_time_days,
        sample_cost=extraction.sample_cost, payment_terms=extraction.payment_terms,
        customization=extraction.customization, raw_text=body,
    )
    await orc.repo.save(quote)

    # Everything the supplier stated becomes evidence, sourced to the email.
    recorded = await _evidence_from_supplier(
        orc, mission, vendor, quote, source_type=SourceType.SUPPLIER_EMAIL,
        source_title=f"Email from {vendor.name}", excerpt=sanitize.excerpt(body),
    )
    quote.evidence_id = recorded[0].id if recorded else None
    await orc.repo.save(quote)

    thread.answered = list(dict.fromkeys(thread.answered + extraction.answered_questions))
    thread.unanswered = [q for q in thread.asked if q not in thread.answered]
    thread.commitments = list(dict.fromkeys(thread.commitments + extraction.commitments))
    await orc.repo.save(thread)

    all_evidence = await orc.repo.vendor_evidence(vendor.id)
    _apply_facts(vendor, all_evidence, await orc.repo.vendor_conflicts(vendor.id))
    vendor.currency = quote.currency
    vendor.missing_fields = [f for f in CONTACTABLE_FIELDS if not vendor.fact(f).known]
    vendor.version += 1
    await orc.repo.save(vendor)

    emitted = [
        event.child(
            EventType.QUOTE_EXTRACTED, vendor_id=vendor.id, quote_id=quote.id,
            version=quote.id, unit_price=quote.package_unit_price, moq=quote.moq,
        )
    ]
    emitted.extend(await _detect_conflicts(orc, event, vendor, all_evidence))
    emitted.append(
        event.child(
            EventType.VENDOR_UPDATED, vendor_id=vendor.id, stage="email", version=quote.id
        )
    )
    return emitted


@on(EventType.QUOTE_EXTRACTED)
async def handle_quote_extracted(orc: Orchestrator, event: Event) -> list[Event]:
    return []


async def _thread_for(orc: Orchestrator, event: Event) -> EmailThread | None:
    """Match an inbound message to the thread that asked for it."""
    provider_thread_id = event.payload.get("provider_thread_id")
    if provider_thread_id:
        threads = await orc.repo.list(
            EmailThread, mission_id=event.mission_id, provider_thread_id=provider_thread_id
        )
        if threads:
            return threads[0]
    if event.payload.get("thread_id"):
        return await orc.repo.load(EmailThread, event.payload["thread_id"])

    sender = (event.payload.get("from_address") or "").lower()
    address = sender.split("<")[-1].strip(" >") if "<" in sender else sender
    for thread in await orc.repo.list(EmailThread, mission_id=event.mission_id):
        if thread.to_address.lower() == address:
            return thread
    return None


def _is_bounce(body: str) -> bool:
    lowered = body.lower()
    return any(
        marker in lowered
        for marker in ("delivery status notification", "undeliverable", "mail delivery failed",
                       "address not found", "recipient rejected")
    )


# ==========================================================================
# 8. Conflicts and follow-up
# ==========================================================================


@on(EventType.CONFLICT_DETECTED)
async def handle_conflict_detected(orc: Orchestrator, event: Event) -> list[Event]:
    """Decide how to settle a disagreement, and route to it."""
    await orc.repo.mission(event.mission_id)   # drops the event if the mission is gone
    vendor = await orc.repo.vendor(event.payload["vendor_id"])
    conflict = await orc.repo.load(Conflict, event.payload["conflict_id"])
    if conflict is None or conflict.status is not ConflictStatus.OPEN:
        return []

    conflict.status = ConflictStatus.RESOLVING
    await orc.repo.save(conflict)

    question = event.payload.get("question") or ""
    if conflict.resolution_action == "call" and vendor.phone:
        return [
            event.child(
                EventType.CALL_REQUIRED, vendor_id=vendor.id, version=conflict.id,
                reason=f"sources disagree on {conflict.field}",
                conflict_id=conflict.id, question=question,
            )
        ]

    if vendor.email:
        return [
            event.child(
                EventType.FOLLOW_UP_REQUIRED, vendor_id=vendor.id,
                version=f"conflict:{conflict.id}",
                reason=f"sources disagree on {conflict.field}",
                conflict_id=conflict.id, question=question,
            )
        ]

    conflict.status = ConflictStatus.UNRESOLVABLE
    conflict.preferred_reason += "; no contact route to resolve it"
    await orc.repo.save(conflict)
    return [event.child(EventType.VENDOR_UPDATED, vendor_id=vendor.id, stage="conflict")]


@on(EventType.FOLLOW_UP_REQUIRED)
async def handle_follow_up(orc: Orchestrator, event: Event) -> list[Event]:
    mission = await orc.repo.mission(event.mission_id)
    vendor = await orc.repo.vendor(event.payload["vendor_id"])

    threads = await orc.repo.list(EmailThread, vendor_id=vendor.id)
    thread = next(
        (t for t in threads if t.id == event.payload.get("thread_id")),
        threads[-1] if threads else None,
    )
    if thread is None or not vendor.email:
        return []

    # A silence timer that fires after the supplier already answered is stale.
    if event.payload.get("reason") == "no response" and thread.status is ThreadStatus.RESPONDED:
        return []
    if thread.follow_up_count >= MAX_FOLLOW_UPS:
        return [
            event.child(
                EventType.VENDOR_UPDATED, vendor_id=vendor.id, stage="follow_up_exhausted",
                version=f"{thread.id}:{thread.follow_up_count}",
            )
        ]
    if mission.emails_sent >= orc.settings.max_outreach_per_mission:
        return []

    # Two follow-ups can be triggered at once — the scheduled silence timer and a
    # reply that answered nothing. Claim the slot before drafting, so the vendor
    # gets one follow-up rather than two, and we pay for one model call.
    if not await orc.reserve_action(
        mission.id, vendor.id, "follow_up", f"{thread.id}:{thread.follow_up_count}"
    ):
        return []

    draft = await orc.agents.communication.follow_up_email(
        vendor_name=vendor.name, thread_summary=_summarize_thread(thread),
        unanswered=thread.unanswered or list(vendor.missing_fields),
        specific_question=event.payload.get("question"),
        mission_id=mission.id, vendor_id=vendor.id,
    )

    def _add_follow_up(record: EmailThread) -> None:
        record.follow_up_count += 1
        record.messages.append(
            Message(direction="outbound", subject=draft.subject, body=draft.body)
        )
        record.asked = list(dict.fromkeys(record.asked + draft.questions_asked))
        record.unanswered = [q for q in record.asked if q not in record.answered]
        record.status = ThreadStatus.DRAFT

    updated = await orc.repo.mutate(EmailThread, thread.id, _add_follow_up)
    thread = updated or thread

    decision = approval_for(ActionType.SEND_FOLLOW_UP, orc.settings.approval_policy)
    send_event = event.child(
        EventType.EMAIL_SENT, vendor_id=vendor.id, thread_id=thread.id,
        version=f"{thread.id}:followup:{thread.follow_up_count}",
    )
    if not decision.requires_approval:
        return [send_event]

    approval = Approval(
        id=stable_id("apr", mission.id, vendor.id, "follow_up", str(thread.follow_up_count)),
        mission_id=mission.id, vendor_id=vendor.id, action_type=ActionType.SEND_FOLLOW_UP.value,
        summary=f"Follow up with {vendor.name}",
        preview={"to": vendor.email, "subject": draft.subject, "body": draft.body,
                 "reason_for_approval": decision.reason},
        resume_event=send_event.model_dump(mode="json"),
    )
    await orc.repo.save(approval)
    thread.status = ThreadStatus.AWAITING_APPROVAL
    await orc.repo.save(thread)
    return [
        event.child(
            EventType.APPROVAL_REQUESTED, vendor_id=vendor.id, approval_id=approval.id,
            action=ActionType.SEND_FOLLOW_UP.value, version=approval.id,
        )
    ]


def _summarize_thread(thread: EmailThread) -> str:
    lines = []
    for message in thread.messages[-4:]:
        who = "we" if message.direction == "outbound" else "supplier"
        lines.append(f"[{who}] {sanitize.excerpt(message.body, limit=600)}")
    return "\n".join(lines)


# ==========================================================================
# 9. Voice
# ==========================================================================


@on(EventType.CALL_REQUIRED)
async def handle_call_required(orc: Orchestrator, event: Event) -> list[Event]:
    mission = await orc.repo.mission(event.mission_id)
    vendor = await orc.repo.vendor(event.payload["vendor_id"])
    if not vendor.phone:
        return []

    conflict = None
    if event.payload.get("conflict_id"):
        conflict = await orc.repo.load(Conflict, event.payload["conflict_id"])

    question = event.payload.get("question")
    if conflict is not None and not question:
        found = conflict_engine.detect(
            conflict.field, await orc.repo.vendor_evidence(vendor.id)
        )
        question = found.question if found else None

    plan = await orc.agents.communication.plan_call(
        vendor_name=vendor.name, reason=event.payload.get("reason", "missing information"),
        missing_fields=[f for f in CRITICAL_FIELDS if not vendor.fact(f).known],
        conflict_question=question, product=mission.product or mission.objective,
        quantity=mission.quantity, mission_id=mission.id, vendor_id=vendor.id,
    )

    call = Call(
        id=stable_id("call", mission.id, vendor.id, str(event.payload.get("version", ""))),
        mission_id=mission.id, vendor_id=vendor.id, to_number=vendor.phone,
        reason=event.payload.get("reason", ""), questions=plan.questions,
        status=CallStatus.REQUIRED,
    )
    await orc.repo.save(call)
    await orc.repo.mutate(Vendor, vendor.id, lambda v: _append_unique(v.call_ids, call.id))

    start_event = event.child(
        EventType.CALL_STARTED, vendor_id=vendor.id, call_id=call.id,
        version=call.id, opening=plan.opening,
    )
    decision = approval_for(ActionType.MAKE_CALL, orc.settings.approval_policy)
    if not decision.requires_approval:
        return [start_event]

    approval = Approval(
        id=stable_id("apr", mission.id, vendor.id, "make_call", call.id),
        mission_id=mission.id, vendor_id=vendor.id, action_type=ActionType.MAKE_CALL.value,
        summary=f"Call {vendor.name} at {vendor.phone}",
        preview={"to": vendor.phone, "opening": plan.opening, "questions": plan.questions,
                 "reason": call.reason, "reason_for_approval": decision.reason},
        resume_event=start_event.model_dump(mode="json"),
    )
    await orc.repo.save(approval)
    call.status = CallStatus.AWAITING_APPROVAL
    await orc.repo.save(call)
    return [
        event.child(
            EventType.APPROVAL_REQUESTED, vendor_id=vendor.id, approval_id=approval.id,
            action=ActionType.MAKE_CALL.value, version=approval.id,
        )
    ]


@on(EventType.CALL_STARTED)
async def handle_call_started(orc: Orchestrator, event: Event) -> list[Event]:
    mission = await orc.repo.mission(event.mission_id)
    vendor = await orc.repo.vendor(event.payload["vendor_id"])
    call = await orc.repo.load(Call, event.payload["call_id"])
    if call is None:
        return []

    claimed = await orc.reserve_action(mission.id, vendor.id, "make_call", call.id)
    if not claimed:
        return []

    # A call raised to settle a disagreement may draw on the reserve; a call to
    # fill in a missing field may not.
    settles_conflict = any(
        c.status is ConflictStatus.RESOLVING for c in await orc.repo.vendor_conflicts(vendor.id)
    )
    if not await _take_budget(
        orc, mission.id, "calls_made", orc.settings.max_calls_per_mission,
        reserve=0 if settles_conflict else CALLS_RESERVED_FOR_CONFLICTS,
    ):
        call.status = CallStatus.NOT_ATTEMPTED
        call.reason = (
            f"{call.reason}; not placed — the mission's call budget was already spent "
            "on higher-priority calls"
        )
        await orc.repo.save(call)
        await _abandon_conflicts(orc, vendor, "the mission's call budget is exhausted")
        return [
            event.child(
                EventType.VENDOR_UPDATED, vendor_id=vendor.id, stage="call_budget",
                version=call.id,
            )
        ]

    call.status = CallStatus.DIALING
    await orc.repo.save(call)

    result = await orc.providers.voice.place_call(
        to=call.to_number, opening=event.payload.get("opening", ""),
        questions=call.questions, call_id=call.id,
    )
    call.provider_call_id = result.provider_call_id
    await orc.confirm_action(
        mission.id, vendor.id, "make_call", call.id, {"provider_call_id": result.provider_call_id}
    )

    if result.status == "dialing":
        # Live telephony: the transcript arrives through /webhooks/voice.
        await orc.repo.save(call)
        return []

    if result.status != "completed":
        call.status = CallStatus.FAILED if result.status == "failed" else CallStatus.NO_ANSWER
        await orc.repo.save(call)
        # A call placed to settle a disagreement that never connected leaves that
        # disagreement open. Say so, or the vendor waits on an answer that is
        # never coming.
        await _abandon_conflicts(
            orc, vendor, f"the call to resolve it {result.status.replace('_', ' ')}"
        )
        return [
            event.child(
                EventType.VENDOR_UPDATED, vendor_id=vendor.id, stage="call_failed",
                version=call.id,
            )
        ]

    call.transcript = result.transcript
    call.duration_seconds = result.duration_seconds
    await orc.repo.save(call)
    return [
        event.child(EventType.CALL_COMPLETED, vendor_id=vendor.id, call_id=call.id, version=call.id)
    ]


@on(EventType.CALL_COMPLETED)
async def handle_call_completed(orc: Orchestrator, event: Event) -> list[Event]:
    mission = await orc.repo.mission(event.mission_id)
    vendor = await orc.repo.vendor(event.payload["vendor_id"])
    call = await orc.repo.load(Call, event.payload["call_id"])
    if call is None:
        return []

    extraction = await orc.agents.communication.extract_call(
        transcript=call.transcript, questions=call.questions,
        mission_id=mission.id, vendor_id=vendor.id,
    )
    call.status = CallStatus.COMPLETED
    call.answered_questions = extraction.answered
    call.unanswered_questions = extraction.unanswered
    await orc.repo.save(call)

    spoken = " ".join(f"{q} — {a}" for q, a in extraction.answered.items())
    quote = Quote(
        id=stable_id("qte", mission.id, vendor.id, call.id),
        mission_id=mission.id, vendor_id=vendor.id, source="call",
        currency=vendor.currency or _currency_for(mission.market),
        line_items={"package": extraction.unit_price} if extraction.unit_price else {},
        moq=extraction.moq, lead_time_days=extraction.lead_time_days,
        raw_text=spoken,
    )
    if quote.line_items or quote.moq or quote.lead_time_days:
        await orc.repo.save(quote)
        await _evidence_from_supplier(
            orc, mission, vendor, quote, source_type=SourceType.SUPPLIER_CALL,
            source_title=f"Call with {vendor.name}", excerpt=sanitize.excerpt(spoken),
        )

    # A call was made to settle something; record that it did.
    for conflict in await orc.repo.vendor_conflicts(vendor.id):
        if conflict.status is not ConflictStatus.RESOLVING:
            continue
        resolved = _resolved_value(conflict.field, extraction)
        if resolved is None:
            conflict.status = ConflictStatus.UNRESOLVABLE
            conflict.preferred_reason += "; the supplier did not answer on the call"
        else:
            conflict.status = ConflictStatus.RESOLVED
            conflict.resolved_value = resolved
            conflict.resolution_action = "call"
            conflict.preferred_value = resolved
            conflict.preferred_reason = "confirmed directly by the supplier on a recorded call"
        await orc.repo.save(conflict)

    all_evidence = await orc.repo.vendor_evidence(vendor.id)
    _apply_facts(vendor, all_evidence, await orc.repo.vendor_conflicts(vendor.id))
    vendor.missing_fields = [f for f in CONTACTABLE_FIELDS if not vendor.fact(f).known]
    vendor.version += 1
    await orc.repo.save(vendor)

    return [
        event.child(
            EventType.VENDOR_UPDATED, vendor_id=vendor.id, stage="call", version=call.id
        )
    ]


def _resolved_value(field: str, extraction: Any) -> Any:
    return {
        "moq": extraction.moq,
        "unit_price": extraction.unit_price,
        "lead_time_days": extraction.lead_time_days,
    }.get(field)


# ==========================================================================
# 10. Recommendation
# ==========================================================================


async def _maybe_finish(orc: Orchestrator, event: Event) -> list[Event]:
    """Emit the recommendation once no vendor is still in play."""
    vendors = await orc.repo.list(Vendor, mission_id=event.mission_id)
    if not vendors:
        return []
    in_play = [
        v for v in vendors
        if v.status not in (VendorStatus.QUALIFIED, VendorStatus.REJECTED)
    ]
    if in_play:
        return []
    return [event.child(EventType.RECOMMENDATION_READY, version=str(len(vendors)))]


@on(EventType.RECOMMENDATION_READY)
async def handle_recommendation_ready(orc: Orchestrator, event: Event) -> list[Event]:
    """Score every vendor deterministically, then let the agent write it up."""
    mission = await orc.repo.mission(event.mission_id)
    mission.status = MissionStatus.RECOMMENDING
    await orc.repo.save(mission)

    nodes = await orc.repo.list(SupplyChainNode, mission_id=mission.id)
    vendors = await orc.repo.list(Vendor, mission_id=mission.id)
    ranking = await rank_vendors(orc, mission, nodes, vendors)

    selections, alternatives, rejected = [], [], []
    for node in nodes:
        ranked = ranking.get(node.key, [])
        eligible = [r for r in ranked if not r["score"]["disqualified"]]
        if eligible:
            selections.append({"node_key": node.key, "node_name": node.name, **eligible[0]})
            alternatives.extend(
                {"node_key": node.key, "node_name": node.name, **r} for r in eligible[1:3]
            )
        rejected.extend(
            {"node_key": node.key, "node_name": node.name, **r}
            for r in ranked
            if r["score"]["disqualified"] or r["vendor"]["status"] == VendorStatus.REJECTED.value
        )

    open_conflicts = [
        c for c in await orc.repo.list(Conflict, mission_id=mission.id)
        if c.status in (ConflictStatus.OPEN, ConflictStatus.RESOLVING, ConflictStatus.UNRESOLVABLE)
    ]

    narrative = await orc.agents.recommendation.narrate(
        mission_summary=_mission_summary(mission),
        ranking_text=_render_ranking(selections, alternatives, rejected, open_conflicts),
        mission_id=mission.id,
    )

    # The narrative may only annotate the computed selection, never reorder it.
    why_by_node = {s.node_key: s.why for s in narrative.selections}
    for selection in selections:
        selection["why"] = why_by_node.get(selection["node_key"]) or _fallback_why(selection)

    recommendation = Recommendation(
        id=stable_id("rec", mission.id, str(event.payload.get("version", ""))),
        mission_id=mission.id, selections=selections, alternatives=alternatives,
        rejected=rejected, risks=narrative.risks, unknowns=narrative.unknowns,
        next_actions=narrative.next_actions, narrative=narrative.summary,
        open_conflicts=[c.id for c in open_conflicts],
        currency=_currency_for(mission.market),
        estimated_unit_cost=_estimated_unit_cost(selections),
    )
    await orc.repo.save(recommendation)

    return [event.child(EventType.MISSION_COMPLETED, recommendation_id=recommendation.id)]


@on(EventType.MISSION_COMPLETED)
async def handle_mission_completed(orc: Orchestrator, event: Event) -> list[Event]:
    mission = await orc.repo.mission(event.mission_id)
    mission.status = MissionStatus.COMPLETED
    await orc.repo.save(mission)
    return []


@on(EventType.MISSION_FAILED)
async def handle_mission_failed(orc: Orchestrator, event: Event) -> list[Event]:
    return []


async def rank_vendors(
    orc: Orchestrator, mission: Mission, nodes: list[SupplyChainNode], vendors: list[Vendor]
) -> dict[str, list[dict[str, Any]]]:
    """Score every vendor for every node it could serve. Pure and reproducible."""
    node_components = {node.key: _components_for(node) for node in nodes}
    ranking: dict[str, list[dict[str, Any]]] = {}

    for node in nodes:
        candidates = [v for v in vendors if node.key in v.node_keys]
        if not candidates:
            ranking[node.key] = []
            continue

        components = node_components[node.key]
        packaged: dict[str, Any] = {}
        for vendor in candidates:
            vendor_quotes = await orc.repo.vendor_quotes(vendor.id)
            comparable, _ = quote_engine.comparable_set(vendor_quotes, components)
            packaged[vendor.id] = comparable[0] if comparable else None

        priced = [p.unit_price for p in packaged.values() if p and p.unit_price]
        cheapest = min(priced) if priced else None

        rows = []
        for vendor in candidates:
            evidence = await orc.repo.vendor_evidence(vendor.id)
            relationships = await orc.repo.vendor_relationships(vendor.id)
            vendor_conflicts = await orc.repo.vendor_conflicts(vendor.id)
            profile = trust.profile(vendor, evidence, relationships, vendor_conflicts)
            score = scoring.score_vendor(
                vendor, weights=mission.weights, trust=profile, quote=packaged[vendor.id],
                cheapest_price=cheapest, quantity=mission.quantity,
                target_lead_days=_target_lead_days(mission), required_nodes=[node.key],
                market=mission.market, conflicts=vendor_conflicts,
            )
            rows.append(
                {
                    "vendor": vendor.model_dump(mode="json"),
                    "score": score.as_dict(),
                    "trust": profile.as_dict(),
                    "quote": _quote_dict(packaged[vendor.id]),
                    "brand_relationships": [r.model_dump(mode="json") for r in relationships],
                    "conflicts": [c.model_dump(mode="json") for c in vendor_conflicts],
                }
            )
        rows.sort(key=lambda r: (r["score"]["disqualified"], -r["score"]["total"]))
        ranking[node.key] = rows
    return ranking


def _components_for(node: SupplyChainNode) -> tuple[str, ...]:
    """What a quote for this node must price to be comparable."""
    from ..domain.quotes import canonical_component

    return (canonical_component(node.key),)


def _quote_dict(package: Any) -> dict[str, Any] | None:
    if package is None:
        return None
    return {
        "quote_id": package.quote_id, "unit_price": package.unit_price,
        "currency": package.currency, "components": list(package.components),
        "covered": list(package.covered), "missing": list(package.missing),
        "bundled": package.bundled, "notes": package.notes,
    }


def _estimated_unit_cost(selections: list[dict[str, Any]]) -> float | None:
    prices = [
        s["quote"]["unit_price"]
        for s in selections
        if s.get("quote") and s["quote"].get("unit_price")
    ]
    return round(sum(prices), 2) if prices else None


def _fallback_why(selection: dict[str, Any]) -> list[str]:
    """If the narrative agent skipped a node, the score still explains itself."""
    return [c["explanation"] for c in selection["score"]["components"] if c["raw"] >= 0.6]


def _mission_summary(mission: Mission) -> str:
    return (
        f"Mission: {mission.objective}\n"
        f"Product: {mission.product}\n"
        f"Quantity: {mission.quantity}\n"
        f"Market: {mission.market}\n"
        f"Priorities: {'; '.join(mission.priorities) or 'none stated'}\n"
        f"Scoring weights in use: "
        + ", ".join(f"{k} {v:.0%}" for k, v in mission.weights.as_dict().items())
    )


def _render_ranking(
    selections: list[dict[str, Any]],
    alternatives: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    open_conflicts: list[Conflict],
) -> str:
    lines: list[str] = ["SELECTED (computed, do not reorder):"]
    for row in selections:
        lines.append(_render_row(row))
    if alternatives:
        lines.append("\nALTERNATIVES:")
        for row in alternatives:
            lines.append(_render_row(row))
    if rejected:
        lines.append("\nNOT VIABLE:")
        for row in rejected:
            reasons = row["score"]["rejection_reasons"] or row["vendor"]["rejection_reasons"]
            lines.append(
                f"- [{row['node_name']}] {row['vendor']['name']}: " + "; ".join(reasons)
            )
    if open_conflicts:
        lines.append("\nUNRESOLVED DISAGREEMENTS:")
        for conflict in open_conflicts:
            lines.append(
                f"- {conflict.field}: {[v['value'] for v in conflict.values]} "
                f"({conflict.status.value})"
            )
    return "\n".join(lines)


def _render_row(row: dict[str, Any]) -> str:
    vendor, score, quote = row["vendor"], row["score"], row["quote"]
    head = (
        f"- [{row['node_name']}] {vendor['name']} — {score['total']:.1f}/100"
        f" — {vendor['city'] or 'location unknown'}"
    )
    detail = [f"    {c['name']}: {c['explanation']}" for c in score["components"]]
    if quote and quote.get("unit_price"):
        detail.append(f"    quoted: {quote['currency']} {quote['unit_price']:,.0f}/unit")
    for relationship in row.get("brand_relationships", []):
        detail.append(
            f"    brand claim ({relationship['brand']}): {relationship['classification']}, "
            f"{relationship['independent_sources']} independent source(s)"
        )
    return head + "\n" + "\n".join(detail)


# ==========================================================================
# Shared helpers
# ==========================================================================


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


async def _set_status(
    orc: Orchestrator, vendor: Vendor, status: VendorStatus, reasons: list[str] | None = None
) -> None:
    """Transition a vendor's status without overwriting a concurrent writer's fields."""

    def _apply(record: Vendor) -> None:
        record.status = status
        if reasons is not None:
            record.rejection_reasons = reasons

    await orc.repo.mutate(Vendor, vendor.id, _apply)
    vendor.status = status
    if reasons is not None:
        vendor.rejection_reasons = reasons


async def _record_evidence(
    orc: Orchestrator, mission_id: str, vendor_id: str, *, claim: str, field: str | None,
    value: Any, source_type: SourceType, source_url: str | None, source_title: str | None,
    excerpt: str,
) -> Evidence:
    """Persist one claim with its provenance. Id is content-derived, so replays merge."""
    clean = sanitize.excerpt(excerpt)
    record = Evidence(
        id=stable_id("ev", mission_id, vendor_id, claim, source_url or "", str(value)),
        mission_id=mission_id, vendor_id=vendor_id, claim=claim, field=field, value=value,
        source_url=source_url, source_type=source_type, source_title=source_title,
        evidence_excerpt=clean,
        confidence=evidence_engine.score_evidence(source_type, clean),
        evidence_strength=evidence_engine.strength_for(source_type, clean),
    )
    await orc.repo.save(record)
    return record


async def _evidence_from_supplier(
    orc: Orchestrator, mission: Mission, vendor: Vendor, quote: Quote, *,
    source_type: SourceType, source_title: str, excerpt: str,
) -> list[Evidence]:
    """Turn a quote's fields into individually sourced evidence records."""
    facts: list[tuple[str, Any, str]] = []
    if quote.moq is not None:
        facts.append(("moq", quote.moq, f"minimum order {quote.moq}"))
    if quote.package_unit_price is not None:
        facts.append(("unit_price", quote.package_unit_price,
                      f"unit price {quote.currency} {quote.package_unit_price:,.0f}"))
    if quote.lead_time_days is not None:
        facts.append(("lead_time_days", quote.lead_time_days,
                      f"production lead time {quote.lead_time_days} days"))
    if quote.sample_lead_time_days is not None:
        facts.append(("sample_lead_time_days", quote.sample_lead_time_days,
                      f"sample lead time {quote.sample_lead_time_days} days"))
    if quote.payment_terms:
        facts.append(
            ("payment_terms", quote.payment_terms, f"payment terms: {quote.payment_terms}")
        )
    if quote.customization:
        facts.append(
            ("customization", quote.customization, f"customization: {quote.customization}")
        )

    records = []
    for field, value, claim in facts:
        records.append(
            await _record_evidence(
                orc, mission.id, vendor.id, claim=f"{vendor.name}: {claim}", field=field,
                value=value, source_type=source_type, source_url=None,
                source_title=source_title, excerpt=excerpt,
            )
        )
    return records


def _apply_facts(
    vendor: Vendor, all_evidence: list[Evidence], conflicts: Sequence[Conflict] = ()
) -> None:
    """Recompute every vendor fact from the full evidence set.

    Deliberately a full recompute rather than an incremental update: the
    provenance of a field depends on everything known about it, so a new email
    can promote a field from `publicly_listed` to `direct_quote` and must.

    A settled conflict wins over the raw evidence. When the supplier told us on a
    recorded call that 500 is possible as a pilot, that answer is the MOQ — not
    the 1,000 their sales desk emailed. Skipping this step is how a system does
    the work of resolving a disagreement and then scores as if it never had.
    """
    resolved = {
        c.field: c
        for c in conflicts
        if c.status is ConflictStatus.RESOLVED and c.resolved_value is not None
    }

    for field in CONTACTABLE_FIELDS:
        supporting = [e for e in all_evidence if e.field == field and e.value is not None]
        if not supporting:
            continue

        settled = resolved.get(field)
        if settled is not None:
            setattr(
                vendor,
                field,
                Fact(
                    value=numbers.normalize_field(field, settled.resolved_value),
                    provenance=Provenance.DIRECT_QUOTE,
                    evidence_ids=[e.id for e in supporting],
                    confidence=max(evidence_engine.confidence_for(supporting), 0.9),
                ),
            )
            continue

        provenance = evidence_engine.provenance_for(supporting)
        best = max(
            supporting,
            key=lambda e: (evidence_engine.SOURCE_WEIGHT.get(e.source_type, 0.0),
                           e.retrieved_at.timestamp()),
        )
        disagreement = conflict_engine.detect(field, supporting)
        # Store the field as the type the rest of the system expects. Gemini
        # legitimately answers "10-14" for a lead time; the scorer needs a number
        # and the evidence record keeps the original wording.
        setattr(
            vendor,
            field,
            Fact(
                value=numbers.normalize_field(field, best.value),
                provenance=Provenance.CONFLICTING if disagreement else provenance,
                evidence_ids=[e.id for e in supporting],
                confidence=evidence_engine.confidence_for(supporting),
            ),
        )


async def _detect_conflicts(
    orc: Orchestrator, event: Event, vendor: Vendor, all_evidence: list[Evidence]
) -> list[Event]:
    """Persist newly detected disagreements and emit one event per new conflict."""
    existing = {c.field: c for c in await orc.repo.vendor_conflicts(vendor.id)}
    emitted: list[Event] = []

    for field in conflict_engine.MATERIAL_FIELDS:
        found = conflict_engine.detect(field, all_evidence)
        if found is None:
            continue
        previous = existing.get(field)
        if previous is not None and previous.status is not ConflictStatus.OPEN:
            continue  # already being resolved, or settled

        conflict = Conflict(
            id=stable_id("cfl", vendor.mission_id, vendor.id, field),
            mission_id=vendor.mission_id, vendor_id=vendor.id, field=field,
            values=found.values, preferred_value=found.preferred_value,
            preferred_reason=found.preferred_reason, resolution_action=found.action,
            status=ConflictStatus.OPEN,
        )
        await orc.repo.save(conflict)
        if conflict.id not in vendor.open_conflicts:
            vendor.open_conflicts.append(conflict.id)
        emitted.append(
            event.child(
                EventType.CONFLICT_DETECTED, vendor_id=vendor.id, conflict_id=conflict.id,
                field=field, version=conflict.id, question=found.question,
            )
        )
    return emitted


async def _personalization_facts(orc: Orchestrator, vendor: Vendor) -> list[str]:
    """Only facts with a real source may appear in an outbound email."""
    evidence = await orc.repo.vendor_evidence(vendor.id)
    usable = [
        e for e in evidence
        if e.evidence_excerpt
        and e.source_type in (SourceType.OFFICIAL_WEBSITE, SourceType.MAPS_LISTING,
                              SourceType.INDUSTRY_PUBLICATION, SourceType.NEWS)
    ]
    return [f"{e.claim} (source: {e.source_url or e.source_type.value})" for e in usable[:6]]


async def _node_names(orc: Orchestrator, mission_id: str, keys: list[str]) -> list[str]:
    nodes = await orc.repo.list(SupplyChainNode, mission_id=mission_id)
    by_key = {n.key: n.name for n in nodes}
    return [by_key.get(k, k) for k in keys]


def _brief_from_mission(mission: Mission, target_lead_time_days: int | None) -> Any:
    from ..agents.schemas import MissionBrief

    return MissionBrief(
        product=mission.product or mission.objective, quantity=mission.quantity,
        unit_spec=mission.unit_spec, market=mission.market, budget_note=mission.budget_note,
        priorities=mission.priorities, success_criteria=mission.success_criteria,
        target_lead_time_days=target_lead_time_days,
    )


def _target_lead_days(mission: Mission) -> int | None:
    for criterion in mission.success_criteria:
        import re

        match = re.search(r"(\d+)\s*(?:working\s*)?days", criterion.lower())
        if match:
            return int(match.group(1))
    return None


def _city_from(address: str | None) -> str | None:
    if not address:
        return None
    parts = [p.strip() for p in address.split(",") if p.strip()]
    return parts[-2] if len(parts) >= 2 else None


def _region_code(market: str | None) -> str:
    if not market:
        return ""
    return {"indonesia": "ID", "malaysia": "MY", "singapore": "SG",
            "vietnam": "VN", "thailand": "TH", "china": "CN", "india": "IN"}.get(
        market.strip().lower(), ""
    )


def _currency_for(market: str | None) -> str:
    if not market:
        return "USD"
    return {"indonesia": "IDR", "malaysia": "MYR", "singapore": "SGD",
            "vietnam": "VND", "thailand": "THB", "china": "CNY", "india": "INR"}.get(
        market.strip().lower(), "USD"
    )
