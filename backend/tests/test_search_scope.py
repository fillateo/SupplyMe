"""Choosing where to look.

Scope is the buyer's decision, not an inference from the wording of an
objective. "A bottle factory in Surabaya" and "a bottle factory anywhere" are
different sourcing problems: someone who can drive to the factory and inspect a
sample before committing is buying something different from someone importing a
container. So the choice has to survive into the queries that get run and the
ranking that comes back — otherwise it is a control that does nothing.
"""

from __future__ import annotations

import pytest

from app.domain.models import Mission, ScoringWeights, SearchScope, Vendor
from app.domain.scoring import score_vendor
from app.domain.trust import TrustProfile
from app.workflow.handlers import _scope_note


def vendor(city: str | None, country: str | None = "Indonesia") -> Vendor:
    return Vendor(mission_id="m", name="PT Example", city=city, country=country)


def logistics(v: Vendor, **kw) -> float:
    score = score_vendor(
        v, weights=ScoringWeights(), trust=TrustProfile(dimensions=[], overall=0.5), **kw
    )
    return next(c["raw"] for c in score.as_dict()["components"] if c["name"] == "logistics")


class TestCityScopeRanksNearbyHigher:
    def test_the_city_you_asked_for_beats_the_rest_of_the_country(self):
        here = logistics(vendor("Surabaya"), market="Indonesia", location="Surabaya",
                         scope=SearchScope.CITY)
        far = logistics(vendor("Tangerang"), market="Indonesia", location="Surabaya",
                        scope=SearchScope.CITY)
        assert here > far, "a supplier in the requested city did not outrank a distant one"
        assert here == 1.0

    def test_a_city_written_with_its_province_still_matches(self):
        assert logistics(vendor("Bekasi, Jawa Barat"), market="Indonesia",
                         location="Bekasi", scope=SearchScope.CITY) == 1.0

    def test_the_explanation_names_the_city_that_was_asked_for(self):
        score = score_vendor(
            vendor("Surabaya"), weights=ScoringWeights(),
            trust=TrustProfile(dimensions=[], overall=0.5),
            market="Indonesia", location="Surabaya", scope=SearchScope.CITY,
        )
        detail = next(c["explanation"] for c in score.as_dict()["components"]
                      if c["name"] == "logistics")
        assert "Surabaya" in detail and "asked for" in detail


class TestGlobalScopeStopsPenalisingImports:
    def test_importing_is_the_premise_not_a_penalty(self):
        overseas = vendor("Guangzhou", "China")
        at_global = logistics(overseas, market="Indonesia", scope=SearchScope.GLOBAL)
        at_country = logistics(overseas, market="Indonesia", scope=SearchScope.COUNTRY)
        assert at_global > at_country

    def test_a_domestic_supplier_still_keeps_an_edge(self):
        assert logistics(vendor("Tangerang"), market="Indonesia",
                         scope=SearchScope.GLOBAL) == 1.0
        assert logistics(vendor("Guangzhou", "China"), market="Indonesia",
                         scope=SearchScope.GLOBAL) == 0.8


class TestCountryScopeIsUnchanged:
    def test_the_default_still_prefers_the_target_market(self):
        assert logistics(vendor("Tangerang"), market="Indonesia") == 1.0
        assert logistics(vendor("Guangzhou", "China"), market="Indonesia") == 0.5

    def test_an_unknown_location_is_neither_rewarded_nor_disqualified(self):
        assert logistics(vendor(None, None), market="Indonesia") == 0.3


class TestWhatTheAgentsAreTold:
    def test_city_scope_names_the_city_and_excludes_elsewhere(self):
        note = _scope_note(
            Mission(objective="x", market="Indonesia", location="Surabaya",
                    search_scope=SearchScope.CITY)
        )
        assert "Surabaya" in note and note.startswith("city")

    def test_global_scope_says_anywhere_rather_than_naming_a_country(self):
        note = _scope_note(
            Mission(objective="x", market="Indonesia", location="Surabaya",
                    search_scope=SearchScope.GLOBAL)
        )
        assert "global" in note and "Surabaya" not in note

    def test_country_scope_names_the_market(self):
        note = _scope_note(
            Mission(objective="x", market="Indonesia", search_scope=SearchScope.COUNTRY)
        )
        assert "Indonesia" in note


class TestTheChoiceOutranksTheModel:
    @pytest.mark.parametrize("scope", list(SearchScope))
    def test_the_scope_survives_onto_the_mission_record(self, scope):
        mission = Mission(objective="x", location="Surabaya", search_scope=scope)
        assert mission.search_scope is scope
        assert mission.location == "Surabaya"

    def test_the_default_is_country_so_existing_behaviour_is_unchanged(self):
        assert Mission(objective="x").search_scope is SearchScope.COUNTRY
        assert Mission(objective="x").location is None


class TestThroughTheWholeWorkflow:
    """A control that does not reach the queries is decoration."""

    async def test_the_chosen_country_overrides_what_the_model_read(self):
        """The objective says Indonesia; the user chose Malaysia. Malaysia wins."""
        from app.config import ApprovalPolicy, Mode, Settings
        from app.runtime import Runtime

        from .fixtures import build_scripted_llm

        settings = Settings(mode=Mode.DEMO, approval_policy=ApprovalPolicy.AUTONOMOUS)
        runtime = Runtime.build(settings, llm=build_scripted_llm(), demo_speedup=200_000.0)
        await runtime.start(concurrency=4)
        try:
            mission = await runtime.create_mission(
                "I want to launch a 50ml EDP perfume in Indonesia. Initial production: 500 units.",
                location="Malaysia", scope=SearchScope.COUNTRY,
            )
            await runtime.drain(timeout=60)
            reloaded = await runtime.repo.mission(mission.id)
            assert reloaded.market == "Malaysia"
        finally:
            await runtime.stop()

    async def test_a_named_city_is_kept_and_the_country_still_gets_inferred(self):
        from app.config import ApprovalPolicy, Mode, Settings
        from app.runtime import Runtime

        from .fixtures import build_scripted_llm

        settings = Settings(mode=Mode.DEMO, approval_policy=ApprovalPolicy.AUTONOMOUS)
        runtime = Runtime.build(settings, llm=build_scripted_llm(), demo_speedup=200_000.0)
        await runtime.start(concurrency=4)
        try:
            mission = await runtime.create_mission(
                "I want to launch a 50ml EDP perfume in Indonesia. Initial production: 500 units.",
                location="Surabaya", scope=SearchScope.CITY,
            )
            await runtime.drain(timeout=60)
            reloaded = await runtime.repo.mission(mission.id)
            assert reloaded.location == "Surabaya"
            assert reloaded.market == "Indonesia", "the country was lost when a city was chosen"
        finally:
            await runtime.stop()

    def test_the_api_accepts_and_records_the_choice(self):
        from fastapi.testclient import TestClient

        from app.api import deps
        from app.api.main import app
        from app.config import ApprovalPolicy, Mode, Settings
        from app.runtime import Runtime

        from .fixtures import build_scripted_llm

        settings = Settings(mode=Mode.DEMO, approval_policy=ApprovalPolicy.AUTONOMOUS)
        runtime = Runtime.build(settings, llm=build_scripted_llm())
        deps._runtime = runtime
        try:
            client = TestClient(app)
            response = client.post("/api/missions", json={
                "objective": "Launch a 50ml EDP perfume. Initial production: 500 units.",
                "location": "Surabaya", "scope": "city",
            })
            assert response.status_code == 201
            body = response.json()
            assert body["location"] == "Surabaya"
            assert body["search_scope"] == "city"
        finally:
            deps._runtime = None

    def test_omitting_the_choice_keeps_the_old_behaviour(self):
        from fastapi.testclient import TestClient

        from app.api import deps
        from app.api.main import app
        from app.config import ApprovalPolicy, Mode, Settings
        from app.runtime import Runtime

        from .fixtures import build_scripted_llm

        settings = Settings(mode=Mode.DEMO, approval_policy=ApprovalPolicy.AUTONOMOUS)
        runtime = Runtime.build(settings, llm=build_scripted_llm())
        deps._runtime = runtime
        try:
            client = TestClient(app)
            response = client.post("/api/missions", json={
                "objective": "Launch a 50ml EDP perfume. Initial production: 500 units.",
            })
            assert response.status_code == 201
            assert response.json()["search_scope"] == "country"
            assert response.json()["location"] is None
        finally:
            deps._runtime = None
