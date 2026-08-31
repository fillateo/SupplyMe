"""Spend guards. These protect a finite credit balance, so they are not advisory."""

from __future__ import annotations

import inspect

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
        """The ceiling has to clear a real mission and still bound a runaway.

        A mission over eight suppliers read on the live web made 98 calls and
        cost $0.29, almost all of it input tokens from real pages. So the cap
        cannot sit at the $0.50 that a fixture-driven mission justified — it
        would fail a real one partway through — and it must still be an amount
        nobody minds losing to a loop.
        """
        settings = Settings()
        assert settings.max_usd_per_mission <= 2.0
        assert settings.max_model_calls_per_mission <= 500

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
        from app.config import ApprovalPolicy

        from .fixtures import build_runtime

        settings = Settings(
            approval_policy=ApprovalPolicy.AUTONOMOUS,
            max_maps_queries_per_node=1,
        )
        runtime = build_runtime(settings)

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
        from app.config import ApprovalPolicy
        from app.domain.models import Vendor

        from .conftest import OBJECTIVE, run_to_completion
        from .fixtures import build_runtime

        settings = Settings(
            approval_policy=ApprovalPolicy.AUTONOMOUS,
            max_vendors_per_mission=3,
        )
        runtime = build_runtime(settings)
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


class TestSpendSurvivesAProcessBoundary:
    """The meter is in memory; a mission is not.

    Cloud Run scales to zero between events and runs several instances at once,
    so a mission routinely spans processes that have never met. Each one used to
    start counting from zero, which meant the cap bounded what one instance
    spent rather than what the mission spent — and a mission that had made a
    hundred calls reported two, because the totals written back were whichever
    instance wrote last.
    """

    async def test_a_fresh_process_picks_up_what_the_mission_already_spent(self):
        from app.config import ApprovalPolicy, Settings

        from .conftest import OBJECTIVE
        from .fixtures import build_runtime

        settings = Settings(approval_policy=ApprovalPolicy.AUTONOMOUS)
        runtime = build_runtime(settings)
        await runtime.start(concurrency=4)
        try:
            mission = await runtime.create_mission(OBJECTIVE)
            # Stand in for a previous instance that spent a great deal.
            mission.model_calls = 97
            mission.input_tokens = 560_000
            mission.output_tokens = 22_000
            mission.estimated_cost_usd = 0.29
            await runtime.repo.save(mission)

            assert runtime.providers.meter.usage(mission.id).calls == 0
            await runtime.orchestrator._restore_spend(mission.id)

            restored = runtime.providers.meter.usage(mission.id)
            assert restored.calls == 97
            assert restored.usd == pytest.approx(0.29)
        finally:
            await runtime.stop()

    async def test_two_instances_spending_at_once_add_up_on_the_record(self):
        """Two meters, one mission, one document.

        Each instance knows only its own calls. If each writes its own total,
        the record ends up holding one instance's number instead of the sum —
        and that is the number the next cold start reads its cap back from, so
        the error is in the direction that lets a mission overspend.
        """
        from app.config import ApprovalPolicy, Settings
        from app.workflow.orchestrator import Orchestrator

        from .conftest import OBJECTIVE
        from .fixtures import build_providers, build_runtime

        settings = Settings(approval_policy=ApprovalPolicy.AUTONOMOUS)
        runtime = build_runtime(settings)
        await runtime.start(concurrency=4)
        try:
            mission = await runtime.create_mission(OBJECTIVE)

            # A second Cloud Run instance: its own meter, the same documents.
            elsewhere = build_providers(settings)
            elsewhere.store = runtime.providers.store
            second = Orchestrator(elsewhere, runtime.orchestrator.agents)

            for instance in (runtime.orchestrator, second):
                await instance._restore_spend(mission.id)
                for _ in range(50):
                    instance.meter.record(mission.id, "gemini-3.5-flash", 1_000, 100)
                await instance._persist_spend(mission.id)

            record = await runtime.providers.store.get("missions", mission.id)
            assert record["model_calls"] == 100, "wrote one instance's total, not the mission's"
            assert record["input_tokens"] == 100_000
        finally:
            await runtime.stop()

    async def test_persisting_twice_does_not_count_the_same_calls_again(self):
        """The write is a delta, so it has to know what it already wrote."""
        from app.config import ApprovalPolicy, Settings

        from .conftest import OBJECTIVE
        from .fixtures import build_runtime

        settings = Settings(approval_policy=ApprovalPolicy.AUTONOMOUS)
        runtime = build_runtime(settings)
        await runtime.start(concurrency=4)
        try:
            mission = await runtime.create_mission(OBJECTIVE)
            orchestrator = runtime.orchestrator
            orchestrator.meter.record(mission.id, "gemini-3.5-flash", 1_000, 100)

            await orchestrator._persist_spend(mission.id)
            await orchestrator._persist_spend(mission.id)
            await orchestrator._persist_spend(mission.id)

            record = await runtime.providers.store.get("missions", mission.id)
            assert record["model_calls"] == 1
        finally:
            await runtime.stop()

    async def test_the_cap_counts_the_whole_mission_not_this_process(self):
        """Otherwise the ceiling is per instance, and four instances is four
        times the budget nobody agreed to."""
        from app.domain.cost import BudgetExceeded, CostMeter, Usage

        meter = CostMeter(max_calls_per_mission=100, max_usd_per_mission=1.0)
        meter.seed("m", Usage(calls=99, input_tokens=1, output_tokens=1, usd=0.30))
        meter.check("m")  # 99 is under the cap

        meter.record("m", "gemini-3.5-flash", 10, 10)
        with pytest.raises(BudgetExceeded, match="100-model-call cap"):
            meter.check("m")


class TestTheCapIsCheckedOnEveryPathThatSpends:
    """A cap that only the agent seam consults is not a cap.

    Measured on a live mission: the ceiling fired at $1.00 after 222 model
    calls, and the mission finished its accounting at $1.52 over 319 — because
    the ADK research loop and grounded search recorded their spend without ever
    asking whether they were allowed to make it.
    """

    def _spent_meter(self) -> CostMeter:
        meter = CostMeter(max_calls_per_mission=1000, max_usd_per_mission=0.10)
        # One expensive call, recorded, puts the mission past its dollar cap.
        meter.record("m1", "gemini-3.5-pro", 100_000, 10_000)
        return meter

    def test_the_adk_tool_loop_consults_the_meter(self):
        from app.agents import adk_research

        meter = self._spent_meter()
        with pytest.raises(BudgetExceeded):
            meter.check("m1")

        # The ADK wrapper reads the same module-level meter and mission that
        # `_record` bills against, so the check it now performs is the same one.
        assert hasattr(adk_research.ThrottledGemini, "generate_content_async")
        source = inspect.getsource(adk_research.ThrottledGemini.generate_content_async)
        assert "_METER.check" in source, "the tool loop bills without checking"

    def test_grounded_search_consults_the_meter(self):
        from app.adapters.google_providers import GoogleSearchProvider

        source = inspect.getsource(GoogleSearchProvider._grounded)
        assert "_meter.check" in source, "grounded search bills without checking"

    def test_a_mission_over_budget_is_refused_before_the_request(self):
        """The check happens before the call, so being over budget costs nothing."""
        meter = self._spent_meter()
        before = meter.usage("m1").calls
        with pytest.raises(BudgetExceeded):
            meter.check("m1")
        assert meter.usage("m1").calls == before
