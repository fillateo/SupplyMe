"""Deterministic vendor scoring.

Gemini never says "vendor A is 92/100". It supplies structured facts; this
module turns those facts into a number, and every component of that number
carries the sentence that produced it. Change the weights and the explanation
changes with it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .models import Conflict, ScoringWeights, SearchScope, Vendor
from .numbers import as_number
from .quotes import PackageQuote
from .trust import TrustProfile

#: A vendor missing this many priced components cannot be ranked on price.
UNPRICED_PENALTY_NOTE = "no comparable quote; price component scored 0"


@dataclass
class Component:
    name: str
    weight: float
    raw: float           # 0..1 before weighting
    explanation: str

    @property
    def contribution(self) -> float:
        return round(self.weight * self.raw, 4)


@dataclass
class VendorScore:
    vendor_id: str
    vendor_name: str
    total: float                      # 0..100
    components: list[Component] = field(default_factory=list)
    disqualified: bool = False
    rejection_reasons: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "vendor_id": self.vendor_id,
            "vendor_name": self.vendor_name,
            "total": self.total,
            "disqualified": self.disqualified,
            "rejection_reasons": self.rejection_reasons,
            "strengths": self.strengths,
            "components": [
                {
                    "name": c.name,
                    "weight": round(c.weight, 4),
                    "raw": round(c.raw, 4),
                    "contribution": c.contribution,
                    "explanation": c.explanation,
                }
                for c in self.components
            ],
        }


def _price_component(
    weight: float, quote: PackageQuote | None, cheapest: float | None
) -> Component:
    if quote is None or quote.unit_price is None or cheapest is None:
        return Component("price", weight, 0.0, UNPRICED_PENALTY_NOTE)
    if quote.unit_price <= 0:
        return Component("price", weight, 0.0, "quoted price is not usable")
    # Cheapest scores 1.0; twice the cheapest scores 0.5; linear in ratio.
    ratio = cheapest / quote.unit_price
    return Component(
        "price",
        weight,
        round(min(ratio, 1.0), 4),
        f"{quote.currency} {quote.unit_price:,.0f}/unit vs best {quote.currency} {cheapest:,.0f}",
    )


def _moq_component(weight: float, vendor: Vendor, needed: int | None) -> Component:
    fact = vendor.moq
    moq = as_number(fact.value) if fact.known else None
    if moq is None or needed is None:
        return Component("moq_fit", weight, 0.0, "MOQ unknown")
    if needed <= 0:
        return Component("moq_fit", weight, 0.0, "order quantity unknown")
    if moq <= needed:
        return Component(
            "moq_fit", weight, 1.0, f"MOQ {moq:g} fits an order of {needed:g}"
        )
    overshoot = moq / needed
    if overshoot >= 4:
        return Component(
            "moq_fit", weight, 0.0, f"MOQ {moq:g} is {overshoot:.1f}x the {needed:g} needed"
        )
    # 1x -> 1.0 down to 4x -> 0.0
    raw = max(0.0, 1.0 - (overshoot - 1.0) / 3.0)
    return Component(
        "moq_fit", weight, round(raw, 4), f"MOQ {moq:g} exceeds the {needed:g} needed"
    )


def _capability_component(
    weight: float, vendor: Vendor, required_nodes: Sequence[str], trust: TrustProfile
) -> Component:
    if not required_nodes:
        covered = 1.0
        detail = "no specific component requested"
    else:
        hits = [n for n in required_nodes if n in vendor.node_keys]
        covered = len(hits) / len(required_nodes)
        detail = f"covers {len(hits)}/{len(required_nodes)} requested component(s)"
    confidence = trust.get("capability").score
    raw = covered * (0.5 + 0.5 * confidence)
    return Component(
        "capability",
        weight,
        round(raw, 4),
        f"{detail}; capability evidence {confidence:.0%}",
    )


def _lead_time_component(weight: float, vendor: Vendor, target_days: int | None) -> Component:
    fact = vendor.lead_time_days
    days = as_number(fact.value, unit="days") if fact.known else None
    if days is None:
        return Component("lead_time", weight, 0.0, "lead time unknown")
    if target_days is None:
        raw = 1.0 if days <= 30 else max(0.0, 1.0 - (days - 30) / 60)
        return Component("lead_time", weight, round(raw, 4), f"{days:g} days quoted")
    if days <= target_days:
        return Component(
            "lead_time", weight, 1.0, f"{days:g} days meets the {target_days}-day target"
        )
    raw = max(0.0, 1.0 - (days - target_days) / max(target_days, 1))
    return Component(
        "lead_time", weight, round(raw, 4), f"{days:g} days misses the {target_days}-day target"
    )


def _evidence_component(weight: float, trust: TrustProfile) -> Component:
    return Component(
        "evidence",
        weight,
        round(trust.overall, 4),
        f"overall evidence confidence {trust.overall:.0%}",
    )


def _logistics_component(
    weight: float,
    vendor: Vendor,
    market: str | None,
    location: str | None = None,
    scope: SearchScope = SearchScope.COUNTRY,
) -> Component:
    """How well this supplier's location answers the question that was asked.

    The same factory is a different proposition under each scope. Someone who
    asked for suppliers in their own city can drive over and look at a sample
    before committing, so a supplier three provinces away is a worse answer even
    when it is the better factory — and someone who chose global scope has
    already accepted importing, so charging them for it twice is wrong.
    """
    if not vendor.country:
        return Component("logistics", weight, 0.3, "location unknown")

    in_market = bool(market) and vendor.country.strip().lower() == market.strip().lower()
    in_city = bool(location) and _same_place(vendor.city, location)

    if scope is SearchScope.CITY:
        if in_city:
            raw, detail = 1.0, f"in {vendor.city} — the city you asked for"
        elif in_market:
            raw, detail = 0.7, f"in {vendor.country}, outside {location}"
        else:
            raw, detail = 0.35, f"located in {vendor.country}; import required"
    elif scope is SearchScope.GLOBAL:
        # Importing is the premise, not a penalty. Distance still costs
        # something, so a domestic supplier keeps a modest edge.
        raw = 1.0 if in_market else 0.8
        detail = (
            f"located in the target market ({vendor.country})" if in_market
            else f"located in {vendor.country}; importing was accepted"
        )
    elif in_market:
        raw, detail = 1.0, f"located in the target market ({vendor.country})"
    else:
        raw, detail = 0.5, f"located in {vendor.country}; import required"

    if vendor.city and vendor.city not in detail:
        detail += f" — {vendor.city}"
    return Component("logistics", weight, raw, detail)


def _same_place(left: str | None, right: str | None) -> bool:
    """City names travel with their province attached: "Bekasi, Jawa Barat"."""
    a = (left or "").strip().lower()
    b = (right or "").strip().lower()
    if not a or not b:
        return False
    return a == b or a in b or b in a


def score_vendor(
    vendor: Vendor,
    *,
    weights: ScoringWeights,
    trust: TrustProfile,
    quote: PackageQuote | None = None,
    cheapest_price: float | None = None,
    quantity: int | None = None,
    target_lead_days: int | None = None,
    required_nodes: Sequence[str] = (),
    market: str | None = None,
    location: str | None = None,
    scope: SearchScope = SearchScope.COUNTRY,
    conflicts: Sequence[Conflict] = (),
) -> VendorScore:
    w = weights.as_dict()
    components = [
        _price_component(w["price"], quote, cheapest_price),
        _moq_component(w["moq_fit"], vendor, quantity),
        _capability_component(w["capability"], vendor, required_nodes, trust),
        _lead_time_component(w["lead_time"], vendor, target_lead_days),
        _evidence_component(w["evidence"], trust),
        _logistics_component(w["logistics"], vendor, market, location, scope),
    ]
    total = round(sum(c.contribution for c in components) * 100, 2)

    reasons: list[str] = []
    disqualified = False
    moq_value = as_number(vendor.moq.value) if vendor.moq.known else None
    if moq_value is not None and quantity is not None and moq_value > quantity * 4:
        disqualified = True
        reasons.append(
            f"MOQ {moq_value:g} against a first batch of {quantity} — "
            "good supplier at scale, wrong fit for this launch"
        )
    if not vendor.email and not vendor.phone:
        disqualified = True
        reasons.append("no contact route found, so nothing can be confirmed")
    for conflict in conflicts:
        if conflict.status.value == "unresolvable":
            reasons.append(f"unresolved disagreement on {conflict.field}")

    strengths = [
        c.explanation for c in components if c.raw >= 0.8 and c.name != "evidence"
    ]
    return VendorScore(
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        total=total,
        components=components,
        disqualified=disqualified,
        rejection_reasons=reasons,
        strengths=strengths,
    )


def apply_priorities(weights: ScoringWeights, priorities: Sequence[str]) -> ScoringWeights:
    """Shift weights from a plain-language priority such as "quality over price".

    Deliberately blunt: a priority moves weight between named buckets by a fixed
    step so the effect is auditable, rather than being re-derived by the model.
    """
    values = weights.model_dump()
    step = 0.08
    for priority in priorities:
        p = priority.lower()
        if any(k in p for k in ("quality", "evidence", "trust", "reliab")):
            values["evidence"] += step
            values["capability"] += step
            values["price"] = max(0.02, values["price"] - step)
        elif any(k in p for k in ("cheap", "price", "cost", "budget")):
            values["price"] += step
            values["evidence"] = max(0.02, values["evidence"] - step / 2)
            values["lead_time"] = max(0.02, values["lead_time"] - step / 2)
        elif any(k in p for k in ("fast", "speed", "lead time", "urgent", "quick")):
            values["lead_time"] += step
            values["price"] = max(0.02, values["price"] - step)
        elif any(k in p for k in ("local", "nearby", "domestic", "logistic", "shipping")):
            values["logistics"] += step
            values["price"] = max(0.02, values["price"] - step / 2)
        elif any(k in p for k in ("small batch", "low moq", "minimize risk", "pilot")):
            values["moq_fit"] += step
            values["price"] = max(0.02, values["price"] - step / 2)
    return ScoringWeights(**values).normalized()
