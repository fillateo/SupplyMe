"""Spend guards. These protect a finite credit balance, so they are not advisory."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.cost import (
    PRICING,
    UNKNOWN_PRICE,
    BudgetExceeded,
    CostMeter,
    Usage,
    price_for,
    usd_for,
)


class TestPricing:
    def test_a_versioned_model_prices_as_its_family(self):
        assert price_for("gemini-2.5-flash-002") == PRICING["gemini-2.5-flash"]

    def test_longest_prefix_wins(self):
        # flash-lite must not price as flash.
        assert price_for("gemini-2.5-flash-lite") == PRICING["gemini-2.5-flash-lite"]
        assert price_for("gemini-2.5-flash-lite") != PRICING["gemini-2.5-flash"]

    def test_an_unknown_model_over_reports_rather_than_under(self):
        # Under-reporting an unknown model would let it slip past the cap.
        unknown = price_for("gemini-99-experimental")
        assert unknown == UNKNOWN_PRICE
        assert unknown[0] >= max(p[0] for p in PRICING.values())
        assert unknown[1] >= max(p[1] for p in PRICING.values())

    def test_cost_scales_with_tokens(self):
        assert usd_for("gemini-2.5-flash", 2000, 400) == pytest.approx(
            2 * usd_for("gemini-2.5-flash", 1000, 200)
        )

    def test_zero_tokens_costs_nothing(self):
        assert usd_for("gemini-2.5-pro", 0, 0) == 0.0


class TestMeter:
    def test_usage_is_attributed_per_mission(self):
        meter = CostMeter()
        meter.record("a", "gemini-2.5-flash", 1000, 100)
        meter.record("b", "gemini-2.5-flash", 5000, 500)
        assert meter.usage("a").calls == 1
        assert meter.usage("b").input_tokens == 5000
        assert meter.total.calls == 2

    def test_an_unseen_mission_has_spent_nothing(self):
        assert CostMeter().usage("never-run").calls == 0

    def test_the_call_cap_stops_a_mission(self):
        meter = CostMeter(max_calls_per_mission=2)
        meter.record("m", "gemini-2.5-flash", 100, 10)
        meter.check("m")                      # still within
        meter.record("m", "gemini-2.5-flash", 100, 10)
        with pytest.raises(BudgetExceeded, match="model-call cap"):
            meter.check("m")

    def test_the_spend_cap_stops_a_mission(self):
        meter = CostMeter(max_calls_per_mission=10_000, max_usd_per_mission=0.001)
        meter.record("m", "gemini-2.5-pro", 100_000, 10_000)
        with pytest.raises(BudgetExceeded, match=r"\$0\.00 cap"):
            meter.check("m")

    def test_one_mission_hitting_its_cap_does_not_stop_another(self):
        meter = CostMeter(max_calls_per_mission=1)
        meter.record("a", "gemini-2.5-flash", 100, 10)
        with pytest.raises(BudgetExceeded):
            meter.check("a")
        meter.check("b")                      # unaffected

    def test_unattributed_calls_are_never_capped_but_are_counted(self):
        # A call with no mission (model resolution, health probes) must not be
        # able to fail a mission, but must still show up in the total.
        meter = CostMeter(max_calls_per_mission=1)
        meter.record("", "gemini-2.5-flash", 100, 10)
        meter.check("")
        assert meter.total.calls == 1

    def test_totals_survive_a_restart_when_seeded(self):
        meter = CostMeter(max_calls_per_mission=5)
        meter.seed("m", Usage(calls=5, input_tokens=1, output_tokens=1, usd=0.01))
        with pytest.raises(BudgetExceeded):
            meter.check("m")


class TestDefaults:
    """The shipped defaults have to be safe on a small credit balance."""

    def test_a_single_mission_cannot_spend_much(self):
        settings = Settings()
        assert settings.max_usd_per_mission <= 1.0
        assert settings.max_model_calls_per_mission <= 200

    def test_the_research_loop_is_bounded_far_below_the_adk_default(self):
        from google.adk.agents.run_config import RunConfig

        assert Settings().max_research_llm_calls < RunConfig().max_llm_calls / 10

    def test_outreach_is_capped(self):
        settings = Settings()
        assert settings.max_outreach_per_mission <= 20


class TestPlacesCost:
    """Places is the priciest call per unit; the defaults have to reflect that."""

    def test_search_does_not_request_the_dearer_review_fields(self):
        from app.adapters.google_providers import PlacesProvider

        # Reviews are explicitly not treated as evidence of capability, so
        # paying a higher SKU to fetch them on every search buys nothing.
        assert "rating" not in PlacesProvider.SEARCH_FIELDS
        assert "userRatingCount" not in PlacesProvider.SEARCH_FIELDS

    def test_details_may_request_more_because_it_runs_once_per_vendor(self):
        from app.adapters.google_providers import PlacesProvider

        assert "rating" in PlacesProvider.DETAIL_FIELDS

    def test_maps_queries_per_node_are_capped_low_by_default(self):
        assert Settings().max_maps_queries_per_node <= 2

    async def test_the_cap_is_enforced_during_discovery(self):
        from app.adapters.scripted_world import build_scripted_llm
        from app.config import ApprovalPolicy, Mode
        from app.runtime import Runtime

        settings = Settings(
            mode=Mode.DEMO, approval_policy=ApprovalPolicy.AUTONOMOUS,
            max_maps_queries_per_node=1,
        )
        runtime = Runtime.build(settings, llm=build_scripted_llm(), demo_speedup=200_000.0)

        seen: list[str] = []
        original = runtime.providers.maps.search_places

        async def counted(query, *, region=""):
            seen.append(query)
            return await original(query, region=region)

        runtime.providers.maps.search_places = counted
        await runtime.start(concurrency=8)
        try:
            from .conftest import OBJECTIVE, run_to_completion

            mission = await run_to_completion(runtime, OBJECTIVE)
            nodes = len(await runtime.repo.list(
                __import__("app.domain.models", fromlist=["SupplyChainNode"]).SupplyChainNode,
                mission_id=mission.id,
            ))
            # One discovery branch per node, one Places query each at most.
            assert len(seen) <= nodes
        finally:
            await runtime.stop()


class TestVendorCeiling:
    """Researching 40 candidates to recommend 5 is the expensive way to be thorough."""

    async def test_a_mission_cannot_admit_more_vendors_than_its_ceiling(self):
        from app.adapters.scripted_world import build_scripted_llm
        from app.config import ApprovalPolicy, Mode
        from app.domain.models import Vendor
        from app.runtime import Runtime

        from .conftest import OBJECTIVE, run_to_completion

        settings = Settings(
            mode=Mode.DEMO, approval_policy=ApprovalPolicy.AUTONOMOUS,
            max_vendors_per_mission=3,
        )
        runtime = Runtime.build(settings, llm=build_scripted_llm(), demo_speedup=200_000.0)
        await runtime.start(concurrency=8)
        try:
            mission = await run_to_completion(runtime, OBJECTIVE)
            vendors = await runtime.repo.list(Vendor, mission_id=mission.id)
            assert len(vendors) <= 3
            assert mission.status.value == "completed"
        finally:
            await runtime.stop()

    def test_the_default_ceiling_is_well_below_category_times_nodes(self):
        settings = Settings()
        # 8 per category across ~7 nodes would be 56 research loops.
        assert settings.max_vendors_per_mission < settings.max_vendors_per_category * 7
