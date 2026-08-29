from __future__ import annotations

import pytest

from app.config import ApprovalPolicy, Mode, Settings
from app.runtime import Runtime

from .fixtures import build_scripted_llm


@pytest.fixture
def settings() -> Settings:
    return Settings(
        mode=Mode.DEMO,
        approval_policy=ApprovalPolicy.AUTONOMOUS,
        max_calls_per_mission=3,
        max_outreach_per_mission=12,
    )


@pytest.fixture
async def runtime(settings: Settings):
    rt = Runtime.build(settings, llm=build_scripted_llm(), demo_speedup=200_000.0)
    await rt.start(concurrency=8)
    try:
        yield rt
    finally:
        await rt.stop()


async def run_to_completion(rt: Runtime, objective: str, *, max_polls: int = 600):
    """Drive a mission until it reaches a terminal state."""
    mission = await rt.create_mission(objective)
    import asyncio

    for _ in range(max_polls):
        await rt.drain(timeout=120)
        current = await rt.repo.mission(mission.id)
        if current.status.value in ("completed", "failed"):
            return current
        await asyncio.sleep(0.02)
    await rt.drain(timeout=120)
    return await rt.repo.mission(mission.id)


OBJECTIVE = (
    "I want to launch a 50ml EDP perfume in Indonesia. Initial production: 500 units. "
    "I want premium packaging, but I want to minimize risk on the first batch."
)
