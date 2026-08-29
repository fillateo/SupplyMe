"""A scripted stand-in for Gemini, driven by the demo world.

These handlers do the job the model does — read the supplied sources and return
schema-valid structured data — but deterministically, so the test suite asserts
on workflow behaviour rather than on model output. They are written against the
same prompts the real agents send, so a change that breaks the contract between
a handler and its agent breaks these too.
"""

from __future__ import annotations

import re

from app.adapters import demo_world as world
from app.adapters.scripted_llm import ScriptedLLM
from app.agents.schemas import (
    BrandFinding,
    BrandInvestigation,
    CallExtraction,
    CallPlan,
    DiscoveredVendor,
    DiscoveryResult,
    EmailDraft,
    ExtractedClaim,
    MissionBrief,
    PlannedNode,
    QuoteExtraction,
    RecommendationNarrative,
    SearchQueries,
    SelectionNarrative,
    SupplyChainPlan,
    VendorResearch,
)
from app.domain.models import SourceType

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
    quantity = int(m.group(1)) if (m := re.search(r"\b(\d{3,6})\b\s*(?:units|bottles|pcs)", prompt)) else None
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
    ("lead_time_days", re.compile(r"[Ll]ead time(?: produksi)?:?\s*(\d+)(?:-\d+)?\s*(?:hari|days)", re.I)),
    ("sample_lead_time_days", re.compile(r"[Ss]ample[^.\n]*?(\d+)\s*(?:hari|working days|days)", re.I)),
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
    if "Questions the call was meant to answer" in prompt:
        return _extract_call(prompt, untrusted or "")
    if "Why we are calling instead of emailing" in prompt:
        return _plan_call(prompt)
    return _draft_email(prompt)


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
    if match := re.search(r"(?:lead time is|[Pp]roduksi|[Ll]ead time)\D{0,20}(\d+)\s*(?:working days|hari|days)", body):
        lead = int(match.group(1))
    sample_lead = None
    if match := re.search(r"[Ss]ample[^.]{0,60}?(\d+)\s*(?:hari kerja|working days|days|hari)", body):
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
        currency="IDR", line_items=line_items, moq=moq, lead_time_days=lead,
        sample_lead_time_days=sample_lead,
        payment_terms=(
            _between(body, "Payment:", "\n") or _between(body, "Pembayaran", "\n") or None
        ),
        answered_questions=answered, still_unanswered=unanswered,
        commitments=[line.strip() for line in body.splitlines() if "Rp" in line][:3],
        not_a_quote=declines and not line_items,
    )


def _plan_call(prompt: str) -> CallPlan:
    conflict = _after(prompt, "Disagreement to resolve:")
    questions = [conflict] if conflict else []
    for field in ("moq", "unit_price", "lead_time_days"):
        if field in prompt:
            questions.append(
                {
                    "moq": "What is your minimum order quantity?",
                    "unit_price": "What is the price per unit at that quantity?",
                    "lead_time_days": "What is the production lead time in days?",
                }[field]
            )
    return CallPlan(
        opening=(
            "Hi, I'm an AI sourcing assistant calling on behalf of a perfume startup. "
            "We're evaluating suppliers for a 500-unit first batch — do you have a moment?"
        ),
        questions=questions[:5] or ["Could you confirm your minimum order quantity?"],
    )


def _extract_call(prompt: str, transcript: str) -> CallExtraction:
    asked = [line[2:] for line in prompt.splitlines() if line.startswith("- ")]
    answered: dict[str, str] = {}
    unanswered: list[str] = []

    turns = [line.split(":", 1) for line in transcript.splitlines() if ":" in line]
    supplier_lines = [t[1].strip() for t in turns if t[0].strip() == "supplier"]
    joined = " ".join(supplier_lines)

    for index, question in enumerate(asked):
        reply = supplier_lines[index + 1] if index + 1 < len(supplier_lines) else ""
        if reply and "harus cek dulu" not in reply:
            answered[question] = reply
        else:
            unanswered.append(question)

    moq = None
    for pattern in (r"pilot order\s*([\d.,]+)\s*pcs", r"[Mm]inimum\s*([\d.,]+)\s*pcs",
                    r"([\d.,]+)\s*pcs\s*(?:bisa|untuk pilot)"):
        if match := re.search(pattern, joined):
            moq = int(_money(match.group(1)))
            break
    price = _money(match.group(1)) if (match := re.search(rf"Rp\s*{_NUM}\s*per", joined)) else None
    lead = None
    for pattern in (r"(\d+)\s*hari kerja", r"kirim\s*(\d+)\s*hari", r"(\d+)\s*(?:working )?days"):
        if match := re.search(pattern, joined):
            lead = int(match.group(1))
            break

    return CallExtraction(
        answered=answered, unanswered=unanswered, moq=moq, unit_price=price,
        lead_time_days=lead, notes="extracted from call transcript",
    )


def _recommendation(prompt: str, untrusted: str | None) -> RecommendationNarrative:
    selections = []
    for line in prompt.splitlines():
        match = re.match(r"- \[(?P<node>[^\]]+)\] (?P<name>.+?) — (?P<score>[\d.]+)/100", line.strip())
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
