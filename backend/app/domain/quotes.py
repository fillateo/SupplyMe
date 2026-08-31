"""Quote normalization.

Vendor A quotes "bottle + pump + cap, Rp 12,000". Vendor B quotes three separate
lines. Comparing the headline numbers would rank B as cheaper by a third. This
module builds a comparable package for a requested component set, and refuses to
produce a number when a vendor has not priced the whole set.

**The component vocabulary belongs to the mission, not to this module.** What a
supplier calls a thing depends entirely on what is being made: `botol` and
`flacon` mean bottle to a perfume packer, `PCB` and `enclosure` mean nothing to
one and everything to an electronics assembler. So the words are taken from the
supply-chain plan the mission actually produced — see `ComponentVocabulary` —
and the only fixed vocabulary here is the handful of words that describe the
*shape* of a quote rather than the product.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .models import Quote, SupplyChainNode

#: The canonical name for "one price covering several components".
PACKAGE = "package"

#: Words a supplier uses to say "this one price covers several things". These
#: are properties of how quotations are written, not of any industry, which is
#: why they are the only component names this module knows on its own. A few
#: non-English ones are here because suppliers reply in their own language and
#: a bundle read as a component name silently becomes an uncomparable quote.
BUNDLE_WORDS: frozenset[str] = frozenset(
    {
        "package", "packages", "set", "sets", "bundle", "kit", "lot",
        "all_in", "all_inclusive", "all_included", "complete", "total",
        "komplit", "paket", "lengkap",       # id / ms
        "conjunto", "completo",              # es / pt
        "ensemble", "complet",               # fr
        "komplett",                          # de
        "套装", "全套",                        # zh
    }
)


def slug(name: str) -> str:
    """Fold a written component name to a comparison key."""
    return "_".join(name.strip().lower().replace("-", " ").replace("_", " ").split())


@dataclass(frozen=True)
class ComponentVocabulary:
    """Which supplier words mean which supply-chain node, for one mission.

    Built from the plan rather than from a table in this file. The planner names
    each node and lists the words a supplier in *that* industry would use for
    it, including the local market's own; this turns that into a lookup, so a
    reply saying `botol` and a reply saying `enclosure` are each resolved
    against the mission that asked the question.
    """

    aliases: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> ComponentVocabulary:
        """No plan to draw on: every word stands for itself."""
        return cls({})

    @classmethod
    def from_nodes(cls, nodes: Iterable[SupplyChainNode]) -> ComponentVocabulary:
        nodes = list(nodes)
        keys = {slug(node.key) for node in nodes}
        aliases: dict[str, str] = {}
        for node in nodes:
            canonical = slug(node.key)
            aliases[canonical] = canonical
            for word in (node.name, *node.aliases):
                key = slug(word)
                # A node key always wins over another node's alias, and a bundle
                # word is never a component however a planner labelled it.
                if not key or key in keys or key in BUNDLE_WORDS:
                    continue
                aliases.setdefault(key, canonical)
        return cls(aliases)

    def canonical(self, name: str) -> str:
        key = slug(name)
        if key in BUNDLE_WORDS:
            return PACKAGE
        return self.aliases.get(key, key)

    def canonical_line_items(self, quote: Quote) -> dict[str, float]:
        """Line items keyed by canonical component, summing duplicates."""
        out: dict[str, float] = {}
        for name, price in quote.line_items.items():
            if price is None:
                continue
            key = self.canonical(name)
            out[key] = out.get(key, 0.0) + float(price)
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
    #: Components this price also covers that nobody asked for. The number is
    #: still real, but it buys more than the comparison is about.
    extras: tuple[str, ...] = ()
    bundled: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def comparable(self) -> bool:
        """True only when every requested component has a price."""
        return self.unit_price is not None and not self.missing


def normalize(
    quote: Quote,
    components: tuple[str, ...],
    *,
    vocabulary: ComponentVocabulary | None = None,
) -> PackageQuote:
    """Price `quote` for `components`, or report what is missing."""
    vocab = vocabulary or ComponentVocabulary.empty()
    items = vocab.canonical_line_items(quote)
    wanted = tuple(dict.fromkeys(vocab.canonical(c) for c in components))
    notes: list[str] = []

    if PACKAGE not in items:
        covered = [c for c in wanted if c in items]
        missing = [c for c in wanted if c not in items]
        total = sum(items[c] for c in covered)
        return PackageQuote(
            vendor_id=quote.vendor_id, quote_id=quote.id, currency=quote.currency,
            components=wanted, unit_price=round(total, 4) if not missing else None,
            covered=tuple(covered), missing=tuple(missing), bundled=False, notes=notes,
        )

    # A bundled line. What it contains is the supplier's statement, not ours to
    # assume — an earlier version assumed a fixed three-component package, which
    # was only ever true of the vertical it was written for and quietly made
    # every bundle in any other one uncomparable.
    contents = tuple(dict.fromkeys(vocab.canonical(c) for c in quote.bundle_covers))
    if not contents:
        notes.append(
            "supplier quoted one bundled price without saying what it covers; "
            "ask before comparing it"
        )
        return PackageQuote(
            vendor_id=quote.vendor_id, quote_id=quote.id, currency=quote.currency,
            components=wanted, unit_price=None, covered=(), missing=wanted,
            bundled=True, notes=notes,
        )

    total = items[PACKAGE]
    covered = [c for c in wanted if c in contents]
    missing: list[str] = []
    for component in wanted:
        if component in contents:
            continue
        if component in items:
            total += items[component]
            covered.append(component)
        else:
            missing.append(component)

    extras = tuple(c for c in contents if c not in wanted)
    notes.append("supplier quoted a bundle covering " + ", ".join(contents))
    if extras:
        notes.append(
            "this price also covers " + ", ".join(extras) + ", which was not asked for here"
        )
    return PackageQuote(
        vendor_id=quote.vendor_id, quote_id=quote.id, currency=quote.currency,
        components=wanted, unit_price=round(total, 4) if not missing else None,
        covered=tuple(covered), missing=tuple(missing), extras=extras,
        bundled=True, notes=notes,
    )


def comparable_set(
    quotes: list[Quote],
    components: tuple[str, ...],
    *,
    vocabulary: ComponentVocabulary | None = None,
) -> tuple[list[PackageQuote], list[PackageQuote]]:
    """Split quotes into (comparable, not-comparable) for the requested components."""
    normalized = [
        normalize(q, components, vocabulary=vocabulary)
        for q in quotes
        if q.superseded_by is None
    ]
    by_currency: dict[str, int] = {}
    for pq in normalized:
        by_currency[pq.currency] = by_currency.get(pq.currency, 0) + 1

    comparable, incomparable = [], []
    for pq in normalized:
        if pq.comparable:
            comparable.append(pq)
        else:
            if pq.missing:
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

    comparable.sort(key=lambda pq: pq.unit_price if pq.unit_price is not None else float("inf"))
    return comparable, incomparable
