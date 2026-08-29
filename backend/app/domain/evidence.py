"""Evidence classification.

The LLM extracts claims; this module decides what a claim is *worth*. Keeping
that decision here means the strength of a fact is a function of its sources and
nothing else — the model cannot talk its way into a higher confidence.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from .models import (
    BrandEvidenceClass,
    Evidence,
    EvidenceStrength,
    Provenance,
    RelationshipType,
    SourceType,
)

#: Base weight of a source type when it supports a claim about the supplier.
SOURCE_WEIGHT: dict[SourceType, float] = {
    SourceType.SUPPLIER_EMAIL: 0.90,
    SourceType.SUPPLIER_CALL: 0.85,
    SourceType.OFFICIAL_WEBSITE: 0.75,
    SourceType.BRAND_WEBSITE: 0.85,
    SourceType.INDUSTRY_PUBLICATION: 0.70,
    SourceType.NEWS: 0.65,
    SourceType.MAPS_LISTING: 0.55,
    SourceType.DIRECTORY: 0.45,
    SourceType.YOUTUBE: 0.40,
    SourceType.SEARCH_RESULT: 0.30,
    SourceType.UNKNOWN: 0.20,
}

#: Sources that are not the supplier talking about itself.
INDEPENDENT_SOURCES = frozenset(
    {
        SourceType.BRAND_WEBSITE,
        SourceType.NEWS,
        SourceType.INDUSTRY_PUBLICATION,
        SourceType.DIRECTORY,
        SourceType.MAPS_LISTING,
    }
)

#: Sources that are the supplier speaking, directly or via its own site.
SUPPLIER_SOURCES = frozenset(
    {
        SourceType.SUPPLIER_EMAIL,
        SourceType.SUPPLIER_CALL,
        SourceType.OFFICIAL_WEBSITE,
        SourceType.YOUTUBE,
    }
)

DIRECT_SOURCES = frozenset({SourceType.SUPPLIER_EMAIL, SourceType.SUPPLIER_CALL})


def strength_for(source_type: SourceType, excerpt: str) -> EvidenceStrength:
    """Strength of one piece of evidence, from its source and whether it quotes."""
    weight = SOURCE_WEIGHT.get(source_type, 0.2)
    if not excerpt.strip():
        # No excerpt means nothing was actually read; cap it low.
        return EvidenceStrength.WEAK if weight >= 0.45 else EvidenceStrength.NONE
    if weight >= 0.75:
        return EvidenceStrength.STRONG
    if weight >= 0.45:
        return EvidenceStrength.MODERATE
    return EvidenceStrength.WEAK


def score_evidence(source_type: SourceType, excerpt: str) -> float:
    """Confidence contributed by a single piece of evidence."""
    weight = SOURCE_WEIGHT.get(source_type, 0.2)
    if not excerpt.strip():
        weight *= 0.5
    elif len(excerpt.strip()) >= 60:
        weight = min(1.0, weight + 0.05)
    return round(weight, 4)


def provenance_for(items: Sequence[Evidence]) -> Provenance:
    """Provenance of a field, given every piece of evidence supporting it."""
    if not items:
        return Provenance.UNKNOWN

    types = {e.source_type for e in items}
    if types & DIRECT_SOURCES:
        return Provenance.DIRECT_QUOTE

    independent = {e.source_type for e in items if e.source_type in INDEPENDENT_SOURCES}
    distinct_domains = {_domain(e.source_url) for e in items if e.source_url}
    distinct_domains.discard(None)

    if len(independent) >= 2 or (independent and len(distinct_domains) >= 2):
        return Provenance.VERIFIED
    if SourceType.OFFICIAL_WEBSITE in types:
        return Provenance.PUBLICLY_LISTED
    if independent:
        return Provenance.PUBLICLY_LISTED
    return Provenance.INFERRED


def confidence_for(items: Sequence[Evidence]) -> float:
    """Combine evidence with diminishing returns; corroboration never exceeds 1.0.

    Uses noisy-OR so two moderate independent sources beat one strong source,
    but ten weak ones never reach certainty.
    """
    if not items:
        return 0.0
    residual = 1.0
    for item in sorted(items, key=lambda e: e.confidence, reverse=True):
        residual *= 1.0 - min(max(item.confidence, 0.0), 0.97)
    return round(1.0 - residual, 4)


def classify_brand_relationship(
    items: Sequence[Evidence],
) -> tuple[BrandEvidenceClass, RelationshipType, float, int]:
    """Decide what a "we work with Brand X" claim is actually supported by.

    Returns (classification, relationship_type, confidence, independent_source_count).
    """
    if not items:
        return (
            BrandEvidenceClass.NO_PUBLIC_EVIDENCE,
            RelationshipType.UNVERIFIED,
            0.0,
            0,
        )

    by_type: dict[SourceType, list[Evidence]] = defaultdict(list)
    for item in items:
        by_type[item.source_type].append(item)

    independent_domains = {
        _domain(e.source_url)
        for e in items
        if e.source_type in INDEPENDENT_SOURCES and e.source_url
    }
    independent_domains.discard(None)
    independent_count = len(independent_domains)

    confidence = confidence_for(items)

    if SourceType.BRAND_WEBSITE in by_type:
        return (
            BrandEvidenceClass.VERIFIED,
            RelationshipType.BRAND_CONFIRMED,
            max(confidence, 0.9),
            independent_count,
        )

    reported = by_type.get(SourceType.INDUSTRY_PUBLICATION, []) + by_type.get(
        SourceType.NEWS, []
    )
    if independent_count >= 2:
        return (
            BrandEvidenceClass.STRONG_EVIDENCE,
            RelationshipType.INDEPENDENT_REPORT,
            confidence,
            independent_count,
        )
    if reported:
        return (
            BrandEvidenceClass.STRONG_EVIDENCE
            if independent_count >= 1
            else BrandEvidenceClass.INDIRECT_EVIDENCE,
            RelationshipType.INDEPENDENT_REPORT,
            confidence,
            independent_count,
        )

    supplier_only = {e.source_type for e in items} <= SUPPLIER_SOURCES
    if supplier_only:
        # The supplier is the only one saying it. That is reportable, not proof.
        return (
            BrandEvidenceClass.SUPPLIER_REPORTED,
            RelationshipType.SUPPLIER_CLAIMED,
            min(confidence, 0.45),
            0,
        )

    return (
        BrandEvidenceClass.INDIRECT_EVIDENCE,
        RelationshipType.INDIRECT,
        min(confidence, 0.6),
        independent_count,
    )


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    stripped = url.split("://", 1)[-1]
    host = stripped.split("/", 1)[0].lower()
    return host[4:] if host.startswith("www.") else host


def dedupe(items: Iterable[Evidence]) -> list[Evidence]:
    """Drop evidence that repeats the same claim from the same URL."""
    seen: set[tuple[str, str | None]] = set()
    out: list[Evidence] = []
    for item in items:
        key = (item.claim.strip().lower(), _domain(item.source_url))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
