"""Research and brand-evidence agents.

Both read content the system does not control, so both are permitted to search
and write evidence and nothing else — they cannot email, call, or score. The
brand agent exists separately because "who does this factory make perfume for"
is the one question where a supplier's own marketing is least reliable and most
persuasive, and it needs an investigator that starts from disbelief.
"""

from __future__ import annotations

from ..domain.policy import Tool
from ..ports.base import PageContent, Place, SearchHit, Video
from .base import Agent
from .schemas import BrandInvestigation, VendorResearch

RESEARCH_INSTRUCTION = """
You investigate one supplier and return what its public sources actually say.

For each fact you extract, set `field` when it maps to one the system tracks
(moq, unit_price, lead_time_days, sample_lead_time_days, customization,
payment_terms, capabilities, email, phone), put the number in numeric_value
only when the source states a number, and quote the sentence it came from.

Read carefully around quantities. "Minimum 500 pcs per design" and "500 pcs per
colour" are different facts; quote enough of the sentence that the difference
survives. Do not convert currencies or units. Do not average a range — record
what is written.

capabilities are what this business does (moulding 50ml glass flacons, hot
stamping, contract filling), not the categories it lists in a menu.

brand_claims: copy any brand the supplier says it works with. Copy the name
only. Do not assess it — a separate agent investigates those claims.

email and phone are the two fields the rest of the mission depends on: a
supplier nobody can write to cannot be asked for a quotation, and drops out
however good it looked. Take them from a contact page, an imprint, or a page
footer — wherever the supplier published them — and set `field` to email or
phone so they become evidence like any other fact. Never construct an address
from the company name, and never carry over one that belongs to a directory,
a marketplace, or the agency that built the site.

missing_fields: name every tracked field no source answered. This list is how
the system decides what to ask the supplier, so an omission here costs a real
email.
""".strip()

BRAND_INSTRUCTION = """
You investigate whether a supplier's claimed relationship with a brand is
supported by anything other than the supplier's own word.

The claim under investigation is precise: that this supplier produces for, or
has produced for, this brand. Judge each source against that exact claim.

supports_relationship is true only when the source states the relationship.
These do NOT support it, and you must say so in reasoning:
- the supplier's own website, catalogue, or video saying it
- the brand's name appearing in a list of "clients" with no detail
- the supplier appearing at the same trade show as the brand
- a video that shows a bottle resembling the brand's
- a news article about the brand that merely mentions the supplier's region

The brand's own website, a case study either party published, or independent
trade-press reporting that names both do support it.

An empty findings list is the correct answer when nothing corroborates the
claim. Never soften that into "likely" or "probably".
""".strip()


class ResearchAgent(Agent):
    name = "research"
    tools = frozenset(
        {Tool.SEARCH_WEB, Tool.READ_PAGE, Tool.QUERY_MAPS, Tool.SEARCH_YOUTUBE,
         Tool.WRITE_EVIDENCE, Tool.WRITE_VENDOR}
    )
    instruction = RESEARCH_INSTRUCTION

    async def investigate(
        self,
        *,
        vendor_name: str,
        node_names: list[str],
        pages: list[PageContent],
        hits: list[SearchHit],
        place: Place | None,
        videos: list[Video],
        wanted_fields: list[str],
        mission_id: str = "",
        vendor_id: str | None = None,
    ) -> VendorResearch:
        prompt = (
            f"Supplier under investigation: {vendor_name}\n"
            f"Components we are sourcing from them: {', '.join(node_names) or 'unspecified'}\n"
            f"Fields we still need: {', '.join(wanted_fields) or 'all'}\n\n"
            "Sources follow. Attribute every claim to the source it came from."
        )

        blocks: list[str] = []
        if place is not None:
            blocks.append(
                "GOOGLE MAPS LISTING (source_type=maps_listing)\n"
                f"name: {place.name}\naddress: {place.address}\nphone: {place.phone}\n"
                f"website: {place.website}\nstatus: {place.business_status}\n"
                f"rating: {place.rating} from {place.user_ratings_total} reviews\n"
                "Note: a Maps listing evidences that a business exists at a location. "
                "It is not evidence of manufacturing capability, and reviews are not "
                "evidence of production quality."
            )
        for page in pages:
            if page.blocked_reason:
                blocks.append(f"PAGE NOT RETRIEVED: {page.url} ({page.blocked_reason})")
                continue
            blocks.append(
                f"WEB PAGE (source_type=official_website if this is the supplier's own domain, "
                f"else directory or news)\nurl: {page.url}\ntitle: {page.title}\n\n{page.text}"
            )
        for hit in hits:
            blocks.append(
                f"SEARCH RESULT (source_type=search_result)\nurl: {hit.url}\n"
                f"title: {hit.title}\nsnippet: {hit.snippet}"
            )
        for video in videos:
            blocks.append(
                f"YOUTUBE VIDEO (source_type=youtube)\nurl: {video.url}\ntitle: {video.title}\n"
                f"channel: {video.channel}"
                f"{' [the supplier own channel]' if video.self_published else ''}\n"
                f"description: {video.description}\n"
                "Note: a video showing a factory evidences that a factory exists. It is not "
                "evidence of who that factory's customers are."
            )

        return await self.call(
            prompt=prompt,
            schema=VendorResearch,
            untrusted="\n\n---\n\n".join(blocks) if blocks else None,
            mission_id=mission_id,
            vendor_id=vendor_id,
            event_type="vendor.research.started",
        )


class BrandEvidenceAgent(Agent):
    name = "brand_evidence"
    tools = frozenset({Tool.SEARCH_WEB, Tool.READ_PAGE, Tool.SEARCH_YOUTUBE, Tool.WRITE_EVIDENCE})
    instruction = BRAND_INSTRUCTION

    async def investigate(
        self,
        *,
        vendor_name: str,
        brand: str,
        hits: list[SearchHit],
        pages: list[PageContent],
        videos: list[Video],
        mission_id: str = "",
        vendor_id: str | None = None,
    ) -> BrandInvestigation:
        prompt = (
            f'Claim under investigation: "{vendor_name} produces for {brand}."\n\n'
            "Assess each source below against that exact claim."
        )
        blocks = []
        for hit in hits:
            blocks.append(f"SEARCH RESULT\nurl: {hit.url}\ntitle: {hit.title}\n{hit.snippet}")
        for page in pages:
            if page.blocked_reason:
                continue
            blocks.append(f"PAGE\nurl: {page.url}\ntitle: {page.title}\n\n{page.text}")
        for video in videos:
            blocks.append(
                f"YOUTUBE\nurl: {video.url}\ntitle: {video.title}\nchannel: {video.channel}"
                f"{' [supplier own channel]' if video.self_published else ''}\n{video.description}"
            )
        return await self.call(
            prompt=prompt,
            schema=BrandInvestigation,
            untrusted="\n\n---\n\n".join(blocks) if blocks else None,
            mission_id=mission_id,
            vendor_id=vendor_id,
            event_type="brand.claim.found",
        )
