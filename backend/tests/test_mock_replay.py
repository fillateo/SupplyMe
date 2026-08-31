"""Mock mode: a replay of a real mission, not a simulation of one.

The distinction is the whole reason this is allowed to exist, so it is what the
tests hold: no provider is bound, anything that reaches for one fails loudly,
the replayed documents are the recorded ones under fresh ids with no dangling
references, and the mode cannot be turned on where the deployment runs.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from app.adapters import registry
from app.adapters.memory_store import MemoryStore
from app.adapters.replay import Recording, Replay
from app.config import Settings

RECORDED = {
    "missions/msn_1111111111111111": {
        "id": "msn_1111111111111111",
        "objective": "Launch a 50ml eau de parfum in Los Angeles.",
        "status": "completed",
        "product": "eau de parfum",
        "estimated_cost_usd": 0.29,
        "model_calls": 98,
        "created_at": "2026-08-31T16:32:25Z",
    },
    "vendors/ven_2222222222222222": {
        "id": "ven_2222222222222222",
        "mission_id": "msn_1111111111111111",
        "name": "General Bottle Supply",
        "created_at": "2026-08-31T16:35:00Z",
    },
    "evidence/evd_3333333333333333": {
        "id": "evd_3333333333333333",
        "mission_id": "msn_1111111111111111",
        "vendor_id": "ven_2222222222222222",
        "source_url": "https://generalbottle.example/moq",
        "created_at": "2026-08-31T17:00:00Z",
    },
    # A second, thinner mission: the richer one is the one worth showing.
    "missions/msn_9999999999999999": {
        "id": "msn_9999999999999999",
        "objective": "A mission that barely started",
        "created_at": "2026-08-31T10:00:00Z",
    },
    # Not mission data, and replaying it would claim actions never taken.
    "idempotency/outreach:ven_2222222222222222": {"status": "done"},
    "mail_state/cursor": {"token": "12345"},
}
EVENTS = {
    "missions/msn_1111111111111111/workflow_events/evt_a": {
        "id": "evt_a",
        "mission_id": "msn_1111111111111111",
        "type": "mission.created",
        "created_at": "2026-08-31T16:32:25Z",
    },
    "missions/msn_1111111111111111/workflow_events/evt_b": {
        "id": "evt_b",
        "mission_id": "msn_1111111111111111",
        "type": "vendor.qualified",
        "payload": {"vendor_id": "ven_2222222222222222"},
        "created_at": "2026-08-31T17:30:00Z",
    },
    "missions/msn_9999999999999999/workflow_events/evt_z": {
        "id": "evt_z",
        "mission_id": "msn_9999999999999999",
        "created_at": "2026-08-31T10:00:01Z",
    },
}


@pytest.fixture
def recording_file(tmp_path: Path) -> Path:
    path = tmp_path / "recording.json"
    path.write_text(json.dumps({"meta": {}, "documents": {**RECORDED, **EVENTS}}))
    return path


def test_it_reads_the_mission_that_got_furthest(recording_file: Path) -> None:
    recording = Recording.load(recording_file)

    assert recording is not None
    assert recording.mission_id == "msn_1111111111111111"
    assert [e["id"] for e in recording.events] == ["evt_a", "evt_b"]
    # The reservation ledger and the mailbox cursor are somebody else's state.
    assert not any(p.startswith(("idempotency/", "mail_state/")) for p in recording.documents)
    # And the other mission's documents are not this mission's.
    assert "missions/msn_9999999999999999" not in recording.documents


async def test_a_replay_is_the_recorded_run_under_fresh_ids(recording_file: Path) -> None:
    recording = Recording.load(recording_file)
    assert recording is not None
    store = MemoryStore()
    replay = Replay(recording, store, duration_seconds=0.0)

    mission_id = "msn_new0000000000000"
    await store.put("missions", mission_id, replay.opening_mission(mission_id, user_id="demo"))
    await replay.play(mission_id)

    vendors = await store.query("vendors")
    evidence = await store.query("evidence")
    assert [v["name"] for v in vendors] == ["General Bottle Supply"]
    assert evidence[0]["source_url"] == "https://generalbottle.example/moq"

    # Fresh ids everywhere, and the reference between them still resolves —
    # a rewrite that missed one would leave the console rendering a blank.
    assert vendors[0]["id"] != "ven_2222222222222222"
    assert evidence[0]["vendor_id"] == vendors[0]["id"]
    assert vendors[0]["mission_id"] == mission_id

    events = await store.timeline(mission_id)
    assert [e["type"] for e in events] == ["mission.created", "vendor.qualified"]
    assert events[1]["payload"]["vendor_id"] == vendors[0]["id"]
    assert "msn_1111111111111111" not in json.dumps(events)


async def test_the_mission_opens_where_the_recorded_one_opened(recording_file: Path) -> None:
    recording = Recording.load(recording_file)
    assert recording is not None
    replay = Replay(recording, MemoryStore(), duration_seconds=0.0)

    opening = replay.opening_mission("msn_new0000000000000", user_id="someone")

    assert opening["status"] == "planning"
    assert opening["objective"] == "Launch a 50ml eau de parfum in Los Angeles."
    # Zero at the start of the run being replayed, so zero here.
    assert opening["estimated_cost_usd"] == 0.0
    assert opening["model_calls"] == 0


def _mock_settings(**overrides: Any) -> Settings:
    return Settings(**{"mock": True, "use_cloud_infra": False, **overrides})


def test_mock_binds_no_provider_and_refuses_to_answer_for_one() -> None:
    providers = registry.build(_mock_settings())

    for provider in (providers.llm, providers.search, providers.maps, providers.mail):
        with pytest.raises(RuntimeError, match="SUPPLYME_MOCK"):
            provider.anything_at_all()
    assert any("replayed from a recording" in note for note in providers.notes)


def test_mock_needs_no_credentials() -> None:
    """The point of the mode: it runs on a laptop with an empty .env."""
    providers = registry.build(_mock_settings(maps_api_key="", smtp_user="", project_id=""))

    assert providers.settings.mock is True


def test_mock_cannot_be_turned_on_where_the_deployment_runs() -> None:
    with pytest.raises(RuntimeError, match="cannot be used with SUPPLYME_USE_CLOUD_INFRA"):
        registry.build(_mock_settings(use_cloud_infra=True, project_id="some-project"))


async def test_creating_a_mission_in_mock_mode_replays_one(recording_file: Path) -> None:
    """The path the console actually takes, end to end.

    Worth its own test rather than trusting the unit ones: everything below
    `Replay` was covered and green while `create_mission` still raised, because
    nothing exercised the two together.
    """
    from app.runtime import Runtime

    providers = registry.build(
        _mock_settings(mock_recording=str(recording_file), mock_duration_seconds=0.0)
    )
    runtime = Runtime(providers)

    mission = await runtime.create_mission("anything at all, it replays what it has")

    # The recorded objective, not the typed one: a replay can only show the
    # mission it has, and the mission itself is where that is admitted.
    assert mission.objective == "Launch a 50ml eau de parfum in Los Angeles."
    assert mission.status.value == "planning"
    assert mission.id.startswith("msn_")

    for task in list(runtime._replays):
        await task

    stored = await providers.store.get("missions", mission.id)
    assert stored is not None and stored["status"] == "completed"
    assert len(await providers.store.timeline(mission.id)) == 2
    assert len(await providers.store.query("vendors")) == 1


async def test_a_replayed_mission_says_which_recording_it_is(recording_file: Path) -> None:
    """By eye a replay is a real run. The record has to be able to tell them apart."""
    recording = Recording.load(recording_file)
    assert recording is not None
    store = MemoryStore()
    replay = Replay(recording, store, duration_seconds=0.0)

    mission_id = "msn_new0000000000000"
    opening = replay.opening_mission(mission_id, user_id="demo")
    assert opening["replay_of"] == "msn_1111111111111111"

    await store.put("missions", mission_id, opening)
    await replay.play(mission_id)

    finished = await store.get("missions", mission_id)
    assert finished is not None
    assert finished["replay_of"] == "msn_1111111111111111"


def test_a_long_silence_is_shortened_but_the_order_is_not(recording_file: Path) -> None:
    """Waiting is most of a real mission and none of a good demo.

    The recording here jumps half an hour between the vendor and the evidence.
    Played proportionally that is most of the run spent on a still screen.
    """
    recording = Recording.load(recording_file)
    assert recording is not None

    faithful = Replay(recording, MemoryStore(), duration_seconds=60.0, max_gap_seconds=0.0)
    capped = Replay(recording, MemoryStore(), duration_seconds=60.0, max_gap_seconds=2.0)
    mapping = faithful._mapping("msn_new0000000000000")

    proportional = faithful._schedule(mapping)
    shortened = capped._schedule(mapping)

    assert [kind for _, kind, _ in proportional] == [kind for _, kind, _ in shortened]
    assert max(b[0] - a[0] for a, b in pairwise(shortened)) <= 2.0 + 1e-9
    assert shortened[-1][0] < proportional[-1][0]
