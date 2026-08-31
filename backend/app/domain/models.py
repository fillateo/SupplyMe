"""Persisted domain objects.

Two rules run through every model here:

1. A missing value is `None` / `Provenance.UNKNOWN`, never a guess. The agents
   are prompted to omit rather than invent, and the schemas make the omission
   representable so nothing has to be filled in to satisfy a type.
2. Any commercially meaningful field carries its provenance, so the UI can show
   where a number came from without a second lookup.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ids import new_id


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(BaseModel):
    model_config = ConfigDict(use_enum_values=False, validate_assignment=True)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def touch(self) -> Self:
        self.updated_at = utcnow()
        return self


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------


class SourceType(StrEnum):
    OFFICIAL_WEBSITE = "official_website"
    BRAND_WEBSITE = "brand_website"
    MAPS_LISTING = "maps_listing"
    DIRECTORY = "directory"
    NEWS = "news"
    INDUSTRY_PUBLICATION = "industry_publication"
    SEARCH_RESULT = "search_result"
    SUPPLIER_EMAIL = "supplier_email"
    UNKNOWN = "unknown"


class EvidenceStrength(StrEnum):
    """How much weight a single source deserves, before corroboration."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    NONE = "none"


class Provenance(StrEnum):
    """The status shown next to any displayed fact.

    Every member is one `evidence.provenance_for` can actually return, or that a
    handler assigns outright. Two more used to sit here — `supplier_reported` and
    `estimated` — which nothing ever computed, so the console shipped a badge and
    a tooltip for states no fact could hold. `estimated` was the worse of the
    two: it described the model guessing a value, which is the one thing this
    system is built not to do.
    """

    VERIFIED = "verified"                  # >=2 independent sources agree
    DIRECT_QUOTE = "direct_quote"          # supplier stated it to us, in writing
    PUBLICLY_LISTED = "publicly_listed"
    INFERRED = "inferred"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class Evidence(Base):
    id: str = Field(default_factory=lambda: new_id("ev"))
    mission_id: str
    vendor_id: str | None = None
    claim: str
    field: str | None = None               # which vendor field this supports
    value: Any | None = None               # normalized value, when the claim is a fact
    source_url: str | None = None
    source_type: SourceType = SourceType.UNKNOWN
    source_title: str | None = None
    evidence_excerpt: str = ""
    retrieved_at: datetime = Field(default_factory=utcnow)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_strength: EvidenceStrength = EvidenceStrength.WEAK
    #: Set when the excerpt came from content we do not control (web page, email).
    untrusted: bool = True

    @model_validator(mode="after")
    def _excerpt_required_for_strong(self) -> Self:
        if self.evidence_strength is EvidenceStrength.STRONG and not self.evidence_excerpt:
            self.evidence_strength = EvidenceStrength.MODERATE
        return self


class RelationshipType(StrEnum):
    SUPPLIER_CLAIMED = "supplier_claimed"
    BRAND_CONFIRMED = "brand_confirmed"
    INDEPENDENT_REPORT = "independent_report"
    PUBLIC_CASE_STUDY = "public_case_study"
    INDIRECT = "indirect"
    UNVERIFIED = "unverified"


class BrandEvidenceClass(StrEnum):
    VERIFIED = "verified"
    STRONG_EVIDENCE = "strong_evidence"
    SUPPLIER_REPORTED = "supplier_reported"
    INDIRECT_EVIDENCE = "indirect_evidence"
    UNVERIFIED = "unverified"
    NO_PUBLIC_EVIDENCE = "no_public_evidence"


class BrandRelationship(Base):
    id: str = Field(default_factory=lambda: new_id("br"))
    mission_id: str
    vendor_id: str
    brand: str
    relationship_type: RelationshipType = RelationshipType.UNVERIFIED
    classification: BrandEvidenceClass = BrandEvidenceClass.UNVERIFIED
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    independent_sources: int = 0
    notes: str = ""


# --------------------------------------------------------------------------
# Mission / supply chain
# --------------------------------------------------------------------------


class MissionStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    DISCOVERING = "discovering"
    RESEARCHING = "researching"
    OUTREACH = "outreach"
    AWAITING_RESPONSE = "awaiting_response"
    AWAITING_APPROVAL = "awaiting_approval"
    RECOMMENDING = "recommending"
    COMPLETED = "completed"
    FAILED = "failed"


class SearchScope(StrEnum):
    """How wide to cast the net when looking for suppliers.

    This is the user's call, not the model's. "A bottle factory in Surabaya" and
    "a bottle factory anywhere" are different sourcing problems with different
    right answers, and inferring which one someone meant from the wording of an
    objective gets it wrong often enough to matter: a founder who can drive to a
    factory and inspect a sample before committing is buying something different
    from one importing a container.
    """

    CITY = "city"          # the named city and the industrial belt around it
    COUNTRY = "country"    # anywhere in the market
    GLOBAL = "global"      # anywhere at all; importing is expected


class ScoringWeights(BaseModel):
    """Weights must sum to 1.0; `normalized()` enforces it."""

    price: float = 0.20
    moq_fit: float = 0.20
    capability: float = 0.20
    lead_time: float = 0.15
    evidence: float = 0.15
    logistics: float = 0.10

    def normalized(self) -> ScoringWeights:
        raw = self.model_dump()
        total = sum(raw.values())
        if total <= 0:
            return ScoringWeights()
        return ScoringWeights(**{k: v / total for k, v in raw.items()})

    def as_dict(self) -> dict[str, float]:
        return self.normalized().model_dump()


class Mission(Base):
    id: str = Field(default_factory=lambda: new_id("msn"))
    user_id: str = "demo-user"
    objective: str
    status: MissionStatus = MissionStatus.CREATED

    # Structured reading of the objective, produced by the Mission agent.
    product: str | None = None
    quantity: int | None = None
    unit_spec: str | None = None
    market: str | None = None
    budget_note: str | None = None
    priorities: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    weights: ScoringWeights = Field(default_factory=ScoringWeights)

    #: Where to look, as the user chose it. `location` is whatever they typed —
    #: a city for CITY, a country for COUNTRY, ignored for GLOBAL — and it
    #: outranks anything the mission agent infers from the objective.
    location: str | None = None
    search_scope: SearchScope = SearchScope.COUNTRY

    #: Counters, kept on the mission so cost guards do not need a collection scan.
    emails_sent: int = 0
    #: Admitted for research. Counted atomically so parallel discovery branches
    #: cannot collectively overshoot the mission's ceiling.
    vendors_admitted: int = 0
    failure_reason: str | None = None

    #: What this mission has actually spent on model calls, from the API's own
    #: token counts. Persisted so a restart does not reset the budget guard.
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


class NodeStatus(StrEnum):
    PENDING = "pending"
    DISCOVERING = "discovering"
    RESEARCHING = "researching"
    QUALIFIED = "qualified"
    BLOCKED = "blocked"


class SupplyChainNode(Base):
    """One thing that must be sourced, e.g. `bottle` or `filling`."""

    id: str = Field(default_factory=lambda: new_id("scn"))
    mission_id: str
    key: str                                # slug, stable within a mission
    name: str
    description: str = ""
    required: bool = True
    status: NodeStatus = NodeStatus.PENDING
    #: Other node keys this one depends on (e.g. filling depends on bottle).
    depends_on: list[str] = Field(default_factory=list)
    #: Node keys a single vendor could plausibly cover together.
    consolidates_with: list[str] = Field(default_factory=list)
    #: Other words suppliers in this industry use for this component, including
    #: the local market's own. This is the mission's component vocabulary: it is
    #: what lets a reply pricing `botol` or `enclosure` be matched to the node
    #: that asked. See `domain/quotes.ComponentVocabulary`.
    aliases: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)
    rationale: str = ""


# --------------------------------------------------------------------------
# Vendors
# --------------------------------------------------------------------------


class VendorStatus(StrEnum):
    DISCOVERED = "discovered"
    RESEARCHING = "researching"
    SHORTLISTED = "shortlisted"
    CONTACTED = "contacted"
    RESPONDED = "responded"
    QUALIFIED = "qualified"
    REJECTED = "rejected"


class Fact(BaseModel):
    """A single vendor attribute plus where it came from."""

    value: Any | None = None
    provenance: Provenance = Provenance.UNKNOWN
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def known(self) -> bool:
        return self.value is not None and self.provenance is not Provenance.UNKNOWN


class Vendor(Base):
    id: str = Field(default_factory=lambda: new_id("ven"))
    mission_id: str
    name: str
    legal_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    domain: str | None = None
    website: str | None = None
    address: str | None = None
    country: str | None = None
    city: str | None = None
    lat: float | None = None
    lng: float | None = None
    phone: str | None = None
    email: str | None = None
    place_id: str | None = None

    node_keys: list[str] = Field(default_factory=list)   # what it can supply
    capabilities: list[str] = Field(default_factory=list)
    status: VendorStatus = VendorStatus.DISCOVERED

    moq: Fact = Field(default_factory=Fact)
    unit_price: Fact = Field(default_factory=Fact)
    currency: str | None = None
    lead_time_days: Fact = Field(default_factory=Fact)
    sample_lead_time_days: Fact = Field(default_factory=Fact)
    customization: Fact = Field(default_factory=Fact)
    payment_terms: Fact = Field(default_factory=Fact)

    evidence_ids: list[str] = Field(default_factory=list)
    brand_relationship_ids: list[str] = Field(default_factory=list)
    open_conflicts: list[str] = Field(default_factory=list)
    thread_ids: list[str] = Field(default_factory=list)

    #: Fields the workflow still needs before this vendor can be scored.
    missing_fields: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    #: Bumped on every material change; used in idempotency keys for outreach.
    version: int = 0

    def fact(self, field: str) -> Fact:
        value = getattr(self, field, None)
        return value if isinstance(value, Fact) else Fact()


# --------------------------------------------------------------------------
# Communications
# --------------------------------------------------------------------------


class ThreadStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    SENT = "sent"
    RESPONDED = "responded"
    CLOSED = "closed"
    BOUNCED = "bounced"


class Message(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg"))
    direction: str                          # "outbound" | "inbound"
    subject: str = ""
    body: str = ""
    sent_at: datetime = Field(default_factory=utcnow)
    provider_message_id: str | None = None


class EmailThread(Base):
    id: str = Field(default_factory=lambda: new_id("thr"))
    mission_id: str
    vendor_id: str
    to_address: str
    subject: str = ""
    provider_thread_id: str | None = None
    status: ThreadStatus = ThreadStatus.DRAFT
    messages: list[Message] = Field(default_factory=list)
    asked: list[str] = Field(default_factory=list)
    answered: list[str] = Field(default_factory=list)
    #: asked minus answered, recomputed on every inbound message.
    unanswered: list[str] = Field(default_factory=list)
    commitments: list[str] = Field(default_factory=list)
    follow_up_count: int = 0


class Quote(Base):
    id: str = Field(default_factory=lambda: new_id("qte"))
    mission_id: str
    vendor_id: str
    node_key: str | None = None
    source: str = "email"                   # email | website
    currency: str = "IDR"
    quantity: int | None = None
    #: Component -> unit price. A vendor quoting a bundle uses the key "package".
    line_items: dict[str, float] = Field(default_factory=dict)
    #: What a bundled price covers, as the supplier stated it. Empty means they
    #: did not say, which makes the bundle uncomparable rather than assumed.
    bundle_covers: list[str] = Field(default_factory=list)
    moq: int | None = None
    lead_time_days: int | None = None
    sample_lead_time_days: int | None = None
    sample_cost: float | None = None
    payment_terms: str | None = None
    customization: str | None = None
    #: Verbatim supplier text this was extracted from. Never paraphrased.
    raw_text: str = ""
    evidence_id: str | None = None
    #: Nothing sets this today. A later reply becomes its own Quote rather than
    #: replacing an earlier one, and which rung applies is decided by
    #: `quotes.comparable_set` against the order quantity instead. Kept because
    #: excluding a withdrawn price is the right behaviour if one ever is.
    superseded_by: str | None = None

    @property
    def package_unit_price(self) -> float | None:
        """Total per-unit cost of everything quoted. None when nothing priced."""
        if not self.line_items:
            return None
        return round(sum(self.line_items.values()), 4)


class ConflictStatus(StrEnum):
    OPEN = "open"
    RESOLVING = "resolving"
    RESOLVED = "resolved"
    UNRESOLVABLE = "unresolvable"


class Conflict(Base):
    id: str = Field(default_factory=lambda: new_id("cfl"))
    mission_id: str
    vendor_id: str
    field: str
    values: list[dict[str, Any]] = Field(default_factory=list)  # {value, provenance, evidence_id}
    preferred_value: Any | None = None
    preferred_reason: str = ""
    status: ConflictStatus = ConflictStatus.OPEN
    resolution_action: str | None = None    # "email" | "none"
    resolved_value: Any | None = None


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"
    AUTO_GRANTED = "auto_granted"


class Approval(Base):
    id: str = Field(default_factory=lambda: new_id("apr"))
    mission_id: str
    vendor_id: str | None = None
    action_type: str                        # "send_email" | "send_follow_up"
    summary: str = ""
    preview: dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    resume_event: dict[str, Any] | None = None   # replayed verbatim on approval
    decided_at: datetime | None = None
    decided_by: str | None = None


class Recommendation(Base):
    id: str = Field(default_factory=lambda: new_id("rec"))
    mission_id: str
    selections: list[dict[str, Any]] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    open_conflicts: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    estimated_unit_cost: float | None = None
    currency: str = "IDR"
    narrative: str = ""


class AgentRun(Base):
    """One agent invocation. This is the audit trail behind "why did it do that"."""

    id: str = Field(default_factory=lambda: new_id("run"))
    mission_id: str
    agent: str
    event_type: str | None = None
    vendor_id: str | None = None
    model: str | None = None
    status: str = "started"                 # started | ok | error
    input_summary: str = ""
    output_summary: str = ""
    tool_calls: list[str] = Field(default_factory=list)
    latency_ms: int | None = None
    error: str | None = None
