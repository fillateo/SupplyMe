from __future__ import annotations

import pytest

from app.config import ApprovalPolicy, Settings

from .fixtures import build_runtime


@pytest.fixture(autouse=True, scope="session")
def _ignore_the_developers_env():
    """Read no `.env`, so the suite tests the shipped defaults.

    `Settings` declares `env_file=".env"` and pytest runs from `backend/`, so
    every `Settings()` in this suite was picking up whoever's machine it ran on.
    That is wrong in both directions: `TestDefaults` asserted that the shipped
    ceilings are safe while actually reading local overrides of them, and a test
    that set `max_concurrent_model_calls` explicitly still inherited a
    `min_model_call_interval_seconds` of 1.0 and quietly serialized.

    Anything a test needs, it passes in. Anything it does not pass in is the
    default the repository ships.
    """
    original = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    try:
        yield
    finally:
        Settings.model_config["env_file"] = original


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    """Nor any SUPPLYME_* variable that happens to be exported."""
    import os

    from app.config import reset_settings_cache

    for name in [k for k in os.environ if k.startswith("SUPPLYME_")]:
        monkeypatch.delenv(name, raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


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
