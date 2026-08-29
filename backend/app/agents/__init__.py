"""Agent container."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .communication import CommunicationAgent
from .discovery import DiscoveryAgent
from .planning import MissionAgent, SupplyChainAgent
from .recommendation import RecommendationAgent
from .research import BrandEvidenceAgent, ResearchAgent


@dataclass
class Agents:
    mission: MissionAgent
    supply_chain: SupplyChainAgent
    discovery: DiscoveryAgent
    #: Either the pre-fetching ResearchAgent or the ADK tool-using one. They
    #: satisfy the same `investigate` contract; see app/runtime.py.
    research: Any
    brand_evidence: BrandEvidenceAgent
    communication: CommunicationAgent
    recommendation: RecommendationAgent

    @classmethod
    def build(cls, llm: Any, store: Any = None, research: Any = None) -> Agents:
        return cls(
            mission=MissionAgent(llm, store),
            supply_chain=SupplyChainAgent(llm, store),
            discovery=DiscoveryAgent(llm, store),
            research=research or ResearchAgent(llm, store),
            brand_evidence=BrandEvidenceAgent(llm, store),
            communication=CommunicationAgent(llm, store),
            recommendation=RecommendationAgent(llm, store),
        )


__all__ = [
    "Agents",
    "BrandEvidenceAgent",
    "CommunicationAgent",
    "DiscoveryAgent",
    "MissionAgent",
    "RecommendationAgent",
    "ResearchAgent",
    "SupplyChainAgent",
]
