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
    research: ResearchAgent
    brand_evidence: BrandEvidenceAgent
    communication: CommunicationAgent
    recommendation: RecommendationAgent

    @classmethod
    def build(cls, llm: Any, store: Any = None) -> "Agents":
        return cls(
            mission=MissionAgent(llm, store),
            supply_chain=SupplyChainAgent(llm, store),
            discovery=DiscoveryAgent(llm, store),
            research=ResearchAgent(llm, store),
            brand_evidence=BrandEvidenceAgent(llm, store),
            communication=CommunicationAgent(llm, store),
            recommendation=RecommendationAgent(llm, store),
        )


__all__ = [
    "Agents", "MissionAgent", "SupplyChainAgent", "DiscoveryAgent",
    "ResearchAgent", "BrandEvidenceAgent", "CommunicationAgent", "RecommendationAgent",
]
