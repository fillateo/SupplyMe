"""A scripted stand-in for Gemini, driven by the demo world.

These handlers do the job the model does — read the supplied sources and return
schema-valid structured data — but deterministically. They are written against
the same prompts the real agents send, so a change that breaks the contract
between a handler and its agent breaks these too.

This lives in the application rather than the test suite because it has two
jobs. It makes the test suite assert on workflow behaviour instead of on model
output; and it lets the whole system — console included — run end to end with no
Google Cloud project, no API key and no network, which is the difference between
"you can read this repo" and "you can run it".

Set `VDS_USE_SCRIPTED_MODEL=true` to bind it. Nothing else changes: the same
agents, events, storage, scoring and console.
"""

from __future__ import annotations

import re

from ..agents.schemas import (
    BrandFinding,
    BrandInvestigation,
    DiscoveredVendor,
    DiscoveryResult,
    EmailDraft,
    ExtractedClaim,
    MissionBrief,
    PlannedNode,
    LineItem,
    QuoteExtraction,
    RecommendationNarrative,
    SearchQueries,
    SelectionNarrative,
    SupplyChainPlan,
    VendorResearch,
)
from ..domain.models import SourceType
from . import demo_world as world
from .scripted_llm import ScriptedLLM

NODES = [
    ("bottle", "50ml glass perfume bottle", ("pump", "cap")),
    ("pump", "Perfume pump sprayer", ("bottle", "cap")),
    ("cap", "Bottle cap / closure", ("bottle", "pump")),
    ("fragrance", "Fragrance concentrate", ()),
    ("filling", "Contract filling and assembly", ("fragrance",)),
    ("label", "Label printing", ("box",)),
    ("box", "Outer packaging box", ("label",)),
]


def build_scripted_llm() -> ScriptedLLM:
    llm = ScriptedLLM()
    llm.register("mission", _mission)
    llm.register("supply_chain", _supply_chain)
    llm.register("discovery", _discovery)
    llm.register("research", _research)
    llm.register("brand_evidence", _brand)
    llm.register("communication", _communication)
    llm.register("recommendation", _recommendation)
    return llm


def _mission(prompt: str, untrusted: str | None) -> MissionBrief:
    found = re.search(r"\b(\d{3,6})\b\s*(?:units|bottles|pcs)", prompt)
    quantity = int(found.group(1)) if found else None
    return MissionBrief(
        product="50ml eau de parfum",
        quantity=quantity or 500,
        unit_spec="50ml EDP",
        market="Indonesia" if "indonesia" in prompt.lower() else None,
        budget_note="minimize investment before validating the product",
        priorities=["premium packaging", "minimize risk on the first batch"],
        success_criteria=[
            "a supplier for every required component has confirmed it can produce 500 units",
            "a direct unit price is on file for each selected supplier",
            "production lead time is confirmed within 30 days",
        ],
        target_lead_time_days=30,
    )


def _supply_chain(prompt: str, untrusted: str | None) -> SupplyChainPlan:
    return SupplyChainPlan(
        nodes=[
            PlannedNode(
                key=key, name=name, description=name, required=True,
                consolidates_with=list(consolidates),
                search_terms=[f"pabrik {key} parfum", f"{name} manufacturer Indonesia"],
                rationale=f"{name} is required to produce a finished 50ml EDP",
            )
            for key, name, consolidates in NODES
        ],
        consolidation_note=(
            "A packaging house may cover bottle, pump and cap together; a contract "
            "filler may cover fragrance and filling."
        ),
    )


def _discovery(prompt: str, untrusted: str | None) -> DiscoveryResult | SearchQueries:
    if "Produce up to 4 web queries" in prompt:
        component = _after(prompt, "Component to source:")
        return SearchQueries(
            queries=[f"pabrik {component} parfum Indonesia", f"{component} manufacturer Indonesia"],
            maps_queries=[f"{component} manufacturer Tangerang"],
        )

    node_key = _between(prompt, "node key: ", ")")
    found: list[DiscoveredVendor] = []
    for vendor in world.VENDORS:
        if vendor.name not in prompt:
            continue
        if node_key not in vendor.node_keys:
            continue
        page = vendor.pages[0] if vendor.pages else None
        found.append(
            DiscoveredVendor(
                name=vendor.name,
                website=f"https://{vendor.domain}/",
                country=vendor.country,
                city=vendor.city,
                why_relevant=f"{vendor.name} states it supplies {node_key}",
                node_keys=[node_key],
                source_url=page.url if page else f"https://{vendor.domain}/",
                excerpt=(page.text[:180] if page else vendor.name),
            )
        )
    return DiscoveryResult(vendors=found, rejected_hits=[])


#: Patterns that pull the demo world's stated facts back out of page text, the
#: way the model reads them out of a real supplier page.
_PAGE_FACTS = (
    ("moq", re.compile(r"[Mm]inimum order(?: quantity)?:?\s*([\d.,]+)\s*pcs", re.I)),
    ("moq", re.compile(r"[Mm]inimum order maklon:\s*([\d.,]+)", re.I)),
    ("moq", re.compile(r"[Mm]inimum order label:\s*([\d.,]+)", re.I)),
    (
        "lead_time_days",
        re.compile(r"[Ll]ead time(?: produksi)?:?\s*(\d+)(?:-\d+)?\s*(?:hari|days)", re.I),
    ),
    (
        "sample_lead_time_days",
        re.compile(r"[Ss]ample[^.\n]*?(\d+)\s*(?:hari|working days|days)", re.I),
    ),
)


def _research(prompt: str, untrusted: str | None) -> VendorResearch:
    vendor = world.vendor_by_name(_after(prompt, "Supplier under investigation:"))
    if vendor is None:
        return VendorResearch(missing_fields=["moq", "unit_price", "lead_time_days"])

    claims: list[ExtractedClaim] = []
    text = " ".join(p.text for p in vendor.pages)
    for field, pattern in _PAGE_FACTS:
        match = pattern.search(text)
        if not match or any(c.field == field for c in claims):
            continue
        raw = match.group(1).replace(".", "").replace(",", "")
        claims.append(
            ExtractedClaim(
                claim=f"{vendor.name} states {field} is {match.group(1)}",
                field=field, numeric_value=float(raw),
                source_type=SourceType.OFFICIAL_WEBSITE,
                source_url=vendor.pages[0].url, source_title=vendor.pages[0].title,
                excerpt=text[max(match.start() - 60, 0) : match.end() + 60],
            )
        )

    known = {c.field for c in claims}
    return VendorResearch(
        email=vendor.email, phone=vendor.phone, address=vendor.address,
        city=vendor.city, country=vendor.country,
        capabilities=[f"supplies {k}" for k in vendor.node_keys],
        node_keys=list(vendor.node_keys),
        claims=claims,
        brand_claims=world.BRAND_CLAIMS.get(vendor.key, []),
        missing_fields=[
            f for f in ("moq", "unit_price", "lead_time_days", "sample_lead_time_days",
                        "customization", "payment_terms")
            if f not in known
        ],
    )


def _brand(prompt: str, untrusted: str | None) -> BrandInvestigation:
    brand = _between(prompt, "produces for ", '."')
    vendor = world.vendor_by_name(_between(prompt, 'Claim under investigation: "', " produces for"))
    findings: list[BrandFinding] = []

    if vendor is not None and untrusted:
        for page in world.INDEPENDENT_PAGES:
            if page.url not in untrusted:
                continue
            supports = vendor.name in page.text and brand in page.text
            source_type = (
                SourceType.BRAND_WEBSITE if "maisonverel" in page.url
                else SourceType.INDUSTRY_PUBLICATION if "review" in page.url
                else SourceType.DIRECTORY
            )
            findings.append(
                BrandFinding(
                    supports_relationship=supports, source_type=source_type,
                    source_url=page.url, source_title=page.title,
                    excerpt=page.text[:200],
                    reasoning=(
                        f"names both {vendor.name} and {brand}" if supports
                        else "does not state the relationship"
                    ),
                )
            )
    return BrandInvestigation(
        brand=brand,
        findings=findings,
        summary=(
            "independent sources name both parties"
            if any(f.supports_relationship for f in findings)
            else "no independent source found; supplier's word only"
        ),
    )


def _communication(prompt: str, untrusted: str | None):
    if "Extract what the reply below commits to" in prompt:
        return _extract_quote(prompt, untrusted or "")
    if "This is a follow-up on an existing thread" in prompt:
        return _draft_follow_up(prompt)
    return _draft_email(prompt)


def _draft_follow_up(prompt: str) -> EmailDraft:
    """A follow-up asks the one thing still outstanding.

    Settling a disagreement is now entirely this email's job, so when the
    workflow supplies the specific point, that point is the whole message rather
    than a line inside a repeat of the original request.
    """
    vendor_name = _after(prompt, "Supplier:")
    specific = _after(prompt, "Specific point to resolve:")
    unanswered = [
        q.strip() for q in (_after(prompt, "Still unanswered:") or "").split(",") if q.strip()
    ]
    questions = [specific] if specific else [q for q in unanswered if q != "none"][:3]
    if not questions:
        questions = ["Could you confirm your minimum order quantity?"]
    body = (
        f"Hello {vendor_name},\n\nFollowing up on our earlier message.\n\n"
        + "\n".join(f"- {q}" for q in questions)
        + "\n\nThank you."
    )
    return EmailDraft(
        subject="Re: quotation request", body=body, questions_asked=questions,
    )


def _draft_email(prompt: str) -> EmailDraft:
    vendor_name = _after(prompt, "Supplier:")
    quantity = _after(prompt, "Quantity for the first batch:") or "500"
    questions = [
        "What is your minimum order quantity?",
        f"What is the unit price at {quantity} units?",
        "What is the production lead time?",
        "Is a sample available, and what does it cost?",
        "What are your payment terms?",
    ]
    facts = [
        line[2:] for line in prompt.splitlines()
        if line.startswith("- ") and "(source:" in line
    ]
    body = (
        f"Hello {vendor_name},\n\n"
        f"We are sourcing packaging for a new perfume brand and are evaluating suppliers "
        f"for an initial run of {quantity} units of 50ml EDP.\n\n"
        + "\n".join(f"- {q}" for q in questions)
        + "\n\nThank you."
    )
    return EmailDraft(
        subject=f"Quotation request - {quantity} x 50ml perfume components",
        body=body, questions_asked=questions,
        personalization_basis=facts[:2],
    )


_NUM = r"([\d][\d.,]*)"


def _money(raw: str) -> float:
    """Read Rp 8.500 / 8,500 / 46,000 as a number."""
    cleaned = raw.strip().rstrip(".,")
    if "." in cleaned and "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(".", "").replace(",", "")
    return float(cleaned)


#: Component labels as they appear in the demo replies, in both languages.
_COMPONENT_LABELS = (
    ("bottle", ("botol", "bottle", "flacon")),
    ("pump", ("pump sprayer", "sprayer", "pump")),
    ("cap", ("cap aluminium", "cap", "tutup")),
    ("label", ("label",)),
    ("box", ("rigid box", "box", "dus")),
)

_PRICE_RE = re.compile(rf"Rp\s*{_NUM}")
#: Indonesian quotes put the price either side of the component name
#: ("Rp 8.500/pcs untuk botol" and "pump sprayer Rp 2.500/pcs" both occur), so
#: each price is matched against the text around it rather than a fixed order.
_PRICE_WINDOW = 45


def _extract_quote(prompt: str, body: str) -> QuoteExtraction:
    line_items: dict[str, float] = {}
    for match in _PRICE_RE.finditer(body):
        window = body[max(match.start() - _PRICE_WINDOW, 0) : match.end() + _PRICE_WINDOW].lower()
        # Anything before another price belongs to that price, not this one.
        for key, labels in _COMPONENT_LABELS:
            if key in line_items:
                continue
            if any(label in window for label in labels):
                line_items[key] = _money(match.group(1))
                break

    bundled = "all-in price" in body or "complete package" in body
    if bundled and (match := re.search(rf"Rp\s*{_NUM}\s*per unit", body)):
        line_items = {"package": _money(match.group(1))}
    if not line_items and (match := re.search(rf"Rp\s*{_NUM}\s*(?:each|/pcs|per pcs)", body)):
        line_items = {"package": _money(match.group(1))}

    # The quantity must be followed by a unit, or "MOQ for 50ml flacons is 5,000"
    # reads the 50 out of the product name.
    moq = None
    for pattern in (
        rf"minimum order kami\s*{_NUM}\s*(?:pcs|pieces)",
        rf"our minimum is\s*{_NUM}\s*(?:pcs|pieces)",
        rf"MOQ.{{0,45}}?{_NUM}\s*(?:pcs|pieces|units)",
        rf"minimum order.{{0,25}}?{_NUM}\s*(?:pcs|pieces|units)",
    ):
        if match := re.search(pattern, body, re.I):
            moq = int(_money(match.group(1)))
            break

    lead = None
    lead_pattern = (
        r"(?:lead time is|[Pp]roduksi|[Ll]ead time)\D{0,20}(\d+)\s*(?:working days|hari|days)"
    )
    if match := re.search(lead_pattern, body):
        lead = int(match.group(1))
    sample_lead = None
    sample_pattern = r"[Ss]ample[^.]{0,60}?(\d+)\s*(?:hari kerja|working days|days|hari)"
    if match := re.search(sample_pattern, body):
        sample_lead = int(match.group(1))

    declines = "cannot produce" in body.lower()
    answered, unanswered = [], []
    asked = [line[2:] for line in prompt.splitlines() if line.startswith("- ")]
    for question in asked:
        lowered = question.lower()
        got = (
            (moq is not None and "minimum" in lowered)
            or (line_items and "price" in lowered)
            or (lead is not None and "lead time" in lowered)
            or (sample_lead is not None and "sample" in lowered)
            or ("payment" in lowered and "payment" in body.lower())
        )
        (answered if got else unanswered).append(question)

    return QuoteExtraction(
        currency="IDR",
        line_items=[LineItem(component=name, unit_price=price)
                    for name, price in line_items.items()],
        moq=moq, lead_time_days=lead,
        sample_lead_time_days=sample_lead,
        payment_terms=(
            _between(body, "Payment:", "\n") or _between(body, "Pembayaran", "\n") or None
        ),
        answered_questions=answered, still_unanswered=unanswered,
        commitments=[line.strip() for line in body.splitlines() if "Rp" in line][:3],
        not_a_quote=declines and not line_items,
    )


def _recommendation(prompt: str, untrusted: str | None) -> RecommendationNarrative:
    ranked_row = re.compile(r"- \[(?P<node>[^\]]+)\] (?P<name>.+?) — (?P<score>[\d.]+)/100")
    selections = []
    for line in prompt.splitlines():
        match = ranked_row.match(line.strip())
        if match and "SELECTED" in prompt.split(line)[0].split("ALTERNATIVES")[0]:
            selections.append(
                SelectionNarrative(
                    node_key=match.group("node"), vendor_id=match.group("name"),
                    why=[f"scored {match.group('score')}/100 on the mission's weights"],
                )
            )
    return RecommendationNarrative(
        selections=selections,
        risks=["Some supplier claims rest on the supplier's own word only."],
        unknowns=["Sample quality has not been assessed."],
        next_actions=["Request samples from the selected suppliers before committing."],
        summary="Selections follow the computed ranking.",
    )


def _after(text: str, marker: str) -> str:
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].split("\n", 1)[0].strip()


def _between(text: str, start: str, end: str) -> str:
    if start not in text:
        return ""
    rest = text.split(start, 1)[1]
    return rest.split(end, 1)[0].strip() if end in rest else rest.strip()
