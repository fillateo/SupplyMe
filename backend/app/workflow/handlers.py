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
from typing import Any

from ..domain import conflicts as conflict_engine
from ..domain import contacts as contact_finder
from ..domain import evidence as evidence_engine
from ..domain import identity, numbers, scoring, trust
from ..domain import quotes as quote_engine
from ..domain.events import Event, EventType
from ..domain.ids import slug, stable_id
from ..domain.models import (
    Approval,
    ApprovalStatus,
    BrandRelationship,
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
    SearchScope,
    SourceType,
    SupplyChainNode,
    ThreadStatus,
    Vendor,
    VendorStatus,
)
from ..domain.policy import ActionType, approval_for
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

#: Per-vendor attempt ceiling. Beyond it the vendor is closed out with a reason
#: rather than left in play: a supplier who has not answered two threads is not
#: going to, and a mission that waits forever never produces a recommendation.
MAX_THREADS_PER_VENDOR = 2

#: Outreach slots held back for settling disagreements. Writing is the only
#: channel, so a mission that spends its whole budget on first contact has
#: nothing left when the MOQ on its best candidate turns out to be disputed —
#: and a disagreement is worth more than a blank, because a blank was never
#: asked and a disagreement already survived being asked once.
EMAILS_RESERVED_FOR_CONFLICTS = 1


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
    # What the user chose outranks what the model read into the objective. A
    # scope of COUNTRY means the location they typed *is* the market; otherwise
    # the brief fills it in, and a city they named keeps its own field.
    if mission.search_scope is SearchScope.COUNTRY and mission.location:
        mission.market = mission.location
    else:
        mission.market = mission.market or brief.market
        if mission.search_scope is SearchScope.CITY and not mission.market:
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
                aliases=planned.aliases,
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
        event.child(EventType.SUPPLIER_DISCOVERY_STARTED, node_id=node.id, node_key=node.key)
        for node in nodes
        if node.required
    ]


# ==========================================================================
# 2. Discovery and identity
# ==========================================================================


@on(EventType.SUPPLIER_DISCOVERY_STARTED)
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
        scope_note=_scope_note(mission),
        mission_id=mission.id,
    )

    hits, places = await _gather_sources(
        orc, plan.queries, plan.maps_queries, mission.market, mission.search_scope
    )
    if not hits and not places:
        node.status = NodeStatus.BLOCKED
        await orc.repo.save(node)
        return []

    result = await orc.agents.discovery.extract(
        node_key=node.key, node_name=node.name, hits=hits[:12], places=places[:8],
        market=mission.market, scope_note=_scope_note(mission), mission_id=mission.id,
    )

    # Identity resolution runs against everything already found for this mission,
    # not just this node, so a vendor discovered under "bottle" and again under
    # "cap" becomes one record that can supply both.
    existing = await orc.repo.list(Vendor, mission_id=mission.id)
    emitted: list[Event] = []
    place_by_name = {p.name.lower(): p for p in places}

    for found in result.vendors[: orc.settings.max_vendors_per_category]:
        place = place_by_name.get(found.name.lower())
        # A supplier with no website cannot be researched for a contact route,
        # and half of what discovery returns has none — the model read a listing
        # and copied the name across. The page it read is often the company's own
        # site, so adopt it when the domain carries the company's name.
        site = found.website or (place.website if place else None) or contact_finder.own_site_from(
            found.source_url, found.name
        )
        candidate = Vendor(
            mission_id=mission.id,
            name=found.name.strip(),
            website=site,
            domain=identity.normalize_domain(site),
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

        # A vendor already known to this mission is free to enrich; a new one
        # costs a research tool loop, so it has to fit inside the mission's
        # ceiling. Taken atomically because every node discovers in parallel.
        if is_new and not await _take_budget(
            orc, mission.id, "vendors_admitted", orc.settings.max_vendors_per_mission
        ):
            log.info(
                "vendor_not_admitted",
                extra={"mission_id": mission.id, "status": "mission vendor ceiling reached"},
            )
            break

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


def _scope_note(mission: Mission) -> str:
    """The buyer's geographic choice, in the words the agents are prompted on."""
    if mission.search_scope is SearchScope.CITY and mission.location:
        return (
            f"city — only suppliers in or around {mission.location}"
            + (f", {mission.market}" if mission.market else "")
        )
    if mission.search_scope is SearchScope.GLOBAL:
        return "global — anywhere in the world; importing is acceptable"
    return f"country — anywhere in {mission.market or mission.location or 'the target market'}"


async def _gather_sources(
    orc: Orchestrator,
    queries: list[str],
    maps_queries: list[str],
    market: str | None,
    scope: SearchScope = SearchScope.COUNTRY,
) -> tuple[list[Any], list[Any]]:
    """Run web and Maps lookups in parallel; a failing source costs its results only."""
    # A region code biases Places towards one country, which is the whole point
    # at city and country scope and exactly wrong at global.
    region = "" if scope is SearchScope.GLOBAL else _region_code(market)
    search_tasks = [orc.providers.search.search(q, limit=6) for q in queries[:4]]
    # Places costs an order of magnitude more per call than web search, so it is
    # capped tightly and used to confirm a business exists, not to find one.
    maps_budget = orc.settings.max_maps_queries_per_node
    maps_tasks = [
        orc.providers.maps.search_places(q, region=region)
        for q in maps_queries[:maps_budget]
    ]
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

    node_names = await _node_names(orc, mission.id, vendor.node_keys)
    wanted = list(CONTACTABLE_FIELDS)

    # Research is the widest fan-out and the most model calls per branch. Hold a
    # slot for the duration so a mission does not rate-limit itself.
    async with orc.research_slots:
        # Marked only once the slot is held. Setting it on the way in showed
        # eight suppliers being researched at once when seven were queued behind
        # one, which is the kind of invented progress this console exists not to
        # show.
        await _set_status(orc, vendor, VendorStatus.RESEARCHING)
        research = await _run_research(orc, mission, vendor, node_names, wanted)

    if research.suspicious_content:
        log.warning(
            "untrusted_content_flagged",
            extra={"mission_id": mission.id, "vendor_id": vendor.id, "stage": "research"},
        )

    for field in ("legal_name", "email", "phone", "address", "city", "country"):
        value = getattr(research, field, None)
        if value and not getattr(vendor, field, None):
            setattr(vendor, field, value)

    # Whatever the research agent read, a supplier with no contact route cannot
    # be asked anything, and the rest of the mission is about asking. Go and look
    # on the pages that actually carry one.
    await _find_contact_route(orc, mission, vendor)
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


async def _run_research(
    orc: Orchestrator, mission: Mission, vendor: Vendor, node_names: list[str],
    wanted: list[str],
) -> Any:
    """Dispatch to whichever research agent is bound.

    The ADK agent fetches its own sources, so pre-fetching for it would pay for
    pages it may never open. The pre-fetching agent is handed a fixed set,
    which is what makes the tests deterministic.
    """
    if hasattr(orc.agents.research, "_runner"):
        return await orc.agents.research.investigate(
            vendor_name=vendor.name, node_names=node_names, wanted_fields=wanted,
            market=mission.market, website=vendor.website,
            mission_id=mission.id, vendor_id=vendor.id,
        )
    pages, hits, place = await _research_sources(orc, vendor, mission)
    return await orc.agents.research.investigate(
        vendor_name=vendor.name, node_names=node_names, pages=pages, hits=hits,
        place=place, wanted_fields=wanted,
        mission_id=mission.id, vendor_id=vendor.id,
    )


#: How many of a supplier's own pages to open looking for a contact route.
#: The homepage footer or `/kontak` answers almost every time; opening eight
#: pages to find an address that was on the first two is a slower mission for no
#: extra suppliers.
MAX_CONTACT_PAGES = 4


async def _find_contact_route(orc: Orchestrator, mission: Mission, vendor: Vendor) -> None:
    """Read an email address and phone number off the supplier's own site.

    Discovery finds companies; search snippets almost never carry a contact
    route. Without this step a live mission researches five real manufacturers
    and then rejects all five for "no email or phone found" — every downstream
    capability the product has is gated on this one field.

    Deliberately not a model call. It runs on whichever research agent is bound,
    it cannot invent an address, and it costs nothing but a page fetch.
    """
    if vendor.email and vendor.phone:
        return

    urls = contact_finder.candidate_urls(vendor.website, vendor.domain)[:MAX_CONTACT_PAGES]
    if not urls:
        # Discovery recorded a company but nothing openable — which used to be
        # the end of it, and was every rejection in one live run. The supplier's
        # own domain is usually in the search results for their name.
        await _adopt_site_from_search(orc, mission, vendor)
        urls = contact_finder.candidate_urls(vendor.website, vendor.domain)[:MAX_CONTACT_PAGES]
    if not urls:
        return

    # Opened together rather than one after another. Most candidates are 404s on
    # a 15-second timeout, and four of those in series is a minute per supplier
    # spent learning that `/contact-us` does not exist.
    fetched = await asyncio.gather(*(_fetch(orc, url) for url in urls))

    own_domain = identity.normalize_domain(vendor.domain or vendor.website)
    for url, result in zip(urls, fetched, strict=True):
        page = _ok(result, None)
        if page is None or not getattr(page, "fetched", False) or not page.text:
            continue

        for finding in contact_finder.find_in_page(
            page.text, page.url or url, prefer_domain=own_domain
        ):
            # Candidates are in priority order, so the first answer of each kind
            # is the best one: the homepage before `/about`, the supplier's own
            # domain before anyone else's.
            if getattr(vendor, finding.kind, None):
                continue
            setattr(vendor, finding.kind, finding.value)
            await _record_evidence(
                orc, mission.id, vendor.id,
                claim=f"{vendor.name} publishes the {finding.kind} {finding.value}",
                field=finding.kind, value=finding.value,
                source_type=SourceType.OFFICIAL_WEBSITE, source_url=finding.source_url,
                source_title=page.title or None, excerpt=finding.excerpt,
            )
            log.info(
                "contact_route_found",
                extra={"mission_id": mission.id, "vendor_id": vendor.id,
                       "status": finding.kind, "stage": finding.source_url},
            )


async def _adopt_site_from_search(orc: Orchestrator, mission: Mission, vendor: Vendor) -> None:
    """Search for the supplier's own site, and take it only if it is theirs.

    Run only for a vendor that has no site at all, because that vendor is
    otherwise finished: nothing can be read about it and nobody can be written
    to. `own_site_from` is what keeps this from adopting the first directory
    that happens to rank for the company's name.
    """
    query = f"{vendor.name} {mission.market or ''}".strip()
    try:
        hits = await orc.providers.search.search(query, limit=6)
    except Exception as exc:  # a search outage costs this vendor, not the mission
        log.warning(
            "contact_search_failed",
            extra={"mission_id": mission.id, "vendor_id": vendor.id, "error": str(exc)[:200]},
        )
        return

    for hit in hits:
        site = contact_finder.own_site_from(getattr(hit, "url", None), vendor.name)
        if site is None:
            continue
        vendor.website = site
        vendor.domain = identity.normalize_domain(site)
        log.info(
            "vendor_site_recovered",
            extra={"mission_id": mission.id, "vendor_id": vendor.id, "stage": site},
        )
        return


async def _fetch(orc: Orchestrator, url: str) -> Any:
    """Fetch that returns the exception instead of raising, like the gathers do."""
    try:
        return await orc.providers.search.fetch(url)
    except Exception as exc:  # a dead contact page must not fail the research
        return exc


async def _research_sources(
    orc: Orchestrator, vendor: Vendor, mission: Mission
) -> tuple[list[Any], list[Any], Any]:
    depth = orc.settings.max_research_depth
    query = f"{vendor.name} {mission.market or ''}".strip()

    tasks: list[Any] = [orc.providers.search.search(query, limit=6)]
    if vendor.website:
        tasks.append(orc.providers.search.fetch(vendor.website))
    if vendor.place_id:
        tasks.append(orc.providers.maps.place_details(vendor.place_id))

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

    return pages, hits, place


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
    investigation = await orc.agents.brand_evidence.investigate(
        vendor_name=vendor.name, brand=brand, hits=hits[:8], pages=pages,
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
    open_conflicts = [c for c in vendor_conflicts if c.status is ConflictStatus.OPEN]
    threads = await orc.repo.list(EmailThread, vendor_id=vendor.id)

    # A conflict being resolved has a follow-up in flight against it, and
    # handle_conflict_detected owns that — stepping in here would write to the
    # same supplier twice. But only while there is still a way to ask: once
    # every thread has spent its follow-ups, waiting is waiting for nothing, and
    # this vendor would sit in `contacted` forever holding the mission open.
    if any(c.status is ConflictStatus.RESOLVING for c in vendor_conflicts):
        if _can_still_ask(mission, vendor, threads, orc.settings.max_outreach_per_mission):
            return []
        await _abandon_conflicts(orc, vendor, "there was no way left to ask the supplier")

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

    # Writing was the only route and it is spent. Close the vendor out with the
    # reason, so the recommendation can explain the gap instead of the mission
    # stalling.
    await _set_status(
        orc, vendor, VendorStatus.REJECTED,
        _no_route_reasons(vendor, missing_critical, len(threads)),
    )
    return [
        event.child(EventType.VENDOR_REJECTED, vendor_id=vendor.id, version=vendor.version),
        *await _maybe_finish(orc, event),
    ]


def _can_still_ask(
    mission: Mission, vendor: Vendor, threads: list[EmailThread], outreach_cap: int
) -> bool:
    """Whether a disagreement can still be put to this supplier.

    Deliberately narrower than "could we contact them at all". A conflict is
    pursued by following up on the thread that produced it, never by opening a
    fresh one — a new thread would re-introduce the project to someone already
    mid-conversation. So room for another thread is not room to ask this
    question, and treating it as though it were leaves the vendor waiting on a
    follow-up that no path will ever send.
    """
    if not vendor.email or mission.emails_sent >= outreach_cap:
        return False
    return any(t.follow_up_count < MAX_FOLLOW_UPS for t in threads)


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
    all observe `emails_sent = 11` and all decide they are within a cap of 12.

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


def _no_route_reasons(vendor: Vendor, missing: list[str], threads: int = 0) -> list[str]:
    if not vendor.email:
        return ["no email address found, so nothing could be confirmed"]
    if not missing:
        return ["no remaining route, though the required facts were obtained"]
    attempted = f"{threads} email thread(s)" if threads else "no reachable contact"
    return [f"still missing {', '.join(missing)} after {attempted}"]


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

    # A follow-up raised to settle a disagreement may draw on the reserve; an
    # ordinary send may not.
    if not await _take_budget(
        orc, mission.id, "emails_sent", orc.settings.max_outreach_per_mission,
        reserve=0 if event.payload.get("settles_conflict") else EMAILS_RESERVED_FOR_CONFLICTS,
    ):
        thread.status = ThreadStatus.DRAFT
        await orc.repo.save(thread)
        if event.payload.get("settles_conflict"):
            await _abandon_conflicts(orc, vendor, "the mission's outreach budget is exhausted")
        return [
            event.child(
                EventType.VENDOR_UPDATED, vendor_id=vendor.id, stage="outreach_budget",
                version=action_version,
            )
        ]

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

    def _awaiting(record: Mission) -> None:
        record.status = MissionStatus.AWAITING_RESPONSE

    await orc.repo.mutate(Mission, mission.id, _awaiting)

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

    nodes = await orc.repo.list(SupplyChainNode, mission_id=mission.id)
    extraction = await orc.agents.communication.extract_quote(
        body=body, questions_asked=thread.asked,
        currency_hint=_currency_for(mission.market), order_quantity=mission.quantity,
        components=_component_names(nodes, vendor.node_keys),
        mission_id=mission.id, vendor_id=vendor.id,
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
        quantity=extraction.quantity, line_items=extraction.price_map(),
        bundle_covers=extraction.bundle_covers(), moq=extraction.moq,
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

    await _settle_conflicts_from_reply(orc, vendor, extraction)

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
    settles_conflict = bool(event.payload.get("conflict_id"))

    # Both ceilings end the disagreement as well as the follow-up. Writing is the
    # only way to ask, so a question that can no longer be asked will not be
    # answered, and saying so beats waiting forever.
    if thread.follow_up_count >= MAX_FOLLOW_UPS:
        await _abandon_conflicts(
            orc, vendor, "the supplier did not answer the follow-up that asked about it"
        )
        return [
            event.child(
                EventType.VENDOR_UPDATED, vendor_id=vendor.id, stage="follow_up_exhausted",
                version=f"{thread.id}:{thread.follow_up_count}",
            )
        ]
    if mission.emails_sent >= orc.settings.max_outreach_per_mission:
        await _abandon_conflicts(orc, vendor, "the mission's outreach budget is exhausted")
        return [
            event.child(
                EventType.VENDOR_UPDATED, vendor_id=vendor.id, stage="outreach_budget",
                version=f"{thread.id}:{thread.follow_up_count}",
            )
        ]

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
        settles_conflict=settles_conflict,
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
# 9. Recommendation
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
    vocabulary = quote_engine.ComponentVocabulary.from_nodes(nodes)
    node_components = {node.key: _components_for(node, vocabulary) for node in nodes}
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
            comparable, _ = quote_engine.comparable_set(
                vendor_quotes, components, vocabulary=vocabulary
            )
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
                market=mission.market, location=mission.location,
                scope=mission.search_scope, conflicts=vendor_conflicts,
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


def _component_names(nodes: list[SupplyChainNode], node_keys: list[str]) -> list[str]:
    """How to name each component this vendor was asked about, for the extractor.

    The vendor's own nodes first, because those are what the email asked for;
    the rest of the plan after, because a supplier who also quotes a neighbouring
    component should have it recognised rather than filed under a new name.
    """
    ordered = sorted(nodes, key=lambda n: n.key not in set(node_keys))
    return [f"{n.key} ({n.name})" if n.name and n.name != n.key else n.key for n in ordered]


def _components_for(
    node: SupplyChainNode, vocabulary: quote_engine.ComponentVocabulary
) -> tuple[str, ...]:
    """What a quote for this node must price to be comparable."""
    return (vocabulary.canonical(node.key),)


def _quote_dict(package: Any) -> dict[str, Any] | None:
    if package is None:
        return None
    return {
        "quote_id": package.quote_id, "unit_price": package.unit_price,
        "currency": package.currency, "components": list(package.components),
        "covered": list(package.covered), "missing": list(package.missing),
        "extras": list(package.extras), "bundled": package.bundled,
        "notes": package.notes,
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


async def _settle_conflicts_from_reply(
    orc: Orchestrator, vendor: Vendor, extraction: Any
) -> None:
    """Close out every disagreement this reply was sent to settle.

    Writing is the only channel, so this reply is the answer. Either it states
    the disputed value — in which case the supplier's own words win over
    anything they published — or it does not, in which case the disagreement is
    unresolvable and the recommendation reports it as an open risk. What it must
    not do is stay `resolving` forever: the vendor never reaches a terminal
    state, and the mission waits on an answer that has already arrived.
    """
    resolved_from = {
        "moq": extraction.moq,
        "unit_price": _package_price(extraction),
        "lead_time_days": extraction.lead_time_days,
        "payment_terms": extraction.payment_terms,
        "customization": extraction.customization,
    }

    for conflict in await orc.repo.vendor_conflicts(vendor.id):
        if conflict.status is not ConflictStatus.RESOLVING:
            continue
        answer = resolved_from.get(conflict.field)
        if answer is None:
            conflict.status = ConflictStatus.UNRESOLVABLE
            conflict.preferred_reason += "; the supplier's reply did not settle it"
        else:
            conflict.status = ConflictStatus.RESOLVED
            conflict.resolved_value = answer
            conflict.resolution_action = "email"
            conflict.preferred_value = answer
            conflict.preferred_reason = "confirmed directly by the supplier in writing"
        await orc.repo.save(conflict)


def _package_price(extraction: Any) -> float | None:
    """What one unit costs, however the supplier chose to break it down."""
    price_map = getattr(extraction, "price_map", None)
    items = price_map() if callable(price_map) else (getattr(extraction, "line_items", None) or {})
    if not items:
        return None
    if "package" in items:
        return items["package"]
    return round(sum(items.values()), 4)


def _apply_facts(
    vendor: Vendor, all_evidence: list[Evidence], conflicts: Sequence[Conflict] = ()
) -> None:
    """Recompute every vendor fact from the full evidence set.

    Deliberately a full recompute rather than an incremental update: the
    provenance of a field depends on everything known about it, so a new email
    can promote a field from `publicly_listed` to `direct_quote` and must.

    A settled conflict wins over the raw evidence. When the supplier confirms in
    writing that 500 is possible as a pilot, that answer is the MOQ — not the
    1,000 their first reply quoted. Skipping this step is how a system does the
    work of resolving a disagreement and then scores as if it never had.
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
