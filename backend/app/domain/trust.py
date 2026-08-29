"""Explainable confidence, one dimension at a time.

There is no "AI trust score" here. Each dimension is a pure function of the
evidence on file, and each one returns the sentence that explains it. If a
number cannot be explained, it is not produced.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .evidence import confidence_for
from .models import (
    BrandEvidenceClass,
    BrandRelationship,
    Conflict,
    ConflictStatus,
    Evidence,
    Provenance,
    Vendor,
)

DIMENSIONS = (
    "identity",
    "capability",
    "moq",
    "pricing",
    "lead_time",
    "brand_evidence",
    "contact",
)


@dataclass(frozen=True)
class Dimension:
    name: str
    score: float
    explanation: str


@dataclass(frozen=True)
class TrustProfile:
    dimensions: tuple[Dimension, ...]
    overall: float

    def as_dict(self) -> dict[str, object]:
        return {
            "dimensions": [
                {"name": d.name, "score": d.score, "explanation": d.explanation}
                for d in self.dimensions
            ],
            "overall": self.overall,
        }

    def get(self, name: str) -> Dimension:
        for dimension in self.dimensions:
            if dimension.name == name:
                return dimension
        return Dimension(name, 0.0, "not evaluated")


#: How much each provenance state is worth as field-level confidence.
PROVENANCE_SCORE: dict[Provenance, float] = {
    Provenance.VERIFIED: 0.95,
    Provenance.DIRECT_QUOTE: 0.90,
    Provenance.PUBLICLY_LISTED: 0.70,
    Provenance.SUPPLIER_REPORTED: 0.60,
    Provenance.INFERRED: 0.35,
    Provenance.ESTIMATED: 0.30,
    Provenance.CONFLICTING: 0.25,
    Provenance.UNKNOWN: 0.0,
}


def _identity(vendor: Vendor) -> Dimension:
    signals: list[str] = []
    score = 0.0
    if vendor.domain or vendor.website:
        score += 0.35
        signals.append("own website")
    if vendor.place_id:
        score += 0.30
        signals.append("Google Maps listing")
    if vendor.phone:
        score += 0.15
        signals.append("published phone")
    if vendor.address:
        score += 0.15
        signals.append("street address")
    if vendor.legal_name:
        score += 0.05
        signals.append("legal name")
    if not signals:
        return Dimension("identity", 0.0, "no identifying signal beyond a name")
    return Dimension(
        "identity", round(min(score, 1.0), 4), "confirmed by " + ", ".join(signals)
    )


def _capability(vendor: Vendor, evidence: Sequence[Evidence]) -> Dimension:
    supporting = [e for e in evidence if e.field == "capabilities" or e.field is None]
    if not vendor.capabilities:
        return Dimension("capability", 0.0, "no capability evidence collected")
    score = confidence_for(supporting) if supporting else 0.3
    return Dimension(
        "capability",
        round(score, 4),
        f"{len(vendor.capabilities)} capabilities across {len(supporting)} source(s)",
    )


def _field_dimension(
    name: str, vendor: Vendor, field: str, conflicts: Sequence[Conflict]
) -> Dimension:
    fact = vendor.fact(field)
    open_conflict = any(
        c.field == field and c.status is not ConflictStatus.RESOLVED for c in conflicts
    )
    if not fact.known:
        return Dimension(name, 0.0, f"{field.replace('_', ' ')} unknown")
    base = PROVENANCE_SCORE.get(fact.provenance, 0.0)
    score = min(base, fact.confidence) if fact.confidence else base
    if open_conflict:
        score = min(score, PROVENANCE_SCORE[Provenance.CONFLICTING])
        return Dimension(
            name, round(score, 4), f"sources disagree on {field.replace('_', ' ')}"
        )
    return Dimension(
        name,
        round(score, 4),
        f"{fact.provenance.value.replace('_', ' ')} from {len(fact.evidence_ids)} source(s)",
    )


BRAND_CLASS_SCORE: dict[BrandEvidenceClass, float] = {
    BrandEvidenceClass.VERIFIED: 0.95,
    BrandEvidenceClass.STRONG_EVIDENCE: 0.80,
    BrandEvidenceClass.INDIRECT_EVIDENCE: 0.50,
    BrandEvidenceClass.SUPPLIER_REPORTED: 0.35,
    BrandEvidenceClass.UNVERIFIED: 0.15,
    BrandEvidenceClass.NO_PUBLIC_EVIDENCE: 0.10,
}


def _brand(relationships: Sequence[BrandRelationship]) -> Dimension:
    if not relationships:
        return Dimension("brand_evidence", 0.0, "no brand relationship claimed")
    best = max(relationships, key=lambda r: BRAND_CLASS_SCORE.get(r.classification, 0.0))
    score = BRAND_CLASS_SCORE.get(best.classification, 0.0)
    label = best.classification.value.replace("_", " ")
    return Dimension(
        "brand_evidence",
        round(score, 4),
        f"strongest claim ({best.brand}) is {label}"
        + (
            f", {best.independent_sources} independent source(s)"
            if best.independent_sources
            else ", no independent source found"
        ),
    )


def _contact(vendor: Vendor) -> Dimension:
    if vendor.email and vendor.phone:
        return Dimension("contact", 0.95, "email and phone on file")
    if vendor.email:
        return Dimension("contact", 0.7, "email only")
    if vendor.phone:
        return Dimension("contact", 0.55, "phone only")
    return Dimension("contact", 0.0, "no usable contact route")


def profile(
    vendor: Vendor,
    evidence: Sequence[Evidence],
    relationships: Sequence[BrandRelationship] = (),
    conflicts: Sequence[Conflict] = (),
) -> TrustProfile:
    dimensions = (
        _identity(vendor),
        _capability(vendor, evidence),
        _field_dimension("moq", vendor, "moq", conflicts),
        _field_dimension("pricing", vendor, "unit_price", conflicts),
        _field_dimension("lead_time", vendor, "lead_time_days", conflicts),
        _brand(relationships),
        _contact(vendor),
    )
    # Overall is the mean of the dimensions that were actually evaluated, so a
    # vendor is not punished for a brand claim it never made.
    evaluated = [d for d in dimensions if d.explanation != "no brand relationship claimed"]
    overall = round(sum(d.score for d in evaluated) / len(evaluated), 4) if evaluated else 0.0
    return TrustProfile(dimensions=dimensions, overall=overall)
