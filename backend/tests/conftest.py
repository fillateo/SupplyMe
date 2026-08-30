from __future__ import annotations

import pytest

from app.config import ApprovalPolicy, Settings

from .fixtures import build_runtime


@pytest.fixture
def settings() -> Settings:
    return Settings(
        approval_policy=ApprovalPolicy.AUTONOMOUS,
        max_outreach_per_mission=12,
        # The doubles answer instantly, so the ADK tool loop has nothing real to
        # decide and its non-determinism would only make assertions flaky.
        use_adk_research=False,
    )


@pytest.fixture
async def runtime(settings: Settings):
    rt = build_runtime(settings)
    await rt.start(concurrency=8)
    try:
        yield rt
    finally:
        await rt.stop()


async def run_to_completion(rt, objective: str, *, max_polls: int = 600):
    """Drive a mission until it reaches a terminal state."""
    import asyncio

    mission = await rt.create_mission(objective)
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
