"""Quote normalization.

Vendor A quotes "bottle + pump + cap, Rp 12,000". Vendor B quotes three separate
lines. Comparing the headline numbers would rank B as cheaper by a third. This
module builds a comparable package for a requested component set, and refuses to
produce a number when a vendor has not priced the whole set.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Quote

#: Line-item aliases that mean the same physical component.
COMPONENT_ALIASES: dict[str, str] = {
    "bottle": "bottle", "botol": "bottle", "glass_bottle": "bottle", "flacon": "bottle",
    "pump": "pump", "sprayer": "pump", "spray": "pump", "atomizer": "pump",
    "cap": "cap", "tutup": "cap", "closure": "cap", "lid": "cap",
    "label": "label", "sticker": "label", "stiker": "label",
    "box": "box", "carton": "box", "dus": "box", "packaging": "box",
    "fragrance": "fragrance", "juice": "fragrance", "bibit": "fragrance",
    "concentrate": "fragrance", "parfum": "fragrance",
    "filling": "filling", "isi": "filling", "assembly": "filling",
    "package": "package", "set": "package", "bundle": "package", "all_in": "package",
    "complete": "package", "komplit": "package",
}

#: What a "package"/"set" line is understood to contain when a vendor bundles.
PACKAGE_CONTENTS: tuple[str, ...] = ("bottle", "pump", "cap")


def canonical_component(name: str) -> str:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    return COMPONENT_ALIASES.get(key, key)


def canonical_line_items(quote: Quote) -> dict[str, float]:
    """Line items keyed by canonical component, summing duplicates."""
    out: dict[str, float] = {}
    for name, price in quote.line_items.items():
        if price is None:
            continue
        out[canonical_component(name)] = out.get(canonical_component(name), 0.0) + float(price)
    return out


@dataclass
class PackageQuote:
    """A vendor's price for exactly the components asked for."""

    vendor_id: str
    quote_id: str
    currency: str
    components: tuple[str, ...]
    unit_price: float | None
    covered: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    bundled: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def comparable(self) -> bool:
        """True only when every requested component has a price."""
        return self.unit_price is not None and not self.missing


def normalize(quote: Quote, components: tuple[str, ...] = PACKAGE_CONTENTS) -> PackageQuote:
    """Price `quote` for `components`, or report what is missing."""
    items = canonical_line_items(quote)
    wanted = tuple(canonical_component(c) for c in components)
    notes: list[str] = []

    if "package" in items:
        # A bundle covers its documented contents. Anything the caller asked for
        # beyond that must still be priced separately.
        total = items["package"]
        covered = [c for c in wanted if c in PACKAGE_CONTENTS]
        missing = []
        for component in wanted:
            if component in PACKAGE_CONTENTS:
                continue
            if component in items:
                total += items[component]
                covered.append(component)
            else:
                missing.append(component)
        notes.append(
            "vendor quoted a bundle covering " + ", ".join(PACKAGE_CONTENTS)
        )
        return PackageQuote(
            vendor_id=quote.vendor_id,
            quote_id=quote.id,
            currency=quote.currency,
            components=wanted,
            unit_price=round(total, 4) if not missing else None,
            covered=tuple(covered),
            missing=tuple(missing),
            bundled=True,
            notes=notes,
        )

    covered = [c for c in wanted if c in items]
    missing = [c for c in wanted if c not in items]
    total = sum(items[c] for c in covered)
    return PackageQuote(
        vendor_id=quote.vendor_id,
        quote_id=quote.id,
        currency=quote.currency,
        components=wanted,
        unit_price=round(total, 4) if not missing else None,
        covered=tuple(covered),
        missing=tuple(missing),
        bundled=False,
        notes=notes,
    )


def comparable_set(
    quotes: list[Quote], components: tuple[str, ...] = PACKAGE_CONTENTS
) -> tuple[list[PackageQuote], list[PackageQuote]]:
    """Split quotes into (comparable, not-comparable) for the requested components."""
    normalized = [normalize(q, components) for q in quotes if q.superseded_by is None]
    by_currency: dict[str, int] = {}
    for pq in normalized:
        by_currency[pq.currency] = by_currency.get(pq.currency, 0) + 1

    comparable, incomparable = [], []
    for pq in normalized:
        if pq.comparable:
            comparable.append(pq)
        else:
            pq.notes.append("missing price for: " + ", ".join(pq.missing))
            incomparable.append(pq)

    if len(by_currency) > 1:
        # Never invent an FX rate. Compare only within the dominant currency.
        dominant = max(by_currency, key=lambda c: by_currency[c])
        held_back = [pq for pq in comparable if pq.currency != dominant]
        for pq in held_back:
            pq.notes.append(
                f"quoted in {pq.currency}; not compared against {dominant} without an FX rate"
            )
        comparable = [pq for pq in comparable if pq.currency == dominant]
        incomparable.extend(held_back)

    comparable.sort(key=lambda pq: pq.unit_price or float("inf"))
    return comparable, incomparable
