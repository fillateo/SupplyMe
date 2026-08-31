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
from app.domain.ids import new_id

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
    "evidence/ev_3333333333333333cccc": {
        "id": "ev_3333333333333333cccc",
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
    # A second supplier, so a scenario with a shorter roster has one to drop.
    "vendors/ven_4444444444444444": {
        "id": "ven_4444444444444444",
        "mission_id": "msn_1111111111111111",
        "name": "Dropped Bottle Co",
        "created_at": "2026-08-31T16:36:00Z",
    },
    "conflicts/cfl_5555555555555555": {
        "id": "cfl_5555555555555555",
        "mission_id": "msn_1111111111111111",
        "vendor_id": "ven_4444444444444444",
        "field": "lead_time_days",
        "created_at": "2026-08-31T17:10:00Z",
    },
    # The closing panel, in the recorded mission's vocabulary. Every phrase here
    # is one a scenario has to rewrite, and every number is one it must not.
    "recommendations/rec_6666666666666666": {
        "id": "rec_6666666666666666",
        "mission_id": "msn_1111111111111111",
        "narrative": (
            "Found options for the fragrance juice and folding cartons, both of which "
            "align well with the 1,000-unit target. However, the launch faces critical "
            "gaps: no viable suppliers were found for the custom glass flacon or the "
            "pump and collar."
        ),
        "risks": [
            "No viable suppliers were found for the custom glass flacon "
            "(custom-glass-bottle) or the pump and collar (pump-and-collar) components."
        ],
        "next_actions": [
            "Identify and contact alternative suppliers for the custom glass flacon and "
            "the pump and collar components, as no viable options were found."
        ],
        "unknowns": ["MOQ for General Bottle Supply"],
        "open_conflicts": ["cfl_5555555555555555"],
        "priced_selections": 1,
        "selections": [
            {
                "node_key": "folding-carton",
                "node_name": "Folding Carton Packaging",
                "vendor": {"id": "ven_2222222222222222", "name": "General Bottle Supply"},
                "quote": {"unit_price": 0.48},
                "why": ["MOQ of 1000 fits the requested order of 1000."],
                "score": {"components": []},
            }
        ],
        "alternatives": [],
        "rejected": [
            {
                "node_key": "custom-glass-bottle",
                "node_name": "Custom Glass Flacon",
                "vendor": {"id": "ven_4444444444444444", "name": "Dropped Bottle Co"},
                "quote": None,
                "score": {"components": []},
            }
        ],
        "created_at": "2026-08-31T18:15:00Z",
    },
    # Not mission data, and replaying it would claim actions never taken.
    "idempotency/outreach:ven_2222222222222222": {"status": "done"},
    "mail_state/cursor": {"token": "12345"},
}
EVENTS = {
    "missions/msn_1111111111111111/workflow_events/evt_aaaaaaaaaaaaaaaaaaaaaaaa": {
        "id": "evt_aaaaaaaaaaaaaaaaaaaaaaaa",
        "mission_id": "msn_1111111111111111",
        "type": "mission.created",
        "created_at": "2026-08-31T16:32:25Z",
    },
    "missions/msn_1111111111111111/workflow_events/evt_bbbbbbbbbbbbbbbbbbbbbbbb": {
        "id": "evt_bbbbbbbbbbbbbbbbbbbbbbbb",
        "mission_id": "msn_1111111111111111",
        "type": "vendor.qualified",
        "payload": {"vendor_id": "ven_2222222222222222"},
        "created_at": "2026-08-31T17:30:00Z",
    },
    "missions/msn_9999999999999999/workflow_events/evt_zzzzzzzzzzzzzzzzzzzzzzzz": {
        "id": "evt_zzzzzzzzzzzzzzzzzzzzzzzz",
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
    assert [e["id"] for e in recording.events] == ["evt_aaaaaaaaaaaaaaaaaaaaaaaa", "evt_bbbbbbbbbbbbbbbbbbbbbbbb"]
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
    assert sorted(v["name"] for v in vendors) == ["Dropped Bottle Co", "General Bottle Supply"]
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

    first = await runtime.create_mission("something none of the briefs is about")
    second = await runtime.create_mission("also unrecognised")

    # An objective no brief recognises falls back to the rotation, so two
    # presses are two missions rather than the same one twice.
    from app.adapters.scenarios import rotate

    assert first.objective == rotate(0).objective
    assert second.objective == rotate(1).objective
    assert first.objective != second.objective
    assert first.status.value == "planning"
    assert first.id.startswith("msn_")

    mission = first

    for task in list(runtime._replays):
        await task

    stored = await providers.store.get("missions", mission.id)
    assert stored is not None and stored["status"] == "completed"
    assert stored["replay_of"] == "msn_1111111111111111"
    assert len(await providers.store.timeline(mission.id)) == 2
    assert [v["mission_id"] for v in await providers.store.query("vendors")].count(mission.id) >= 1


def test_the_typed_objective_picks_the_brief() -> None:
    """The bug this exists to prevent, which was on screen at a demo.

    Every press rotated, so the prompt the recording was made from — a 50ml eau
    de parfum in Los Angeles — was answered with a vitamin C serum. The replay
    holds a fragrance mission; when fragrance is what was asked for it has to
    play it.
    """
    from app.adapters.scenarios import (
        CANDLE,
        FRAGRANCE,
        SKINCARE,
        as_dict,
        for_objective,
        rotate,
    )

    parfum = (
        "Launch a 50ml eau de parfum in Los Angeles. 1,000 units to start. Custom "
        "glass flacon, pump and collar, folding carton, and contract filling with "
        "low minimums on the first run."
    )
    assert for_objective(parfum) is FRAGRANCE
    assert for_objective(parfum, turn=1) is FRAGRANCE
    # And that brief states nothing about the product, so the recorded objective,
    # quantity and success criteria are the ones that reach the screen.
    assert as_dict(FRAGRANCE) == {}

    # And each scenario answers its own brief, whatever the rotation is on.
    assert for_objective(SKINCARE.objective, turn=1) is SKINCARE
    assert for_objective(CANDLE.objective, turn=0) is CANDLE

    # A tie goes to the scenario: candles are sold on their fragrance.
    assert for_objective("a scented soy candle, 8oz") is CANDLE

    # Only an objective naming none of them rotates.
    assert for_objective("500 aluminium bike frames in Berlin") is rotate(0)
    assert for_objective("500 aluminium bike frames in Berlin", turn=1) is rotate(1)


async def test_asking_for_the_recorded_brief_replays_it_unskinned(
    recording_file: Path,
) -> None:
    """End to end: the prompt the recording was made from gets the recording."""
    from app.runtime import Runtime

    providers = registry.build(
        _mock_settings(mock_recording=str(recording_file), mock_duration_seconds=0.0)
    )
    runtime = Runtime(providers)

    mission = await runtime.create_mission(
        "Launch a 50ml eau de parfum in Los Angeles. 1,000 units to start. Custom "
        "glass flacon, pump and collar, folding carton, and contract filling with "
        "low minimums on the first run."
    )

    assert mission.objective == "Launch a 50ml eau de parfum in Los Angeles."
    for task in list(runtime._replays):
        await task

    # Nothing is renamed and no supplier is dropped: the recorded roster, the
    # recorded vocabulary, and the recorded brief, because that is what was asked
    # for. Only the two suppliers this brief adds are new.
    stored = await providers.store.get("missions", mission.id)
    assert stored is not None
    assert stored["objective"] == "Launch a 50ml eau de parfum in Los Angeles."
    assert stored["product"] == "eau de parfum"
    assert stored["replay_of"] == "msn_1111111111111111"
    names = {v["name"] for v in await providers.store.query("vendors")}
    assert {"General Bottle Supply", "Dropped Bottle Co"} <= names
    assert {"O.Berk West", "APackaging Group"} <= names
    rec = (await providers.store.query("recommendations"))[0]
    assert "custom glass flacon" in rec["narrative"]


async def test_an_added_supplier_carries_only_its_own_facts(recording_file: Path) -> None:
    """A brief's own suppliers are built off a recorded document, and the fields
    they do not fill have to be emptied.

    They were not: the template's minimum, lead time and capabilities came along
    for the ride, so a candle pourer arrived quoting a carton printer's 21-day
    lead time and filed under folding cartons. Everything one of these suppliers
    displays has to come from the page it was read off, and the rest has to say
    unknown.
    """
    from app.adapters.scenarios import FRAGRANCE

    recording = Recording.load(recording_file)
    assert recording is not None
    store = MemoryStore()
    replay = Replay(recording, store, duration_seconds=0.0, scenario=FRAGRANCE)

    mission_id = "msn_new0000000000000"
    await store.put("missions", mission_id, replay.opening_mission(mission_id, user_id="demo"))
    await replay.play(mission_id)

    added = {v["name"]: v for v in await store.query("vendors")}
    pumps = added["APackaging Group"]
    assert pumps["node_keys"] == ["pump-and-collar"]
    assert pumps["status"] == "discovered"      # found on a website, never contacted
    assert pumps["moq"]["value"] == "10000"     # what their own page lists
    assert pumps["moq"]["provenance"] == "publicly_listed"
    for borrowed in ("unit_price", "lead_time_days", "customization"):
        assert pumps[borrowed]["value"] is None, f"{borrowed} came from another supplier"
        assert pumps[borrowed]["provenance"] == "unknown"

    glass = added["O.Berk West"]
    assert glass["node_keys"] == ["custom-glass-bottle"]
    assert glass["moq"]["value"] is None        # they publish none
    evidence = {e["vendor_id"]: e for e in await store.query("evidence", limit=500)}
    assert evidence[glass["id"]]["source_url"] == "https://www.oberk.com/glass-fragrance-bottle"
    assert evidence[pumps["id"]]["evidence_excerpt"] == "MOQ (Subject to Change): 10,000 pcs"


async def test_the_fragrance_brief_does_not_report_gaps_it_has_filled(
    recording_file: Path,
) -> None:
    """The recorded panel said no supplier was found for the flacon or the pump.

    Two are on screen now, so that sentence would be the console contradicting
    its own supplier list. What replaces it stays inside what is known: found on
    their own sites, neither contacted, one minimum that does not fit.
    """
    from app.adapters.scenarios import FRAGRANCE

    recording = Recording.load(recording_file)
    assert recording is not None
    store = MemoryStore()
    replay = Replay(recording, store, duration_seconds=0.0, scenario=FRAGRANCE)

    mission_id = "msn_new0000000000000"
    await store.put("missions", mission_id, replay.opening_mission(mission_id, user_id="demo"))
    await replay.play(mission_id)

    rec = (await store.query("recommendations"))[0]
    prose = " ".join([rec["narrative"], *rec["risks"], *rec["next_actions"]])
    assert "no viable suppliers were found" not in prose.lower()
    assert "O.Berk West" in prose and "APackaging Group" in prose
    assert "neither was contacted" in prose
    assert "10,000-piece minimum against the 1,000 needed" in prose

    # The recorded numbers are still the recorded numbers.
    assert "1,000-unit target" in rec["narrative"]
    assert rec["selections"][0]["quote"]["unit_price"] == 0.48


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


def test_each_scenario_is_a_different_brief_over_real_suppliers() -> None:
    """Two presses must give two missions, not one mission twice.

    What varies is the brief, the component vocabulary and the length of the
    shortlist. What does not vary is that the suppliers are real Los Angeles
    companies — the scenarios re-skin the question, never the answer.
    """
    from app.adapters.scenarios import SCENARIOS, rotate

    assert len(SCENARIOS) >= 2
    assert rotate(0) is not rotate(1)
    assert rotate(len(SCENARIOS)) is rotate(0)

    for scenario in SCENARIOS:
        assert "Los Angeles" in scenario.objective
        assert scenario.vendor_limit and scenario.vendor_limit > 0
        for extra in scenario.extra_vendors:
            assert extra.city == "Los Angeles"
            # Real companies at their real domains, quoted from their own pages.
            assert extra.source_url.startswith("https://")
            assert extra.domain in extra.source_url
            assert not extra.source_url.endswith(".example")
            assert extra.excerpt


async def test_a_scenario_replay_carries_no_reference_to_a_dropped_supplier(
    recording_file: Path,
) -> None:
    """A shorter shortlist must take its evidence and its timeline with it."""
    from app.adapters.scenarios import CANDLE

    recording = Recording.load(recording_file)
    assert recording is not None
    store = MemoryStore()
    replay = Replay(recording, store, duration_seconds=0.0, scenario=CANDLE)

    mission_id = "msn_new0000000000000"
    await store.put("missions", mission_id, replay.opening_mission(mission_id, user_id="demo"))
    await replay.play(mission_id)

    mission = await store.get("missions", mission_id)
    assert mission is not None
    assert mission["product"] == "soy candle"
    assert mission["quantity"] == CANDLE.quantity

    vendor_ids = {v["id"] for v in await store.query("vendors")}
    for evidence in await store.query("evidence", limit=500):
        assert evidence["vendor_id"] in vendor_ids

    # The scenario's own real suppliers arrive with what their site actually says.
    names = {v["name"] for v in await store.query("vendors")}
    assert {"Lumient LA", "INTI Candles"} <= names


async def test_a_scenario_replay_ends_on_a_recommendation_about_the_brief(
    recording_file: Path,
) -> None:
    """The closing beat, in the vocabulary of the brief on screen.

    This is the bug the scenarios shipped with: the supply-chain tab said
    "Amber Glass Dropper Bottle" and the recommendation under it still reported
    that no supplier had been found for the custom glass flacon, against a
    fragrance target, naming suppliers the roster had already dropped. Only
    node documents and one vendor field were being skinned.

    The line this holds: rewrite the *words the model wrote about the product*,
    and nothing else. Every quantity, MOQ and price below is asserted unchanged,
    because those are recorded facts and a scenario that edits them is inventing
    a supplier's terms.
    """
    from app.adapters.scenarios import SKINCARE, Scenario

    recording = Recording.load(recording_file)
    assert recording is not None

    # One supplier only, so the roster has to drop the one the rejected list
    # names — and keep the one the shortlist names, whatever its evidence.
    narrow = Scenario(**{**SKINCARE.__dict__, "vendor_limit": 1})

    store = MemoryStore()
    replay = Replay(recording, store, duration_seconds=0.0, scenario=narrow)
    mission_id = "msn_new0000000000000"
    await store.put("missions", mission_id, replay.opening_mission(mission_id, user_id="demo"))
    await replay.play(mission_id)

    recommendations = await store.query("recommendations")
    assert len(recommendations) == 1
    rec = recommendations[0]

    prose = " ".join(
        [rec["narrative"], *rec["risks"], *rec["next_actions"], *rec["unknowns"]]
    )
    for recorded_term in ("flacon", "pump and collar", "fragrance juice", "folding carton"):
        assert recorded_term not in prose.lower(), f"{recorded_term!r} survived into {prose!r}"
    assert "amber dropper bottle" in prose.lower()
    assert "dropper and collar" in prose.lower()

    # The heading over the shortlist is this brief's component, not the recorded one.
    assert [s["node_name"] for s in rec["selections"]] == ["Serum Carton"]

    # The supplier the roster dropped takes its rejection and its conflict with it.
    kept_ids = {v["id"] for v in await store.query("vendors")}
    for group in ("selections", "alternatives", "rejected"):
        for entry in rec[group]:
            assert entry["vendor"]["id"] in kept_ids
    assert rec["open_conflicts"] == []

    # Numbers are recorded facts and survive untouched.
    assert "1,000-unit target" in rec["narrative"]
    assert rec["selections"][0]["why"] == ["MOQ of 1000 fits the requested order of 1000."]
    assert rec["selections"][0]["quote"]["unit_price"] == 0.48
    assert rec["priced_selections"] == 1


async def test_a_replay_never_writes_over_the_recording(recording_file: Path) -> None:
    """The bug this exists to prevent, which shipped and had to be found live.

    Ids were remapped only if they matched a pattern assuming a three-letter
    prefix and a short suffix. `ev_...` has two letters and `evt_...` can be
    longer, so those documents were written back at their *recorded* paths with
    a new mission_id on them — the replay quietly took the recording's evidence
    for itself, and the original mission's evidence tab went from 61 rows to 5.

    Against the file store the recording is the local database, so this is data
    loss, not cosmetics.
    """
    from app.adapters.scenarios import SKINCARE

    recording = Recording.load(recording_file)
    assert recording is not None
    store = MemoryStore()

    # Put the recording in the store, exactly as seeding does.
    for path, document in recording.documents.items():
        collection, doc_id = path.split("/")
        await store.put(collection, doc_id, document)
    for event in recording.events:
        await store.append_event(recording.mission_id, event)

    before = {
        "evidence": len(await store.query("evidence", limit=500)),
        "vendors": len(await store.query("vendors", limit=500)),
    }

    for scenario in (None, SKINCARE):
        replay = Replay(recording, store, duration_seconds=0.0, scenario=scenario)
        mission_id = new_id("msn")
        await store.put(
            "missions", mission_id, replay.opening_mission(mission_id, user_id="demo")
        )
        await replay.play(mission_id)

    # Every recorded document is still there, still on the recorded mission.
    for path, document in recording.documents.items():
        collection, doc_id = path.split("/")
        stored = await store.get(collection, doc_id)
        assert stored is not None, f"{path} was deleted by a replay"
        assert stored.get("mission_id") == document.get("mission_id"), (
            f"{path} was reassigned to another mission"
        )

    still_mine = [
        e
        for e in await store.query("evidence", limit=500)
        if e["mission_id"] == recording.mission_id
    ]
    assert len(still_mine) == before["evidence"]
    assert len(await store.query("evidence", limit=500)) > before["evidence"]
    assert len(await store.query("vendors", limit=500)) > before["vendors"]
