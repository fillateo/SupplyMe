"""Response schemas.

Every model call in the system returns one of these. Two conventions run
throughout:

* Unknown is representable. Optional fields exist so the model can decline to
  answer instead of inventing a number to satisfy the schema — §36.
* Anything asserted about the outside world carries a `source_url` and an
  `excerpt`, so it can become an Evidence record. A claim with no excerpt is
  downgraded by app/domain/evidence.py rather than trusted.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain.models import SourceType

# --------------------------------------------------------------------------
# Mission
# --------------------------------------------------------------------------


class MissionBrief(BaseModel):
    product: str = Field(description="What is being manufactured, in a few words")
    quantity: int | None = Field(default=None, description="First-batch unit count if stated")
    unit_spec: str | None = Field(
        default=None,
        description="The unit being made, as specified: '50ml eau de parfum', "
        "'1.5m oak dining table', '10000mAh power bank'",
    )
    market: str | None = Field(default=None, description="Country or region of production/sale")
    budget_note: str | None = None
    priorities: list[str] = Field(
        default_factory=list,
        description="Plain-language priorities the user stated, e.g. 'minimize first-batch risk'",
    )
    success_criteria: list[str] = Field(
        default_factory=list, description="Concrete, checkable conditions for a finished mission"
    )
    target_lead_time_days: int | None = None
    clarifications_needed: list[str] = Field(
        default_factory=list,
        description="Only things that genuinely block sourcing. Empty is a valid answer.",
    )


# --------------------------------------------------------------------------
# Supply chain
# --------------------------------------------------------------------------


class PlannedNode(BaseModel):
    key: str = Field(
        description="lowercase_snake identifier for this component, drawn from the "
        "product being made: 'glass_bottle', 'oak_panel', 'lithium_cell'"
    )
    name: str
    description: str = ""
    required: bool = True
    depends_on: list[str] = Field(default_factory=list, description="keys of prerequisite nodes")
    consolidates_with: list[str] = Field(
        default_factory=list,
        description="keys a single vendor could plausibly supply together with this one",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Other words a supplier in THIS industry would use for this same "
        "component when quoting it, including the local market's own language. "
        "These are matched against supplier quotations, so give the words that "
        "appear on an invoice line, not search phrases.",
    )
    search_terms: list[str] = Field(
        default_factory=list, description="2-4 search phrases a sourcing agent would actually use"
    )
    rationale: str = ""


class SupplyChainPlan(BaseModel):
    nodes: list[PlannedNode]
    consolidation_note: str = Field(
        default="",
        description="Where one vendor could cover several nodes, and why that is worth testing",
    )


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


class DiscoveredVendor(BaseModel):
    name: str
    website: str | None = None
    country: str | None = None
    city: str | None = None
    why_relevant: str = Field(description="What in the source suggests they supply this component")
    node_keys: list[str] = Field(
        default_factory=list, description="Which supply-chain nodes this vendor may cover"
    )
    source_url: str | None = None
    excerpt: str = Field(default="", description="Verbatim text supporting the entry")


class DiscoveryResult(BaseModel):
    vendors: list[DiscoveredVendor] = Field(default_factory=list)
    rejected_hits: list[str] = Field(
        default_factory=list, description="URLs skipped, e.g. marketplaces or resellers, with why"
    )


class SearchQueries(BaseModel):
    queries: list[str] = Field(description="Search phrases, most specific first")
    maps_queries: list[str] = Field(
        default_factory=list, description="Google Maps queries including a locality"
    )


# --------------------------------------------------------------------------
# Research / evidence
# --------------------------------------------------------------------------


class ExtractedClaim(BaseModel):
    claim: str = Field(description="One factual statement, as the source supports it")
    field: str | None = Field(
        default=None,
        description=(
            "Vendor field this supports, if any: moq, unit_price, lead_time_days, "
            "sample_lead_time_days, customization, payment_terms, capabilities, email, phone"
        ),
    )
    numeric_value: float | None = Field(
        default=None, description="Set only when the claim is a number the source actually states"
    )
    text_value: str | None = None
    source_type: SourceType = SourceType.UNKNOWN
    source_url: str | None = None
    source_title: str | None = None
    excerpt: str = Field(description="Verbatim quote from the source. Never paraphrase.")


class VendorResearch(BaseModel):
    legal_name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    node_keys: list[str] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)
    brand_claims: list[str] = Field(
        default_factory=list,
        description="Brands the supplier claims to work with. Copy the name only, verify nothing.",
    )
    missing_fields: list[str] = Field(
        default_factory=list, description="Fields no source answered"
    )
    #: Set when the retrieved content tried to give the agent instructions.
    suspicious_content: bool = False


# --------------------------------------------------------------------------
# Brand evidence
# --------------------------------------------------------------------------


class BrandFinding(BaseModel):
    supports_relationship: bool = Field(
        description="True only if this source states the supplier and brand actually work together"
    )
    source_type: SourceType = SourceType.UNKNOWN
    source_url: str | None = None
    source_title: str | None = None
    excerpt: str = ""
    reasoning: str = Field(description="Why this does or does not support the exact claim")


class BrandInvestigation(BaseModel):
    brand: str
    findings: list[BrandFinding] = Field(default_factory=list)
    #: The model's read; the final classification is computed, not taken from here.
    summary: str = ""


# --------------------------------------------------------------------------
# Communication
# --------------------------------------------------------------------------


class EmailDraft(BaseModel):
    subject: str
    body: str
    questions_asked: list[str] = Field(
        description="Each distinct question in the email, so replies can be matched to them"
    )
    personalization_basis: list[str] = Field(
        default_factory=list,
        description="Evidence ids or verbatim facts used to personalize. Empty if generic.",
    )


class LineItem(BaseModel):
    """One component and what it costs per unit."""

    component: str = Field(
        description="What is priced. Use 'package' for a single bundled price."
    )
    unit_price: float
    covers: list[str] = Field(
        default_factory=list,
        description="Only for a 'package' line: the components that one price includes, "
        "as the supplier described them. Leave empty if the supplier did not say — "
        "an unexplained bundle is reported as uncomparable rather than guessed at.",
    )


class QuoteExtraction(BaseModel):
    quantity: int | None = None
    currency: str | None = None
    #: A list of pairs rather than a component -> price mapping, which is what
    #: this was. A response schema has to declare its properties, and an
    #: open-ended object has none to declare — so Gemini answered every reply
    #: with an empty map, however plainly the price was stated. Every live
    #: mission then rejected every supplier for "still missing unit_price"
    #: while reporting their MOQ and lead time correctly, which is a hard
    #: symptom to read backwards. Use `price_map()` to get the mapping.
    line_items: list[LineItem] = Field(
        default_factory=list,
        description="Each component and its per-unit price.",
    )
    moq: int | None = None
    lead_time_days: int | None = None
    sample_lead_time_days: int | None = None
    sample_cost: float | None = None
    payment_terms: str | None = None
    customization: str | None = None
    answered_questions: list[str] = Field(
        default_factory=list, description="Which of the questions we asked this reply answers"
    )
    commitments: list[str] = Field(
        default_factory=list, description="Anything the supplier committed to, verbatim"
    )
    still_unanswered: list[str] = Field(default_factory=list)
    #: True when the message is a bounce, an auto-reply, or otherwise not a quote.
    not_a_quote: bool = False
    suspicious_content: bool = False

    def price_map(self) -> dict[str, float]:
        """The component -> unit price mapping the domain works in."""
        return {
            item.component.strip(): item.unit_price
            for item in self.line_items
            if item.component.strip()
        }

    def bundle_covers(self) -> list[str]:
        """What the supplier said a bundled line includes, across every bundle."""
        covered: list[str] = []
        for item in self.line_items:
            for name in item.covers:
                if name.strip() and name.strip() not in covered:
                    covered.append(name.strip())
        return covered


# --------------------------------------------------------------------------
# Recommendation
# --------------------------------------------------------------------------


class SelectionNarrative(BaseModel):
    node_key: str
    vendor_id: str
    why: list[str] = Field(description="Reasons drawn only from the supplied facts")


class RecommendationNarrative(BaseModel):
    selections: list[SelectionNarrative] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    summary: str = ""
