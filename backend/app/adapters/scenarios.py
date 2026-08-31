"""Other products the same Los Angeles suppliers really make.

`SUPPLYME_MOCK` replays one recorded mission — a 50ml eau de parfum in Los
Angeles — and a console showing that same mission five times reads as broken.
These re-skin the replay into a different brief, so the list looks like a console
somebody has been using.

Which one a press gets is decided by the objective typed into it, in
`for_objective` at the bottom of this file. Ask for fragrance and the recorded
mission plays under its own brief; ask for a serum or a candle and it plays as
one of these. That is the whole of the fix for the thing this file first shipped
doing, which was to rotate blindly and answer a perfume brief with a vitamin C
serum.

`FRAGRANCE` renames nothing, because it is the brief the run was for. What it
adds is two suppliers for the two components that run closed on nothing — a
glass flacon and a pump and collar — found the same way as everybody else's
specialists: a real company at its real domain, one sentence off its own page,
and nothing claimed past it. They arrive as `discovered`, with no minimum, no
price and no lead time except where their own site publishes one, because nobody
wrote to them. The closing panel's sentence about finding no supplier for those
two goes with them, since leaving it would have the console contradicting its
own supplier list.

**The companies are real and so are their facts.** Every supplier below is a
real business in or near Los Angeles, at its real domain, and the claims
attached to them were read off their own pages — Lumient's 120-unit minimum and
INTI's hand-pouring are quoted from the sites, not invented. The twelve
suppliers in the recording are carried over as they are, because a carton
printer, a glass distributor and a contract filler in Los Angeles serve skincare
and candles as readily as they serve fragrance; that is what those companies do.

What a scenario changes is the *brief* and the vocabulary derived from it: the
objective, the supply-chain node names, and the fields a model wrote about the
product. What it never touches is primary source material — an evidence excerpt,
a source URL, an email body, a supplier's quoted price stay exactly as recorded,
because those are somebody's actual words and rewriting them would put sentences
in a real company's mouth.

So a re-skinned mission is a real supply chain, really researched, under a brief
it was not researched for; the fragrance one is that supply chain under the brief
it *was*. That is the honest description of both, and `replay_of` on the mission
says which recording it came from either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NodeSkin:
    """What a supply-chain node is called in this scenario."""

    key: str
    name: str
    description: str
    aliases: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtraVendor:
    """A real Los Angeles supplier specific to this scenario.

    Built by overwriting the identity fields of a recorded supplier document, so
    the shape is always whatever the current schema is rather than a hand-written
    dictionary that drifts. `claim` and `excerpt` are quoted from the company's
    own site; `source_url` is the page they were read from.
    """

    name: str
    domain: str
    email: str | None
    city: str
    claim: str
    excerpt: str
    source_url: str
    field_name: str = "moq"
    value: str = ""
    #: Which components this supplier is a candidate for, in *this* brief's key
    #: space — the names after the skin, since nothing rewrites these. Without
    #: them a supplier inherits the template's components and the console files
    #: a candle pourer under folding cartons.
    node_keys: tuple[str, ...] = ()
    #: Read off the same pages the excerpt came from. Everything else about the
    #: supplier — minimum, price, lead time — stays unknown, because nobody
    #: asked them.
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    key: str
    objective: str
    product: str
    unit_spec: str
    quantity: int
    priorities: tuple[str, ...]
    success_criteria: tuple[str, ...]
    #: Recorded node key -> what it becomes here. Keys are rewritten wherever
    #: they are referenced, so a quote's `node_key` still resolves.
    nodes: dict[str, NodeSkin]
    #: Words that mean somebody is asking for *this* brief. Matched against the
    #: objective that was typed, so a replay answers the question on screen when
    #: it holds an answer to it.
    triggers: tuple[str, ...] = ()
    #: Vocabulary for fields a model wrote about the product. Never applied to
    #: excerpts, URLs, email bodies or quoted prices.
    terms: dict[str, str] = field(default_factory=dict)
    extra_vendors: tuple[ExtraVendor, ...] = ()
    #: How many of the recorded suppliers this brief carries. Fewer suppliers is
    #: a different-looking mission and a different email count.
    vendor_limit: int | None = None


FRAGRANCE = Scenario(
    key="eau-de-parfum",
    # Every brief field below is deliberately empty. This *is* the recorded
    # mission's brief, and the recording already carries the objective, the
    # product, the quantity and the success criteria that were really worked on;
    # `as_dict` drops what is empty, so those recorded values stand. Writing
    # them out again here would only be a second copy to drift from the
    # snapshot.
    objective="",
    product="",
    unit_spec="",
    quantity=0,
    priorities=(),
    success_criteria=(),
    # Nothing is renamed either: a flacon is called a flacon here because that
    # is the component the run went looking for.
    nodes={},
    triggers=(
        "parfum",
        "perfume",
        "cologne",
        "fragrance",
        "flacon",
        "scent",
        "atomiser",
        "atomizer",
    ),
    # The two components the recorded run closed on nothing. The suppliers below
    # exist now, so the closing panel cannot go on saying none were found — but
    # neither was contacted and neither quoted a price, and the replacement text
    # says exactly that. Model-written prose about the product, which is the only
    # kind of sentence a brief is allowed to touch.
    terms={
        (
            "No viable suppliers were found for the custom glass flacon "
            "(custom-glass-bottle) or the pump and collar (pump-and-collar) "
            "components."
        ): (
            "The custom glass flacon (custom-glass-bottle) and the pump and collar "
            "(pump-and-collar) have candidates read off their own websites and "
            "nothing further: O.Berk West publishes no minimum or price for its "
            "crimp-finish fragrance glass, and APackaging Group lists a "
            "10,000-piece minimum against the 1,000 needed."
        ),
        (
            "no viable suppliers were found for the custom glass flacon or the "
            "pump and collar"
        ): (
            "neither the custom glass flacon nor the pump and collar has a priced "
            "supplier (O.Berk West in Cerritos and APackaging Group in Azusa were "
            "read off their own sites, and neither was contacted)"
        ),
        (
            "Identify and contact alternative suppliers for the custom glass flacon "
            "and the pump and collar components, as no viable options were found."
        ): (
            "Contact O.Berk West about the crimp-finish flacon, ask APackaging Group "
            "whether the 10,000-piece pump minimum moves for a first run, and find a "
            "second pump source that will quote 1,000 units."
        ),
    },
    extra_vendors=(
        ExtraVendor(
            name="O.Berk West",
            domain="oberk.com",
            email=None,
            city="Cerritos",
            claim=(
                "Stocks glass fragrance bottles with a crimp-on finish that takes "
                "standard fine-mist sprayers and overcaps, from its West Coast "
                "warehouse in Cerritos, Los Angeles County."
            ),
            excerpt=(
                "O.Berk now offers a collection of up-scale, elegantly designed glass "
                "bottles that fit your beauty and fragrance needs. These glass bottles "
                "feature a crimp-on finish that accepts a wide range of crimp on "
                "fine-mist sprayers and over cap."
            ),
            source_url="https://www.oberk.com/glass-fragrance-bottle",
            field_name="customization",
            value="Crimp-on finish glass, taking standard fine-mist sprayers and overcaps",
            node_keys=("custom-glass-bottle",),
            capabilities=(
                "glass fragrance bottles",
                "crimp-on neck finish",
                "fine-mist sprayers",
                "overcaps",
                "bottle decorating",
            ),
        ),
        ExtraVendor(
            name="APackaging Group",
            domain="apackaginggroup.com",
            email=None,
            city="Azusa",
            claim=(
                "Lists a 10,000-piece minimum, subject to change, on the 808-series "
                "crimp perfume sprayer pump it stocks in Azusa, Los Angeles County."
            ),
            excerpt="MOQ (Subject to Change): 10,000 pcs",
            source_url="https://apackaginggroup.com/products/perfume-sprayer-808-series-0-1cc",
            field_name="moq",
            value="10000",
            node_keys=("pump-and-collar",),
            capabilities=(
                "crimp perfume sprayer pumps",
                "crimpless perfume sprayer pumps",
                "15mm to 20mm ferrule",
                "0.10ml dosage",
            ),
        ),
    ),
    vendor_limit=None,
)


SKINCARE = Scenario(
    key="skincare-serum",
    objective=(
        "Launch a 30ml vitamin C face serum in Los Angeles. 1,000 units to start. "
        "Amber glass dropper bottle, child-resistant dropper, folding carton, and "
        "contract filling with cold-fill capability for an ascorbic acid formula."
    ),
    product="vitamin C face serum",
    unit_spec="30ml amber glass dropper bottle",
    quantity=1000,
    priorities=(
        "cold-fill capability for ascorbic acid",
        "amber glass for UV protection",
        "child-resistant dropper",
        "folding carton",
        "contract filling",
    ),
    success_criteria=(
        "Identify contract fillers in Los Angeles able to handle an anhydrous vitamin C serum",
        "Confirm amber dropper bottle minimums at 1,000 units",
        "Get written lead times from at least three suppliers",
    ),
    triggers=(
        "serum",
        "skincare",
        "skin care",
        "vitamin c",
        "ascorbic",
        "dropper",
        "moisturiser",
        "moisturizer",
        "lotion",
        "cream",
    ),
    nodes={
        "custom-glass-bottle": NodeSkin(
            key="amber-dropper-bottle",
            name="Amber Glass Dropper Bottle",
            description=(
                "30ml amber glass bottle with an 18mm neck finish, for actives. "
                "UV-sensitive"
            ),
            aliases=("amber serum bottle", "boston round 30ml", "UV glass dropper"),
            search_terms=(
                "amber glass dropper bottle 30ml wholesale",
                "cosmetic amber bottle supplier Los Angeles",
            ),
        ),
        "pump-and-collar": NodeSkin(
            key="dropper-assembly",
            name="Dropper and Collar Assembly",
            description=(
                "Glass pipette, bulb and matching collar, sized to the bottle's "
                "neck finish."
            ),
            aliases=("glass pipette", "child-resistant dropper", "18mm dropper"),
            search_terms=("cosmetic glass dropper supplier", "child resistant dropper assembly"),
        ),
        "perfume-cap": NodeSkin(
            key="serum-closure",
            name="Serum Closure",
            description="Overcap and tamper-evident seal matched to the dropper assembly.",
            aliases=("overcap", "tamper seal"),
            search_terms=("cosmetic overcap supplier", "tamper evident seal cosmetics"),
        ),
        "fragrance-juice": NodeSkin(
            key="serum-formulation",
            name="Serum Formulation (Bulk)",
            description=(
                "Bulk anhydrous vitamin C formulation, stability-tested for an "
                "18-month shelf life."
            ),
            aliases=("bulk serum", "ascorbic acid formulation"),
            search_terms=(
                "private label vitamin C serum formulation",
                "cosmetic formulator Los Angeles",
            ),
        ),
        "folding-carton": NodeSkin(
            key="folding-carton",
            name="Serum Carton",
            description=(
                "Printed folding carton with an insert that holds the dropper "
                "bottle upright."
            ),
            aliases=(
                "serum box",
                "folding carton",
                "SBS carton",
            ),
            search_terms=(
                "cosmetic folding carton printer Los Angeles",
                "skincare carton with insert",
            ),
        ),
        "contract-filling-assembly": NodeSkin(
            key="contract-filling-assembly",
            name="Contract Filling and Assembly",
            description=(
                "Cold filling, dropper insertion, labelling and cartoning under "
                "cosmetic GMP."
            ),
            aliases=("contract filler", "cosmetic co-packer"),
            search_terms=("cosmetic contract filling Los Angeles", "serum filling private label"),
        ),
    },
    terms={
        "50ml eau de parfum": "30ml vitamin C serum",
        "eau de parfum": "vitamin C serum",
        "custom glass flacon": "amber dropper bottle",
        "fragrance juice": "serum formulation",
        "fragrance bulk": "serum formulation",
        "pump and collar": "dropper and collar",
        "folding cartons": "serum cartons",
        "folding carton": "serum carton",
        "perfume carton": "serum carton",
        "perfume cap": "serum closure",
        "perfume": "serum",
        "fragrance": "skincare",
        "flacon": "dropper bottle",
        "FEA 15 pump": "18mm dropper",
    },
    extra_vendors=(
        ExtraVendor(
            name="Velocity Pro Pack",
            domain="velocitypropack.com",
            email=None,
            city="Los Angeles",
            claim=(
                "Offers contract manufacturing, filling and custom labelling for in Los "
                "skincare Angeles."
            ),
            excerpt=(
                "We offer packaging design, assembly, and custom labeling solutions "
                "compliant with industry standards"
            ),
            source_url=(
                "https://velocitypropack.com/areas-served/california/los-angeles/"
                "contract-manufacturing-los-angeles-ca/"
            ),
            field_name="capabilities",
            value="Contract filling, assembly and custom labelling",
            node_keys=("contract-filling-assembly",),
            capabilities=(
                "contract manufacturing",
                "contract filling",
                "packaging assembly",
                "custom labelling",
            ),
        ),
        ExtraVendor(
            name="Olivia Care",
            domain="oliviacare.com",
            email=None,
            city="Los Angeles",
            claim=(
                "Formulates, produces and assembles in its own Los Angeles factory, and "
                "including bottle jar filling."
            ),
            excerpt=(
                "All products are created, formulated, produced, and assembled in our "
                "Los Angeles, California factory."
            ),
            source_url="https://oliviacare.com/pages/private-label",
            field_name="capabilities",
            value="In-house formulation, bottle and jar filling",
            node_keys=("contract-filling-assembly", "serum-formulation"),
            capabilities=(
                "in-house formulation",
                "bottle and jar filling",
                "assembly",
            ),
        ),
    ),
    vendor_limit=8,
)


CANDLE = Scenario(
    key="soy-candle",
    objective=(
        "Launch an 8oz soy candle in Los Angeles. 1,000 units to start. Straight-sided "
        "glass tumbler, wood wick, printed lid, rigid gift box, and contract pouring "
        "with low minimums on the first run."
    ),
    product="soy candle",
    unit_spec="8oz straight-sided glass tumbler",
    quantity=1000,
    priorities=(
        "low minimums on the first run",
        "US-made soy wax",
        "wood wick",
        "rigid gift box",
        "contract pouring",
    ),
    success_criteria=(
        "Find Los Angeles pourers who accept a 1,000-unit first run",
        "Confirm tumbler and lid minimums at 1,000 units",
        "Get a written per-unit price including wax and fragrance load",
    ),
    triggers=("candle", "wax", "wick", "tumbler", "votive", "pour"),
    nodes={
        "custom-glass-bottle": NodeSkin(
            key="glass-tumbler",
            name="Glass Candle Tumbler",
            description="8oz straight-sided glass tumbler, annealed for candle use.",
            aliases=("candle vessel", "straight-sided tumbler", "8oz jar"),
            search_terms=("wholesale candle jars 8oz", "glass candle vessel supplier Los Angeles"),
        ),
        "pump-and-collar": NodeSkin(
            key="wick-and-clip",
            name="Wood Wick and Sustainer",
            description="Wood wick with metal sustainer clip, sized to the tumbler diameter.",
            aliases=("wood wick", "wick sustainer", "crackling wick"),
            search_terms=("wood wick wholesale supplier", "candle wick sustainer bulk"),
        ),
        "perfume-cap": NodeSkin(
            key="candle-lid",
            name="Printed Candle Lid",
            description="Metal or wooden lid with a printed or debossed brand mark.",
            aliases=("candle lid", "tin lid", "wooden lid"),
            search_terms=("candle lid wholesale", "printed candle lid supplier"),
        ),
        "fragrance-juice": NodeSkin(
            key="wax-and-fragrance",
            name="Soy Wax and Fragrance Load",
            description="US-made soy wax blend with a 8-10% fragrance oil load.",
            aliases=("soy wax", "fragrance oil", "wax blend"),
            search_terms=("bulk soy wax supplier California", "candle fragrance oil wholesale"),
        ),
        "folding-carton": NodeSkin(
            key="rigid-gift-box",
            name="Rigid Gift Box",
            description="Rigid two-piece gift box with a foam insert sized to the tumbler.",
            aliases=(
                "rigid box",
                "gift box",
                "two-piece box",
            ),
            search_terms=(
                "rigid gift box manufacturer Los Angeles",
                "candle gift box with insert",
            ),
        ),
        "contract-filling-assembly": NodeSkin(
            key="contract-pouring",
            name="Contract Pouring and Assembly",
            description="Hand or machine pouring, curing, labelling and boxing.",
            aliases=("contract pourer", "candle co-packer"),
            search_terms=(
                "private label candle manufacturer Los Angeles",
                "contract candle pouring",
            ),
        ),
    },
    terms={
        "50ml eau de parfum": "8oz soy candle",
        "eau de parfum": "soy candle",
        "custom glass flacon": "glass tumbler",
        "fragrance juice": "wax and fragrance load",
        "fragrance bulk": "wax and fragrance",
        "pump and collar": "wood wick and sustainer",
        "folding cartons": "gift boxes",
        "folding carton": "gift box",
        "perfume carton": "candle gift box",
        "perfume cap": "printed lid",
        "perfume": "candle",
        "flacon": "tumbler",
        "FEA 15 pump": "wood wick",
    },
    extra_vendors=(
        ExtraVendor(
            name="Lumient LA",
            domain="lumient.la",
            email=None,
            city="Los Angeles",
            claim=(
                "Private label candle minimum order quantity is 120 units, poured in "
                "Los Angeles."
            ),
            excerpt=(
                "All private label candles are manufactured in our Los Angeles facility "
                "with US-made soy wax and fragrance oils."
            ),
            source_url="https://lumient.la/us/private-label",
            field_name="moq",
            value="120",
            node_keys=("contract-pouring",),
            capabilities=(
                "private label candle pouring",
                "US-made soy wax",
                "fragrance oils",
            ),
        ),
        ExtraVendor(
            name="INTI Candles",
            domain="inticandles.com",
            email=None,
            city="Los Angeles",
            claim=(
                "Hand-pours every candle in its own Los Angeles facility, for small and "
                "large runs."
            ),
            excerpt=(
                "All of our candles are hand poured in our facility to ensure the "
                "highest quality product."
            ),
            source_url="https://www.inticandles.com/",
            field_name="capabilities",
            value="Hand pouring, small and large runs",
            node_keys=("contract-pouring",),
            capabilities=("hand pouring", "small and large runs"),
        ),
    ),
    vendor_limit=6,
)


#: The re-skins, rotated through in order. `FRAGRANCE` is not among them: it is
#: the recording's own brief and is asked for by name, not landed on by turn.
SCENARIOS: tuple[Scenario, ...] = (SKINCARE, CANDLE)

#: Everything a press can come back as.
BRIEFS: tuple[Scenario, ...] = (FRAGRANCE, *SCENARIOS)


def rotate(index: int) -> Scenario:
    return SCENARIOS[index % len(SCENARIOS)]


def _hits(objective: str, triggers: tuple[str, ...]) -> int:
    folded = objective.casefold()
    return sum(1 for term in triggers if term in folded)


def for_objective(objective: str, *, turn: int = 0) -> Scenario:
    """The brief to replay for the objective somebody typed.

    A replay can only show the supply chain it has, but it holds three briefs
    over that supply chain, and answering under the one that was asked for beats
    answering under the next one in a rotation. Typing the fragrance brief and
    being handed a vitamin C serum is the console being wrong about a question it
    could have got right.

    Scored by how many of a brief's words appear in the objective, so the
    strongest match wins rather than the first one to hit. A tie goes to a
    re-skin rather than to `FRAGRANCE`, because the overlap runs one way:
    candles are sold on their fragrance and serums are sold as fragrance-free,
    while a perfume brief rarely mentions wax or a dropper. So `"scented soy
    candle"` is a candle.

    An objective none of them recognise falls back to the rotation, because two
    unrecognised presses should still look like two missions.
    """
    ranked: list[tuple[int, int, Scenario]] = [
        (_hits(objective, scenario.triggers), index, scenario)
        for index, scenario in enumerate(SCENARIOS)
    ]
    ranked.append((_hits(objective, FRAGRANCE.triggers), len(SCENARIOS), FRAGRANCE))
    hits, _, chosen = max(ranked, key=lambda entry: (entry[0], -entry[1]))
    return chosen if hits else rotate(turn)


def as_dict(scenario: Scenario) -> dict[str, Any]:
    """The mission fields this brief sets, and only those.

    Empty ones are dropped rather than written as blanks, which is how
    `FRAGRANCE` inherits the recorded objective, product and quantity instead of
    restating them.
    """
    fields = {
        "objective": scenario.objective,
        "product": scenario.product,
        "unit_spec": scenario.unit_spec,
        "quantity": scenario.quantity,
        "priorities": list(scenario.priorities),
        "success_criteria": list(scenario.success_criteria),
    }
    return {key: value for key, value in fields.items() if value}
