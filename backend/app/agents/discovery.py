"""Discovery agent.

Turns a supply-chain node into search queries, then turns search and Maps
results into vendor candidates. It is deliberately conservative about what
counts as a supplier: a marketplace listing or a reseller blog is not a vendor,
and admitting one pollutes every downstream stage with a company that cannot
actually quote.
"""

from __future__ import annotations

from ..domain.policy import Tool
from ..ports.base import Place, SearchHit
from .base import Agent
from .schemas import DiscoveryResult, SearchQueries

QUERY_INSTRUCTION = """
You write the search queries a sourcing professional would actually run to find
manufacturers of a specific component in a specific market.

Good queries name the component precisely, the market, and the role you want
(manufacturer, pabrik, produsen, converter, contract filler) — not the product
category alone. Include the local-language phrasing when it would surface
factories that English queries miss.

maps_queries must include a locality, because Places searches without one return
the wrong region. Prefer the industrial areas where this kind of manufacturing
actually clusters.

Respect the geographic scope you are given, because it is the buyer's own
decision and not a hint:

- A city scope means every query names that city or an industrial area inside
  it. A supplier two provinces away is not an answer to "near me", however good.
- A country scope means the country, and the local-language phrasing for it.
- A global scope means no place name at all unless the component has a real
  centre of production worth naming. Do not quietly fall back to one country.
""".strip()

EXTRACT_INSTRUCTION = """
You read search results and map listings and decide which are real suppliers of
the requested component.

Include a result only when the text indicates the business itself manufactures,
fills, prints, or supplies the component. Exclude and list in rejected_hits:
marketplace and B2B-aggregator listings, retailers selling finished perfume,
news articles, and directory pages that only repeat a company name.

node_keys: only the nodes the source shows evidence for. A bottle factory that
says nothing about caps does not get the cap node.

Every vendor you return must carry the source_url it came from and a verbatim
excerpt. If a result has no usable excerpt, reject it instead of guessing.
""".strip()


class DiscoveryAgent(Agent):
    name = "discovery"
    tools = frozenset({Tool.SEARCH_WEB, Tool.QUERY_MAPS, Tool.READ_PAGE, Tool.WRITE_VENDOR})
    instruction = EXTRACT_INSTRUCTION

    async def queries(
        self, *, node_name: str, node_description: str, search_terms: list[str],
        market: str | None, scope_note: str = "", mission_id: str = "",
    ) -> SearchQueries:
        prompt = (
            f"Component to source: {node_name}\n"
            f"Description: {node_description or 'none'}\n"
            f"Planner's suggested terms: {', '.join(search_terms) or 'none'}\n"
            f"Market: {market or 'not stated'}\n"
            f"Geographic scope: {scope_note or 'the stated market'}\n\n"
            "Produce up to 4 web queries and up to 3 Maps queries."
        )
        return await self.call(
            prompt=prompt, schema=SearchQueries, fast=True, mission_id=mission_id,
            event_type="vendor.discovery.started", instruction=QUERY_INSTRUCTION,
        )

    async def extract(
        self, *, node_key: str, node_name: str, hits: list[SearchHit], places: list[Place],
        market: str | None, scope_note: str = "", mission_id: str = "",
    ) -> DiscoveryResult:
        lines = [
            f"Sourcing '{node_name}' (node key: {node_key}) in {market or 'any market'}.",
            f"Geographic scope: {scope_note or 'the stated market'}.",
        ]
        if hits:
            lines.append("\nWeb results:")
            for hit in hits:
                lines.append(f"- {hit.title}\n  {hit.url}\n  {hit.snippet}")
        if places:
            lines.append("\nGoogle Maps listings:")
            for place in places:
                detail = ", ".join(
                    filter(None, [place.address, place.phone, place.website, place.business_status])
                )
                lines.append(f"- {place.name} (place_id={place.place_id})\n  {detail}")
        lines.append(
            "\nReturn the entries that are genuine suppliers of this component. "
            f"Use node key '{node_key}' where the source supports it."
        )
        return await self.call(
            prompt="\n".join(lines), schema=DiscoveryResult, fast=True,
            mission_id=mission_id, event_type="vendor.discovered",
        )

