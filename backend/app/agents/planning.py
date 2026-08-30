"""Mission and supply-chain agents.

These two run once each, at the top of a mission, and everything downstream is
shaped by what they produce: the mission brief sets the scoring targets, the
supply-chain plan sets what gets discovered and how many parallel branches run.
"""

from __future__ import annotations

from ..domain.policy import Tool
from .base import Agent
from .schemas import MissionBrief, SupplyChainPlan

MISSION_INSTRUCTION = """
You turn a founder's stated objective into a structured sourcing brief.

Read only what is there. If the objective does not state a quantity, leave it
null — do not assume a typical order size. Priorities are the user's own words
about what matters ("premium packaging", "minimize risk on the first batch"),
not your inference about what they should want.

success_criteria are conditions someone could check off at the end, phrased
concretely: "a supplier for every required component has confirmed it can
produce at the stated quantity", not "find good suppliers".

clarifications_needed is for things that genuinely block sourcing. Most briefs
need none, and returning an empty list is the normal outcome. Never ask for
information the objective already gives.
""".strip()

SUPPLY_CHAIN_INSTRUCTION = """
You decompose a product into the supplier categories needed to actually make it.

Think about the physical bill of materials and the manufacturing services around
it: the components, and the thing that combines them. You are not working in a
fixed industry — the product may be a cosmetic, a piece of furniture, a garment,
a consumer electronic, a packaged food. Derive the categories from the product
in front of you, in that industry's own terms, and never from a template.

Every node must be something a supplier can put a price on. The system will go
and ask each one for a minimum order quantity, a unit price and a lead time, and
rank the answers — so a node has to be a thing you buy by the unit. Certification,
regulatory registration, legal advice and brand design are real obligations and
real costs, but they are not purchase orders with an MOQ, and making them nodes
sends the mission to consultancies that can never answer the questions it asks.
When the market requires something like that, put it in the plan's
consolidation_note or leave it to the brief's success criteria; do not make it a
supplier category.

Two judgments matter more than completeness:

- consolidates_with: which categories one vendor could plausibly supply
  together. Nearly every industry has a tier of suppliers who cover several
  neighbouring categories at once — a contract manufacturer that also sources
  its own inputs, a converter that prints and assembles, an integrator that
  buys the sub-assemblies. Say where that is likely so the system can test
  consolidation instead of contacting six vendors for what one could deliver.
- depends_on: what must be decided before something else can be quoted.
  Assembly, filling and finishing steps generally cannot be priced before the
  thing they act on has been chosen.

Mark a category required=false when it is genuinely optional at this stage
(a premium outer box for a pilot batch) rather than when you are unsure.

aliases are how a supplier will WRITE this component on a quotation, which is
rarely how you would search for it: the trade word, the abbreviation, the local
language's word. They are matched against supplier replies, so an invoice line
reading `botol` or `PCBA` or `MDF-Platte` resolves to the node that asked for
it. Give two to five per node, and none that name a different node.

search_terms are what a sourcing professional would type — include the local
market's own vocabulary where it would find better suppliers than English.
Keep the plan to the categories that actually need a separate supplier: prefer
6-10 well-chosen nodes over an exhaustive list nobody will contact.
""".strip()


class MissionAgent(Agent):
    name = "mission"
    tools = frozenset({Tool.WRITE_VENDOR})
    instruction = MISSION_INSTRUCTION

    async def brief(self, objective: str, *, mission_id: str = "") -> MissionBrief:
        return await self.call(
            prompt=f"Objective from the user:\n\n{objective}",
            schema=MissionBrief,
            mission_id=mission_id,
            event_type="mission.created",
        )


class SupplyChainAgent(Agent):
    name = "supply_chain"
    tools = frozenset()
    instruction = SUPPLY_CHAIN_INSTRUCTION

    async def plan(self, brief: MissionBrief, *, mission_id: str = "") -> SupplyChainPlan:
        prompt = (
            f"Product: {brief.product}\n"
            f"Specification: {brief.unit_spec or 'not stated'}\n"
            f"First batch quantity: "
            f"{brief.quantity if brief.quantity is not None else 'not stated'}\n"
            f"Market: {brief.market or 'not stated'}\n"
            f"Priorities: {'; '.join(brief.priorities) or 'none stated'}\n"
            f"Budget note: {brief.budget_note or 'none stated'}\n\n"
            "Decompose this into the supplier categories required to produce it."
        )
        return await self.call(
            prompt=prompt,
            schema=SupplyChainPlan,
            mission_id=mission_id,
            event_type="requirements.created",
        )
