"""Vendor identity resolution.

Discovery returns the same business several times under different names — a
Maps listing, a directory row, the company's own site. Merging them wrongly is
worse than not merging: two different factories collapsed into one record would
attach one vendor's quote to another's capabilities. So the rule is a strong
signal (domain, phone, place id) merges outright; name similarity alone only
merges when the locality also agrees.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Vendor

#: Legal-form and filler tokens that carry no identifying information in
#: Indonesian and common international company names.
_NOISE = {
    "pt", "cv", "ud", "tbk", "persero", "inc", "llc", "ltd", "co", "corp",
    "company", "limited", "gmbh", "sa", "bv", "sdn", "bhd", "group", "indonesia",
    "international", "global", "the", "and",
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_PHONE_STRIP = re.compile(r"[^0-9]")


def normalize_name(name: str) -> str:
    tokens = [t for t in _NON_ALNUM.sub(" ", name.lower()).split() if t and t not in _NOISE]
    return " ".join(tokens)


def name_tokens(name: str) -> frozenset[str]:
    return frozenset(normalize_name(name).split())


def normalize_domain(value: str | None) -> str | None:
    if not value:
        return None
    host = value.strip().lower()
    host = host.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def normalize_phone(value: str | None, default_country: str = "62") -> str | None:
    """Reduce a phone number to comparable digits.

    Indonesian numbers appear as `021-...`, `+62 21 ...` and `62...` in the same
    dataset; without this they never match.
    """
    if not value:
        return None
    digits = _PHONE_STRIP.sub("", value)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = default_country + digits[1:]
    return digits[-11:] if len(digits) > 11 else digits


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True)
class MatchResult:
    is_same: bool
    confidence: float
    reason: str


def compare(left: Vendor, right: Vendor) -> MatchResult:
    """Decide whether two vendor records describe the same business."""
    ld, rd = normalize_domain(left.domain or left.website), normalize_domain(
        right.domain or right.website
    )
    if ld and rd and ld == rd:
        return MatchResult(True, 0.98, f"same domain ({ld})")

    if left.place_id and right.place_id:
        if left.place_id == right.place_id:
            return MatchResult(True, 0.97, "same Google Maps place id")
        # Two distinct place ids is positive evidence they are *different* sites.
        return MatchResult(False, 0.9, "different Google Maps place ids")

    lp, rp = normalize_phone(left.phone), normalize_phone(right.phone)
    if lp and rp and lp == rp:
        return MatchResult(True, 0.92, "same phone number")

    similarity = jaccard(name_tokens(left.name), name_tokens(right.name))
    if similarity >= 0.85:
        same_city = bool(left.city and right.city and left.city.lower() == right.city.lower())
        if same_city:
            return MatchResult(True, 0.85, f"near-identical name in {left.city}")
        if not left.city or not right.city:
            return MatchResult(True, 0.7, "near-identical name, locality unknown")
        return MatchResult(False, 0.6, "same name, different city")

    if similarity >= 0.6:
        return MatchResult(False, similarity, "similar name, no corroborating signal")

    return MatchResult(False, 0.0, "no matching identifier")


def merge(primary: Vendor, other: Vendor) -> Vendor:
    """Fold `other` into `primary`, preferring values that already exist.

    Known facts win over unknown ones; a fact already backed by evidence is
    never overwritten by one that is not.
    """
    for field in (
        "legal_name", "domain", "website", "address", "country", "city",
        "phone", "email", "place_id", "lat", "lng",
    ):
        if getattr(primary, field, None) in (None, "") and getattr(other, field, None):
            setattr(primary, field, getattr(other, field))

    if (
        other.name
        and normalize_name(other.name) != normalize_name(primary.name)
        and other.name not in primary.aliases
    ):
        primary.aliases.append(other.name)
    for alias in other.aliases:
        if alias not in primary.aliases and normalize_name(alias) != normalize_name(primary.name):
            primary.aliases.append(alias)

    for field in ("node_keys", "capabilities", "evidence_ids", "brand_relationship_ids"):
        merged = list(dict.fromkeys(getattr(primary, field) + getattr(other, field)))
        setattr(primary, field, merged)

    for field in (
        "moq", "unit_price", "lead_time_days", "sample_lead_time_days",
        "customization", "payment_terms",
    ):
        mine, theirs = getattr(primary, field), getattr(other, field)
        if theirs.known and (not mine.known or theirs.confidence > mine.confidence):
            setattr(primary, field, theirs)

    primary.version += 1
    return primary.touch()


def resolve(candidate: Vendor, existing: list[Vendor]) -> tuple[Vendor, MatchResult | None]:
    """Return the record to persist: either a merged existing vendor or the new one."""
    best: tuple[Vendor, MatchResult] | None = None
    for vendor in existing:
        result = compare(candidate, vendor)
        if result.is_same and (best is None or result.confidence > best[1].confidence):
            best = (vendor, result)
    if best is None:
        return candidate, None
    return merge(best[0], candidate), best[1]
