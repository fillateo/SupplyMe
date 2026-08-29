"""Recommendation agent.

The ranking is already decided before this agent runs — app/domain/scoring.py
produced it, deterministically, with an explanation for every component. This
agent writes the prose around that result and is explicitly forbidden from
disagreeing with it. If it could re-rank, the scores would be decoration.
"""

from __future__ import annotations

from ..domain.policy import Tool
from .base import Agent
from .schemas import RecommendationNarrative

INSTRUCTION = """
You write the sourcing summary for a buyer, given a ranking that has already
been computed.

You may not change the ranking, invent a reason that is not in the supplied
score explanations, or mention a vendor that is not in the supplied data. Every
entry in `why` must restate a fact that appears in the input — a quoted price, a
confirmed MOQ, an evidence classification, a lead time.

risks are things that could go wrong given what is known: a single unverified
supplier claim on a critical component, a supplier whose price is unconfirmed, a
node with only one viable candidate.

unknowns are facts the mission never obtained. Name the field and the vendor.

next_actions are the specific things a person should do now, in order. "Request
a sample from vendor X before committing" beats "evaluate options further".

Write plainly. No adjectives about the software, no summary of what the system
did, no marketing tone.
""".strip()


class RecommendationAgent(Agent):
    name = "recommendation"
    tools = frozenset({Tool.WRITE_SCORE})
    instruction = INSTRUCTION

    async def narrate(
        self, *, mission_summary: str, ranking_text: str, mission_id: str = ""
    ) -> RecommendationNarrative:
        prompt = (
            f"{mission_summary}\n\n"
            "Computed ranking and score explanations:\n\n"
            f"{ranking_text}\n\n"
            "Write the summary for this mission."
        )
        return await self.call(
            prompt=prompt, schema=RecommendationNarrative, mission_id=mission_id,
            event_type="recommendation.ready",
        )
